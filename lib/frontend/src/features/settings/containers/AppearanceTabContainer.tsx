/**
 * 外观设置 Tab 容器组件
 * 将 ThemePage 的设置内容集成到设置页面的外观 Tab 中
 */
import { useRef, ChangeEvent, useState } from 'react'
import { shallow } from 'zustand/shallow'
import { useThemeStore } from '@/shared/store/themeStore'
import { useI18nStore, LANGUAGES } from '@/i18n'
import { presetThemes, applyPresetTheme } from '@/features/theme/presetThemes'
import styles from '@/features/theme/ThemePage.module.css'

export function AppearanceTabContainer() {
  // 使用选择器 + shallow 浅比较，避免整个 store 变化触发重渲染
  const { config, setConfig } = useThemeStore(s => ({
    config: s.config,
    setConfig: s.setConfig,
  }), shallow)
  const { locale, setLocale, isLocaleLoaded, t } = useI18nStore(s => ({
    locale: s.locale,
    setLocale: s.setLocale,
    isLocaleLoaded: s.isLocaleLoaded,
    t: s.t,
  }), shallow)

  const logoInputRef = useRef<HTMLInputElement>(null)
  const bgInputRef = useRef<HTMLInputElement>(null)
  const [customCSSError, setCustomCSSError] = useState<string>('')

  const handleFontFamilyChange = (e: ChangeEvent<HTMLInputElement>) => {
    setConfig({ fontFamily: e.target.value })
  }

  const handleFontSizeChange = (e: ChangeEvent<HTMLSelectElement>) => {
    setConfig({ fontSize: e.target.value })
  }

  const handleThemeColorChange = (e: ChangeEvent<HTMLInputElement>) => {
    setConfig({ themeColor: e.target.value })
  }

  const handleFileChange = (field: 'logoIcon' | 'backgroundImage') => (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return

    if (file.size > 2 * 1024 * 1024) {
      alert(t('theme.fileTooLarge'))
      return
    }

    const reader = new FileReader()
    reader.onload = (event) => {
      const base64 = event.target?.result as string
      setConfig({ [field]: base64 })
    }
    reader.readAsDataURL(file)
  }

  const handleReset = () => {
    setConfig({
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
    })
  }

  const handlePresetThemeSelect = (presetId: string) => {
    const presetConfig = applyPresetTheme(presetId)
    setConfig(presetConfig)
  }

  const handleCustomCSSChange = (e: ChangeEvent<HTMLTextAreaElement>) => {
    const css = e.target.value
    // 限制长度 10KB
    if (css.length > 10240) {
      setCustomCSSError(t('theme.customCSS.tooLong'))
      return
    }
    setCustomCSSError('')
    setConfig({ customCSS: css })
  }

  return (
    <div className={styles['theme-page']}>
      {/* 语言设置 */}
      <div className={styles['settings-group']}>
        <h3>{t('settings.language')}</h3>
        <div className={styles['setting-item']}>
          <label>{t('settings.interfaceLanguage')}</label>
          <select
            value={locale}
            onChange={(e) => setLocale(e.target.value)}
            disabled={!isLocaleLoaded}
          >
            {LANGUAGES.map((lang) => (
              <option key={lang.code} value={lang.code}>
                {lang.nativeName} ({lang.name})
              </option>
            ))}
          </select>
          <span className={styles['help-text']}>
            {isLocaleLoaded ? t('settings.languageLoaded') : t('settings.languageLoading')}
          </span>
        </div>
      </div>

      {/* 预设主题 */}
      <div className={styles['settings-group']}>
        <h3>{t('theme.preset.title')}</h3>
        <div className={styles['preset-grid']}>
          {presetThemes.map((preset) => (
            <div
              key={preset.id}
              className={`${styles['preset-card']} ${config.presetTheme === preset.id ? styles['preset-active'] : ''}`}
              onClick={() => handlePresetThemeSelect(preset.id)}
            >
              <div className={styles['preset-color']} style={{ backgroundColor: preset.colors.primary }}></div>
              <div className={styles['preset-name']}>{t(preset.nameKey)}</div>
              <div className={styles['preset-desc']}>{t(preset.descriptionKey)}</div>
            </div>
          ))}
        </div>
      </div>

      {/* 字体设置 */}
      <div className={styles['settings-group']}>
        <h3>{t('theme.font')}</h3>
        <div className={styles['setting-item']}>
          <label>{t('theme.fontName')}</label>
          <input
            type="text"
            placeholder={t('theme.fontNamePlaceholder')}
            value={config.fontFamily}
            onChange={handleFontFamilyChange}
          />
        </div>
        <div className={styles['setting-item']}>
          <label>{t('theme.fontSize')}</label>
          <select value={config.fontSize} onChange={handleFontSizeChange}>
            <option value="12px">{t('theme.fontSizeSmall')}</option>
            <option value="14px">{t('theme.fontSizeDefault')}</option>
            <option value="16px">{t('theme.fontSizeMedium')}</option>
            <option value="18px">{t('theme.fontSizeLarge')}</option>
          </select>
        </div>
        <div className={styles['setting-item']}>
          <label>{t('theme.messageFontSize')}</label>
          <select
            value={config.messageFontSize || '16px'}
            onChange={(e) => setConfig({ messageFontSize: e.target.value })}
          >
            <option value="14px">{t('theme.fontSizeSmall')}</option>
            <option value="16px">{t('theme.fontSizeDefault')}</option>
            <option value="18px">{t('theme.fontSizeMedium')}</option>
            <option value="20px">{t('theme.fontSizeLarge')}</option>
          </select>
        </div>
        <div className={styles['setting-item']}>
          <label>{t('theme.codeFont')}</label>
          <input
            type="text"
            placeholder="例如: 'Fira Code', 'Courier New', monospace"
            value={config.codeFontFamily}
            onChange={(e) => setConfig({ codeFontFamily: e.target.value })}
          />
        </div>
      </div>

      {/* 布局与间距 */}
      <div className={styles['settings-group']}>
        <h3>{t('theme.layout')}</h3>
        <div className={styles['setting-item']}>
          <label>{t('theme.borderRadius', { value: config.borderRadius || t('theme.borderRadius.default') })}</label>
          <input
            type="range"
            min="0"
            max="20"
            value={config.borderRadius !== '' ? parseInt(config.borderRadius) : 8}
            onChange={(e) => setConfig({ borderRadius: `${e.target.value}px` })}
            className={styles['range-slider']}
          />
          <div className={styles['range-labels']}>
            <span>{t('theme.borderRadius.straight')}</span>
            <span>{t('theme.borderRadius.round')}</span>
          </div>
        </div>
        <div className={styles['setting-item']}>
          <label>{t('theme.density')}</label>
          <div className={styles['segmented-control']}>
            <button
              className={config.density === 'compact' ? styles['segment-active'] : ''}
              onClick={() => setConfig({ density: 'compact' })}
            >
              {t('theme.density.compact')}
            </button>
            <button
              className={config.density === 'default' ? styles['segment-active'] : ''}
              onClick={() => setConfig({ density: 'default' })}
            >
              {t('theme.density.default')}
            </button>
            <button
              className={config.density === 'comfortable' ? styles['segment-active'] : ''}
              onClick={() => setConfig({ density: 'comfortable' })}
            >
              {t('theme.density.comfortable')}
            </button>
          </div>
        </div>
      </div>

      {/* 动效设置 */}
      <div className={styles['settings-group']}>
        <h3>{t('theme.animation')}</h3>
        <div className={styles['setting-item']}>
          <label className={styles['toggle-label']}>
            <span>{t('theme.animation.enable')}</span>
            <input
              type="checkbox"
              checked={config.animationsEnabled}
              onChange={(e) => setConfig({ animationsEnabled: e.target.checked })}
              className={styles['toggle-checkbox']}
            />
            <span className={styles['toggle-slider']}></span>
          </label>
        </div>
      </div>

      {/* 色彩与背景 */}
      <div className={styles['settings-group']}>
        <h3>{t('theme.color')}</h3>
        <div className={styles['setting-item']}>
          <label>{t('theme.primaryColor')}</label>
          <div className={styles['color-picker-wrap']}>
            <input
              type="color"
              value={config.themeColor || '#4f46e5'}
              onChange={handleThemeColorChange}
            />
            <span className={styles['color-value']}>{config.themeColor || t('theme.borderRadius.default')}</span>
          </div>
        </div>

        <div className={styles['setting-item']}>
          <label>{t('theme.background')}</label>
          <div className={styles['file-upload-wrap']}>
            <input
              type="text"
              placeholder={t('theme.bgPlaceholder')}
              value={config.backgroundImage?.startsWith('data:') ? t('theme.bgUploaded') : config.backgroundImage}
              onChange={(e) => setConfig({ backgroundImage: e.target.value })}
            />
            <button onClick={() => bgInputRef.current?.click()} className={styles['upload-btn']}>{t('app.upload')}</button>
            <input
              type="file"
              accept="image/*"
              ref={bgInputRef}
              style={{ display: 'none' }}
              onChange={handleFileChange('backgroundImage')}
            />
          </div>
          {config.backgroundImage && (
            <button
              className={styles['clear-btn']}
              onClick={() => setConfig({ backgroundImage: '' })}
            >{t('theme.bgClear')}</button>
          )}
        </div>

        {/* 背景图高级选项 */}
        {config.backgroundImage && (
          <>
            <div className={styles['setting-item']}>
              <label>{t('theme.bg.blur', { value: config.backgroundBlur || '0px' })}</label>
              <input
                type="range"
                min="0"
                max="20"
                value={parseInt(config.backgroundBlur) || 0}
                onChange={(e) => setConfig({ backgroundBlur: `${e.target.value}px` })}
                className={styles['range-slider']}
              />
            </div>
            <div className={styles['setting-item']}>
              <label>{t('theme.bg.overlay')}</label>
              <input
                type="text"
                placeholder="例如: rgba(0, 0, 0, 0.3)"
                value={config.backgroundOverlay}
                onChange={(e) => setConfig({ backgroundOverlay: e.target.value })}
                pattern="^(rgba?|hsla?|#[0-9a-fA-F]{3,8}|[a-z]+).*$"
              />
            </div>
          </>
        )}
      </div>

      {/* 头像设置 */}
      <div className={styles['settings-group']}>
        <h3>{t('theme.avatar')}</h3>
        <div className={styles['setting-item']}>
          <label>{t('theme.avatar.shape')}</label>
          <div className={styles['segmented-control']}>
            <button
              className={config.avatarShape === 'circle' ? styles['segment-active'] : ''}
              onClick={() => setConfig({ avatarShape: 'circle' })}
            >
              {t('theme.avatar.circle')}
            </button>
            <button
              className={config.avatarShape === 'rounded' ? styles['segment-active'] : ''}
              onClick={() => setConfig({ avatarShape: 'rounded' })}
            >
              {t('theme.avatar.rounded')}
            </button>
          </div>
        </div>
        <div className={styles['setting-item']}>
          <label>{t('theme.avatar.border')}</label>
          <input
            type="text"
            placeholder="例如: 2px solid #3b82f6"
            value={config.avatarBorder}
            onChange={(e) => setConfig({ avatarBorder: e.target.value })}
          />
        </div>
      </div>

      {/* 品牌设定 */}
      <div className={styles['settings-group']}>
        <h3>{t('theme.brand')}</h3>
        <div className={styles['setting-item']}>
          <label>{t('theme.logo')}</label>
          <div className={styles['file-upload-wrap']}>
            <input
              type="text"
              placeholder={t('theme.logoPlaceholder')}
              value={config.logoIcon?.startsWith('data:') ? t('theme.logoUploaded') : config.logoIcon}
              onChange={(e) => setConfig({ logoIcon: e.target.value })}
            />
            <button onClick={() => logoInputRef.current?.click()} className={styles['upload-btn']}>{t('app.upload')}</button>
            <input
              type="file"
              accept="image/*"
              ref={logoInputRef}
              style={{ display: 'none' }}
              onChange={handleFileChange('logoIcon')}
            />
          </div>
          {config.logoIcon && (
             <div className={styles['logo-preview']}>
               <img src={config.logoIcon} alt={t('theme.logo')} loading="lazy" decoding="async" />
               <button
                  className={styles['clear-btn']}
                  onClick={() => setConfig({ logoIcon: '' })}
                >{t('theme.logoClear')}</button>
             </div>
          )}
        </div>
      </div>

      {/* 自定义 CSS */}
      <div className={styles['settings-group']}>
        <h3>{t('theme.customCSS')}</h3>
        <div className={styles['setting-item']}>
          <label>{t('theme.customCSS.hint')}</label>
          <textarea
            className={styles['css-editor']}
            placeholder="/* 在此输入自定义 CSS 代码 */&#10;.my-class {&#10;  color: red;&#10;}"
            value={config.customCSS}
            onChange={handleCustomCSSChange}
            rows={10}
          />
          {customCSSError && (
            <span className={styles['error-text']}>{customCSSError}</span>
          )}
          <span className={styles['help-text']}>
            {t('theme.customCSS.helpText', { count: (config.customCSS?.length ?? 0).toLocaleString() })}
          </span>
        </div>
      </div>

      <div className={styles['actions']}>
        <button className={styles['reset-btn']} onClick={handleReset}>{t('theme.restoreDefault')}</button>
      </div>
    </div>
  )
}
