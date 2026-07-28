"""
browser_cdp 内置技能 — 基于 Chrome DevTools Protocol (CDP) 的浏览器自动化。
支持页面导航、点击、输入、截图、JS 求值等无头浏览器操作。
"""
from typing import Any, Optional
from loguru import logger

SKILL_NAME = "browser_cdp"
SKILL_DESCRIPTION = "Chrome DevTools Protocol 浏览器自动化，支持导航/点击/输入/截图/页面求值"

try:
    import asyncio as _asyncio
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
    **kwargs: Any,
) -> dict[str, Any]:
    """
    执行浏览器 CDP 操作。

    Args:
        action: 操作类型（navigate/click/type/screenshot/evaluate/get_text/get_html）
        url: 目标 URL
        selector: CSS 选择器
        text: 输入文本或验证文本
        script: JavaScript 脚本

    Returns:
        操作结果
    """
    if not HAS_PLAYWRIGHT:
        return {
            "success": False,
            "error": "缺少 playwright 依赖，请运行: pip install playwright && playwright install chromium",
        }

    valid_actions = {"navigate", "click", "type", "screenshot", "evaluate", "get_text", "get_html"}
    if action not in valid_actions:
        return {"success": False, "error": f"不支持的操作: {action}，支持: {', '.join(sorted(valid_actions))}"}

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                page = await browser.new_page()

                if action == "navigate":
                    if not url:
                        return {"success": False, "error": "navigate 需要提供 url"}
                    await page.goto(url, wait_until="networkidle")
                    title = await page.title()
                    content = await page.content()
                    return {
                        "success": True,
                        "action": "navigate",
                        "url": url,
                        "title": title,
                        "html_length": len(content),
                    }

                elif action == "click":
                    if not selector:
                        return {"success": False, "error": "click 需要提供 selector"}
                    if url:
                        await page.goto(url, wait_until="networkidle")
                    await page.click(selector)
                    await page.wait_for_timeout(1000)
                    content = await page.content()
                    return {
                        "success": True,
                        "action": "click",
                        "selector": selector,
                        "html_length": len(content),
                    }

                elif action == "type":
                    if not selector or text is None:
                        return {"success": False, "error": "type 需要提供 selector 和 text"}
                    if url:
                        await page.goto(url, wait_until="networkidle")
                    await page.fill(selector, text)
                    return {
                        "success": True,
                        "action": "type",
                        "selector": selector,
                    }

                elif action == "screenshot":
                    if not url:
                        return {"success": False, "error": "screenshot 需要提供 url"}
                    await page.goto(url, wait_until="networkidle")
                    output_path = kwargs.get("output_path", "screenshot.png")
                    await page.screenshot(path=output_path, full_page=True)
                    return {
                        "success": True,
                        "action": "screenshot",
                        "url": url,
                        "output": output_path,
                    }

                elif action == "evaluate":
                    if not script:
                        return {"success": False, "error": "evaluate 需要提供 script"}
                    if url:
                        await page.goto(url, wait_until="networkidle")
                    result = await page.evaluate(script)
                    return {
                        "success": True,
                        "action": "evaluate",
                        "result": result,
                    }

                elif action == "get_text":
                    if not selector:
                        return {"success": False, "error": "get_text 需要提供 selector"}
                    if url:
                        await page.goto(url, wait_until="networkidle")
                    element_text = await page.text_content(selector)
                    return {
                        "success": True,
                        "action": "get_text",
                        "selector": selector,
                        "text": element_text or "",
                    }

                elif action == "get_html":
                    if url:
                        await page.goto(url, wait_until="networkidle")
                    html = await page.content()
                    return {
                        "success": True,
                        "action": "get_html",
                        "url": url or page.url,
                        "html": html[:5000],
                        "truncated": len(html) > 5000,
                    }

                return {"success": False, "error": "未识别的操作"}
            finally:
                await browser.close()

    except Exception as e:
        logger.bind(event="browser_cdp_error", action=action).error(f"CDP 操作失败: {str(e)}")
        return {"success": False, "error": f"CDP 操作失败: {str(e)}"}
