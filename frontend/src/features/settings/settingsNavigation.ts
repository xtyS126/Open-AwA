export type SettingsSection =
  | 'general'
  | 'models'
  | 'ai'
  | 'connections'
  | 'data'
  | 'security'
  | 'appearance'
  | 'usage'

export type SettingsView =
  | 'general'
  | 'models'
  | 'profile'
  | 'search'
  | 'prompts'
  | 'backend'
  | 'messaging'
  | 'mcp'
  | 'retention'
  | 'collection'
  | 'security'
  | 'permissions'
  | 'env-vars'
  | 'visual'
  | 'companion'
  | 'usage'

export interface SettingsSectionDefinition {
  id: SettingsSection
  label: string
  defaultView: SettingsView
}

export interface ResolvedSettingsLocation {
  section: SettingsSection
  view: SettingsView
}

export const SETTINGS_SECTIONS: readonly SettingsSectionDefinition[] = [
  { id: 'general', label: '通用', defaultView: 'general' },
  { id: 'models', label: '模型与供应商', defaultView: 'models' },
  { id: 'ai', label: 'AI 与个性', defaultView: 'profile' },
  { id: 'connections', label: '连接', defaultView: 'backend' },
  { id: 'data', label: '数据与隐私', defaultView: 'retention' },
  { id: 'security', label: '安全与权限', defaultView: 'security' },
  { id: 'appearance', label: '外观与伴侣', defaultView: 'visual' },
  { id: 'usage', label: '用量与预算', defaultView: 'usage' },
] as const

const SECTION_VIEWS: Record<SettingsSection, readonly SettingsView[]> = {
  general: ['general'],
  models: ['models'],
  ai: ['profile', 'search', 'prompts'],
  connections: ['backend', 'messaging', 'mcp'],
  data: ['retention', 'collection'],
  security: ['security', 'permissions', 'env-vars'],
  appearance: ['visual', 'companion'],
  usage: ['usage'],
}

function isSettingsSection(value: string): value is SettingsSection {
  return SETTINGS_SECTIONS.some((section) => section.id === value)
}

/**
 * 将设置路径和查询参数解析为受约束的产品分区与子视图。
 */
export function resolveSettingsLocation(pathname: string, search: string): ResolvedSettingsLocation {
  const pathSection = pathname.split('/').filter(Boolean)[1] ?? 'general'
  const section: SettingsSection = isSettingsSection(pathSection) ? pathSection : 'general'
  const params = new URLSearchParams(search)
  const requestedView = section === 'connections'
    ? params.get('type')
    : section === 'appearance'
      ? params.get('section')
      : params.get('view')
  const definition = SETTINGS_SECTIONS.find((item) => item.id === section)
  const defaultView = definition?.defaultView ?? 'general'
  const view = requestedView && SECTION_VIEWS[section].includes(requestedView as SettingsView)
    ? requestedView as SettingsView
    : defaultView

  return { section, view }
}

/**
 * 为设置分区生成唯一规范路径，连接与外观沿用设计文档指定的查询键。
 */
export function buildSettingsPath(section: SettingsSection, view?: SettingsView): string {
  const definition = SETTINGS_SECTIONS.find((item) => item.id === section)
  const normalizedView = view && SECTION_VIEWS[section].includes(view)
    ? view
    : definition?.defaultView
  const base = `/settings/${section}`

  if (!normalizedView || normalizedView === definition?.defaultView) {
    return base
  }
  if (section === 'connections') {
    return `${base}?type=${normalizedView}`
  }
  if (section === 'appearance') {
    return `${base}?section=${normalizedView}`
  }
  return `${base}?view=${normalizedView}`
}

export function getSettingsViews(section: SettingsSection): readonly SettingsView[] {
  return SECTION_VIEWS[section]
}
