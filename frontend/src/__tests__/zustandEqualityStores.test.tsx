import { render } from '@testing-library/react'
import { shallow } from 'zustand/shallow'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { useSessionStore } from '@/features/chat/store/sessionStore'
import { useCodingStore } from '@/features/coding/store/codingStore'
import { useInboxStore } from '@/features/inbox/store/inboxStore'
import { useTtsStore } from '@/features/tts/store/ttsStore'
import { useWorkspaceStore } from '@/features/workspace/store/workspaceStore'
import { useI18nStore } from '@/i18n'
import { useAuthStore } from '@/shared/store/authStore'
import { useProfileStore } from '@/shared/store/profileStore'
import { useThemeStore } from '@/shared/store/themeStore'

function EqualityConsumer() {
  useSessionStore((state) => ({ isLoading: state.isLoading }), shallow)
  useCodingStore((state) => ({ projectDir: state.projectDir }), shallow)
  useInboxStore((state) => ({ unreadCount: state.unreadCount }), shallow)
  useTtsStore((state) => ({ text: state.text }), shallow)
  useWorkspaceStore((state) => ({ currentWorkspaceId: state.currentWorkspaceId }), shallow)
  useI18nStore((state) => ({ locale: state.locale }), shallow)
  useAuthStore((state) => ({ isAuthenticated: state.isAuthenticated }), shallow)
  useProfileStore((state) => ({ loading: state.loading }), shallow)
  useThemeStore((state) => ({ theme: state.theme }), shallow)
  return null
}

describe('Zustand equalityFn store 兼容性', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('所有使用 shallow equalityFn 的 Store 均不触发弃用警告', () => {
    const warningSpy = vi.spyOn(console, 'warn').mockImplementation(() => undefined)

    render(<EqualityConsumer />)

    const warningText = warningSpy.mock.calls.flat().map(String).join('\n')
    expect(warningText).not.toContain('equalityFn')
    expect(warningText).not.toContain('deprecated')
  })
})
