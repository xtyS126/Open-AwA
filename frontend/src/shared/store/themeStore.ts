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
  setTheme: (theme: Theme, options?: { syncToServer?: boolean }) => void
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
  if (typeof document === 'undefined') return
  const root = document.documentElement

  // 逐条设置/移除 CSS 属性，使用 removeProperty 而非 initial 确保样式表回退正常
  if (config.fontFamily) {
    root.style.setProperty('--custom-font-family', config.fontFamily)
    root.style.fontFamily = `var(--custom-font-family), "Inter", sans-serif`
  } else {
    root.style.removeProperty('--custom-font-family')
    root.style.fontFamily = ''
  }

  if (config.fontSize) {
    root.style.setProperty('--custom-font-size', config.fontSize)
    root.style.fontSize = 'var(--custom-font-size)'
  } else {
    root.style.removeProperty('--custom-font-size')
    root.style.fontSize = ''
  }

  if (config.themeColor) {
    root.style.setProperty('--custom-theme-color', config.themeColor)
    root.style.setProperty('--color-primary', config.themeColor)
    root.style.setProperty('--button-bg', config.themeColor)
  } else {
    root.style.removeProperty('--custom-theme-color')
    root.style.removeProperty('--color-primary')
    root.style.removeProperty('--button-bg')
  }

  if (config.backgroundImage) {
    // 对 URL 中的特殊字符做 CSS 转义（括号、引号）
    const escapedUrl = config.backgroundImage.replace(/[()'"]/g, '\\$&')
    root.style.setProperty('--custom-bg-image', `url(${escapedUrl})`)
    Object.assign(document.body.style, {
      backgroundImage: 'var(--custom-bg-image)',
      backgroundSize: 'cover',
      backgroundAttachment: 'fixed',
      backgroundPosition: 'center',
    })
  } else {
    root.style.removeProperty('--custom-bg-image')
    Object.assign(document.body.style, {
      backgroundImage: '',
      backgroundSize: '',
      backgroundAttachment: '',
      backgroundPosition: '',
    })
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

  setTheme: (theme: Theme, options) => set(() => {
    safeSetItem('theme', theme)
    applyTheme(theme)
    if (options?.syncToServer !== false) {
      syncPreferenceToServer('theme', theme)
    }
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

