"""自动更新服务 —— 周期性检查并应用 backend 源码 tag。

发布契约：
- backend 源码更新是名为 ``backend-vX.Y.Z`` 的 git tag；
- 旧版 ``vX.Y.Z`` / 裸 ``X.Y.Z`` tag 对旧安装被容忍；
- 扩展产物使用 ``extension-vX.Y.Z`` 且必须在此被忽略；
- GitHub ``/releases/latest`` 对 backend 更新不是权威来源，因为
  当前的 Releases 是扩展产物。``_fetch_latest_version`` 因此直接
  查询 ``/tags`` 并过滤 backend tag。
"""

from __future__ import annotations

import asyncio
import locale
import logging
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import unquote, urlparse

import httpx

import openbiliclaw

logger = logging.getLogger(__name__)

_GITHUB_TAGS = "https://api.github.com/repos/whiteguo233/OpenBiliClaw/tags"
_GITHUB_TAGS_ATOM = "https://github.com/whiteguo233/OpenBiliClaw/tags.atom"
_BACKEND_TAG_PREFIX = "backend-v"
_DESKTOP_TAG_PREFIX = "desktop-v"
_MAX_TAG_PAGES = 5
_TAGS_PER_PAGE = 100
_ATOM_NS = "{http://www.w3.org/2005/Atom}"
_VERSION_RE = re.compile(
    r"^(?P<version>\d+(?:\.\d+)*)(?P<prerelease>-[0-9A-Za-z][0-9A-Za-z.-]*)?"
    r"(?:\+[0-9A-Za-z.-]+)?$"
)
DEFAULT_ALLOWED_REMOTES = (
    "https://github.com/whiteguo233/OpenBiliClaw.git",
    "git@github.com:whiteguo233/OpenBiliClaw.git",
)
_OBSERVE_VIA = "runtime-stream"


@dataclass(frozen=True)
class _BackendTagCandidate:
    version: tuple[int, ...]
    version_text: str
    tag: str
    canonical: bool
    prerelease: bool


@dataclass(frozen=True)
class _BackendTagSelection:
    tag: str = ""
    version: tuple[int, ...] = (0,)
    version_text: str = ""
    ignored_prerelease_version: tuple[int, ...] | None = None
    error_reason: str = ""


def _project_root() -> Path:
    """返回项目的 git root（best-effort）。"""
    env_root = os.environ.get("OPENBILICLAW_PROJECT_ROOT", "").strip()
    if env_root:
        return Path(env_root).resolve()
    # 从包位置向上查找
    pkg_dir = Path(openbiliclaw.__file__).resolve().parent
    for parent in [pkg_dir, *pkg_dir.parents]:
        if (parent / ".git").exists():
            return parent
    return Path.cwd()


def detect_install_mode() -> str:
    """对更新状态表面的 best-effort 安装模式检测。

    - ``frozen``：PyInstaller 桌面包。没有 git checkout 可以
      fast-forward，因此 backend 自更新在结构上不受支持 ——
      用户通过安装更新的桌面包来更新。
    - ``git``：项目 root 是 git checkout（一行安装器、
      agent 安装或 dev checkout）—— 自动更新流程可以应用。
    - ``unsupported``：其他任何情况（例如裸 pip install）。
    """
    if getattr(sys, "frozen", False):
        return "frozen"
    if (_project_root() / ".git").exists():
        return "git"
    return "unsupported"


def _parse_version(v: str) -> tuple[int, ...]:
    """将 'v0.2.1' 或 '0.2.1' 这样的版本字符串解析为可比较的 tuple。"""
    v = v.strip().lstrip("vV")
    parts: list[int] = []
    for seg in v.split("."):
        try:
            parts.append(int(seg))
        except ValueError:
            break
    return tuple(parts) or (0,)


def _parse_backend_candidate(
    tag: str,
    *,
    include_prerelease: bool = False,
) -> _BackendTagCandidate | None:
    """解析 backend 发布 tag 并忽略 extension/非 backend tag。"""
    raw = tag.strip()
    if not raw:
        return None
    canonical = False
    if raw.startswith(_BACKEND_TAG_PREFIX):
        canonical = True
        version_text = raw.removeprefix(_BACKEND_TAG_PREFIX)
    elif raw[:1] in {"v", "V"} and len(raw) > 1 and raw[1].isdigit():
        version_text = raw[1:]
    elif raw[0].isdigit():
        version_text = raw
    elif raw[0].isalpha():
        return None
    else:
        version_text = raw

    match = _VERSION_RE.match(version_text)
    if match is None:
        return None
    prerelease = bool(match.group("prerelease"))
    if prerelease and not include_prerelease:
        return None
    version = tuple(int(part) for part in match.group("version").split("."))
    return _BackendTagCandidate(
        version=version,
        version_text=match.group("version"),
        tag=raw,
        canonical=canonical,
        prerelease=prerelease,
    )


def _parse_backend_version(tag: str) -> tuple[int, ...] | None:
    """解析稳定的 backend 发布 tag 并忽略 extension/prerelease tag。"""
    candidate = _parse_backend_candidate(tag)
    return candidate.version if candidate is not None else None


def _parse_desktop_candidate(
    tag: str,
    *,
    include_prerelease: bool = False,
) -> _BackendTagCandidate | None:
    """解析桌面安装器发布 tag —— 仅 ``desktop-vX.Y.Z``。

    Frozen 包通过下载更新的安装器更新，安装器在 ``desktop-v*`` tag 下
    发布（并不总是与 ``backend-v*`` 源码 tag 同步发布）。旧版 ``v*`` /
    裸 semver tag 是 backend 源码发布，因此它们永不计数为安装器候选。
    """
    raw = tag.strip()
    if not raw.startswith(_DESKTOP_TAG_PREFIX):
        return None
    match = _VERSION_RE.match(raw.removeprefix(_DESKTOP_TAG_PREFIX))
    if match is None:
        return None
    prerelease = bool(match.group("prerelease"))
    if prerelease and not include_prerelease:
        return None
    return _BackendTagCandidate(
        version=tuple(int(part) for part in match.group("version").split(".")),
        version_text=match.group("version"),
        tag=raw,
        canonical=True,
        prerelease=prerelease,
    )


def _string_from_mapping_field(
    payload: Mapping[str, object],
    field: str,
) -> str:
    value = payload.get(field)
    return value.strip() if isinstance(value, str) else ""


def _remote_has_credentials(remote_url: str) -> bool:
    parsed = urlparse(remote_url)
    if parsed.scheme in {"http", "https"}:
        return bool(parsed.username or parsed.password)
    return False


def _is_tls_verification_error(exc: Exception) -> bool:
    if not isinstance(exc, httpx.TransportError):
        return False
    text = repr(exc).lower()
    return "certificate" in text or "cert_verify" in text or "tls" in text or "ssl" in text


def _is_github_rate_limited_response(resp: httpx.Response) -> bool:
    remaining = str(resp.headers.get("x-ratelimit-remaining", "")).strip()
    if remaining == "0":
        return True
    if resp.status_code == 429:
        return True
    if resp.status_code != 403:
        return False
    try:
        payload = resp.json()
    except Exception:
        return False
    if not isinstance(payload, Mapping):
        return False
    message = _string_from_mapping_field(payload, "message").lower()
    return "rate limit" in message


def _tag_from_release_url(url: str) -> str:
    path = urlparse(url).path
    marker = "/releases/tag/"
    if marker not in path:
        return ""
    return unquote(path.rsplit(marker, maxsplit=1)[1]).strip()


def _tag_names_from_atom(text: str) -> list[str]:
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return []
    tags: list[str] = []
    for entry in root.findall(f"{_ATOM_NS}entry"):
        for link in entry.findall(f"{_ATOM_NS}link"):
            tag = _tag_from_release_url(link.attrib.get("href", ""))
            if tag:
                tags.append(tag)
                break
    return tags


def _select_latest_candidate_from_tag_names(
    tag_names: Sequence[str],
    *,
    allow_prerelease: bool,
    channel: str,
) -> _BackendTagSelection:
    parse = _parse_desktop_candidate if channel == "desktop" else _parse_backend_candidate
    canonical: list[_BackendTagCandidate] = []
    legacy: list[_BackendTagCandidate] = []
    ignored_prereleases: list[_BackendTagCandidate] = []
    for tag in tag_names:
        candidate = parse(tag, include_prerelease=True)
        if candidate is None:
            continue
        if candidate.prerelease and not allow_prerelease:
            ignored_prereleases.append(candidate)
            continue
        if candidate.canonical:
            canonical.append(candidate)
        else:
            legacy.append(candidate)

    candidates = canonical or legacy
    ignored = max(
        ignored_prereleases,
        key=lambda item: item.version,
        default=None,
    )
    if candidates:
        latest = max(candidates, key=lambda item: item.version)
        return _BackendTagSelection(
            tag=latest.tag,
            version=latest.version,
            version_text=latest.version_text,
            ignored_prerelease_version=ignored.version if ignored else None,
        )
    return _BackendTagSelection(
        ignored_prerelease_version=ignored.version if ignored else None,
    )


def _decode_process_output(data: bytes | str | None) -> str:
    if data is None:
        return ""
    if isinstance(data, str):
        return data
    encoding = locale.getpreferredencoding(False)
    return data.decode(encoding, errors="replace")


def _dirty_paths_besides_uv_lock(porcelain: str) -> list[str]:
    """从 ``git status --porcelain`` 返回脏路径，忽略 uv.lock。

    ``uv sync`` 每当发布 tag 附带陈旧的 lock 时就会重写 uv.lock
    （版本提升忘记 ``uv lock``），因此几乎每个安装从第一天起就有
    一个修改过的 uv.lock。仅此一项绝不能阻止更新 ——
    apply 流程在合并前重置 uv.lock 并在之后重新 sync。
    """
    dirty: list[str] = []
    for line in porcelain.splitlines():
        if not line.strip():
            continue
        if line.startswith(("??", "!!")):
            continue
        index_status = line[0] if len(line) > 0 else " "
        worktree_status = line[1] if len(line) > 1 else " "
        if index_status != " " and worktree_status == " ":
            continue
        path = line[3:].strip().strip('"')
        if " -> " in path:
            path = path.rsplit(" -> ", maxsplit=1)[1].strip().strip('"')
        if path == "uv.lock":
            continue
        if path == "ollama-models" or path.startswith("ollama-models/"):
            continue
        dirty.append(path)
    return dirty


def _merge_or_rebase_in_progress(root: Path, git_dir_text: str) -> bool:
    git_dir = Path(git_dir_text)
    if not git_dir.is_absolute():
        git_dir = root / git_dir
    return any(
        (git_dir / marker).exists() for marker in ("MERGE_HEAD", "rebase-merge", "rebase-apply")
    )


@dataclass
class AutoUpdateService:
    """周期性检查 GitHub 是否有更新版本并自动应用更新。"""

    enabled: bool = False
    check_interval_hours: int = 6
    check_interval_seconds: int = 600  # 到期检查之间的循环 sleep
    allow_prerelease: bool = False
    allowed_remotes: Sequence[str] = DEFAULT_ALLOWED_REMOTES
    event_publisher: Callable[[dict[str, object]], Awaitable[object]] | None = None
    _last_check_at: datetime | None = field(default=None, repr=False)
    _latest_remote_version: str = field(default="", repr=False)
    _latest_tag: str = field(default="", repr=False)
    _state: str = field(default="", repr=False)
    _reason: str = field(default="none", repr=False)
    _update_error: str = field(default="", repr=False)
    _apply_lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)
    _apply_task: asyncio.Task[None] | None = field(default=None, repr=False)

    # --- 公共 API -----------------------------------------------------------

    async def check_and_update_if_due(self) -> dict[str, object]:
        """仅在配置的间隔已过时运行更新检查。"""
        if detect_install_mode() == "frozen":
            # 桌面包无法自应用（二进制就是代码；没有自己的
            # git checkout 可以 fast-forward），但它们仍然轮询新的
            # 安装器发布 —— 无论自动更新开关如何（开关仅管理
            # 自动应用）—— 以便设置页面和 runtime 流可以提示
            # 用户下载下一个桌面包。
            # ``request_apply`` 单独拒绝非 git 安装，因此这永远
            # 不会 mutate 共置的 git checkout。
            if not self._is_due():
                return {"checked": False, "reason": "not_due"}
            backend = await self.check_now()
            return {
                "checked": True,
                "updated": False,
                "reason": "unsupported_install_mode",
                "current_version": backend["current_version"],
                "remote_version": backend["latest_tag"],
            }
        if not self.enabled:
            return {"checked": False, "reason": "disabled"}
        if not self._is_due():
            return {"checked": False, "reason": "not_due"}
        return await self.check_and_update_now()

    async def check_and_update_now(self) -> dict[str, object]:
        """检查新版本并在调度启用时自动应用。"""
        backend = await self.check_now()
        if backend["state"] != "update_available":
            reason = str(backend.get("reason", "none"))
            if reason == "none" and backend["state"] == "error":
                reason = "github_unreachable"
            if reason == "no_backend_tag_yet":
                return {"checked": True, "updated": False, "reason": reason}
            return {
                "checked": True,
                "updated": False,
                "reason": reason,
                "current_version": backend["current_version"],
                "remote_version": backend["latest_tag"],
            }
        if detect_install_mode() != "git":
            # 非 git 安装显示更新但永不尝试应用 ——
            # request_apply 无论如何会拒绝；在此返回保持
            # 刚设置的 update_available 状态不被 apply 尝试的
            # unsupported/blocked 状态覆盖。
            return {
                "checked": True,
                "updated": False,
                "reason": "unsupported_install_mode",
                "current_version": backend["current_version"],
                "remote_version": backend["latest_tag"],
            }
        if not self.enabled:
            return {
                "checked": True,
                "updated": False,
                "reason": "disabled",
                "current_version": backend["current_version"],
                "remote_version": backend["latest_tag"],
            }
        status_code, payload = await self.request_apply(tag=str(backend["latest_tag"]))
        return {
            "checked": True,
            "updated": status_code == 202,
            "reason": payload.get("reason", "none"),
            "current_version": backend["current_version"],
            "remote_version": backend["latest_tag"],
        }

    async def check_now(self) -> dict[str, object]:
        """手动刷新 backend 更新状态而不应用更新。"""
        self._state = "checking"
        self._reason = "none"
        self._last_check_at = datetime.now(tz=UTC)
        current = openbiliclaw.__version__
        current_parsed = _parse_version(current)
        # Frozen 包通过下载更新的安装器更新，因此它们跟踪
        # ``desktop-v*`` 安装器 tag；git checkout 跟踪 ``backend-v*``
        # 源码 tag。两者并不总是同步发布。
        channel = "desktop" if detect_install_mode() == "frozen" else "backend"
        selection = await self._fetch_latest_candidate(channel=channel)

        if selection.error_reason:
            self._state = "error"
            self._reason = selection.error_reason
            self._update_error = selection.error_reason
            logger.warning("Auto-update version check failed: %s", selection.error_reason)
            return self.get_update_status()

        self._latest_tag = selection.tag
        self._latest_remote_version = selection.version_text
        ignored_newer_prerelease = (
            selection.ignored_prerelease_version is not None
            and selection.ignored_prerelease_version > current_parsed
        )
        if not selection.tag:
            if ignored_newer_prerelease:
                self._state = "up_to_date"
                self._reason = "prerelease_ignored"
                self._update_error = ""
            else:
                self._state = "error"
                self._reason = "no_backend_tag_yet"
                self._update_error = "no_backend_tag_yet"
                logger.info("Auto-update check found no_backend_tag_yet")
            return self.get_update_status()

        if selection.version <= current_parsed:
            self._state = "up_to_date"
            self._reason = "prerelease_ignored" if ignored_newer_prerelease else "none"
            self._update_error = ""
            logger.info("Already up-to-date: current=%s, remote=%s", current, selection.tag)
            return self.get_update_status()

        self._state = "update_available"
        self._reason = "none"
        self._update_error = ""
        await self._publish_event(
            {
                "type": "backend_update_available",
                "current_version": current,
                "latest_version": selection.version_text,
                "latest_tag": selection.tag,
            }
        )
        return self.get_update_status()

    async def request_apply(self, *, tag: str = "") -> tuple[int, dict[str, object]]:
        """验证并启动 backend apply 流程，在重启前返回。"""
        async with self._apply_lock:
            if self._apply_task is not None and not self._apply_task.done():
                self._state = "applying"
                self._reason = "already_applying"
                return 409, self._apply_response(
                    state="applying",
                    reason="already_applying",
                    accepted=False,
                )

            target_tag = tag.strip() or self._latest_tag
            if not target_tag:
                self._state = "blocked"
                self._reason = "missing_target_tag"
                return 409, self._apply_response(
                    state="blocked",
                    reason="missing_target_tag",
                    accepted=False,
                )

            guard_reason = await self._check_apply_guards(target_tag)
            if guard_reason:
                self._state = (
                    "unsupported"
                    if guard_reason.startswith("unsupported_")
                    else "error"
                    if guard_reason == "github_unreachable"
                    else "blocked"
                )
                self._reason = guard_reason
                return 409, self._apply_response(
                    state=self._state,
                    reason=guard_reason,
                    accepted=False,
                )

            self._state = "applying"
            self._reason = "none"
            self._apply_task = asyncio.create_task(self._apply_update_to_tag(target_tag))
            return 202, self._apply_response(
                state="applying",
                reason="none",
                accepted=True,
            )

    def get_update_status(self) -> dict[str, object]:
        """为更新状态 API 暴露 backend 更新状态。"""
        state = self._state or ("disabled" if not self.enabled else "unknown")
        return {
            "state": state,
            "auto_update_enabled": self.enabled,
            "install_mode": detect_install_mode(),
            "current_version": openbiliclaw.__version__,
            "latest_version": self._latest_remote_version,
            "latest_tag": self._latest_tag,
            "last_check_at": self._last_check_at.isoformat() if self._last_check_at else "",
            "last_error": self._update_error,
            "reason": self._reason or "none",
        }

    def get_runtime_status(self) -> dict[str, object]:
        """为 runtime 状态 API 暴露更新状态。"""
        return {
            "auto_update_enabled": self.enabled,
            "install_mode": detect_install_mode(),
            "current_version": openbiliclaw.__version__,
            "latest_remote_version": self._latest_remote_version,
            "last_update_check_at": (
                self._last_check_at.isoformat() if self._last_check_at else ""
            ),
            "last_update_error": self._update_error,
            "backend_update_state": (
                self._state or ("disabled" if not self.enabled else "unknown")
            ),
            "backend_update_reason": self._reason or "none",
        }

    def adopt_status_from(self, other: AutoUpdateService) -> None:
        """跨热重载重建携带上次检查结果。

        一次配置保存会重建每个可替换组件，包括此服务。没有这个，
        一个刚 fetch 的 ``update_available`` / ``up_to_date`` 状态会
        在设置页面回退到"尚未检查更新"，直到下次计划检查（最多
        ``check_interval_hours``）。仅采用已稳定的状态 —— 瞬态
        ``checking`` / ``applying`` 状态留给重新推导，以便前一实例
        上进行中的 apply 不会被新实例误报。
        """
        self._last_check_at = other._last_check_at
        self._latest_remote_version = other._latest_remote_version
        self._latest_tag = other._latest_tag
        if other._state in {"", "checking", "applying"}:
            return
        self._state = other._state
        self._reason = other._reason
        self._update_error = other._update_error

    def _background_loop_enabled(self) -> bool:
        """当自动更新开启时循环运行 —— 或在 frozen 包上始终运行。

        Frozen 桌面安装运行 check-only 循环（开关管理自动应用，
        frozen 永远做不到），以便用户无需选择加入任何东西即可获得
        "有新安装器可用，去下载"提醒。
        """
        return self.enabled or detect_install_mode() == "frozen"

    async def run_forever(self) -> None:
        """后台循环：周期性检查（并在 git 安装上应用）更新。"""
        if not self._background_loop_enabled():
            return
        # 小的初始延迟，让主应用完成启动
        await asyncio.sleep(10)
        while True:
            try:
                await self.check_and_update_if_due()
            except Exception:
                logger.exception("Unexpected error in auto-update loop")
            await asyncio.sleep(self.check_interval_seconds)

    # --- 内部 ------------------------------------------------------------

    def _is_due(self) -> bool:
        if self._last_check_at is None:
            return True
        elapsed = datetime.now(tz=UTC) - self._last_check_at
        return elapsed >= timedelta(hours=self.check_interval_hours)

    async def _fetch_latest_candidate(
        self,
        *,
        channel: str = "backend",
    ) -> _BackendTagSelection:
        """查询 GitHub tag 并为 *channel* 选择最新允许的 tag。

        ``backend``（默认）跟踪 ``backend-v*`` 源码 tag 并有旧版
        ``v*`` / 裸 semver 回退；``desktop`` 仅跟踪 ``desktop-v*``
        安装器 tag。
        """
        selection = await self._fetch_latest_candidate_once(channel=channel, verify_tls=True)
        if selection.error_reason != "tls_verification_failed":
            return selection
        logger.warning(
            "Auto-update tag check TLS verification failed; retrying without "
            "certificate verification"
        )
        return await self._fetch_latest_candidate_once(channel=channel, verify_tls=False)

    async def _fetch_latest_candidate_once(
        self,
        *,
        channel: str,
        verify_tls: bool,
    ) -> _BackendTagSelection:
        async with httpx.AsyncClient(timeout=30, verify=verify_tls) as client:
            tag_names: list[str] = []
            for page in range(1, _MAX_TAG_PAGES + 1):
                try:
                    resp = await client.get(
                        _GITHUB_TAGS,
                        headers={"Accept": "application/vnd.github.v3+json"},
                        params={"per_page": _TAGS_PER_PAGE, "page": page},
                    )
                except Exception as exc:
                    if verify_tls and _is_tls_verification_error(exc):
                        return _BackendTagSelection(error_reason="tls_verification_failed")
                    logger.warning("Auto-update tag check failed: %s", exc)
                    return _BackendTagSelection(error_reason="github_unreachable")
                if resp.status_code != 200:
                    reason = (
                        "github_rate_limited"
                        if _is_github_rate_limited_response(resp)
                        else "github_unreachable"
                    )
                    logger.warning(
                        "Auto-update tag check failed: HTTP %s (%s)",
                        resp.status_code,
                        reason,
                    )
                    if reason == "github_rate_limited":
                        atom_selection = await self._fetch_latest_candidate_from_atom(
                            client,
                            channel=channel,
                        )
                        if not atom_selection.error_reason:
                            logger.info("Auto-update tag check recovered via GitHub tags Atom feed")
                            return atom_selection
                    return _BackendTagSelection(error_reason=reason)
                tags = resp.json()
                if not tags:
                    break
                if not isinstance(tags, list):
                    logger.warning("Auto-update tag check failed: unexpected tags payload")
                    return _BackendTagSelection(error_reason="github_unreachable")
                for tag_payload in tags:
                    if not isinstance(tag_payload, Mapping):
                        continue
                    tag = _string_from_mapping_field(tag_payload, "name")
                    if tag:
                        tag_names.append(tag)
        return _select_latest_candidate_from_tag_names(
            tag_names,
            allow_prerelease=self.allow_prerelease,
            channel=channel,
        )

    async def _fetch_latest_candidate_from_atom(
        self,
        client: httpx.AsyncClient,
        *,
        channel: str,
    ) -> _BackendTagSelection:
        try:
            resp = await client.get(
                _GITHUB_TAGS_ATOM,
                headers={"Accept": "application/atom+xml"},
            )
        except Exception as exc:
            logger.warning("Auto-update Atom tag fallback failed: %s", exc)
            return _BackendTagSelection(error_reason="github_unreachable")
        if resp.status_code != 200:
            logger.warning("Auto-update Atom tag fallback failed: HTTP %s", resp.status_code)
            return _BackendTagSelection(error_reason="github_unreachable")
        tag_names = _tag_names_from_atom(resp.text)
        if not tag_names:
            logger.warning("Auto-update Atom tag fallback failed: unexpected tags payload")
            return _BackendTagSelection(error_reason="github_unreachable")
        return _select_latest_candidate_from_tag_names(
            tag_names,
            allow_prerelease=self.allow_prerelease,
            channel=channel,
        )

    async def _fetch_latest_version(self) -> str:
        """查询 GitHub tag 以获取最新的 backend 版本 tag。"""
        return (await self._fetch_latest_candidate()).tag

    async def _check_apply_guards(self, tag: str) -> str:
        """当本地状态使 apply 不安全时返回稳定 reason。"""
        # PyInstaller 桌面包即使与共置的 git checkout 共享数据 root
        # 也报告 ``frozen``（entry.py 将 OPENBILICLAW_PROJECT_ROOT 指向
        # ~/OpenBiliClaw，与 AI / 一行安装使用的同一目录）。fast-forward
        # 该 checkout 会在打包二进制重启时继续运行其捆绑的旧代码的
        # 同时 mutate 别人的源码 + venv —— 一个无尽的更新循环。
        # 在结构上拒绝，无论磁盘上的 ``.git``。
        if detect_install_mode() != "git":
            return "unsupported_install_mode"
        root = _project_root()
        if not (root / ".git").exists():
            inside = await self._run_git(["rev-parse", "--is-inside-work-tree"], root)
            if inside.returncode != 0 or inside.stdout.strip().lower() != "true":
                return "unsupported_install_mode"

        remote = await self._run_git(["config", "--get", "remote.origin.url"], root)
        remote_url = remote.stdout.strip() if remote.returncode == 0 else ""
        if not remote_url or _remote_has_credentials(remote_url):
            return "untrusted_remote"
        if remote_url not in set(self.allowed_remotes):
            return "untrusted_remote"

        status = await self._run_git(["status", "--porcelain"], root)
        if status.returncode != 0:
            return "unsupported_install_mode"
        if _dirty_paths_besides_uv_lock(status.stdout):
            return "dirty_worktree"

        git_dir = await self._run_git(["rev-parse", "--git-dir"], root)
        if git_dir.returncode != 0:
            return "unsupported_install_mode"
        if _merge_or_rebase_in_progress(root, git_dir.stdout.strip()):
            return "merge_or_rebase_in_progress"

        fetch = await self._run_git(["fetch", "--force", "--tags", "origin"], root, timeout=120)
        if fetch.returncode != 0:
            return "github_unreachable"

        target = await self._run_git(["rev-parse", "--verify", f"{tag}^{{commit}}"], root)
        if target.returncode != 0:
            return "missing_target_tag"

        ff = await self._run_git(["merge-base", "--is-ancestor", "HEAD", tag], root)
        if ff.returncode != 0:
            return "branch_not_fast_forwardable"
        return ""

    async def _apply_update_to_tag(self, tag: str) -> None:
        """Fast-forward 到 *tag*，重装依赖，并重启。"""
        root = _project_root()
        try:
            # 丢弃本地 uv.lock 重写（陈旧 lock 发布让 uv sync
            # 在安装时弄脏它），以便 --ff-only 不会被"本地更改
            # 会被覆盖"拒绝；合并后的 sync 重新生成它。
            await self._run_git(["checkout", "--", "uv.lock"], root)

            merge = await self._run_git(["merge", "--ff-only", tag], root, timeout=120)
            if merge.returncode != 0:
                await self._mark_apply_failed("branch_not_fast_forwardable")
                return

            install_cmd = self._detect_install_command(root)
            install = await self._run_command(install_cmd, root, timeout=300)
            if install.returncode != 0:
                await self._mark_apply_failed("dependency_sync_failed")
                return

            self._state = "restart_pending"
            self._reason = "none"
            self._update_error = ""
            await self._publish_event(
                {
                    "type": "backend_restart_pending",
                    "latest_tag": tag,
                }
            )
            try:
                logger.info("Auto-update applied; restarting process for %s", tag)
                self._restart_process()
            except Exception as exc:
                logger.error("Auto-update restart failed: %s", exc)
                await self._mark_apply_failed("restart_failed")
        except Exception:
            logger.exception("Auto-update apply failed")
            await self._mark_apply_failed("dependency_sync_failed")

    async def _mark_apply_failed(self, reason: str) -> None:
        self._state = "error"
        self._reason = reason
        self._update_error = reason
        await self._publish_event({"type": "backend_update_failed", "reason": reason})

    async def _publish_event(self, event: dict[str, object]) -> None:
        if self.event_publisher is None:
            return
        try:
            result = self.event_publisher(dict(event))
            if hasattr(result, "__await__"):
                await result
        except Exception:
            logger.debug("Runtime update event publish failed", exc_info=True)

    def _apply_response(
        self,
        *,
        state: str,
        reason: str,
        accepted: bool,
    ) -> dict[str, object]:
        return {
            "target": "backend",
            "state": state,
            "reason": reason,
            "accepted": accepted,
            "observe_via": _OBSERVE_VIA,
        }

    async def _run_git(
        self,
        args: Sequence[str],
        root: Path,
        *,
        timeout: int = 30,
    ) -> subprocess.CompletedProcess[str]:
        return await self._run_command(["git", *args], root, timeout=timeout)

    async def _run_command(
        self,
        command: Sequence[str],
        root: Path,
        *,
        timeout: int,
    ) -> subprocess.CompletedProcess[str]:
        args = list(command)
        proc = await asyncio.create_subprocess_exec(
            *args,
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            stdout_data, stderr_data = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except TimeoutError as exc:
            proc.kill()
            stdout_data, stderr_data = await proc.communicate()
            raise subprocess.TimeoutExpired(
                args,
                timeout,
                output=_decode_process_output(stdout_data),
                stderr=_decode_process_output(stderr_data),
            ) from exc
        returncode = proc.returncode if proc.returncode is not None else -1
        return subprocess.CompletedProcess(
            args,
            returncode,
            _decode_process_output(stdout_data),
            _decode_process_output(stderr_data),
        )

    @staticmethod
    def _detect_install_command(root: Path) -> list[str]:
        """根据项目环境检测最佳安装命令。"""
        # 如果 uv.lock 存在则优先使用 uv
        if (root / "uv.lock").exists():
            return ["uv", "sync"]
        # 回退到 pip
        return [sys.executable, "-m", "pip", "install", "-e", "."]

    @staticmethod
    def _restart_process() -> None:
        """用相同的参数重启当前进程。"""
        logger.info("Restarting process: %s %s", sys.executable, sys.argv)
        os.execv(sys.executable, [sys.executable, *sys.argv])
