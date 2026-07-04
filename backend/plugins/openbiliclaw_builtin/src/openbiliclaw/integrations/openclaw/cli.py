"""OpenClaw 适配器的 JSON CLI 桥接。"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from contextlib import suppress
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .bootstrap import build_openclaw_adapter
from .errors import AdapterOperationError, AdapterValidationError
from .schemas import AvoidanceProbeFeedbackRequest, ChatRequest, FeedbackRequest
from .skill import build_openclaw_skills

if TYPE_CHECKING:
    from collections.abc import Sequence

_SKILL_PACK_PATH = (
    Path(__file__).resolve().parents[4] / "skills" / "openbiliclaw-adapter" / "SKILL.md"
)

_RUNTIME_STREAM_URL = "ws://127.0.0.1:8420/api/runtime-stream"

# ``listen`` 命令转发到 stdout 的事件类型。
#
# ``delight.candidate`` — 主动惊喜推荐推送。
# ``interest.probe``    — agent 有一个新的推测性兴趣假设，
#                         想让用户确认；payload 与
#                         ``next-probe`` 的响应一致。
_LISTEN_EVENT_TYPES = frozenset({"delight.candidate", "interest.probe", "avoidance.probe"})


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="openbiliclaw-openclaw")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("sync-account")
    subparsers.add_parser("get-profile")
    subparsers.add_parser("get-delight")
    subparsers.add_parser("next-probe")
    subparsers.add_parser("next-avoidance-probe")
    subparsers.add_parser("runtime-status")
    subparsers.add_parser("doctor")
    subparsers.add_parser("emit-skill-descriptors")

    chat_parser = subparsers.add_parser(
        "chat",
        help="Send one Socratic dialogue turn and print the agent's reply as JSON.",
    )
    chat_parser.add_argument(
        "--message",
        required=True,
        help="User message to send to the Socratic dialogue.",
    )
    chat_parser.add_argument(
        "--session",
        default="openclaw",
        help="Dialogue session label (default: 'openclaw').",
    )

    listen_parser = subparsers.add_parser(
        "listen",
        help="Stream proactive events (delight.candidate) via WebSocket as JSON lines.",
    )
    listen_parser.add_argument(
        "--ws-url",
        default=_RUNTIME_STREAM_URL,
        help="WebSocket URL for the runtime stream.",
    )
    listen_parser.add_argument(
        "--events",
        default=",".join(sorted(_LISTEN_EVENT_TYPES)),
        help="Comma-separated event types to forward (default: delight.candidate).",
    )

    recommend_parser = subparsers.add_parser("recommend")
    recommend_parser.add_argument("--limit", type=int, default=5)
    refresh_group = recommend_parser.add_mutually_exclusive_group()
    refresh_group.add_argument(
        "--refresh-if-needed",
        action="store_true",
        help="Trigger runtime refresh before returning recommendations.",
    )
    refresh_group.add_argument(
        "--skip-refresh",
        action="store_true",
        help="Skip runtime refresh and only read/generate recommendations.",
    )

    feedback_parser = subparsers.add_parser("submit-feedback")
    feedback_parser.add_argument("--recommendation-id", type=int, required=True)
    feedback_parser.add_argument("--feedback-type", required=True)
    feedback_parser.add_argument("--note", default="")

    avoidance_feedback_parser = subparsers.add_parser("respond-avoidance-probe")
    avoidance_feedback_parser.add_argument("--domain", required=True)
    avoidance_feedback_parser.add_argument(
        "--response",
        choices=["confirm", "reject", "chat"],
        required=True,
    )
    avoidance_feedback_parser.add_argument("--message", default="")
    return parser


def _print_payload(payload: dict[str, object]) -> None:
    sys.stdout.write(f"{json.dumps(payload, ensure_ascii=False)}\n")


async def _run_command(args: argparse.Namespace, adapter: Any) -> dict[str, object]:
    if args.command == "doctor":
        skills = build_openclaw_skills(adapter)
        return {
            "ok": True,
            "data": {
                "skill_pack_path": str(_SKILL_PACK_PATH),
                "skill_pack_exists": _SKILL_PACK_PATH.exists(),
                "skill_count": len(skills),
                "skill_names": [item.name for item in skills],
                "cli_module": "openbiliclaw.integrations.openclaw.cli",
            },
        }
    if args.command == "emit-skill-descriptors":
        skills = build_openclaw_skills(adapter)
        return {
            "ok": True,
            "data": {
                "skills": [
                    {
                        "name": item.name,
                        "description": item.description,
                        "input_schema": item.input_schema,
                    }
                    for item in skills
                ]
            },
        }
    try:
        if args.command == "sync-account":
            result = await adapter.sync_account()
        elif args.command == "get-profile":
            result = await adapter.get_profile()
        elif args.command == "get-delight":
            result = await adapter.get_delight()
        elif args.command == "runtime-status":
            result = await adapter.get_runtime_status()
        elif args.command == "recommend":
            result = await adapter.recommend(
                limit=args.limit,
                refresh_if_needed=bool(args.refresh_if_needed),
            )
        elif args.command == "submit-feedback":
            request = FeedbackRequest(
                recommendation_id=args.recommendation_id,
                feedback_type=args.feedback_type,
                note=args.note,
            )
            result = await adapter.submit_feedback(request)
        elif args.command == "chat":
            chat_request = ChatRequest(
                message=args.message,
                session=getattr(args, "session", "openclaw"),
            )
            result = await adapter.chat(chat_request)
        elif args.command == "next-probe":
            result = await adapter.get_next_probe()
        elif args.command == "next-avoidance-probe":
            result = await adapter.get_next_avoidance_probe()
        elif args.command == "respond-avoidance-probe":
            avoidance_request = AvoidanceProbeFeedbackRequest(
                domain=args.domain,
                response=args.response,
                message=args.message,
            )
            result = await adapter.respond_avoidance_probe(avoidance_request)
        else:  # pragma: no cover - argparse guarantees command validity
            raise AdapterValidationError(f"Unsupported command: {args.command}")
    except AdapterValidationError as exc:
        return {
            "ok": False,
            "error": str(exc),
            "error_type": "validation_error",
        }
    except AdapterOperationError as exc:
        return {
            "ok": False,
            "error": str(exc),
            "error_type": "operation_error",
        }
    return {
        "ok": True,
        "data": asdict(result),
    }


# ---------------------------------------------------------------------------
# ``listen`` — 长时运行的 WebSocket 事件流
# ---------------------------------------------------------------------------

_WS_RECONNECT_DELAY = 3.0
_DELIGHT_ACK_URL = "http://127.0.0.1:8420/api/delight/sent"


async def _acknowledge_delight(bvid: str) -> None:
    """POST 确认，以便后端将该条目标记为已通知。"""
    try:
        import aiohttp

        async with (
            aiohttp.ClientSession() as session,
            session.post(
                _DELIGHT_ACK_URL,
                json={"bvid": bvid},
            ) as resp,
        ):
            resp.raise_for_status()
    except Exception:
        # aiohttp 不可用时回退到同步 urllib
        try:
            import urllib.request

            req = urllib.request.Request(
                _DELIGHT_ACK_URL,
                data=json.dumps({"bvid": bvid}).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            urllib.request.urlopen(req, timeout=5)  # noqa: S310
        except Exception:
            pass


async def _listen_ws(ws_url: str, event_types: frozenset[str]) -> None:
    """连接运行时 WebSocket 流并转发匹配的事件。

    每个匹配的事件作为单行 JSON 写入 stdout：

        {"type": "delight.candidate", "bvid": "BV1xxx", ...}

    连接失败时自动重连。按 Ctrl-C 停止。
    """
    try:
        import websockets
    except ModuleNotFoundError:
        _print_payload(
            {
                "ok": False,
                "error": (
                    "The 'listen' command requires the 'websockets' package. "
                    "Install it with:  pip install websockets"
                ),
                "error_type": "dependency_error",
            }
        )
        return

    while True:
        try:
            async with websockets.connect(ws_url) as ws:
                _print_payload(
                    {
                        "ok": True,
                        "data": {
                            "status": "connected",
                            "ws_url": ws_url,
                            "event_types": sorted(event_types),
                        },
                    }
                )
                sys.stdout.flush()
                async for raw_message in ws:
                    try:
                        event = json.loads(raw_message)
                    except (json.JSONDecodeError, TypeError):
                        continue
                    if not isinstance(event, dict):
                        continue
                    event_type = str(event.get("type", ""))
                    if event_type not in event_types:
                        continue
                    _print_payload({"ok": True, "data": event})
                    sys.stdout.flush()
                    # 自动 ACK 惊喜候选，使冷却立即开始
                    if event_type == "delight.candidate":
                        bvid = str(event.get("bvid", ""))
                        if bvid:
                            await _acknowledge_delight(bvid)
        except (OSError, Exception):
            _print_payload(
                {
                    "ok": False,
                    "error": "WebSocket disconnected, reconnecting...",
                    "error_type": "connection_error",
                }
            )
            sys.stdout.flush()
            await asyncio.sleep(_WS_RECONNECT_DELAY)


def main(argv: Sequence[str] | None = None, *, adapter: Any | None = None) -> int:
    """运行 OpenClaw 适配器 CLI 并打印 JSON 输出。"""
    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    # ``listen`` 是长时运行流 — 单独处理
    if args.command == "listen":
        event_types = (
            frozenset(t.strip() for t in args.events.split(",") if t.strip()) or _LISTEN_EVENT_TYPES
        )
        with suppress(KeyboardInterrupt):
            asyncio.run(_listen_ws(args.ws_url, event_types))
        return 0

    if adapter is not None:
        resolved_adapter = adapter
    elif args.command in {"doctor", "emit-skill-descriptors"}:
        resolved_adapter = object()
    else:
        resolved_adapter = build_openclaw_adapter()
    payload = asyncio.run(_run_command(args, resolved_adapter))
    _print_payload(payload)
    return 0 if bool(payload.get("ok", False)) else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
