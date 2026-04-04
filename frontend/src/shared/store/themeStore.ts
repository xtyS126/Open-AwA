import { create } from 'zustand'

type Theme = 'light' | 'dark'

interface ThemeState {
  theme: Theme
  toggleTheme: () => void
  setTheme: (theme: Theme) => void
}

export const useThemeStore = create<ThemeState>((set) => ({
  theme: (localStorage.getItem('theme') as Theme) || 'light',
  
  toggleTheme: () => set((state) => {
    const newTheme = state.theme === 'light' ? 'dark' : 'light'
    localStorage.setItem('theme', newTheme)
    return { theme: newTheme }
  }),
  
  setTheme: (theme: Theme) => set(() => {
    localStorage.setItem('theme', theme)
    return { theme }
  }),
}))
