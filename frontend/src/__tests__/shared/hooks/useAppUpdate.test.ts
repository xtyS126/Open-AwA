import '@testing-library/jest-dom/vitest'
import { renderHook, act } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useAppUpdate } from '@/shared/hooks/useAppUpdate'
import { checkForUpdate } from '@/shared/api/updateApi'

vi.mock('@/shared/utils/platform', () => ({ isNativeApp: () => true }))
vi.mock('@/shared/api/updateApi', () => ({
  checkForUpdate: vi.fn(),
  buildDownloadUrl: vi.fn(() => 'http://lan:8000/api/system/apk/download'),
}))
vi.mock('@/shared/api/appUpdatePlugin', () => ({
  appUpdatePlugin: {
    getCurrentVersionCode: vi.fn(async () => ({ version_code: 1, version_name: '1.0' })),
    downloadAndInstall: vi.fn(),
    addListener: vi.fn(async () => ({ remove: vi.fn() })),
  },
}))

const updateInfo = {
  has_update: true,
  latest_version: '1.0.1',
  latest_version_code: 2,
  apk_size: 1000,
  apk_sha256: 'a'.repeat(64),
  changelog: '修复',
  download_url: '/api/system/apk/download',
  published_at: '',
}

describe('useAppUpdate', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('无更新时状态为 idle 且不弹窗', async () => {
    vi.mocked(checkForUpdate).mockResolvedValue({ has_update: false } as never)
    const { result } = renderHook(() => useAppUpdate())
    await act(async () => {
      await result.current.check()
    })
    expect(result.current.status).toBe('idle')
    expect(result.current.updateInfo).toBeNull()
  })

  it('检测到更新时状态为 available 并携带元数据', async () => {
    vi.mocked(checkForUpdate).mockResolvedValue(updateInfo as never)
    const { result } = renderHook(() => useAppUpdate())
    await act(async () => {
      await result.current.check()
    })
    expect(result.current.status).toBe('available')
    expect(result.current.updateInfo?.latest_version).toBe('1.0.1')
  })

  it('用户点击稍后关闭后本次会话不再自动弹出', async () => {
    vi.mocked(checkForUpdate).mockResolvedValue(updateInfo as never)
    const { result } = renderHook(() => useAppUpdate())
    await act(async () => {
      await result.current.check()
    })
    act(() => {
      result.current.dismiss()
    })
    expect(result.current.status).toBe('idle')
    // 再次 check 不应触发弹窗
    await act(async () => {
      await result.current.check()
    })
    expect(result.current.status).toBe('idle')
  })

  it('更新检查失败时状态为 error 并携带错误信息（不静默降级为 idle）', async () => {
    vi.mocked(checkForUpdate).mockRejectedValue(new Error('后端未部署更新包'))
    const { result } = renderHook(() => useAppUpdate())
    await act(async () => {
      await result.current.check()
    })
    expect(result.current.status).toBe('error')
    expect(result.current.error).toContain('更新检查失败')
  })

  it('startDownload 进入 downloading 并在完成后进入 installing', async () => {
    vi.mocked(checkForUpdate).mockResolvedValue(updateInfo as never)
    const { appUpdatePlugin } = await import('@/shared/api/appUpdatePlugin')
    vi.mocked(appUpdatePlugin.downloadAndInstall).mockResolvedValue({ installing: true } as never)
    const { result } = renderHook(() => useAppUpdate())
    await act(async () => {
      await result.current.check()
    })
    await act(async () => {
      await result.current.startDownload()
    })
    expect(appUpdatePlugin.downloadAndInstall).toHaveBeenCalledWith(
      expect.objectContaining({
        url: 'http://lan:8000/api/system/apk/download',
        fileName: 'openawa-1.0.1.apk',
        sha256: 'a'.repeat(64),
      }),
    )
    expect(result.current.status).toBe('installing')
  })

  it('下载失败时状态为 error 并携带错误信息', async () => {
    vi.mocked(checkForUpdate).mockResolvedValue(updateInfo as never)
    const { appUpdatePlugin } = await import('@/shared/api/appUpdatePlugin')
    vi.mocked(appUpdatePlugin.downloadAndInstall).mockRejectedValue(new Error('APK 校验失败'))
    const { result } = renderHook(() => useAppUpdate())
    await act(async () => {
      await result.current.check()
    })
    await act(async () => {
      await result.current.startDownload()
    })
    expect(result.current.status).toBe('error')
    expect(result.current.error).toContain('校验失败')
  })
})
