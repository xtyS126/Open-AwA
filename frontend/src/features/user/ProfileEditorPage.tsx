/**
 * 可交互用户画像编辑器——支持查看、编辑、确认/否定、添加和删除画像事实。
 */

import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  ArrowLeft, Plus, Check, X, Edit3, Trash2, Loader2,
  Search, Save, AlertCircle,
} from 'lucide-react'
import { shallow } from 'zustand/shallow'
import { useProfileStore } from '@/shared/store/profileStore'
import { extractProfile } from '@/shared/api/profileApi'
import { PROFILE_CATEGORY_LABELS } from './profileCategoryLabels'
import styles from './ProfileEditorPage.module.css'

const ALL_CATEGORIES = '全部'

function ProfileEditorPage() {
  const navigate = useNavigate()
  // 使用选择器 + shallow 浅比较，避免整个 store 变化触发重渲染
  const {
    facts, loading, extracting, error,
    fetchFacts, fetchStats,
    editFact, addFact, removeFact,
    confirmFact, disputeFactItem,
    setSelectedCategory,
    clearError,
  } = useProfileStore(s => ({
    facts: s.facts,
    loading: s.loading,
    extracting: s.extracting,
    error: s.error,
    fetchFacts: s.fetchFacts,
    fetchStats: s.fetchStats,
    editFact: s.editFact,
    addFact: s.addFact,
    removeFact: s.removeFact,
    confirmFact: s.confirmFact,
    disputeFactItem: s.disputeFactItem,
    setSelectedCategory: s.setSelectedCategory,
    clearError: s.clearError,
  }), shallow)

  const [searchTerm, setSearchTerm] = useState('')
  const [editingFactId, setEditingFactId] = useState<string | null>(null)
  const [editValue, setEditValue] = useState('')
  const [showAddForm, setShowAddForm] = useState(false)
  const [newCategory, setNewCategory] = useState('preference')
  const [newKey, setNewKey] = useState('')
  const [newValue, setNewValue] = useState('')
  const [successMsg, setSuccessMsg] = useState<string | null>(null)
  const [activeCategory, setActiveCategory] = useState(ALL_CATEGORIES)

  useEffect(() => {
    void fetchFacts()
    void fetchStats()
  }, [fetchFacts, fetchStats])

  const handleCategoryFilter = (cat: string) => {
    setActiveCategory(cat)
    setSelectedCategory(cat === ALL_CATEGORIES ? null : cat)
    void fetchFacts({ category: cat === ALL_CATEGORIES ? undefined : cat })
  }

  const startEdit = (factId: string, currentValue: string) => {
    setEditingFactId(factId)
    setEditValue(currentValue)
  }

  const cancelEdit = () => {
    setEditingFactId(null)
    setEditValue('')
  }

  const saveEdit = async (factId: string) => {
    if (!editValue.trim()) return
    await editFact(factId, editValue.trim())
    setEditingFactId(null)
    setEditValue('')
    setSuccessMsg('已更新')
    setTimeout(() => setSuccessMsg(null), 2000)
  }

  const handleAdd = async () => {
    if (!newKey.trim() || !newValue.trim()) return
    await addFact(newCategory, newKey.trim().toLowerCase().replace(/\s+/g, '_'), newValue.trim())
    setShowAddForm(false)
    setNewKey('')
    setNewValue('')
    setSuccessMsg('已添加')
    setTimeout(() => setSuccessMsg(null), 2000)
  }

  const handleDelete = async (factId: string) => {
    if (!confirm('确定删除此画像事实吗？')) return
    await removeFact(factId)
    setSuccessMsg('已删除')
    setTimeout(() => setSuccessMsg(null), 2000)
  }

  const handleVerify = async (factId: string) => {
    await confirmFact(factId)
    setSuccessMsg('已确认')
    setTimeout(() => setSuccessMsg(null), 2000)
  }

  const handleDispute = async (factId: string) => {
    await disputeFactItem(factId)
    setSuccessMsg('已反馈，将重新评估')
    setTimeout(() => setSuccessMsg(null), 2000)
  }

  const handleExtract = async () => {
    await extractProfile({})
    await fetchFacts()
    await fetchStats()
    setSuccessMsg('提取完成')
    setTimeout(() => setSuccessMsg(null), 2000)
  }

  // 按类别分组
  const groupedFacts: Record<string, typeof facts> = facts.reduce((acc, fact) => {
    const cat = fact.category
    if (!acc[cat]) acc[cat] = []
    acc[cat].push(fact)
    return acc
  }, {} as Record<string, typeof facts>)

  // 搜索过滤
  const filteredGrouped = searchTerm.trim()
    ? Object.fromEntries(
        Object.entries(groupedFacts).map(([cat, catFacts]) => [
          cat,
          catFacts.filter((f) =>
            f.fact_key.includes(searchTerm.toLowerCase()) ||
            f.fact_value.includes(searchTerm)
          ),
        ]).filter((entry): entry is [string, typeof facts] => entry[1].length > 0)
      )
    : groupedFacts

  // 获取所有存在的类别
  const allCategories = [ALL_CATEGORIES, ...Object.keys(PROFILE_CATEGORY_LABELS).filter(
    (c) => c !== 'custom'
  )]

  return (
    <div className={styles['editor-page']}>
      {/* 顶部栏 */}
      <div className={styles['top-bar']}>
        <button className={styles['back-btn']} onClick={() => navigate('/user')}>
          <ArrowLeft size={16} /> 返回用户中心
        </button>
        <h1>画像编辑器</h1>
        <div className={styles['top-actions']}>
          {successMsg && <span className={styles['success-msg']}>{successMsg}</span>}
          <button
            className="btn btn-primary"
            onClick={() => void handleExtract()}
            disabled={extracting}
          >
            {extracting ? <><Loader2 size={14} className={styles['spin']} /> 提取中...</> : '智能提取'}
          </button>
          <button className="btn btn-secondary" onClick={() => setShowAddForm(!showAddForm)}>
            <Plus size={14} /> 手动添加
          </button>
        </div>
      </div>

      {error && (
        <div className={styles['error-banner']}>
          <AlertCircle size={16} />
          <span>{error}</span>
          <button onClick={clearError}>关闭</button>
        </div>
      )}

      {/* 搜索和筛选 */}
      <div className={styles['toolbar']}>
        <div className={styles['search-box']}>
          <Search size={14} />
          <input
            type="text"
            placeholder="搜索事实..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
          />
        </div>
        <div className={styles['category-filters']}>
          {allCategories.map((cat) => (
            <button
              key={cat}
              className={`${styles['filter-btn']} ${activeCategory === cat ? styles['filter-active'] : ''}`}
              onClick={() => handleCategoryFilter(cat)}
            >
              {cat === ALL_CATEGORIES ? '全部' : PROFILE_CATEGORY_LABELS[cat] || cat}
            </button>
          ))}
        </div>
      </div>

      {/* 添加表单 */}
      {showAddForm && (
        <div className={styles['add-form']}>
          <h3>添加画像事实</h3>
          <div className={styles['add-form-fields']}>
            <select value={newCategory} onChange={(e) => setNewCategory(e.target.value)}>
              {Object.entries(PROFILE_CATEGORY_LABELS).filter(([k]) => k !== 'custom').map(([k, v]) => (
                <option key={k} value={k}>{v}</option>
              ))}
            </select>
            <input
              type="text"
              placeholder="键名（如 preferred_language）"
              value={newKey}
              onChange={(e) => setNewKey(e.target.value)}
            />
            <input
              type="text"
              placeholder="值（如 Python）"
              value={newValue}
              onChange={(e) => setNewValue(e.target.value)}
            />
            <button className="btn btn-primary" onClick={() => void handleAdd()}>
              <Save size={14} /> 保存
            </button>
            <button className="btn btn-secondary" onClick={() => setShowAddForm(false)}>取消</button>
          </div>
        </div>
      )}

      {/* 事实列表 */}
      <div className={styles['facts-container']}>
        {loading ? (
          <div className={styles['loading']}>
            <Loader2 size={24} className={styles['spin']} />
            <span>加载中...</span>
          </div>
        ) : Object.keys(filteredGrouped).length === 0 ? (
          <div className={styles['empty']}>
            <p>暂无画像数据</p>
            <p className={styles['hint']}>使用"智能提取"或"手动添加"来创建画像事实</p>
          </div>
        ) : (
          Object.entries(filteredGrouped).map(([category, items]) => (
            <div key={category} className={styles['category-section']}>
              <h3 className={styles['category-title']}>
                {PROFILE_CATEGORY_LABELS[category] || category}
                <span className={styles['category-count']}>{items.length} 条</span>
              </h3>
              <div className={styles['facts-list']}>
                {items.map((fact) => (
                  <div key={fact.id} className={styles['fact-card']}>
                    <div className={styles['fact-header']}>
                      <code className={styles['fact-key']}>{fact.fact_key}</code>
                      <span
                        className={`${styles['conf-badge']} ${
                          fact.confidence_label === '高' ? styles['conf-high'] :
                          fact.confidence_label === '中' ? styles['conf-med'] :
                          styles['conf-low']
                        }`}
                      >
                        {fact.confidence_label} ({(fact.confidence * 100).toFixed(0)}%)
                      </span>
                      <span className={styles['source-badge']}>{fact.source_type}</span>
                    </div>

                    <div className={styles['fact-body']}>
                      {editingFactId === fact.id ? (
                        <div className={styles['edit-row']}>
                          <input
                            type="text"
                            value={editValue}
                            onChange={(e) => setEditValue(e.target.value)}
                            className={styles['edit-input']}
                            autoFocus
                          />
                          <button
                            className={styles['action-btn-sm']}
                            onClick={() => void saveEdit(fact.id)}
                            title="保存"
                          >
                            <Check size={14} />
                          </button>
                          <button
                            className={styles['action-btn-sm']}
                            onClick={cancelEdit}
                            title="取消"
                          >
                            <X size={14} />
                          </button>
                        </div>
                      ) : (
                        <span className={styles['fact-val']}>{fact.fact_value}</span>
                      )}
                    </div>

                    <div className={styles['fact-footer']}>
                      <span className={styles['fact-meta']}>
                        更新于 {fact.last_updated_at ? new Date(fact.last_updated_at).toLocaleDateString('zh-CN') : '未知'}
                        {fact.verification_count > 0 && ` · 已验证 ${fact.verification_count} 次`}
                      </span>
                      <div className={styles['fact-actions']}>
                        <button
                          className={styles['action-btn']}
                          onClick={() => void handleVerify(fact.id)}
                          title="确认此事实"
                        >
                          <Check size={14} /> 确认
                        </button>
                        <button
                          className={styles['action-btn']}
                          onClick={() => void handleDispute(fact.id)}
                          title="否定此事实"
                        >
                          <X size={14} /> 否定
                        </button>
                        <button
                          className={styles['action-btn']}
                          onClick={() => startEdit(fact.id, fact.fact_value)}
                          title="编辑"
                          disabled={editingFactId !== null}
                        >
                          <Edit3 size={14} /> 编辑
                        </button>
                        <button
                          className={`${styles['action-btn']} ${styles['action-danger']}`}
                          onClick={() => void handleDelete(fact.id)}
                          title="删除"
                        >
                          <Trash2 size={14} />
                        </button>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  )
}

export default ProfileEditorPage
