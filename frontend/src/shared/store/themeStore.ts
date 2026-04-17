import { create } from 'zustand'
import { safeGetItem, safeSetItem } from '@/shared/utils/safeStorage'

type Theme = 'light' | 'dark'

interface ThemeState {
  theme: Theme
  toggleTheme: () => void
  setTheme: (theme: Theme) => void
}

const getInitialTheme = (): Theme => {
  if (typeof window !== 'undefined') {
    const savedTheme = safeGetItem('theme', '') as Theme
    if (savedTheme) {
      return savedTheme
    }
    if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {
      return 'dark'
    }
  }
  return 'light'
}

const applyTheme = (theme: Theme) => {
  if (typeof document !== 'undefined') {
    const html = document.documentElement
    if (theme === 'dark') {
      html.classList.add('dark')
    } else {
      html.classList.remove('dark')
    }
  }
}

// Apply initial theme immediately to avoid flash
if (typeof document !== 'undefined') {
  applyTheme(getInitialTheme())
}

export const useThemeStore = create<ThemeState>((set) => ({
  theme: getInitialTheme(),
  
  toggleTheme: () => set((state) => {
    const newTheme = state.theme === 'light' ? 'dark' : 'light'
    safeSetItem('theme', newTheme)
    applyTheme(newTheme)
    return { theme: newTheme }
  }),
  
  setTheme: (theme: Theme) => set(() => {
    safeSetItem('theme', theme)
    applyTheme(theme)
    return { theme }
  }),
}))

