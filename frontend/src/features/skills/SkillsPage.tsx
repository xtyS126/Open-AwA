import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate } from '@/shared/routing'
import { useQuery } from '@tanstack/react-query'
import {
  Search,
  Plus,
  Store,
  Edit3,
  Eye,
  Wrench,
  Globe,
  FileText,
  Search as SearchIcon,
  Boxes,
  type LucideIcon,
} from 'lucide-react'
import { skillsAPI } from '@/shared/api/api'
import type { SkillItem } from '@/shared/api/types'
import SkillModal from '@/features/skills/SkillModal'
import { EmptyState, Toggle, Badge } from '@/shared/components/ui'
import { appLogger } from '@/shared/utils/logger'
import { getErrorMessage } from '@/shared/utils/errorMessages'
import styles from './SkillsPage.module.css'

/* ──────────────────────────────────────────────────────────────
 * 说明：原页面的「卸载」操作在 Canvas 设计参考中未提供入口，
 * 此处仅保留启用/禁用切换。编辑/详情按钮为视觉占位，
 * 待后续接入编辑模态与详情视图后再补充回调。
 * ────────────────────────────────────────────────────────────── */

/* ──────────────────────────────────────────────────────────────
 * 技能分类定义
 * 根据技能名称或 config.category 推断分类，用于决定图标和配色
 * ────────────────────────────────────────────────────────────── */

type SkillCategory = 'search' | 'tool' | 'browser' | 'document' | 'general'

interface CategoryStyle {
  /** 图标组件 */
  Icon: LucideIcon
  /** 图标容器背景色（CSS 变量） */
  bg: string
  /** 图标颜色（CSS 变量） */
  color: string
  /** 中文标签 */
  label: string
}

/** 分类样式映射，对齐 Canvas 设计参考的语义色板 */
const CATEGORY_STYLES: Record<SkillCategory, CategoryStyle> = {
  search: {
    Icon: SearchIcon,
    bg: 'var(--color-info-bg)',
    color: 'var(--color-primary)',
    label: '搜索',
  },
  tool: {
    Icon: Wrench,
    bg: 'var(--color-warning-bg)',
    color: 'var(--color-warning-strong)',
    label: '工具',
  },
  browser: {
    Icon: Globe,
    bg: 'var(--color-tag-purple-bg)',
    color: 'var(--color-tag-purple-text)',
    label: '浏览器',
  },
  document: {
    Icon: FileText,
    bg: 'var(--color-error-bg)',
    color: 'var(--color-error-strong)',
    label: '文档',
  },
  general: {
    Icon: Boxes,
    bg: 'var(--color-bg-tertiary)',
    color: 'var(--color-text-tertiary)',
    label: '通用',
  },
}

/** 根据技能名称关键词推断分类 */
function inferCategoryFromName(name: string): SkillCategory {
  const lower = name.toLowerCase()
  if (lower.includes('search') || lower.includes('检索')) return 'search'
  if (lower.includes('browser') || lower.includes('cdp') || lower.includes('selenium')) return 'browser'
  if (lower.includes('pdf') || lower.includes('doc') || lower.includes('document')) return 'document'
  if (lower.includes('file') || lower.includes('tool') || lower.includes('manager')) return 'tool'
  return 'general'
}

/** 从 skill.config.category 字段读取分类，缺失时根据名称推断 */
function resolveSkillCategory(skill: SkillItem): SkillCategory {
  const configCategory = skill.config?.['category']
  if (typeof configCategory === 'string' && configCategory in CATEGORY_STYLES) {
    return configCategory as SkillCategory
  }
  return inferCategoryFromName(skill.name)
}

/** 判断技能是否为内置（config.is_builtin === true 时为内置） */
function isBuiltInSkill(skill: SkillItem): boolean {
  return skill.config?.['is_builtin'] === true
}

/* ──────────────────────────────────────────────────────────────
 * 筛选器类型
 * ────────────────────────────────────────────────────────────── */

type StatusFilter = 'all' | 'enabled' | 'disabled'
type TypeFilter = 'all' | SkillCategory

/* ──────────────────────────────────────────────────────────────
 * 主组件
 * ────────────────────────────────────────────────────────────── */

function SkillsPage() {
  const navigate = useNavigate()

  const [isModalOpen, setIsModalOpen] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)
  const [pendingSkillId, setPendingSkillId] = useState<string | null>(null)

  // 筛选状态
  const [searchQuery, setSearchQuery] = useState('')
  const [typeFilter, setTypeFilter] = useState<TypeFilter>('all')
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all')

  /** 技能列表查询 —— TanStack Query 管理服务端状态 */
  const skillsQuery = useQuery<SkillItem[], Error>({
    queryKey: ['skills', 'list'],
    queryFn: async () => {
      const response = await skillsAPI.getAll()
      return response.data
    },
    retry: false,
  })

  const skills = skillsQuery.data ?? []
  const loading = skillsQuery.isLoading
  const loadError = skillsQuery.error
    ? getErrorMessage(skillsQuery.error, '加载技能列表失败，请稍后重试')
    : null

  /** 失败时记录日志（error 变化时触发） */
  useEffect(() => {
    if (skillsQuery.error) {
      const error = skillsQuery.error
      appLogger.error({
        event: 'skills_page_load_failed',
        module: 'skills',
        action: 'load',
        status: 'failure',
        message: '加载技能列表失败',
        extra: { error: error instanceof Error ? error.message : String(error) },
      })
    }
  }, [skillsQuery.error])

  /** 刷新技能列表 */
  const loadSkills = useCallback(async () => {
    await skillsQuery.refetch()
  }, [skillsQuery])

  /** 切换技能启用状态 */
  const handleToggle = useCallback(
    async (id: string) => {
      setActionError(null)
      setPendingSkillId(id)
      try {
        await skillsAPI.toggle(id)
        await skillsQuery.refetch()
      } catch (error) {
        appLogger.error({
          event: 'skills_page_toggle_failed',
          module: 'skills',
          action: 'toggle',
          status: 'failure',
          message: '切换技能状态失败',
          extra: { skill_id: id, error: error instanceof Error ? error.message : String(error) },
        })
        setActionError(getErrorMessage(error, '切换技能状态失败，请稍后重试'))
      } finally {
        setPendingSkillId(null)
      }
    },
    [skillsQuery]
  )

  /** 跳转技能市场 */
  const handleOpenMarket = useCallback(() => {
    navigate('/skills/market')
  }, [navigate])

  /** 根据筛选条件过滤技能列表 */
  const filteredSkills = useMemo(() => {
    const query = searchQuery.trim().toLowerCase()
    return skills.filter((skill) => {
      // 名称搜索匹配
      if (query && !skill.name.toLowerCase().includes(query)) return false
      // 类型筛选
      if (typeFilter !== 'all' && resolveSkillCategory(skill) !== typeFilter) return false
      // 状态筛选
      if (statusFilter === 'enabled' && !skill.enabled) return false
      if (statusFilter === 'disabled' && skill.enabled) return false
      return true
    })
  }, [skills, searchQuery, typeFilter, statusFilter])

  /** 汇总统计 */
  const summaryStats = useMemo(() => {
    const total = skills.length
    const enabledCount = skills.filter((s) => s.enabled).length
    const builtInCount = skills.filter(isBuiltInSkill).length
    return { total, enabledCount, builtInCount }
  }, [skills])

  if (loading) {
    return <div className={styles.loading}>加载中...</div>
  }

  return (
    <div className={styles['skills-page']}>
      {/* 页面头部 */}
      <header className={styles['page-header']}>
        <div className={styles['page-header-left']}>
          <h1 className={styles['page-title']}>技能管理</h1>
          <p className={styles['page-subtitle']}>管理和配置 AI Agent 可用的技能工具</p>
        </div>
        <div className={styles['page-header-right']}>
          <button
            type="button"
            className={styles['btn-secondary']}
            onClick={handleOpenMarket}
          >
            <Store size={16} />
            <span>技能市场</span>
          </button>
          <button
            type="button"
            className={styles['btn-primary']}
            onClick={() => setIsModalOpen(true)}
          >
            <Plus size={16} />
            <span>创建技能</span>
          </button>
        </div>
      </header>

      {/* 错误提示 */}
      {loadError && <div className={styles['error-banner']}>{loadError}</div>}
      {actionError && <div className={styles['error-banner']}>{actionError}</div>}

      {/* 内容区 */}
      <div className={styles['content']}>
        {/* 筛选栏 */}
        <div className={styles['filter-bar']}>
          <div className={styles['search-wrapper']}>
            <Search size={16} className={styles['search-icon']} />
            <input
              type="text"
              className={styles['search-input']}
              placeholder="搜索技能名称..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
            />
          </div>
          <select
            className={styles['filter-select']}
            value={typeFilter}
            onChange={(e) => setTypeFilter(e.target.value as TypeFilter)}
          >
            <option value="all">全部类型</option>
            <option value="search">搜索</option>
            <option value="tool">工具</option>
            <option value="browser">浏览器</option>
            <option value="document">文档</option>
            <option value="general">通用</option>
          </select>
          <select
            className={styles['filter-select']}
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value as StatusFilter)}
          >
            <option value="all">全部状态</option>
            <option value="enabled">已启用</option>
            <option value="disabled">已停用</option>
          </select>
        </div>

        {/* 技能卡片列表 */}
        {filteredSkills.length === 0 ? (
          <EmptyState
            title={loadError ? '技能列表暂时不可用' : '没有匹配的技能'}
            description={
              loadError
                ? '请检查网络连接后重试'
                : '尝试调整筛选条件，或点击下方按钮创建第一个技能'
            }
            actionLabel={loadError ? '重试加载' : '创建技能'}
            onAction={
              loadError
                ? () => {
                    void loadSkills()
                  }
                : () => setIsModalOpen(true)
            }
          />
        ) : (
          <div className={styles['card-list']}>
            {filteredSkills.map((skill) => {
              const category = resolveSkillCategory(skill)
              const categoryStyle = CATEGORY_STYLES[category]
              const { Icon } = categoryStyle
              const builtIn = isBuiltInSkill(skill)
              const isPending = pendingSkillId === skill.id

              return (
                <div key={skill.id} className={styles['skill-card']}>
                  {/* 图标 */}
                  <div
                    className={styles['skill-icon']}
                    style={{ background: categoryStyle.bg }}
                  >
                    <Icon size={22} color={categoryStyle.color} />
                  </div>

                  {/* 中间信息 */}
                  <div className={styles['skill-info']}>
                    <div className={styles['skill-title-row']}>
                      <h3 className={styles['skill-name']}>{skill.name}</h3>
                      <Badge variant="primary" text={builtIn ? '内置' : '自定义'} />
                      {skill.enabled ? (
                        <Badge variant="success" text="已启用" />
                      ) : (
                        <span className={styles['badge-disabled']}>已停用</span>
                      )}
                    </div>
                    <p className={styles['skill-desc']}>
                      {skill.description || '暂无描述'}
                    </p>
                    <div className={styles['skill-meta']}>
                      <span className={styles['meta-item']}>
                        <span className={styles['meta-label']}>分类</span>
                        {categoryStyle.label}
                      </span>
                      <span className={styles['meta-divider']} />
                      <span className={styles['meta-item']}>
                        <span className={styles['meta-label']}>版本</span>
                        v{skill.version || '1.0.0'}
                      </span>
                    </div>
                  </div>

                  {/* 右侧操作 */}
                  <div className={styles['skill-actions']}>
                    <Toggle
                      checked={skill.enabled}
                      onChange={() => void handleToggle(skill.id)}
                      disabled={isPending}
                      size="md"
                      aria-label={skill.enabled ? '停用技能' : '启用技能'}
                    />
                    <button
                      type="button"
                      className={styles['btn-outline-sm']}
                      disabled={isPending}
                      title="编辑技能（即将上线）"
                    >
                      <Edit3 size={12} />
                      <span>编辑</span>
                    </button>
                    <button
                      type="button"
                      className={styles['btn-outline-sm']}
                      disabled={isPending}
                      title="查看技能详情（即将上线）"
                    >
                      <Eye size={12} />
                      <span>详情</span>
                    </button>
                  </div>
                </div>
              )
            })}
          </div>
        )}

        {/* 汇总信息栏 */}
        {skills.length > 0 && (
          <div className={styles['summary-bar']}>
            <Boxes size={16} className={styles['summary-icon']} />
            <span className={styles['summary-text']}>
              共 <span className={styles['summary-total']}>{summaryStats.total}</span> 个技能，
              <span className={styles['summary-enabled']}>{summaryStats.enabledCount}</span> 个已启用
              {summaryStats.builtInCount > 0 && (
                <>
                  ，<span className={styles['summary-total']}>{summaryStats.builtInCount}</span> 个内置
                </>
              )}
            </span>
          </div>
        )}
      </div>

      {isModalOpen && (
        <SkillModal
          onClose={() => setIsModalOpen(false)}
          onSuccess={() => {
            setIsModalOpen(false)
            void loadSkills()
          }}
        />
      )}
    </div>
  )
}

export default SkillsPage
