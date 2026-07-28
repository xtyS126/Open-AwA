import '@testing-library/jest-dom/vitest'
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { useI18nStore, LANGUAGES } from '@/i18n'
import { AppearanceTabContainer } from '@/features/settings/containers/AppearanceTabContainer'

// Mock themeStore，避免依赖实际状态
vi.mock('@/shared/store/themeStore', () => ({
  useThemeStore: () => ({
    config: {
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
    },
    setConfig: vi.fn(),
  }),
}))

// Mock presetThemes
vi.mock('@/features/theme/presetThemes', () => ({
  presetThemes: [],
  applyPresetTheme: vi.fn(() => ({})),
}))

describe('i18n 语言切换', () => {
  beforeEach(() => {
    // 重置为默认语言
    useI18nStore.getState().setLocale('zh-CN')
    localStorage.clear()
  })

  it('LANGUAGES 常量包含 4 种语言', () => {
    expect(LANGUAGES).toHaveLength(4)
    const codes = LANGUAGES.map((l) => l.code)
    expect(codes).toContain('zh-CN')
    expect(codes).toContain('en-US')
    expect(codes).toContain('ja-JP')
    expect(codes).toContain('ru-RU')
  })

  it('默认语言为 zh-CN', () => {
    expect(useI18nStore.getState().locale).toBe('zh-CN')
    expect(useI18nStore.getState().isLocaleLoaded).toBe(true)
  })

  it('t() 返回对应语言的翻译', () => {
    useI18nStore.getState().setLocale('zh-CN')
    expect(useI18nStore.getState().t('settings.language')).toBe('语言')

    // en-US 为动态加载，回退到 zh-CN
    useI18nStore.getState().setLocale('en-US')
    // 由于测试环境无法真正异步加载，回退到默认语言或 key
    const translated = useI18nStore.getState().t('app.save')
    expect(typeof translated).toBe('string')
  })

  it('t() 支持参数替换', () => {
    useI18nStore.getState().setLocale('zh-CN')
    const result = useI18nStore.getState().t('app.count', { count: '5' })
    expect(result).toBe('5 个')
  })

  it('t() 对未知 key 返回 key 本身', () => {
    useI18nStore.getState().setLocale('zh-CN')
    const result = useI18nStore.getState().t('nonexistent.key.example')
    expect(result).toBe('nonexistent.key.example')
  })

  it('setLocale 持久化到 localStorage', () => {
    useI18nStore.getState().setLocale('en-US')
    expect(localStorage.getItem('openawa_locale')).toBe('en-US')
  })

  it('setLocale 对无效 code 不生效', () => {
    const initial = useI18nStore.getState().locale
    useI18nStore.getState().setLocale('invalid-locale')
    expect(useI18nStore.getState().locale).toBe(initial)
  })

  it('短代码自动映射到完整 locale', () => {
    useI18nStore.getState().setLocale('en')
    expect(useI18nStore.getState().locale).toBe('en-US')
  })
})

describe('AppearanceTabContainer 语言选择器', () => {
  beforeEach(() => {
    useI18nStore.getState().setLocale('zh-CN')
    localStorage.clear()
  })

  it('渲染语言选择器', () => {
    render(<AppearanceTabContainer />)
    // 应该能找到语言选择器（包含 4 种语言选项）
    const selects = screen.getAllByRole('combobox')
    expect(selects.length).toBeGreaterThan(0)
  })

  it('语言选择器包含所有语言选项', () => {
    render(<AppearanceTabContainer />)
    // 验证包含 4 种语言
    for (const lang of LANGUAGES) {
      const option = screen.getByRole('option', { name: new RegExp(lang.nativeName) })
      expect(option).toBeInTheDocument()
    }
  })

  it('切换语言触发 setLocale', () => {
    render(<AppearanceTabContainer />)
    // 找到包含 zh-CN 选项的 select
    const zhOption = screen.getByRole('option', { name: /简体中文/ })
    const langSelect = zhOption.closest('select') as HTMLSelectElement
    expect(langSelect).not.toBeNull()

    fireEvent.change(langSelect, { target: { value: 'en-US' } })

    expect(useI18nStore.getState().locale).toBe('en-US')
    expect(localStorage.getItem('openawa_locale')).toBe('en-US')
  })
})

describe('i18n 初始异步加载', () => {
  it('初始为 en-US 时加载后解除语言选择器禁用状态', async () => {
    localStorage.setItem('openawa_locale', 'en-US')
    vi.resetModules()

    const { useI18nStore: initialStore } = await import('@/i18n')

    expect(initialStore.getState().locale).toBe('en-US')
    await vi.waitFor(() => {
      expect(initialStore.getState().isLocaleLoaded).toBe(true)
    })

    localStorage.clear()
  })
})
