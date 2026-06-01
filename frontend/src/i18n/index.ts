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

export const useI18nStore = create<I18nStore>((set, get) => ({
  locale: localStorage.getItem('openawa_locale') || navigator.language || FALLBACK_LOCALE,
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
