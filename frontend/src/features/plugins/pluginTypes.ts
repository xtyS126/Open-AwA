/**
 * 插件类型工具函数 —— 判定插件来源与受保护状态。
 *
 * 内置插件（source === 'builtin'）受系统保护：
 * - 不可卸载（is_uninstallable === true）
 * - 不可禁用/启用切换
 * - 不可删除
 *
 * 仅允许查看配置。
 */
import type { Plugin } from '@/features/dashboard/dashboard'

/** 内置插件来源标识 */
export const BUILTIN_PLUGIN_SOURCE = 'builtin'

/**
 * 判定插件是否为系统内置插件。
 *
 * 判定依据：source 字段 === 'builtin'。当 source 缺省时回退到 category 字段，
 * 兼容历史数据中仅设置 category 而未设置 source 的情况。
 */
export function isBuiltinPlugin(plugin: Pick<Plugin, 'source' | 'category'>): boolean {
  if (typeof plugin.source === 'string' && plugin.source.trim() !== '') {
    return plugin.source === BUILTIN_PLUGIN_SOURCE
  }
  if (typeof plugin.category === 'string' && plugin.category.trim() !== '') {
    return plugin.category === BUILTIN_PLUGIN_SOURCE
  }
  return false
}

/**
 * 判定插件是否不可卸载（受保护）。
 *
 * 判定依据：is_uninstallable === true。当字段缺失时，回退到 isBuiltinPlugin 判定，
 * 保证内置插件在缺少显式标记时也受保护。
 */
export function isUninstallablePlugin(plugin: Plugin): boolean {
  if (typeof plugin.is_uninstallable === 'boolean') {
    return plugin.is_uninstallable
  }
  return isBuiltinPlugin(plugin)
}
