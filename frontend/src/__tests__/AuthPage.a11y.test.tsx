/**
 * LoginPage 无障碍自动化测试 — 使用 axe-core 检测 WCAG 违规。
 * 本文件作为 axe-core 集成参考，后续可为其他关键页面添加类似测试。
 */
import { render } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import axe from 'axe-core'
import { BrowserRouter } from 'react-router-dom'
import LoginPage from '../features/auth/LoginPage'

function renderLogin() {
  return render(
    <BrowserRouter>
      <LoginPage />
    </BrowserRouter>
  )
}

describe('LoginPage 无障碍 (axe-core)', () => {
  it('初始渲染无 WCAG 违规', async () => {
    const { container } = renderLogin()
    const results = await axe.run(container)
    const violations = results.violations.filter(
      (v) => !(v.impact === 'minor')
    )
    if (violations.length > 0) {
      const messages = violations.map(
        (v) => `[${v.impact}] ${v.help}: ${v.nodes.map((n) => n.html).join('; ')}`
      )
      throw new Error(`WCAG violations found:\n${messages.join('\n')}`)
    }
  })

  it('表单输入区域有正确的 label 关联', () => {
    const { getByLabelText } = renderLogin()
    expect(getByLabelText('用户名')).toBeInTheDocument()
    expect(getByLabelText('密码')).toBeInTheDocument()
  })

  it('提交按钮可被辅助技术识别', () => {
    const { getByRole } = renderLogin()
    expect(getByRole('button', { name: /登录/ })).toBeInTheDocument()
  })
})
