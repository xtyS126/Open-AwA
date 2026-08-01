/**
 * i18n 国际化框架 — 多语言支持和语言切换。
 *
 * 语言包采用动态加载策略：仅默认语言（zh-CN）在首屏加载，其他语言按需异步拉取，
 * 减少初始打包体积约 180KB（三个非默认语言包）。
 */
import { createWithEqualityFn } from 'zustand/traditional';

// 语言包类型
export type LocaleKey = string;
export type LocaleDict = Record<LocaleKey, string>;

// 默认语言包静态加载（zh-CN 为默认语言，首屏必需）
import zhCN from './locales/zh-CN';

// 其他语言包动态加载，减小首屏打包体积
const localeLoaders: Record<string, () => Promise<{ default: LocaleDict }>> = {
  'en-US': () => import('./locales/en-US'),
  'ja-JP': () => import('./locales/ja-JP'),
  'ru-RU': () => import('./locales/ru-RU'),
};

// 已加载的语言包缓存（zh-CN 默认已加载）
const loadedLocales: Record<string, LocaleDict> = {
  'zh-CN': zhCN,
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
  /** 当前语言包是否已加载完成（未加载时回退显示 key 或默认语言文本） */
  isLocaleLoaded: boolean;
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
  const candidate = _normalizeLocale(stored || navigator.language);
  return localeLoaders[candidate] || candidate === FALLBACK_LOCALE
    ? candidate
    : FALLBACK_LOCALE;
}

/**
 * 异步加载指定语言包，若已缓存则立即返回。
 */
async function loadLocaleAsync(locale: string): Promise<void> {
  if (loadedLocales[locale]) return;
  const loader = localeLoaders[locale];
  if (!loader) return;
  try {
    const module = await loader();
    loadedLocales[locale] = module.default;
  } catch {
    // 加载失败时静默处理，t() 会回退到默认语言
    console.warn(`[i18n] Failed to load locale: ${locale}`);
  }
}

/**
 * 同步预加载当前初始语言包（在 store 创建前调用）。
 * 若初始语言非 zh-CN，会在后台异步加载，期间 t() 回退到 zh-CN。
 */
const initialLocale = getInitialLocale();

export const useI18nStore = createWithEqualityFn<I18nStore>((set, get) => ({
  locale: initialLocale,
  isLocaleLoaded: initialLocale === FALLBACK_LOCALE || Boolean(loadedLocales[initialLocale]),
  setLocale: (locale) => {
    const normalized = _normalizeLocale(locale);
    if (!normalized || !localeLoaders[normalized] && normalized !== FALLBACK_LOCALE) return;
    localStorage.setItem('openawa_locale', normalized);
    // 标记为未加载，让 UI 显示过渡状态
    const isLoaded = Boolean(loadedLocales[normalized]);
    set({ locale: normalized, isLocaleLoaded: isLoaded });
    // 异步加载语言包
    if (!isLoaded) {
      loadLocaleAsync(normalized).then(() => {
        // 仅当用户未再切换语言时才更新加载状态
        if (get().locale === normalized) {
          set({ isLocaleLoaded: true });
        }
      });
    }
  },
  t: (key, params) => {
    const { locale } = get();
    const dict = loadedLocales[locale] || loadedLocales[FALLBACK_LOCALE] || {};
    // 开发模式下检测缺失的翻译 key
    if (import.meta.env.DEV && !dict[key]) {
      console.warn(`[i18n] Missing translation: "${key}" (locale: ${locale})`);
    }
    let text = dict[key] || key;
    if (params) {
      Object.entries(params).forEach(([k, v]) => {
        text = text.replace(`{${k}}`, v);
      });
    }
    return text;
  },
}));

if (!useI18nStore.getState().isLocaleLoaded) {
  void loadLocaleAsync(initialLocale).then(() => {
    if (useI18nStore.getState().locale === initialLocale) {
      useI18nStore.setState({ isLocaleLoaded: true });
    }
  });
}

/**
 * 便捷翻译函数（非组件中使用）。
 */
export function t(key: string, params?: Record<string, string>): string {
  return useI18nStore.getState().t(key, params);
}

export default useI18nStore;
