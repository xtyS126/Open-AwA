"""执行 Open-AwA 评分提升任务的真实 Chromium 验收。"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Callable

from playwright.sync_api import Page, sync_playwright


BASE_URL = os.getenv("OPENAWA_BROWSER_BASE_URL", "http://127.0.0.1:15173")
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
        r"D:\代码\Open-AwA\var\test-runs\score-boost-20260731\browser",
    )
)
AXE_PATH = Path(__file__).resolve().parents[1] / "node_modules" / "axe-core" / "axe.min.js"


def _assert_single_landmarks(page: Page, route: str) -> dict[str, Any]:
    """校验页面主地标、标题和重复 ID。"""
    main_count = page.locator("main").count()
    heading_count = page.locator("h1").count()
    duplicate_ids = page.evaluate(
        """
        () => {
          const ids = Array.from(document.querySelectorAll('[id]')).map((node) => node.id)
          return ids.filter((id, index) => ids.indexOf(id) !== index)
        }
        """
    )
    if main_count != 1:
        raise AssertionError(f"{route} 的 main 数量为 {main_count}，预期为 1")
    if heading_count != 1:
        raise AssertionError(f"{route} 的 h1 数量为 {heading_count}，预期为 1")
    if duplicate_ids:
        raise AssertionError(f"{route} 存在重复 ID: {duplicate_ids}")
    return {
        "route": route,
        "main_count": main_count,
        "h1_count": heading_count,
        "duplicate_ids": duplicate_ids,
    }


def _run_axe(page: Page, route: str) -> dict[str, Any]:
    """在真实浏览器中执行 axe，并单独核验颜色对比度。"""
    page.add_script_tag(path=str(AXE_PATH))
    result = page.evaluate(
        """
        async () => {
          return await window.axe.run(document, {
            runOnly: {
              type: 'tag',
              values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']
            }
          })
        }
        """
    )
    violations = result.get("violations", [])
    severe = [
        item
        for item in violations
        if item.get("impact") in {"serious", "critical"}
    ]
    contrast = [item for item in violations if item.get("id") == "color-contrast"]
    if severe:
        summary = [
            {
                "id": item.get("id"),
                "impact": item.get("impact"),
                "nodes": len(item.get("nodes", [])),
            }
            for item in severe
        ]
        raise AssertionError(f"{route} 存在严重 axe 违规: {summary}")
    if contrast:
        raise AssertionError(
            f"{route} 存在颜色对比度违规，节点数为 "
            f"{sum(len(item.get('nodes', [])) for item in contrast)}"
        )
    return {
        "route": route,
        "violations": [
            {
                "id": item.get("id"),
                "impact": item.get("impact"),
                "nodes": len(item.get("nodes", [])),
            }
            for item in violations
        ],
        "color_contrast_violations": 0,
    }


def _check(name: str, fn: Callable[[], Any], records: list[dict[str, Any]]) -> None:
    """执行单项检查并保留结构化结果。"""
    started = time.perf_counter()
    try:
        detail = fn()
    except Exception as exc:
        records.append(
            {
                "name": name,
                "status": "fail",
                "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                "error": str(exc),
            }
        )
    else:
        records.append(
            {
                "name": name,
                "status": "ok",
                "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                "detail": detail,
            }
        )


def main() -> int:
    """运行浏览器验收并返回进程退出码。"""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    console_issues: list[dict[str, str]] = []
    page_errors: list[str] = []
    failed_requests: list[dict[str, str]] = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            executable_path=CHROMIUM_PATH,
        )
        context = browser.new_context(
            viewport={"width": 1440, "height": 900},
            locale="zh-CN",
        )
        api_context = playwright.request.new_context(
            base_url=BASE_URL,
            extra_http_headers={"Authorization": f"Bearer {API_KEY}"},
        )
        page = context.new_page()
        page.on(
            "console",
            lambda message: console_issues.append(
                {"type": message.type, "text": message.text}
            )
            if message.type in {"warning", "error"}
            else None,
        )
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        page.on(
            "requestfailed",
            lambda request: failed_requests.append(
                {
                    "url": request.url,
                    "error": request.failure or "unknown",
                }
            ),
        )

        def login() -> dict[str, Any]:
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
            return {"url": page.url}

        _check("登录并进入聊天页", login, records)

        def service_health() -> dict[str, Any]:
            ping = api_context.get("/api/system/ping")
            health = api_context.get("/api/system/health")
            if ping.status != 200:
                raise AssertionError(f"ping 返回 {ping.status}")
            if health.status != 200:
                raise AssertionError(f"health 返回 {health.status}")
            return {"ping": ping.json(), "health": health.json()}

        _check("服务 ping 与 health", service_health, records)

        def retired_scheduler_is_not_advertised() -> dict[str, Any]:
            """校验插件 API 与动态配置页均不再暴露已退役调度入口。"""
            plugins_response = api_context.get("/api/plugins")
            if plugins_response.status != 200:
                raise AssertionError(
                    f"插件列表返回 {plugins_response.status}: "
                    f"{plugins_response.text()[:200]}"
                )
            plugins = plugins_response.json()
            plugin = next(
                (
                    item
                    for item in plugins
                    if item.get("name") == "bilibili-toolkit-builtin"
                ),
                None,
            )
            if plugin is None:
                raise AssertionError("插件列表中缺少 bilibili-toolkit-builtin")

            plugin_id = str(plugin["id"])
            schema_response = api_context.get(
                f"/api/plugins/{plugin_id}/config/schema"
            )
            if schema_response.status != 200:
                raise AssertionError(
                    f"插件 schema 返回 {schema_response.status}: "
                    f"{schema_response.text()[:200]}"
                )
            properties = schema_response.json().get("schema", {}).get(
                "properties", {}
            )
            if "trigger" in properties:
                raise AssertionError("插件 schema 仍暴露 trigger 配置")

            page.goto(
                f"{BASE_URL}/plugins/config/{plugin_id}",
                wait_until="domcontentloaded",
            )
            page.get_by_role("heading", name="插件配置").wait_for(
                state="visible",
                timeout=20_000,
            )
            page.wait_for_timeout(300)
            if page.get_by_text("调度触发器", exact=True).count() != 0:
                raise AssertionError("动态配置页仍渲染调度触发器")
            return {
                "plugin_id": plugin_id,
                "schema_has_trigger": False,
                "ui_trigger_controls": 0,
            }

        _check(
            "统一调度迁移后的插件配置入口",
            retired_scheduler_is_not_advertised,
            records,
        )

        def history_restore() -> dict[str, Any]:
            suffix = str(int(time.time() * 1000))
            title = f"评分验收会话 {suffix}"
            user_message = f"评分验收用户消息 {suffix}"
            assistant_message = f"评分验收助手回复 {suffix}"
            created = api_context.post(
                "/api/conversations",
                data={"title": title},
            )
            if created.status not in {200, 201}:
                raise AssertionError(
                    f"创建会话返回 {created.status}: {created.text()[:200]}"
                )
            session_id = created.json()["session_id"]
            for role, content in (
                ("user", user_message),
                ("assistant", assistant_message),
            ):
                response = api_context.post(
                    "/api/memory/short-term",
                    data={
                        "session_id": session_id,
                        "role": role,
                        "content": content,
                    },
                )
                if response.status not in {200, 201}:
                    raise AssertionError(
                        f"写入历史消息返回 {response.status}: {response.text()[:200]}"
                    )
            page.goto(
                f"{BASE_URL}/chat/{session_id}",
                wait_until="domcontentloaded",
            )
            page.get_by_text(user_message, exact=True).wait_for(
                state="visible",
                timeout=20_000,
            )
            page.get_by_text(assistant_message, exact=True).wait_for(
                state="visible",
                timeout=20_000,
            )
            page.reload(wait_until="domcontentloaded")
            page.get_by_text(user_message, exact=True).wait_for(
                state="visible",
                timeout=20_000,
            )
            return {"session_id": session_id, "title": title}

        _check("历史消息刷新恢复", history_restore, records)

        def chat_transport_paths() -> dict[str, Any]:
            """验证真实端口上的非流、SSE 与 WebSocket 聊天协议。"""
            suffix = str(int(time.time() * 1000))
            created = api_context.post(
                "/api/conversations",
                data={"title": f"传输验收会话 {suffix}"},
            )
            if created.status not in {200, 201}:
                raise AssertionError(
                    f"创建传输会话返回 {created.status}: {created.text()[:200]}"
                )
            session_id = created.json()["session_id"]

            nonstream = api_context.post(
                "/api/chat",
                data={
                    "session_id": session_id,
                    "message": "请回复传输验收",
                    "mode": "non-stream",
                },
                timeout=60_000,
            )
            if nonstream.status != 200:
                raise AssertionError(
                    f"非流式聊天返回 {nonstream.status}: {nonstream.text()[:200]}"
                )
            nonstream_payload = nonstream.json()
            if nonstream_payload.get("status") not in {
                "success",
                "error",
                "cancelled",
            }:
                raise AssertionError(
                    f"非流式聊天终态无效: {nonstream_payload}"
                )

            sse = api_context.post(
                "/api/chat",
                data={
                    "session_id": session_id,
                    "message": "请回复 SSE 传输验收",
                    "mode": "stream",
                },
                timeout=60_000,
            )
            content_type = sse.headers.get("content-type", "")
            sse_body = sse.text()
            if sse.status != 200 or "text/event-stream" not in content_type:
                raise AssertionError(
                    f"SSE 返回异常: status={sse.status}, content-type={content_type}"
                )
            if "data:" not in sse_body or "data: [DONE]" not in sse_body:
                raise AssertionError(f"SSE 帧不完整: {sse_body[:500]}")

            websocket_url = re.sub(r"^http", "ws", BASE_URL)
            websocket_result = page.evaluate(
                """
                ({ url, protocol, content }) => new Promise((resolve, reject) => {
                  const socket = new WebSocket(url, [protocol])
                  const messages = []
                  const timeout = window.setTimeout(() => {
                    socket.close()
                    reject(new Error(`WebSocket 超时，已收到 ${messages.length} 帧`))
                  }, 60000)
                  socket.onopen = () => {
                    socket.send(JSON.stringify({
                      type: 'message',
                      content,
                      request_id: `browser-${Date.now()}`
                    }))
                  }
                  socket.onerror = () => {
                    window.clearTimeout(timeout)
                    reject(new Error('WebSocket 连接错误'))
                  }
                  socket.onmessage = (event) => {
                    const payload = JSON.parse(event.data)
                    messages.push(payload)
                    if (payload.type === 'response' || payload.type === 'error') {
                      window.clearTimeout(timeout)
                      socket.close()
                      resolve({
                        protocol: socket.protocol,
                        messageTypes: messages.map((item) => item.type),
                        final: payload
                      })
                    }
                  }
                })
                """,
                {
                    "url": f"{websocket_url}/api/chat/ws/{session_id}",
                    "protocol": f"bearer.{API_KEY}",
                    "content": "请回复 WebSocket 传输验收",
                },
            )
            message_types = websocket_result.get("messageTypes", [])
            if not any(
                item in {"response_chunk", "response", "error"}
                for item in message_types
            ):
                raise AssertionError(
                    f"WebSocket 未返回响应帧: {websocket_result}"
                )

            return {
                "session_id": session_id,
                "nonstream_status": nonstream_payload.get("status"),
                "nonstream_error": nonstream_payload.get("error"),
                "sse_content_type": content_type,
                "sse_has_done": True,
                "websocket": websocket_result,
            }

        _check("真实聊天非流、SSE 与 WebSocket", chat_transport_paths, records)

        def route_and_accessibility(route: str) -> dict[str, Any]:
            page.goto(f"{BASE_URL}{route}", wait_until="domcontentloaded")
            page.wait_for_function(
                """
                () => document.querySelectorAll('main').length === 1
                  && document.querySelectorAll('h1').length === 1
                """,
                timeout=20_000,
            )
            page.wait_for_timeout(300)
            landmarks = _assert_single_landmarks(page, route)
            axe = _run_axe(page, route)
            return {"landmarks": landmarks, "axe": axe}

        for current_route in ("/chat", "/dashboard", "/settings"):
            _check(
                f"{current_route} 语义与真实 axe",
                lambda route=current_route: route_and_accessibility(route),
                records,
            )

        def rapid_navigation() -> dict[str, Any]:
            visited = []
            for route in (
                "/chat",
                "/dashboard",
                "/settings",
                "/chat",
                "/settings",
                "/dashboard",
            ):
                page.goto(f"{BASE_URL}{route}", wait_until="domcontentloaded")
                page.locator("main").wait_for(state="visible", timeout=20_000)
                visited.append(page.url)
            return {"visited": visited}

        _check("快速切页", rapid_navigation, records)

        def mobile_and_keyboard() -> dict[str, Any]:
            page.set_viewport_size({"width": 390, "height": 844})
            page.goto(f"{BASE_URL}/chat", wait_until="domcontentloaded")
            page.locator("main").wait_for(state="visible", timeout=20_000)
            overflow = page.evaluate(
                "() => document.documentElement.scrollWidth - document.documentElement.clientWidth"
            )
            if overflow > 1:
                raise AssertionError(f"390×844 横向溢出 {overflow}px")
            page.locator("body").click(position={"x": 1, "y": 1})
            page.keyboard.press("Tab")
            active = page.evaluate(
                """
                () => ({
                  tag: document.activeElement?.tagName || '',
                  role: document.activeElement?.getAttribute('role') || '',
                  name: document.activeElement?.getAttribute('aria-label')
                    || document.activeElement?.textContent?.trim().slice(0, 80)
                    || ''
                })
                """
            )
            if active.get("tag") in {"", "BODY", "HTML"}:
                raise AssertionError(f"Tab 后未进入可聚焦控件: {active}")
            screenshot_path = OUTPUT_DIR / "chat-mobile-390x844.png"
            page.screenshot(path=str(screenshot_path), full_page=True)
            return {
                "overflow_px": overflow,
                "first_focus": active,
                "screenshot": str(screenshot_path),
            }

        _check("390×844 与键盘焦点", mobile_and_keyboard, records)

        api_context.dispose()
        context.close()
        browser.close()

    unexpected_failed_requests = [
        item
        for item in failed_requests
        if "ERR_ABORTED" not in item["error"]
        and "NS_BINDING_ABORTED" not in item["error"]
    ]
    runtime = {
        "console_issues": console_issues,
        "page_errors": page_errors,
        "failed_requests": failed_requests,
        "unexpected_failed_requests": unexpected_failed_requests,
    }
    records.append(
        {
            "name": "浏览器运行时噪音",
            "status": (
                "ok"
                if not console_issues
                and not page_errors
                and not unexpected_failed_requests
                else "fail"
            ),
            "detail": runtime,
        }
    )
    failed = [record for record in records if record["status"] != "ok"]
    report = {
        "base_url": BASE_URL,
        "records": records,
        "passed": len(records) - len(failed),
        "failed": len(failed),
    }
    report_path = OUTPUT_DIR / "browser-acceptance.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"REPORT_PATH={report_path}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
