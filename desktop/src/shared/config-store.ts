/**
 * electron-store 配置存储封装
 * 提供类型安全的配置读写接口
 *
 * 安全：使用 Electron safeStorage API（Windows DPAPI / macOS Keychain / Linux libsecret）
 * 保护加密密钥，而非硬编码字符串。攻击者反编译 app.asar 无法直接获得密钥，
 * 必须在目标用户操作系统上下文中调用 safeStorage.decryptString 才能解密配置。
 *
 * 实现说明：safeStorage.encryptString 是非确定性的（每次返回不同密文），
 * 因此不能直接作为 electron-store 的 encryptionKey。方案是：
 * 1. 首次运行生成随机 UUID 作为 encryptionKey
 * 2. 用 safeStorage 加密该 UUID，持久化到独立密钥文件
 * 3. 后续运行从密钥文件读取密文，用 safeStorage 解密得到原始 UUID
 */
import Store from 'electron-store'
import { safeStorage } from 'electron'
import { randomUUID } from 'node:crypto'
import { existsSync, readFileSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { app } from 'electron'
import { DEFAULT_CONFIG, type AppConfig, type WindowBounds, type UpdateConfig, type CompanionConfig, type PetConfig } from './types'

let _store: Store<AppConfig> | null = null

/** 密钥文件路径：放在 userData 目录下（OS 用户隔离） */
function _keyFilePath(): string {
  return join(app.getPath('userData'), 'store.key')
}

/** 加载或生成 electron-store 加密密钥，使用 safeStorage 保护 */
function _loadOrCreateEncryptionKey(): string | undefined {
  const keyPath = _keyFilePath()

  // safeStorage 不可用时降级为明文（electron-store 默认行为）
  if (!safeStorage.isEncryptionAvailable()) {
    console.warn('[config-store] safeStorage 不可用，配置文件将明文存储，请检查 OS 密钥链服务')
    return undefined
  }

  try {
    if (existsSync(keyPath)) {
      // 读取已持久化的密文，用 safeStorage 解密
      const encryptedBuf = readFileSync(keyPath)
      return safeStorage.decryptString(encryptedBuf)
    }
    // 首次运行：生成随机 UUID 作为密钥，用 safeStorage 加密后持久化
    const newKey = randomUUID()
    const encrypted = safeStorage.encryptString(newKey)
    writeFileSync(keyPath, encrypted, { mode: 0o600 })
    return newKey
  } catch (err) {
    // 解密失败（如 OS 用户切换、密钥链重置）：删除旧密钥文件重新生成
    console.warn('[config-store] 密钥加载失败，将重新生成（旧配置可能无法解密）:', err)
    try {
      if (existsSync(keyPath)) {
        // 重新生成密钥并覆盖旧文件
        const newKey = randomUUID()
        const encrypted = safeStorage.encryptString(newKey)
        writeFileSync(keyPath, encrypted, { mode: 0o600 })
        return newKey
      }
    } catch (regenErr) {
      console.error('[config-store] 密钥重新生成失败:', regenErr)
    }
    return undefined
  }
}

/** 获取 store 单例 */
export function getConfigStore(): Store<AppConfig> {
  if (!_store) {
    const encryptionKey = _loadOrCreateEncryptionKey()
    _store = new Store<AppConfig>({
      name: 'openawa-config',
      defaults: DEFAULT_CONFIG,
      encryptionKey,
    })
  }
  return _store
}

/** 获取后端 URL */
export function getBackendUrl(): string {
  return getConfigStore().get('backend.url')
}

/** 设置后端 URL */
export function setBackendUrl(url: string): void {
  getConfigStore().set('backend.url', url)
}

/** 获取窗口边界 */
export function getWindowBounds(): WindowBounds {
  return getConfigStore().get('window.bounds')
}

/** 设置窗口边界 */
export function setWindowBounds(bounds: WindowBounds): void {
  getConfigStore().set('window.bounds', bounds)
}

/** 获取窗口是否最大化 */
export function getIsMaximized(): boolean {
  return getConfigStore().get('window.isMaximized')
}

/** 设置窗口是否最大化 */
export function setIsMaximized(isMaximized: boolean): void {
  getConfigStore().set('window.isMaximized', isMaximized)
}

/** 获取托盘配置：是否最小化到托盘 */
export function getMinimizeToTray(): boolean {
  return getConfigStore().get('tray.minimizeToTray')
}

/** 设置托盘配置：是否最小化到托盘 */
export function setMinimizeToTray(minimizeToTray: boolean): void {
  getConfigStore().set('tray.minimizeToTray', minimizeToTray)
}

/** 获取开机自启设置 */
export function getAutostart(): boolean {
  return getConfigStore().get('autostart')
}

/** 设置开机自启 */
export function setAutostart(autostart: boolean): void {
  getConfigStore().set('autostart', autostart)
}

/** 获取自动更新配置 */
export function getUpdateConfig(): UpdateConfig {
  return getConfigStore().get('update')
}

/** 设置自动更新配置 */
export function setUpdateConfig(autoCheck: boolean, source: string): void {
  getConfigStore().set('update', { autoCheck, source })
}

/** 获取陪伴通知配置 */
export function getCompanionConfig(): CompanionConfig {
  return getConfigStore().get('companion')
}

/** 设置陪伴通知配置 */
export function setCompanionConfig(config: CompanionConfig): void {
  getConfigStore().set('companion', config)
}

/** 获取宠物悬浮窗配置 */
export function getPetConfig(): PetConfig {
  return getConfigStore().get('pet')
}

/** 设置宠物悬浮窗配置 */
export function setPetConfig(config: PetConfig): void {
  getConfigStore().set('pet', config)
}
