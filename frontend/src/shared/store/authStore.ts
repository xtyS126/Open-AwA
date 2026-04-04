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
  token: localStorage.getItem('token'),
  isAuthenticated: !!localStorage.getItem('token'),
  isInitialized: false,

  setAuth: (user, token) => {
    if (token) {
      localStorage.setItem('token', token)
    } else {
      localStorage.removeItem('token')
    }
    
    if (user) {
      localStorage.setItem('username', user.username)
    } else {
      localStorage.removeItem('username')
    }

    set({ user, token, isAuthenticated: !!token })
  },

  setInitialized: (initialized) => set({ isInitialized: initialized }),

  logout: () => {
    localStorage.removeItem('token')
    localStorage.removeItem('username')
    set({ user: null, token: null, isAuthenticated: false })
  },
}))
