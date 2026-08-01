"""分别验证 Open-AwA 非流、SSE 与 WebSocket 聊天传输。"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

from playwright.sync_api import APIRequestContext, Page, sync_playwright


BASE_URL = os.getenv("OPENAWA_BROWSER_BASE_URL", "http://127.0.0.1:15173")
BACKEND_URL = os.getenv(
    "OPENAWA_BACKEND_BASE_URL",
    f"http://127.0.0.1:{os.getenv('OPENAWA_E2E_BACKEND_PORT', '18000')}",
)
API_KEY = os.getenv(
    "OPENAWA_E2E_API_KEY",
    "openawa-e2e-api-key-at-least-32-characters",
)
OWNER_PASSWORD = os.getenv("OPENAWA_ADMIN_PASSWORD", "OpenAwAE2e1")
CHROMIUM_PATH = os.getenv(
    "OPENAWA_CHROMIUM_PATH",
    r"C:\Users\23941\AppData\Local\ms-playwright\chromium-1208\chrome-win64\chrome.exe",
)
OUTPUT_DIR = Path(
    os.getenv(
        "OPENAWA_BROWSER_OUTPUT_DIR",
        r"D:\代码\Open-AwA\var\test-runs\score-boost-20260801\chat-transport",
    )
)
REQUEST_TIMEOUT_MS = int(os.getenv("OPENAWA_CHAT_PROBE_TIMEOUT_MS", "60000"))


def _login(page: Page) -> None:
    """完成隔离环境首次初始化并通过访问密钥进入聊天页。"""
    page.goto(f"{BASE_URL}/", wait_until="domcontentloaded")
    page.wait_for_load_state("networkidle")
    if page.url.endswith("/setup"):
        page.get_by_label("密码", exact=True).fill(OWNER_PASSWORD)
        page.get_by_label("确认密码").fill(OWNER_PASSWORD)
        page.get_by_role("button", name="完成部署初始化").click()
        page.wait_for_url(re.compile(r"/login$"), timeout=30_000)
        page.wait_for_load_state("networkidle")
    page.get_by_label("访问密钥").fill(API_KEY)
    page.get_by_role("button", name="连接").click()
    page.wait_for_url(re.compile(r"/chat(?:/|$)"), timeout=30_000)
    page.get_by_test_id("chat-input-container").wait_for(
        state="visible",
        timeout=30_000,
    )


def _create_session(api: APIRequestContext, transport: str) -> str:
    """为单条传输检查创建独立会话。"""
    response = api.post(
        "/api/conversations",
        data={"title": f"{transport} 传输验收 {int(time.time() * 1000)}"},
        timeout=REQUEST_TIMEOUT_MS,
    )
    if response.status not in {200, 201}:
        raise AssertionError(
            f"创建会话返回 {response.status}: {response.text()[:300]}"
        )
    return str(response.json()["session_id"])


def _probe_nonstream(api: APIRequestContext, session_id: str) -> dict[str, Any]:
    """验证非流请求在时限内返回合法终态。"""
    response = api.post(
        "/api/chat",
        data={
            "session_id": session_id,
            "message": "请回复非流传输验收",
            "mode": "non-stream",
        },
        timeout=REQUEST_TIMEOUT_MS,
    )
    if response.status != 200:
        raise AssertionError(
            f"非流请求返回 {response.status}: {response.text()[:300]}"
        )
    payload = response.json()
    if payload.get("status") not in {"success", "error", "cancelled"}:
        raise AssertionError(f"非流终态无效: {payload}")
    return {
        "http_status": response.status,
        "status": payload.get("status"),
        "error": payload.get("error"),
    }


def _probe_sse(api: APIRequestContext, session_id: str) -> dict[str, Any]:
    """验证 SSE 响应类型、数据帧与结束帧。"""
    response = api.post(
        "/api/chat",
        data={
            "session_id": session_id,
            "message": "请回复 SSE 传输验收",
            "mode": "stream",
        },
        timeout=REQUEST_TIMEOUT_MS,
    )
    content_type = response.headers.get("content-type", "")
    body = response.text()
    if response.status != 200 or "text/event-stream" not in content_type:
        raise AssertionError(
            f"SSE 返回异常: status={response.status}, content-type={content_type}"
        )
    if "data:" not in body or "data: [DONE]" not in body:
        raise AssertionError(f"SSE 帧不完整: {body[:500]}")
    return {
        "http_status": response.status,
        "content_type": content_type,
        "has_done": True,
        "body_prefix": body[:500],
    }


def _get_websocket_token(api: APIRequestContext) -> str:
    """使用隔离环境管理员凭据获取 WebSocket 所需的短期令牌。"""
    response = api.post(
        "/api/auth/login",
        form={"username": "admin", "password": OWNER_PASSWORD},
        timeout=REQUEST_TIMEOUT_MS,
    )
    if response.status != 200:
        raise AssertionError(
            f"获取 WebSocket 令牌返回 {response.status}: {response.text()[:300]}"
        )
    token = str(response.json().get("access_token") or "")
    if not token:
        raise AssertionError("登录响应缺少 access_token")
    return token


def _probe_websocket(
    page: Page,
    api: APIRequestContext,
    session_id: str,
) -> dict[str, Any]:
    """通过真实 Chromium 验证 WebSocket 握手与业务终态帧。"""
    token = _get_websocket_token(api)
    websocket_url = re.sub(r"^http", "ws", BACKEND_URL)
    result = page.evaluate(
        """
        ({ url, protocol, content, timeoutMs }) => new Promise((resolve, reject) => {
          const socket = new WebSocket(url, [protocol])
          const messages = []
          let settled = false
          const timeout = window.setTimeout(() => {
            settled = true
            socket.close()
            reject(new Error(`WebSocket 超时，已收到 ${messages.length} 帧`))
          }, timeoutMs)
          socket.onopen = () => {
            socket.send(JSON.stringify({
              type: 'message',
              content,
              request_id: `browser-${Date.now()}`
            }))
          }
          socket.onerror = () => {
            settled = true
            window.clearTimeout(timeout)
            reject(new Error('WebSocket 连接错误'))
          }
          socket.onclose = (event) => {
            if (!settled) {
              settled = true
              window.clearTimeout(timeout)
              reject(new Error(
                `WebSocket 提前关闭 code=${event.code} reason=${event.reason} frames=${messages.length}`
              ))
            }
          }
          socket.onmessage = (event) => {
            const payload = JSON.parse(event.data)
            messages.push(payload)
            if (payload.type === 'response' || payload.type === 'error') {
              settled = true
              window.clearTimeout(timeout)
              socket.close()
              resolve({
                protocolAccepted: socket.protocol.startsWith('bearer.'),
                messageTypes: messages.map((item) => item.type),
                final: payload
              })
            }
          }
        })
        """,
        {
            "url": f"{websocket_url}/api/chat/ws/{session_id}",
            "protocol": f"bearer.{token}",
            "content": "请回复 WebSocket 传输验收",
            "timeoutMs": REQUEST_TIMEOUT_MS,
        },
    )
    message_types = result.get("messageTypes", [])
    if not any(
        item in {"response_chunk", "response", "error"}
        for item in message_types
    ):
        raise AssertionError(f"WebSocket 未返回终态帧: {result}")
    return result


def main() -> int:
    """执行单条传输检查并写入结构化证据。"""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "transport",
        choices=("nonstream", "sse", "websocket"),
    )
    args = parser.parse_args()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    report: dict[str, Any] = {
        "transport": args.transport,
        "base_url": BASE_URL,
    }

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=True,
                executable_path=CHROMIUM_PATH,
            )
            context = browser.new_context(locale="zh-CN")
            page = context.new_page()
            api = playwright.request.new_context(
                base_url=BASE_URL,
                extra_http_headers={"Authorization": f"Bearer {API_KEY}"},
            )
            _login(page)
            session_id = _create_session(api, args.transport)
            if args.transport == "nonstream":
                detail = _probe_nonstream(api, session_id)
            elif args.transport == "sse":
                detail = _probe_sse(api, session_id)
            else:
                detail = _probe_websocket(page, api, session_id)
            report.update(
                {
                    "status": "ok",
                    "session_id": session_id,
                    "detail": detail,
                }
            )
            api.dispose()
            context.close()
            browser.close()
    except Exception as exc:
        report.update({"status": "fail", "error": str(exc)})

    report["duration_ms"] = round((time.perf_counter() - started) * 1000, 2)
    report_path = OUTPUT_DIR / f"{args.transport}.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"REPORT_PATH={report_path}")
    return 0 if report["status"] == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
