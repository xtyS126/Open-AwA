"""
browser_visible 内置技能 — 可见浏览器操作，适用于需要人工参与的浏览器场景。
与 browser_cdp 不同，此技能启动可见浏览器窗口，方便用户观察和交互。
"""
from typing import Any, Optional
from loguru import logger

SKILL_NAME = "browser_visible"
SKILL_DESCRIPTION = "可见浏览器自动化操作，适用于需人工参与的浏览器场景，支持导航/截图/表单填写"

try:
    HAS_PLAYWRIGHT = False
    try:
        from playwright.async_api import async_playwright
        HAS_PLAYWRIGHT = True
    except ImportError:
        pass
except ImportError:
    HAS_PLAYWRIGHT = False


async def execute(
    action: str,
    url: Optional[str] = None,
    selector: Optional[str] = None,
    text: Optional[str] = None,
    script: Optional[str] = None,
    wait_seconds: Optional[int] = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """
    执行可见浏览器操作。

    Args:
        action: 操作类型（open/navigate/click/type/screenshot/fill_form/evaluate/close）
        url: 目标 URL
        selector: CSS 选择器
        text: 输入文本
        script: JavaScript 脚本
        wait_seconds: 操作后等待秒数（用于人工观察）

    Returns:
        操作结果
    """
    if not HAS_PLAYWRIGHT:
        return {
            "success": False,
            "error": "缺少 playwright 依赖，请运行: pip install playwright && playwright install chromium",
        }

    valid_actions = {"open", "navigate", "click", "type", "screenshot", "fill_form", "evaluate", "close"}
    if action not in valid_actions:
        return {"success": False, "error": f"不支持的操作: {action}，支持: {', '.join(sorted(valid_actions))}"}

    try:
        async with async_playwright() as p:
            # 启动可见浏览器窗口
            browser = await p.chromium.launch(headless=False, slow_mo=100)
            context = await browser.new_context()
            page = await context.new_page()

            wait_ms = (wait_seconds or 0) * 1000 if wait_seconds else 0

            if action == "open" or action == "navigate":
                if not url:
                    await browser.close()
                    return {"success": False, "error": f"{action} 需要提供 url"}
                await page.goto(url, wait_until="networkidle")
                if wait_ms:
                    await page.wait_for_timeout(wait_ms)
                title = await page.title()
                await browser.close()
                return {
                    "success": True,
                    "action": action,
                    "url": url,
                    "title": title,
                }

            elif action == "click":
                if not selector:
                    await browser.close()
                    return {"success": False, "error": "click 需要提供 selector"}
                if url:
                    await page.goto(url, wait_until="networkidle")
                await page.click(selector)
                if wait_ms:
                    await page.wait_for_timeout(wait_ms)
                await browser.close()
                return {"success": True, "action": "click", "selector": selector}

            elif action == "type":
                if not selector or text is None:
                    await browser.close()
                    return {"success": False, "error": "type 需要提供 selector 和 text"}
                if url:
                    await page.goto(url, wait_until="networkidle")
                await page.fill(selector, text)
                if wait_ms:
                    await page.wait_for_timeout(wait_ms)
                await browser.close()
                return {"success": True, "action": "type", "selector": selector}

            elif action == "screenshot":
                if not url:
                    await browser.close()
                    return {"success": False, "error": "screenshot 需要提供 url"}
                await page.goto(url, wait_until="networkidle")
                if wait_ms:
                    await page.wait_for_timeout(wait_ms)
                output_path = kwargs.get("output_path", "visible_screenshot.png")
                await page.screenshot(path=output_path, full_page=True)
                await browser.close()
                return {
                    "success": True,
                    "action": "screenshot",
                    "url": url,
                    "output": output_path,
                }

            elif action == "fill_form":
                if not url:
                    await browser.close()
                    return {"success": False, "error": "fill_form 需要提供 url"}
                await page.goto(url, wait_until="networkidle")
                # 从 kwargs 中获取表单字段映射
                fields = kwargs.get("fields", {})
                filled = []
                for field_sel, field_val in fields.items():
                    try:
                        await page.fill(field_sel, str(field_val))
                        filled.append(field_sel)
                    except Exception as e:
                        logger.warning(f"填充字段 {field_sel} 失败: {str(e)}")
                if wait_ms:
                    await page.wait_for_timeout(wait_ms)
                await browser.close()
                return {
                    "success": True,
                    "action": "fill_form",
                    "filled_fields": filled,
                    "total_fields": len(fields),
                }

            elif action == "evaluate":
                if not script:
                    await browser.close()
                    return {"success": False, "error": "evaluate 需要提供 script"}
                if url:
                    await page.goto(url, wait_until="networkidle")
                result = await page.evaluate(script)
                if wait_ms:
                    await page.wait_for_timeout(wait_ms)
                await browser.close()
                return {"success": True, "action": "evaluate", "result": result}

            elif action == "close":
                await browser.close()
                return {"success": True, "action": "close", "note": "浏览器已关闭"}

            await browser.close()
            return {"success": False, "error": "未识别的操作"}

    except Exception as e:
        logger.bind(event="browser_visible_error", action=action).error(f"可见浏览器操作失败: {str(e)}")
        return {"success": False, "error": f"可见浏览器操作失败: {str(e)}"}
