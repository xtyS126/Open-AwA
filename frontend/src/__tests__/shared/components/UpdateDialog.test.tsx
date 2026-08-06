import '@testing-library/jest-dom/vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { UpdateDialog } from '@/shared/components/UpdateDialog/UpdateDialog'
import { useI18nStore } from '@/i18n'
import type { UpdateInfo } from '@/shared/api/updateApi'

const info: UpdateInfo = {
  has_update: true,
  latest_version: '1.0.1',
  latest_version_code: 2,
  apk_size: 1024 * 1024,
  apk_sha256: 'a'.repeat(64),
  changelog: '修复已知问题\n新增功能',
  download_url: '/api/system/apk/download',
  published_at: '',
}

describe('UpdateDialog', () => {
  beforeEach(() => {
    useI18nStore.getState().setLocale('zh-CN')
  })

  it('展示版本号、changelog 与文件大小', () => {
    render(
      <UpdateDialog info={info} status="available" progress={null} onUpdate={vi.fn()} onLater={vi.fn()} />,
    )
    expect(screen.getByText(/1\.0\.1/)).toBeInTheDocument()
    expect(screen.getByText(/修复已知问题/)).toBeInTheDocument()
    expect(screen.getByText(/1\.00 MB/)).toBeInTheDocument()
  })

  it('点击立即更新触发 onUpdate，点击稍后触发 onLater', () => {
    const onUpdate = vi.fn()
    const onLater = vi.fn()
    render(
      <UpdateDialog info={info} status="available" progress={null} onUpdate={onUpdate} onLater={onLater} />,
    )
    fireEvent.click(screen.getByRole('button', { name: /立即更新/ }))
    expect(onUpdate).toHaveBeenCalledTimes(1)
    fireEvent.click(screen.getByRole('button', { name: /稍后/ }))
    expect(onLater).toHaveBeenCalledTimes(1)
  })

  it('下载中显示进度百分比且隐藏按钮', () => {
    render(
      <UpdateDialog
        info={info}
        status="downloading"
        progress={{ loaded: 512 * 1024, total: 1024 * 1024, percent: 50 }}
        onUpdate={vi.fn()}
        onLater={vi.fn()}
      />,
    )
    expect(screen.getByText(/50%/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /立即更新/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /稍后/ })).not.toBeInTheDocument()
  })

  it('错误状态显示错误信息', () => {
    render(
      <UpdateDialog info={info} status="error" progress={null} error="下载失败" onUpdate={vi.fn()} onLater={vi.fn()} />,
    )
    expect(screen.getByRole('alert')).toHaveTextContent('下载失败')
  })
})
