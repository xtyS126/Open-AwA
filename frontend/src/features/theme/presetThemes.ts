import type { ThemeConfig } from '@/shared/store/themeStore'

/**
 * 预设主题方案定义
 * 每个预设包含完整的颜色配置和样式参数
 */
export interface PresetTheme {
  id: string
  name: string
  description: string
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
    name: 'Default',
    description: '经典蓝色主题，适合大多数场景',
    colors: {
      primary: '#3b82f6',
      background: '#ffffff',
      surface: '#f8fafc',
      border: '#e2e8f0',
      text: '#0f172a',
      textSecondary: '#64748b',
    },
    config: {
      themeColor: '#3b82f6',
      borderRadius: '8px',
      density: 'default',
      animationsEnabled: true,
    },
  },
  {
    id: 'ocean',
    name: 'Ocean',
    description: '天蓝色主题，清新自然',
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
    name: 'Forest',
    description: '绿色主题，护眼舒适',
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
    name: 'Sunset',
    description: '橙色主题，温暖活力',
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
    name: 'Rose',
    description: '玫红色主题，优雅浪漫',
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
    name: 'Violet',
    description: '紫色主题，神秘高贵',
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
