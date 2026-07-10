import { test, expect, type Page } from '@playwright/test'
import { loginAsAdminPage } from '../auth'

/**
 * 移动端键盘适配与滑动手势测试
 *
 * 覆盖 SubTask 21.2：移动端键盘适配 E2E 用例
 * 覆盖 SubTask 21.3：滑动手势关闭侧边栏 E2E 用例
 *
 * 实现说明：
 * - Playwright 桌面浏览器无法真实模拟移动端虚拟键盘，键盘适配测试通过
 *   page.evaluate 覆盖 window.visualViewport.height 并触发 resize 事件实现
 * - Playwright 的 Touchscreen 类只提供 tap 方法，滑动手势通过 page.evaluate
 *   派发原生 TouchEvent（touchstart/touchmove/touchend）实现
 */

/** 模拟键盘弹起：覆盖 visualViewport.height 使其比 innerHeight 小指定像素 */
async function simulateKeyboardOpen(page: Page, keyboardHeight = 300): Promise<void> {
  await page.evaluate((kh) => {
    const vv = window.visualViewport
    if (!vv) return
    const reducedHeight = window.innerHeight - kh
    // 覆盖 height getter，模拟键盘占用可视区域
    Object.defineProperty(vv, 'height', {
      value: reducedHeight,
      configurable: true,
    })
    vv.dispatchEvent(new Event('resize'))
  }, keyboardHeight)
}

/** 模拟键盘收起：恢复 visualViewport.height 到 window.innerHeight */
async function simulateKeyboardClose(page: Page): Promise<void> {
  await page.evaluate(() => {
    const vv = window.visualViewport
    if (!vv) return
    Object.defineProperty(vv, 'height', {
      value: window.innerHeight,
      configurable: true,
    })
    vv.dispatchEvent(new Event('resize'))
  })
}

/**
 * 在侧边栏元素上模拟左滑手势
 *
 * 通过 page.evaluate 派发原生 TouchEvent（touchstart → touchmove → touchend），
 * 触发 Sidebar 组件的 onTouchStart/onTouchMove/onTouchEnd 处理器。
 *
 * @param page Playwright 页面对象
 * @param startX 起始 X 坐标（视口相对）
 * @param startY 起始 Y 坐标（视口相对）
 * @param deltaX X 方向位移（负值表示左滑）
 */
async function simulateSwipeLeft(page: Page, startX: number, startY: number, deltaX: number): Promise<void> {
  await page.evaluate(({ startX, startY, deltaX }) => {
    const sidebar = document.querySelector('[data-testid="sidebar"]') as HTMLElement | null
    if (!sidebar) return

    const endX = startX + deltaX

    // 创建 Touch 对象的工厂函数
    const makeTouch = (x: number, y: number): Touch => {
      return new Touch({
        identifier: 1,
        target: sidebar,
        clientX: x,
        clientY: y,
        pageX: x,
        pageY: y,
        radiusX: 0,
        radiusY: 0,
        rotationAngle: 0,
        force: 1,
      })
    }

    // touchstart：记录起始坐标
    const startTouch = makeTouch(startX, startY)
    const startEvent = new TouchEvent('touchstart', {
      touches: [startTouch],
      targetTouches: [startTouch],
      changedTouches: [startTouch],
      bubbles: true,
      cancelable: true,
    })
    sidebar.dispatchEvent(startEvent)

    // touchmove：移动到结束坐标
    const moveTouch = makeTouch(endX, startY)
    const moveEvent = new TouchEvent('touchmove', {
      touches: [moveTouch],
      targetTouches: [moveTouch],
      changedTouches: [moveTouch],
      bubbles: true,
      cancelable: true,
    })
    sidebar.dispatchEvent(moveEvent)

    // touchend：触摸结束，touches 为空，changedTouches 包含最后一个触摸点
    const endEvent = new TouchEvent('touchend', {
      touches: [],
      targetTouches: [],
      changedTouches: [moveTouch],
      bubbles: true,
      cancelable: true,
    })
    sidebar.dispatchEvent(endEvent)
  }, { startX, startY, deltaX })
}

// ============================================================
// 移动端键盘适配测试
// ============================================================

test.describe('移动端键盘适配 (375×812)', () => {
  test.describe.configure({ mode: 'serial' })
  test.use({ viewport: { width: 375, height: 812 } })

  test('聊天页 - ChatInput 容器在移动端可见', async ({ page }) => {
    await loginAsAdminPage(page)
    await page.waitForLoadState('domcontentloaded')

    const chatInput = page.locator('[data-testid="chat-input-container"]').first()
    await expect(chatInput).toBeVisible({ timeout: 15_000 })
  })

  test('聊天页 - 模拟 visualViewport resize 触发键盘弹起样式', async ({ page }) => {
    await loginAsAdminPage(page)
    await page.waitForLoadState('domcontentloaded')

    // 聚焦聊天输入框（触发 useVisualViewport hook 监听）
    const textarea = page.locator('[data-testid="chat-input-textarea"]').first()
    await textarea.click()

    // 模拟键盘弹起
    await simulateKeyboardOpen(page, 300)

    // 等待 React 状态更新与重渲染
    await page.waitForTimeout(300)

    // 验证 ChatInput 容器添加了 is-keyboard-open 类
    const containerClass = await page.evaluate(() => {
      const el = document.querySelector('[data-testid="chat-input-container"]') as HTMLElement | null
      return el?.className ?? ''
    })
    expect(containerClass, '键盘弹起后应添加 is-keyboard-open 类').toContain('is-keyboard-open')

    // 验证 inline bottom 样式被设置（键盘偏移 calc(100vh - ...px)）
    // 注意：浏览器读取 el.style.bottom 时会规范化 calc 表达式
    // 例如 calc(100vh - 512px) 可能被规范化为 calc(-512px + 100vh)，数学等价但字符串格式不同
    // 因此改为更宽松的检查：同时包含 100vh 与键盘占用像素值（512 = 812 - 300）
    const containerBottom = await page.evaluate(() => {
      const el = document.querySelector('[data-testid="chat-input-container"]') as HTMLElement | null
      return el?.style.bottom ?? ''
    })
    expect(containerBottom, '应设置 inline bottom 偏移').not.toBe('')
    expect(containerBottom, 'bottom 偏移应包含 100vh').toContain('100vh')
    expect(containerBottom, 'bottom 偏移应包含键盘占用像素值').toContain('512')
  })

  test('聊天页 - visualViewport 恢复后键盘样式移除', async ({ page }) => {
    await loginAsAdminPage(page)
    await page.waitForLoadState('domcontentloaded')

    const textarea = page.locator('[data-testid="chat-input-textarea"]').first()
    await textarea.click()

    // 先模拟键盘弹起
    await simulateKeyboardOpen(page, 300)
    await page.waitForTimeout(200)

    // 模拟键盘收起
    await simulateKeyboardClose(page)
    await page.waitForTimeout(300)

    // 验证 is-keyboard-open 类已移除
    const containerClass = await page.evaluate(() => {
      const el = document.querySelector('[data-testid="chat-input-container"]') as HTMLElement | null
      return el?.className ?? ''
    })
    expect(containerClass, '键盘收起后应移除 is-keyboard-open 类').not.toContain('is-keyboard-open')
  })
})

// ============================================================
// 移动端滑动手势关闭侧边栏测试
// ============================================================

test.describe('移动端滑动手势关闭侧边栏 (375×812)', () => {
  test.describe.configure({ mode: 'serial' })
  test.use({ viewport: { width: 375, height: 812 } })

  test('侧边栏 - 向左滑动超过 60px 可关闭抽屉', async ({ page }) => {
    await loginAsAdminPage(page)
    await page.waitForLoadState('domcontentloaded')

    // 显式重置到 /chat 初始状态，防止 serial 模式下前序测试状态泄漏
    await page.goto('/chat')
    await page.waitForLoadState('domcontentloaded')

    // 打开侧边栏抽屉
    const mobileMenu = page.locator('[data-testid="mobile-menu-btn"]').first()
    await expect(mobileMenu).toBeVisible({ timeout: 15_000 })
    await mobileMenu.click()

    const sidebar = page.locator('[data-testid="sidebar"]').first()
    await expect(sidebar).toHaveAttribute('data-mobile-open', 'true')

    // 验证遮罩层显示
    const overlay = page.locator('[data-testid="mobile-overlay"]').first()
    await expect(overlay).toHaveAttribute('data-visible', 'true')

    // 获取侧边栏中心坐标作为滑动起点
    const sidebarBox = await sidebar.boundingBox()
    expect(sidebarBox).not.toBeNull()
    const startX = sidebarBox!.x + sidebarBox!.width * 0.5
    const startY = sidebarBox!.y + sidebarBox!.height * 0.5

    // 模拟左滑 100px（超过 60px 关闭阈值）
    await simulateSwipeLeft(page, startX, startY, -100)

    // 等待状态更新与过渡动画
    await page.waitForTimeout(400)

    // 验证侧边栏已关闭
    await expect(sidebar).not.toHaveAttribute('data-mobile-open', 'true')

    // 验证遮罩层已隐藏
    await expect(overlay).not.toHaveAttribute('data-visible', 'true')
  })

  test('侧边栏 - 小幅度滑动（< 60px）不关闭抽屉', async ({ page }) => {
    await loginAsAdminPage(page)
    await page.waitForLoadState('domcontentloaded')

    // 显式重置到 /chat 初始状态，防止 serial 模式下前序测试状态泄漏
    // 前序用例滑动 -100px 关闭抽屉后可能残留过渡态，强制重新加载确保 sidebar 处于关闭初始状态
    await page.goto('/chat')
    await page.waitForLoadState('domcontentloaded')

    const mobileMenu = page.locator('[data-testid="mobile-menu-btn"]').first()
    await mobileMenu.click()

    const sidebar = page.locator('[data-testid="sidebar"]').first()
    await expect(sidebar).toHaveAttribute('data-mobile-open', 'true')

    const sidebarBox = await sidebar.boundingBox()
    expect(sidebarBox).not.toBeNull()
    const startX = sidebarBox!.x + sidebarBox!.width * 0.5
    const startY = sidebarBox!.y + sidebarBox!.height * 0.5

    // 模拟左滑 40px（未达 60px 关闭阈值）
    await simulateSwipeLeft(page, startX, startY, -40)

    await page.waitForTimeout(400)

    // 侧边栏应保持打开
    await expect(sidebar).toHaveAttribute('data-mobile-open', 'true')
  })
})
