/**
 * 模型等级（Model Tier）分配区块。
 *
 * 展示 Fable / Opus / Sonnet / Haiku 四档模型，每档可绑定一个 provider/model，
 * 并说明各档被什么功能调用；同时说明 Subagent 的模型由主 Agent 自行选择。
 */
import { useEffect, useState } from 'react'
import { modelsAPI, type ModelTier } from '@/features/settings/modelsApi'
import { useModelStore } from '@/features/chat/store/modelStore'

/** 把下拉值 "provider:model" 拆回 provider 与 model 两部分 */
function splitTierValue(value: string): { provider: string; model: string } {
  const idx = value.indexOf(':')
  if (idx === -1) return { provider: '', model: '' }
  return { provider: value.slice(0, idx), model: value.slice(idx + 1) }
}

export function ModelTierSection() {
  const modelOptions = useModelStore(s => s.modelOptions)
  const [tiers, setTiers] = useState<ModelTier[]>([])
  const [subagentNote, setSubagentNote] = useState('')
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [savingTier, setSavingTier] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    modelsAPI.getModelTiers()
      .then((res) => {
        if (cancelled) return
        const list: ModelTier[] = res.data.tiers ?? []
        setTiers(list)
        setSubagentNote(res.data.subagent_note ?? '')
        setDrafts(Object.fromEntries(
          list.map(t => [t.tier, t.provider && t.model ? `${t.provider}:${t.model}` : ''])
        ))
      })
      .catch(() => {
        if (!cancelled) setError('加载模型等级失败')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => { cancelled = true }
  }, [])

  const handleChange = (tier: string, value: string) => {
    setDrafts(prev => ({ ...prev, [tier]: value }))
  }

  const handleSave = async (tier: string) => {
    const value = drafts[tier] ?? ''
    const { provider, model } = splitTierValue(value)
    setSavingTier(tier)
    try {
      await modelsAPI.updateModelTier(tier, { provider, model })
      setTiers(prev => prev.map(t => t.tier === tier ? { ...t, provider, model } : t))
      setError(null)
    } catch {
      setError(`保存 ${tier} 档失败`)
    } finally {
      setSavingTier(null)
    }
  }

  if (loading) {
    return <p style={{ color: '#6b7280', fontSize: '13px' }}>正在加载模型等级…</p>
  }

  return (
    <div style={{ marginTop: '24px', padding: '16px', border: '1px solid #e5e7eb', borderRadius: '10px' }}>
      <h3 style={{ margin: '0 0 4px' }}>模型等级分配</h3>
      <p style={{ margin: '0 0 16px', color: '#6b7280', fontSize: '13px' }}>
        为不同功能分配不同档位的模型，各档功能说明如下。
      </p>

      {error && <p style={{ color: '#dc2626', fontSize: '13px' }}>{error}</p>}

      <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
        {tiers.map(tier => {
          const current = drafts[tier.tier] ?? ''
          const options = modelOptions.map(opt => ({ id: opt.id, label: opt.display_name }))
          return (
            <div key={tier.tier} style={{ borderBottom: '1px solid #f3f4f6', paddingBottom: '12px' }}>
              <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: '12px' }}>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontWeight: 600 }}>{tier.name}</div>
                  <div style={{ color: '#6b7280', fontSize: '12px', marginTop: '2px' }}>{tier.description}</div>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexShrink: 0 }}>
                  {options.length === 0 ? (
                    <span style={{ color: '#9ca3af', fontSize: '12px' }}>请先配置模型</span>
                  ) : (
                    <>
                      <select
                        value={current}
                        onChange={(e) => handleChange(tier.tier, e.target.value)}
                        style={{ padding: '6px 8px', borderRadius: '6px', border: '1px solid #d1d5db', minWidth: '220px' }}
                      >
                        <option value="">（未设定，使用默认模型）</option>
                        {options.map(opt => (
                          <option key={opt.id} value={opt.id}>{opt.label}</option>
                        ))}
                      </select>
                      <button
                        className="btn btn-primary"
                        onClick={() => handleSave(tier.tier)}
                        disabled={savingTier === tier.tier}
                      >
                        {savingTier === tier.tier ? '保存中…' : '保存'}
                      </button>
                    </>
                  )}
                </div>
              </div>
            </div>
          )
        })}
      </div>

      {subagentNote && (
        <p style={{ margin: '14px 0 0', padding: '10px', background: '#f9fafb', borderRadius: '8px', color: '#6b7280', fontSize: '12px', lineHeight: 1.6 }}>
          {subagentNote}
        </p>
      )}
    </div>
  )
}

export default ModelTierSection