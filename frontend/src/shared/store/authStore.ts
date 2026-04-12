import { create } from 'zustand'

interface User {
  username: string
}

interface AuthState {
  user: User | null
  token: string | null
  isAuthenticated: boolean
  isInitialized: boolean
  setAuth: (user: User | null, token: string | null) => void
  setInitialized: (initialized: boolean) => void
  logout: () => void
}

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  token: null,
  isAuthenticated: false,
  isInitialized: false,

  setAuth: (user, token) => {
    set({ user, token, isAuthenticated: !!user })
  },

  setInitialized: (initialized) => set({ isInitialized: initialized }),

  logout: () => {
    set({ user: null, token: null, isAuthenticated: false })
  },
}))
