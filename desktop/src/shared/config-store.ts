/**
 * electron-store 配置存储封装
 * 提供类型安全的配置读写接口
 */
import Store from 'electron-store'
import { DEFAULT_CONFIG, type AppConfig, type WindowBounds, type UpdateConfig } from './types'

let _store: Store<AppConfig> | null = null

/** 获取 store 单例 */
export function getConfigStore(): Store<AppConfig> {
  if (!_store) {
    _store = new Store<AppConfig>({
      name: 'openawa-config',
      defaults: DEFAULT_CONFIG,
      encryptionKey: 'openawa-desktop-v1',
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
