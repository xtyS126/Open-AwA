import { useRef, ChangeEvent } from 'react'
import { useThemeStore } from '@/shared/store/themeStore'
import styles from './ThemePage.module.css'

export default function ThemePage() {
  const { config, setConfig } = useThemeStore()
  
  const logoInputRef = useRef<HTMLInputElement>(null)
  const bgInputRef = useRef<HTMLInputElement>(null)

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
      logoIcon: ''
    })
  }

  return (
    <div className={styles['theme-page']}>
      <h2>外观与主题设置</h2>
      
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
      </div>

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
      </div>

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
               <img src={config.logoIcon} alt="Logo 预览" />
               <button 
                  className={styles['clear-btn']} 
                  onClick={() => setConfig({ logoIcon: '' })}
                >清除自定义 Logo</button>
             </div>
          )}
        </div>
      </div>

      <div className={styles['actions']}>
        <button className={styles['reset-btn']} onClick={handleReset}>恢复所有默认设置</button>
      </div>
    </div>
  )
}
