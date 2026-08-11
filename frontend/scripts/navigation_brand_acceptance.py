"""使用隔离服务验证五域导航、品牌壳层和关键响应式断点。"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from playwright.sync_api import Page, sync_playwright


BASE_URL = "http://127.0.0.1:15173"
API_KEY = "openawa-e2e-api-key-at-least-32-characters"
VIEWPORTS = [
    ("mobile-narrow", 375, 812),
    ("mobile", 480, 812),
    ("tablet", 768, 900),
    ("compact-desktop", 1024, 900),
    ("wide-desktop", 1440, 900),
]


def wait_for_app(page: Page) -> None:
    """等待动态应用完成首轮脚本和请求。"""
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_load_state("networkidle", timeout=30_000)


def initialize_and_login(page: Page) -> None:
    """在隔离后端中完成首次初始化并建立认证态。"""
    page.goto(f"{BASE_URL}/")
    wait_for_app(page)

    if page.url.endswith("/setup"):
        page.get_by_label("密码", exact=True).fill("OpenAwAE2e1")
        page.get_by_label("确认密码").fill("OpenAwAE2e1")
        page.get_by_role("button", name="完成部署初始化").click()
        page.wait_for_url("**/login", timeout=30_000)

    if not page.url.endswith("/login"):
        page.goto(f"{BASE_URL}/login")
    page.get_by_label("访问密钥").fill(API_KEY)
    page.get_by_role("button", name="连接").click()
    page.wait_for_url("**/assistant", timeout=30_000)
    page.get_by_test_id("chat-input-container").wait_for(state="visible", timeout=30_000)


def assert_no_horizontal_overflow(page: Page) -> None:
    """检查页面根布局没有产生横向溢出。"""
    metrics = page.evaluate(
        """() => ({
          documentWidth: document.documentElement.scrollWidth,
          viewportWidth: document.documentElement.clientWidth,
        })"""
    )
    if metrics["documentWidth"] > metrics["viewportWidth"] + 2:
        raise AssertionError(f"页面横向溢出: {metrics}")


def assert_no_domain_selected(page: Page, width: int) -> None:
    """账户与设置属于全局页面，不得错误标记任何工作域为当前页。"""
    navigation_name = "底部主导航" if width < 768 else "工作域"
    navigation = page.get_by_role("navigation", name=navigation_name)
    navigation.wait_for(state="visible")
    if navigation.locator('[aria-current="page"]').count() != 0:
        raise AssertionError(f"全局页面错误选中了工作域: {page.url}")


def verify_chat_shell_alignment(page: Page, width: int) -> None:
    """验证聊天输入区与 768px 壳层边界、移动底栏不存在重叠。"""
    page.goto("/assistant")
    # 聊天页存在长连接，不能用 networkidle 作为就绪条件。
    page.wait_for_load_state("domcontentloaded")
    chat_input = page.get_by_test_id("chat-input-container")
    chat_input.wait_for(state="visible")

    if width < 768:
        bottom_navigation = page.get_by_role("navigation", name="底部主导航")
        bottom_navigation.wait_for(state="visible")
        input_box = chat_input.bounding_box()
        navigation_box = bottom_navigation.bounding_box()
        if input_box is None or navigation_box is None:
            raise AssertionError("无法读取聊天输入区或移动底栏的布局尺寸")
        input_bottom = input_box["y"] + input_box["height"]
        if input_bottom > navigation_box["y"] + 2:
            raise AssertionError(
                f"聊天输入区与移动底栏重叠: input_bottom={input_bottom}, "
                f"navigation_top={navigation_box['y']}"
            )
    elif width == 768:
        position = chat_input.evaluate("element => getComputedStyle(element).position")
        if position == "fixed":
            raise AssertionError("768px 平板视口不应继续使用移动端固定聊天输入区")

    assert_no_horizontal_overflow(page)


def verify_viewport(browser, storage_state: dict, output_dir: Path, name: str, width: int, height: int) -> dict:
    """验证单个视口的导航结构和关键交互。"""
    context = browser.new_context(
        base_url=BASE_URL,
        locale="zh-CN",
        storage_state=storage_state,
        viewport={"width": width, "height": height},
    )
    context.add_init_script(
        f"try {{ window.sessionStorage.setItem('openawa_api_key', {json.dumps(API_KEY)}); }} catch {{}}"
    )
    page = context.new_page()
    page_errors: list[str] = []
    console_errors: list[str] = []
    navigation_events: list[str] = []
    page.on("pageerror", lambda error: page_errors.append(str(error)))
    page.on(
        "console",
        lambda message: console_errors.append(message.text) if message.type == "error" else None,
    )
    page.on(
        "framenavigated",
        lambda frame: navigation_events.append(frame.url) if frame == page.main_frame else None,
    )

    page.goto("/library/capabilities?type=plugin&view=installed")
    wait_for_app(page)
    page.get_by_role("heading", name="能力资源").wait_for(state="visible")
    page.get_by_role("button", name="打开全局搜索").wait_for(state="visible")

    if width < 768:
        page.get_by_role("navigation", name="底部主导航").wait_for(state="visible")
        if page.get_by_test_id("sidebar").is_visible():
            raise AssertionError("移动视口不应显示桌面领域轨道")
        if page.get_by_role("navigation", name="底部主导航").get_by_role("link").count() != 5:
            raise AssertionError("移动底栏必须固定为五个工作域")
    else:
        sidebar = page.get_by_test_id("sidebar")
        sidebar.wait_for(state="visible")
        expected_layout = "temporary" if width < 1024 else "collapsible" if width < 1440 else "wide"
        if sidebar.get_attribute("data-layout") != expected_layout:
            raise AssertionError(
                f"侧栏布局错误: 期望 {expected_layout}, 实际 {sidebar.get_attribute('data-layout')}"
            )
        if page.get_by_role("navigation", name="工作域").get_by_role("link").count() != 5:
            raise AssertionError("桌面领域轨道必须固定为五个工作域")

    assert_no_horizontal_overflow(page)

    if width <= 768:
        verify_chat_shell_alignment(page, width)
        page.goto("/library/capabilities?type=plugin&view=installed")
        wait_for_app(page)
        page.get_by_role("heading", name="能力资源").wait_for(state="visible")

    page.keyboard.press("Control+K")
    search_dialog = page.get_by_role("dialog", name="全局搜索")
    search_dialog.wait_for(state="visible")
    search_input = search_dialog.get_by_role("combobox", name="搜索页面与功能")
    search_input.fill("设置")
    settings_option = search_dialog.get_by_role("option", name="设置", exact=True)
    settings_option.wait_for(state="visible")
    if settings_option.get_attribute("aria-selected") != "true":
        raise AssertionError("全局搜索精确结果未成为当前键盘选项")
    search_input.press("Enter")
    try:
        page.wait_for_url("**/settings/general")
    except Exception:
        print(
            json.dumps(
                {
                    "event": "global_search_navigation_failed",
                    "viewport": f"{width}x{height}",
                    "url": page.url,
                    "dialog_visible": search_dialog.is_visible(),
                    "navigation_events": navigation_events,
                    "page_errors": page_errors,
                    "console_errors": console_errors,
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
        raise
    page.get_by_role("heading", name="设置", exact=True).wait_for(state="visible")
    assert_no_domain_selected(page, width)

    page.goto("/library/personas?view=discover")
    wait_for_app(page)
    page.get_by_role("heading", name="角色资源").wait_for(state="visible")
    page.goto("/library/knowledge?view=experience")
    wait_for_app(page)
    page.get_by_role("heading", name="知识资源").wait_for(state="visible")
    page.goto("/account?section=profile")
    wait_for_app(page)
    page.get_by_role("heading", name="账户").wait_for(state="visible")
    assert_no_domain_selected(page, width)

    page.goto("/library/capabilities?type=skill&view=installed")
    wait_for_app(page)

    screenshot = output_dir / f"navigation-brand-{name}-{width}x{height}.png"
    page.screenshot(path=str(screenshot), full_page=False)
    font_scale_screenshot: str | None = None
    if width >= 1440:
        page.evaluate("document.documentElement.style.fontSize = '200%'")
        assert_no_horizontal_overflow(page)
        skip_link_box = page.get_by_role("link", name="跳转到主内容").bounding_box()
        if skip_link_box is None or skip_link_box["y"] + skip_link_box["height"] > 0:
            raise AssertionError(f"200% 字体下未聚焦的跳转链接泄漏到视口: {skip_link_box}")
        font_scale_path = output_dir / f"navigation-brand-{name}-{width}x{height}-font-200.png"
        page.screenshot(path=str(font_scale_path), full_page=False)
        font_scale_screenshot = str(font_scale_path)

    result = {
        "name": name,
        "viewport": f"{width}x{height}",
        "screenshot": str(screenshot),
        "font_scale_screenshot": font_scale_screenshot,
        "page_errors": page_errors,
        "console_errors": console_errors,
    }
    context.close()

    if page_errors or console_errors:
        raise AssertionError(json.dumps(result, ensure_ascii=False))
    return result


def main() -> None:
    """运行设计要求的四档视口和额外窄屏验收，并输出证据路径。"""
    output_dir = Path(tempfile.mkdtemp(prefix="openawa-navigation-acceptance-"))
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        bootstrap_context = browser.new_context(base_url=BASE_URL, locale="zh-CN")
        bootstrap_page = bootstrap_context.new_page()
        initialize_and_login(bootstrap_page)
        storage_state = bootstrap_context.storage_state()
        bootstrap_context.close()

        results = [
            verify_viewport(browser, storage_state, output_dir, name, width, height)
            for name, width, height in VIEWPORTS
        ]
        browser.close()

    print(json.dumps({"output_dir": str(output_dir), "results": results}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
