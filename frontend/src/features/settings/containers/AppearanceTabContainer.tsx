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
      alert('文件大小不能超过 2MB')
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
      setCustomCSSError('自定义 CSS 长度不能超过 10KB')
      return
    }
    setCustomCSSError('')
    setConfig({ customCSS: css })
  }

  return (
    <div className={styles['theme-page']}>
      {/* 语言设置 */}
      <div className={styles['settings-group']}>
        <h3>{t('settings.language') || '语言设置'}</h3>
        <div className={styles['setting-item']}>
          <label>{t('settings.interfaceLanguage') || '界面语言'}</label>
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
            {isLocaleLoaded
              ? (t('settings.languageLoaded') || '语言包已加载')
              : (t('settings.languageLoading') || '正在加载语言包...')}
          </span>
        </div>
      </div>

      {/* 预设主题 */}
      <div className={styles['settings-group']}>
        <h3>预设主题</h3>
        <div className={styles['preset-grid']}>
          {presetThemes.map((preset) => (
            <div
              key={preset.id}
              className={`${styles['preset-card']} ${config.presetTheme === preset.id ? styles['preset-active'] : ''}`}
              onClick={() => handlePresetThemeSelect(preset.id)}
            >
              <div className={styles['preset-color']} style={{ backgroundColor: preset.colors.primary }}></div>
              <div className={styles['preset-name']}>{preset.name}</div>
              <div className={styles['preset-desc']}>{preset.description}</div>
            </div>
          ))}
        </div>
      </div>

      {/* 字体设置 */}
      <div className={styles['settings-group']}>
        <h3>字体设置</h3>
        <div className={styles['setting-item']}>
          <label>自定义字体名称</label>
          <input
            type="text"
            placeholder="例如: 'Microsoft YaHei', Arial"
            value={config.fontFamily}
            onChange={handleFontFamilyChange}
          />
        </div>
        <div className={styles['setting-item']}>
          <label>全局字体大小</label>
          <select value={config.fontSize} onChange={handleFontSizeChange}>
            <option value="12px">较小 (12px)</option>
            <option value="14px">默认 (14px)</option>
            <option value="16px">中等 (16px)</option>
            <option value="18px">较大 (18px)</option>
          </select>
        </div>
        <div className={styles['setting-item']}>
          <label>消息字体大小</label>
          <select
            value={config.messageFontSize || '16px'}
            onChange={(e) => setConfig({ messageFontSize: e.target.value })}
          >
            <option value="14px">较小 (14px)</option>
            <option value="16px">默认 (16px)</option>
            <option value="18px">中等 (18px)</option>
            <option value="20px">较大 (20px)</option>
          </select>
        </div>
        <div className={styles['setting-item']}>
          <label>代码字体</label>
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
        <h3>布局与间距</h3>
        <div className={styles['setting-item']}>
          <label>圆角大小: {config.borderRadius || '默认'}</label>
          <input
            type="range"
            min="0"
            max="20"
            value={config.borderRadius !== '' ? parseInt(config.borderRadius) : 8}
            onChange={(e) => setConfig({ borderRadius: `${e.target.value}px` })}
            className={styles['range-slider']}
          />
          <div className={styles['range-labels']}>
            <span>0px (直角)</span>
            <span>20px (圆润)</span>
          </div>
        </div>
        <div className={styles['setting-item']}>
          <label>间距密度</label>
          <div className={styles['segmented-control']}>
            <button
              className={config.density === 'compact' ? styles['segment-active'] : ''}
              onClick={() => setConfig({ density: 'compact' })}
            >
              紧凑
            </button>
            <button
              className={config.density === 'default' ? styles['segment-active'] : ''}
              onClick={() => setConfig({ density: 'default' })}
            >
              默认
            </button>
            <button
              className={config.density === 'comfortable' ? styles['segment-active'] : ''}
              onClick={() => setConfig({ density: 'comfortable' })}
            >
              宽松
            </button>
          </div>
        </div>
      </div>

      {/* 动效设置 */}
      <div className={styles['settings-group']}>
        <h3>动效设置</h3>
        <div className={styles['setting-item']}>
          <label className={styles['toggle-label']}>
            <span>启用动效</span>
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
        <h3>色彩与背景</h3>
        <div className={styles['setting-item']}>
          <label>主色调</label>
          <div className={styles['color-picker-wrap']}>
            <input
              type="color"
              value={config.themeColor || '#4f46e5'}
              onChange={handleThemeColorChange}
            />
            <span className={styles['color-value']}>{config.themeColor || '默认'}</span>
          </div>
        </div>

        <div className={styles['setting-item']}>
          <label>自定义背景图片</label>
          <div className={styles['file-upload-wrap']}>
            <input
              type="text"
              placeholder="请输入图片 URL 或点击右侧上传"
              value={config.backgroundImage?.startsWith('data:') ? '已上传本地图片' : config.backgroundImage}
              onChange={(e) => setConfig({ backgroundImage: e.target.value })}
            />
            <button onClick={() => bgInputRef.current?.click()} className={styles['upload-btn']}>上传</button>
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
            >清除背景图</button>
          )}
        </div>

        {/* 背景图高级选项 */}
        {config.backgroundImage && (
          <>
            <div className={styles['setting-item']}>
              <label>背景模糊度: {config.backgroundBlur || '0px'}</label>
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
              <label>背景覆盖层颜色</label>
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
        <h3>头像设置</h3>
        <div className={styles['setting-item']}>
          <label>头像形状</label>
          <div className={styles['segmented-control']}>
            <button
              className={config.avatarShape === 'circle' ? styles['segment-active'] : ''}
              onClick={() => setConfig({ avatarShape: 'circle' })}
            >
              圆形
            </button>
            <button
              className={config.avatarShape === 'rounded' ? styles['segment-active'] : ''}
              onClick={() => setConfig({ avatarShape: 'rounded' })}
            >
              圆角方形
            </button>
          </div>
        </div>
        <div className={styles['setting-item']}>
          <label>头像边框样式</label>
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
        <h3>品牌设定</h3>
        <div className={styles['setting-item']}>
          <label>自定义 Logo 图标</label>
          <div className={styles['file-upload-wrap']}>
            <input
              type="text"
              placeholder="请输入图标 URL 或点击右侧上传"
              value={config.logoIcon?.startsWith('data:') ? '已上传本地图标' : config.logoIcon}
              onChange={(e) => setConfig({ logoIcon: e.target.value })}
            />
            <button onClick={() => logoInputRef.current?.click()} className={styles['upload-btn']}>上传</button>
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
               <img src={config.logoIcon} alt="Logo 预览" loading="lazy" decoding="async" />
               <button
                  className={styles['clear-btn']}
                  onClick={() => setConfig({ logoIcon: '' })}
                >清除自定义 Logo</button>
             </div>
          )}
        </div>
      </div>

      {/* 自定义 CSS */}
      <div className={styles['settings-group']}>
        <h3>自定义 CSS</h3>
        <div className={styles['setting-item']}>
          <label>高级用户可注入自定义样式代码</label>
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
            最大长度: 10KB | 当前: {(config.customCSS?.length ?? 0).toLocaleString()} 字符 | 代码将实时应用到页面 | 请勿包含外部资源引用
          </span>
        </div>
      </div>

      <div className={styles['actions']}>
        <button className={styles['reset-btn']} onClick={handleReset}>恢复所有默认设置</button>
      </div>
    </div>
  )
}
