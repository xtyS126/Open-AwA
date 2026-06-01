/**
 * i18n 国际化框架 — 多语言支持和语言切换。
 */
import { create } from 'zustand';

// 语言包类型
export type LocaleKey = string;
export type LocaleDict = Record<LocaleKey, string>;

// 加载语言包
import zhCN from './locales/zh-CN';
import enUS from './locales/en-US';
import jaJP from './locales/ja-JP';
import ruRU from './locales/ru-RU';

const LOCALES: Record<string, LocaleDict> = {
  'zh-CN': zhCN,
  'en-US': enUS,
  'ja-JP': jaJP,
  'ru-RU': ruRU,
};

const FALLBACK_LOCALE = 'zh-CN';

// 语言元数据
export const LANGUAGES = [
  { code: 'zh-CN', name: '简体中文', nativeName: '简体中文' },
  { code: 'en-US', name: 'English', nativeName: 'English' },
  { code: 'ja-JP', name: '日本語', nativeName: '日本語' },
  { code: 'ru-RU', name: 'Русский', nativeName: 'Русский' },
] as const;

interface I18nStore {
  locale: string;
  setLocale: (locale: string) => void;
  t: (key: string, params?: Record<string, string>) => string;
}

function _normalizeLocale(raw: string): string {
  // 将短代码映射到完整 locale（如 'en' → 'en-US'）
  const shortMap: Record<string, string> = {
    en: 'en-US',
    ja: 'ja-JP',
    ru: 'ru-RU',
    zh: 'zh-CN',
  };
  if (shortMap[raw]) return shortMap[raw];
  // 已是完整代码（如 'en-US'），直接返回
  if (raw.includes('-')) return raw;
  return raw;
}

function getInitialLocale(): string {
  if (typeof window === 'undefined') return FALLBACK_LOCALE;
  const stored = localStorage.getItem('openawa_locale');
  if (stored) return stored;
  return _normalizeLocale(navigator.language) || FALLBACK_LOCALE;
}

export const useI18nStore = create<I18nStore>((set, get) => ({
  locale: getInitialLocale(),
  setLocale: (locale) => {
    localStorage.setItem('openawa_locale', locale);
    set({ locale });
  },
  t: (key, params) => {
    const { locale } = get();
    const dict = LOCALES[locale] || LOCALES[FALLBACK_LOCALE] || {};
    let text = dict[key] || key;
    if (params) {
      Object.entries(params).forEach(([k, v]) => {
        text = text.replace(`{${k}}`, v);
      });
    }
    return text;
  },
}));

/**
 * 便捷翻译函数（非组件中使用）。
 */
export function t(key: string, params?: Record<string, string>): string {
  return useI18nStore.getState().t(key, params);
}

export default useI18nStore;
