import { create } from 'zustand'
import { safeGetItem, safeSetItem } from '@/shared/utils/safeStorage'
import { syncPreferenceToServer } from '@/shared/utils/preferenceSync'

type Theme = 'light' | 'dark'

export interface ThemeConfig {
  fontFamily: string
  fontSize: string
  themeColor: string
  backgroundImage: string
  logoIcon: string
}

interface ThemeState {
  theme: Theme
  config: ThemeConfig
  toggleTheme: () => void
  setTheme: (theme: Theme) => void
  setConfig: (config: Partial<ThemeConfig>) => void
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

const getInitialConfig = (): ThemeConfig => {
  if (typeof window !== 'undefined') {
    return {
      fontFamily: safeGetItem('theme_fontFamily', '') as string || '',
      fontSize: safeGetItem('theme_fontSize', '') as string || '14px',
      themeColor: safeGetItem('theme_themeColor', '') as string || '',
      backgroundImage: safeGetItem('theme_backgroundImage', '') as string || '',
      logoIcon: safeGetItem('theme_logoIcon', '') as string || ''
    }
  }
  return { fontFamily: '', fontSize: '14px', themeColor: '', backgroundImage: '', logoIcon: '' }
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

const applyConfig = (config: ThemeConfig) => {
  if (typeof document !== 'undefined') {
    const root = document.documentElement
    if (config.fontFamily) {
      root.style.setProperty('--custom-font-family', config.fontFamily)
      root.style.fontFamily = `var(--custom-font-family), "Inter", sans-serif`
    } else {
      root.style.removeProperty('--custom-font-family')
      root.style.fontFamily = ''
    }

    if (config.fontSize) {
      root.style.setProperty('--custom-font-size', config.fontSize)
      root.style.fontSize = `var(--custom-font-size)`
    } else {
      root.style.removeProperty('--custom-font-size')
      root.style.fontSize = ''
    }

    if (config.themeColor) {
      root.style.setProperty('--custom-theme-color', config.themeColor)
      // Attempting to overwrite primary color variables if possible, simplistic approach
      root.style.setProperty('--color-primary', config.themeColor)
      root.style.setProperty('--button-bg', config.themeColor)
    } else {
      root.style.removeProperty('--custom-theme-color')
      root.style.removeProperty('--color-primary')
      root.style.removeProperty('--button-bg')
    }

    if (config.backgroundImage) {
      root.style.setProperty('--custom-bg-image', `url(${config.backgroundImage})`)
      document.body.style.backgroundImage = `var(--custom-bg-image)`
      document.body.style.backgroundSize = 'cover'
      document.body.style.backgroundAttachment = 'fixed'
      document.body.style.backgroundPosition = 'center'
    } else {
      root.style.removeProperty('--custom-bg-image')
      document.body.style.backgroundImage = ''
      document.body.style.backgroundSize = ''
      document.body.style.backgroundAttachment = ''
      document.body.style.backgroundPosition = ''
    }

    // Refresh Favicon
    if (config.logoIcon) {
      let link: HTMLLinkElement | null = document.querySelector("link[rel~='icon']")
      if (!link) {
        link = document.createElement('link')
        link.rel = 'icon'
        document.getElementsByTagName('head')[0].appendChild(link)
      }
      link.href = config.logoIcon
    } else {
      const link: HTMLLinkElement | null = document.querySelector("link[rel~='icon']")
      if (link) {
        link.href = '/vite.svg'
      }
    }
  }
}

// Apply initial theme immediately to avoid flash
if (typeof document !== 'undefined') {
  applyTheme(getInitialTheme())
  applyConfig(getInitialConfig())
}

export const useThemeStore = create<ThemeState>((set) => ({
  theme: getInitialTheme(),
  config: getInitialConfig(),

  toggleTheme: () => set((state) => {
    const newTheme = state.theme === 'light' ? 'dark' : 'light'
    safeSetItem('theme', newTheme)
    applyTheme(newTheme)
    syncPreferenceToServer('theme', newTheme)
    return { theme: newTheme }
  }),

  setTheme: (theme: Theme) => set(() => {
    safeSetItem('theme', theme)
    applyTheme(theme)
    syncPreferenceToServer('theme', theme)
    return { theme }
  }),

  setConfig: (newConfig: Partial<ThemeConfig>) => set((state) => {
    const updatedConfig = { ...state.config, ...newConfig }
    
    // Save all distinct keys
    Object.entries(newConfig).forEach(([key, value]) => {
      safeSetItem(`theme_${key}`, value as string)
    })
    
    applyConfig(updatedConfig)
    return { config: updatedConfig }
  })
}))

