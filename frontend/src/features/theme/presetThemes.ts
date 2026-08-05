import type { ThemeConfig } from '@/shared/store/themeStore'

/**
 * 预设主题方案定义
 * 每个预设包含完整的颜色配置和样式参数
 *
 * name 与 description 通过 i18n key 引用，避免在源码中硬编码多语言文案。
 * key 约定：`theme.preset.<id>` 与 `theme.preset.<id>.desc`，定义于 src/i18n/locales/zh-CN.ts。
 */
export interface PresetTheme {
  id: string
  /** 主题名称的 i18n key */
  nameKey: string
  /** 主题描述的 i18n key */
  descriptionKey: string
  colors: {
    primary: string
    background: string
    surface: string
    border: string
    text: string
    textSecondary: string
  }
  config: Partial<ThemeConfig>
}

/**
 * 6 种预设主题方案
 */
export const presetThemes: PresetTheme[] = [
  {
    id: 'default',
    nameKey: 'theme.preset.default',
    descriptionKey: 'theme.preset.default.desc',
    colors: {
      primary: '#0d9488',
      background: '#ffffff',
      surface: '#f8fafc',
      border: '#e2e8f0',
      text: '#0f172a',
      textSecondary: '#64748b',
    },
    config: {
      themeColor: '#0d9488',
      borderRadius: '8px',
      density: 'default',
      animationsEnabled: true,
    },
  },
  {
    id: 'ocean',
    nameKey: 'theme.preset.ocean',
    descriptionKey: 'theme.preset.ocean.desc',
    colors: {
      primary: '#0ea5e9',
      background: '#f0f9ff',
      surface: '#e0f2fe',
      border: '#bae6fd',
      text: '#0c4a6e',
      textSecondary: '#0369a1',
    },
    config: {
      themeColor: '#0ea5e9',
      borderRadius: '12px',
      density: 'default',
      animationsEnabled: true,
    },
  },
  {
    id: 'forest',
    nameKey: 'theme.preset.forest',
    descriptionKey: 'theme.preset.forest.desc',
    colors: {
      primary: '#10b981',
      background: '#f0fdf4',
      surface: '#dcfce7',
      border: '#bbf7d0',
      text: '#064e3b',
      textSecondary: '#047857',
    },
    config: {
      themeColor: '#10b981',
      borderRadius: '10px',
      density: 'default',
      animationsEnabled: true,
    },
  },
  {
    id: 'sunset',
    nameKey: 'theme.preset.sunset',
    descriptionKey: 'theme.preset.sunset.desc',
    colors: {
      primary: '#f59e0b',
      background: '#fffbeb',
      surface: '#fef3c7',
      border: '#fde68a',
      text: '#78350f',
      textSecondary: '#b45309',
    },
    config: {
      themeColor: '#f59e0b',
      borderRadius: '14px',
      density: 'default',
      animationsEnabled: true,
    },
  },
  {
    id: 'rose',
    nameKey: 'theme.preset.rose',
    descriptionKey: 'theme.preset.rose.desc',
    colors: {
      primary: '#ec4899',
      background: '#fdf2f8',
      surface: '#fce7f3',
      border: '#fbcfe8',
      text: '#831843',
      textSecondary: '#be185d',
    },
    config: {
      themeColor: '#ec4899',
      borderRadius: '16px',
      density: 'default',
      animationsEnabled: true,
    },
  },
  {
    id: 'violet',
    nameKey: 'theme.preset.violet',
    descriptionKey: 'theme.preset.violet.desc',
    colors: {
      primary: '#8b5cf6',
      background: '#faf5ff',
      surface: '#f3e8ff',
      border: '#e9d5ff',
      text: '#581c87',
      textSecondary: '#7c3aed',
    },
    config: {
      themeColor: '#8b5cf6',
      borderRadius: '12px',
      density: 'default',
      animationsEnabled: true,
    },
  },
]

/**
 * 根据 ID 获取预设主题
 */
export function getPresetThemeById(id: string): PresetTheme | undefined {
  return presetThemes.find((theme) => theme.id === id)
}

/**
 * 应用预设主题到配置
 */
export function applyPresetTheme(presetId: string): Partial<ThemeConfig> {
  const preset = getPresetThemeById(presetId)
  if (!preset) {
    return {}
  }
  return {
    ...preset.config,
    presetTheme: presetId,
  }
}
