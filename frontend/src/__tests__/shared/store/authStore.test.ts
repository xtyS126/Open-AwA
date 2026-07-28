import { beforeEach, describe, expect, it } from 'vitest'
import { useAuthStore } from '@/shared/store/authStore'

describe('authStore', () => {
  beforeEach(() => {
    useAuthStore.getState().logout()
    useAuthStore.getState().setInitialized(false)
    useAuthStore.getState().setSystemInitialized(false)
  })

  it('sets authenticated user and API key', () => {
    useAuthStore.getState().setAuth({ id: 'u1', username: 'admin' }, 'key')
    expect(useAuthStore.getState()).toMatchObject({ isAuthenticated: true, apiKey: 'key' })
  })

  it('merges user profile updates without dropping authentication', () => {
    useAuthStore.getState().setAuth({ id: 'u1', username: 'admin' }, 'key')
    useAuthStore.getState().updateUser({ nickname: '管理员' })
    expect(useAuthStore.getState().user).toMatchObject({ username: 'admin', nickname: '管理员' })
    expect(useAuthStore.getState().isAuthenticated).toBe(true)
  })

  it('clears credentials on logout', () => {
    useAuthStore.getState().setAuth({ username: 'admin' }, 'key')
    useAuthStore.getState().logout()
    expect(useAuthStore.getState()).toMatchObject({ user: null, apiKey: null, isAuthenticated: false })
  })
})
