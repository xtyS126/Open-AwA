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
  // 新增字段
  borderRadius: string
  density: 'compact' | 'default' | 'comfortable'
  animationsEnabled: boolean
  messageFontSize: string
  codeFontFamily: string
  customCSS: string
  presetTheme: string
  backgroundBlur: string
  backgroundOverlay: string
  avatarShape: 'circle' | 'rounded'
  avatarBorder: string
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
      logoIcon: safeGetItem('theme_logoIcon', '') as string || '',
      // 新增字段默认值
      borderRadius: safeGetItem('theme_borderRadius', '') as string || '',
      density: safeGetItem('theme_density', 'default') as 'compact' | 'default' | 'comfortable' || 'default',
      animationsEnabled: safeGetItem('theme_animationsEnabled', 'true') !== 'false',
      messageFontSize: safeGetItem('theme_messageFontSize', '') as string || '',
      codeFontFamily: safeGetItem('theme_codeFontFamily', '') as string || '',
      customCSS: safeGetItem('theme_customCSS', '') as string || '',
      presetTheme: safeGetItem('theme_presetTheme', '') as string || '',
      backgroundBlur: safeGetItem('theme_backgroundBlur', '') as string || '',
      backgroundOverlay: safeGetItem('theme_backgroundOverlay', '') as string || '',
      avatarShape: safeGetItem('theme_avatarShape', 'circle') as 'circle' | 'rounded' || 'circle',
      avatarBorder: safeGetItem('theme_avatarBorder', '') as string || '',
    }
  }
  return {
    fontFamily: '',
    fontSize: '14px',
    themeColor: '',
    backgroundImage: '',
    logoIcon: '',
    borderRadius: '',
    density: 'default',
    animationsEnabled: true,
    messageFontSize: '',
    codeFontFamily: '',
    customCSS: '',
    presetTheme: '',
    backgroundBlur: '',
    backgroundOverlay: '',
    avatarShape: 'circle',
    avatarBorder: '',
  }
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

  // 圆角大小
  if (config.borderRadius) {
    root.style.setProperty('--custom-border-radius', config.borderRadius)
  } else {
    root.style.removeProperty('--custom-border-radius')
  }

  // 间距密度
  const densityMap = { compact: '0.75', default: '1', comfortable: '1.25' }
  if (config.density && config.density !== 'default') {
    root.style.setProperty('--custom-density-multiplier', densityMap[config.density])
  } else {
    root.style.removeProperty('--custom-density-multiplier')
  }

  // 动效开关
  if (config.animationsEnabled === false) {
    root.style.setProperty('--custom-transition-duration', '0ms')
  } else {
    root.style.removeProperty('--custom-transition-duration')
  }

  // 消息字体大小
  if (config.messageFontSize) {
    root.style.setProperty('--custom-message-font-size', config.messageFontSize)
  } else {
    root.style.removeProperty('--custom-message-font-size')
  }

  // 代码字体
  if (config.codeFontFamily) {
    root.style.setProperty('--custom-code-font-family', config.codeFontFamily)
  } else {
    root.style.removeProperty('--custom-code-font-family')
  }

  // 背景模糊度
  if (config.backgroundBlur) {
    root.style.setProperty('--custom-background-blur', config.backgroundBlur)
  } else {
    root.style.removeProperty('--custom-background-blur')
  }

  // 背景覆盖层
  if (config.backgroundOverlay) {
    root.style.setProperty('--custom-background-overlay', config.backgroundOverlay)
  } else {
    root.style.removeProperty('--custom-background-overlay')
  }

  // 头像形状
  const AVATAR_ROUNDED_RADIUS = '8px'
  if (config.avatarShape && config.avatarShape !== 'circle') {
    root.style.setProperty('--custom-avatar-shape', config.avatarShape === 'rounded' ? AVATAR_ROUNDED_RADIUS : '50%')
  } else {
    root.style.removeProperty('--custom-avatar-shape')
  }

  // 头像边框（需校验防止注入）
  const CSS_VALUE_REGEX = /^[a-zA-Z0-9#.,()%\-\s]+$/
  if (config.avatarBorder && CSS_VALUE_REGEX.test(config.avatarBorder)) {
    root.style.setProperty('--custom-avatar-border', config.avatarBorder)
  } else {
    root.style.removeProperty('--custom-avatar-border')
  }

  // 自定义 CSS（需经过安全过滤）
  let customStyleEl = document.getElementById('custom-theme-css')
  if (config.customCSS) {
    if (!customStyleEl) {
      customStyleEl = document.createElement('style')
      customStyleEl.id = 'custom-theme-css'
      document.head.appendChild(customStyleEl)
    }
    // 移除危险 CSS 语法：url()、@import、expression()
    const sanitized = config.customCSS
      .replace(/url\s*\([^)]*\)/gi, '')
      .replace(/@import\s+[^;]+;/gi, '')
      .replace(/expression\s*\([^)]*\)/gi, '')
    customStyleEl.textContent = sanitized
  } else if (customStyleEl) {
    customStyleEl.remove()
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

