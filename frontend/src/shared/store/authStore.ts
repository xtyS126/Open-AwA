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
  token: sessionStorage.getItem('token'),
  isAuthenticated: !!sessionStorage.getItem('token'),
  isInitialized: false,

  setAuth: (user, token) => {
    if (token) {
      sessionStorage.setItem('token', token)
    } else {
      sessionStorage.removeItem('token')
    }
    
    if (user) {
      sessionStorage.setItem('username', user.username)
    } else {
      sessionStorage.removeItem('username')
    }

    set({ user, token, isAuthenticated: !!token })
  },

  setInitialized: (initialized) => set({ isInitialized: initialized }),

  logout: () => {
    sessionStorage.removeItem('token')
    sessionStorage.removeItem('username')
    set({ user: null, token: null, isAuthenticated: false })
  },
}))
