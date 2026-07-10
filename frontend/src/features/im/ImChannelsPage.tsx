/**
 * IM 渠道管理页面 — 提供渠道列表、配置编辑、消息发送测试等功能。
 * 合并了原 CommunicationPage 的微信配置能力，作为「微信」Tab 嵌入。
 */
import { useState, useEffect, useCallback, Suspense, lazy } from 'react'
import { Send, Settings, Power, PowerOff } from 'lucide-react'
import { getChannels, updateChannelConfig, sendMessage, getIMStatus } from '@/shared/api/imApi'
import type { IMChannel, IMStatus } from '@/shared/api/imApi'
import { Skeleton } from '@/shared/components/ui/Skeleton'
import styles from './ImChannelsPage.module.css'

// 懒加载微信配置模块，避免阻塞首屏渲染
const WechatConfigModule = lazy(() => import('@/features/chat/wechat-module'))

/** 顶部 Tab 类型：标准 IM 渠道 / 微信 */
type TopTab = 'channels' | 'wechat'

/** 渠道显示名称映射 */
const CHANNEL_NAMES: Record<string, string> = {
  telegram: 'Telegram',
  feishu: '飞书',
  dingtalk: '钉钉',
}

export default function ImChannelsPage() {
  // 顶部 Tab：channels 显示标准 IM 渠道，wechat 显示微信配置
  const [activeTab, setActiveTab] = useState<TopTab>('channels')

  const [channels, setChannels] = useState<IMChannel[]>([])
  const [status, setStatus] = useState<IMStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [editingChannel, setEditingChannel] = useState<string | null>(null)
  const [configForm, setConfigForm] = useState({
    bot_token: '',
    app_id: '',
    app_secret: '',
    webhook_url: '',
  })
  const [sendForm, setSendForm] = useState({ channel: '', chat_id: '', text: '' })
  const [sendResult, setSendResult] = useState<string | null>(null)

  const loadData = useCallback(async () => {
    try {
      setLoading(true)
      const [channelsResp, statusResp] = await Promise.all([getChannels(), getIMStatus()])
      setChannels(channelsResp.channels)
      setStatus(statusResp)
    } catch (e) {
      console.error('加载 IM 数据失败', e)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { loadData() }, [loadData])

  const handleToggleChannel = async (channel: string, enabled: boolean) => {
    try {
      await updateChannelConfig(channel, { ...configForm, enabled: !enabled, channel })
      loadData()
    } catch (e) {
      console.error('切换渠道状态失败', e)
    }
  }

  const handleSaveConfig = async () => {
    if (!editingChannel) return
    try {
      await updateChannelConfig(editingChannel, {
        ...configForm,
        channel: editingChannel,
        enabled: true,
      })
      setEditingChannel(null)
      loadData()
    } catch (e) {
      console.error('保存配置失败', e)
    }
  }

  const handleSend = async () => {
    if (!sendForm.channel || !sendForm.chat_id || !sendForm.text) return
    try {
      setSendResult('发送中...')
      const result = await sendMessage(sendForm.channel, sendForm.chat_id, sendForm.text)
      setSendResult(result.ok ? '发送成功' : '发送失败')
    } catch (e) {
      // 严格模式下 catch 变量为 unknown，需安全提取错误信息
      const errMsg = e instanceof Error ? e.message : String(e)
      setSendResult(`发送失败: ${errMsg}`)
    }
  }

  const startEdit = (channel: string) => {
    setEditingChannel(channel)
    setConfigForm({ bot_token: '', app_id: '', app_secret: '', webhook_url: '' })
  }

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <h1>IM 渠道管理</h1>
        {activeTab === 'channels' && status && (
          <span className={`${styles.statusBadge} ${status.running ? styles.active : styles.inactive}`}>
            {status.running ? '运行中' : '已停止'}
          </span>
        )}
      </div>

      {/* 顶部 Tab 切换：标准 IM 渠道 / 微信 */}
      <div className={styles.tabs}>
        <button
          type="button"
          className={`${styles.tab} ${activeTab === 'channels' ? styles.tabActive : ''}`}
          onClick={() => setActiveTab('channels')}
        >
          标准 IM 渠道
        </button>
        <button
          type="button"
          className={`${styles.tab} ${activeTab === 'wechat' ? styles.tabActive : ''}`}
          onClick={() => setActiveTab('wechat')}
        >
          微信
        </button>
      </div>

      {activeTab === 'channels' && (
        <>
          {loading ? (
            <div className={styles.loading}>加载中...</div>
          ) : (
            <>
              {/* 渠道列表 */}
              <section className={styles.section}>
                <h2 className={styles.sectionTitle}>渠道列表</h2>
                <div className={styles.channelGrid}>
                  {channels.map(ch => (
                    <div key={ch.channel} className={styles.channelCard}>
                      <div className={styles.channelHeader}>
                        <h3>{CHANNEL_NAMES[ch.channel] || ch.channel}</h3>
                        <span className={`${styles.channelStatus} ${ch.enabled ? styles.active : styles.inactive}`}>
                          {ch.enabled ? '已启用' : '未启用'}
                        </span>
                      </div>
                      <div className={styles.channelInfo}>
                        <span>配置状态: {ch.configured ? '已配置' : '未配置'}</span>
                      </div>
                      <div className={styles.channelActions}>
                        <button className={styles.actionBtn} onClick={() => startEdit(ch.channel)}>
                          <Settings size={14} />
                          配置
                        </button>
                        <button
                          className={`${styles.actionBtn} ${ch.enabled ? styles.dangerBtn : styles.successBtn}`}
                          onClick={() => handleToggleChannel(ch.channel, ch.enabled)}
                        >
                          {ch.enabled ? <PowerOff size={14} /> : <Power size={14} />}
                          {ch.enabled ? '停用' : '启用'}
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              </section>

              {/* 配置编辑 */}
              {editingChannel && (
                <section className={styles.section}>
                  <h2 className={styles.sectionTitle}>
                    配置 {CHANNEL_NAMES[editingChannel] || editingChannel}
                  </h2>
                  <div className={styles.configForm}>
                    {editingChannel === 'telegram' && (
                      <div className={styles.formGroup}>
                        <label>Bot Token</label>
                        <input
                          type="password"
                          value={configForm.bot_token}
                          onChange={e => setConfigForm({ ...configForm, bot_token: e.target.value })}
                          placeholder="输入 Telegram Bot Token"
                        />
                      </div>
                    )}
                    {(editingChannel === 'feishu' || editingChannel === 'dingtalk') && (
                      <>
                        <div className={styles.formGroup}>
                          <label>App ID</label>
                          <input
                            value={configForm.app_id}
                            onChange={e => setConfigForm({ ...configForm, app_id: e.target.value })}
                            placeholder="输入 App ID"
                          />
                        </div>
                        <div className={styles.formGroup}>
                          <label>App Secret</label>
                          <input
                            type="password"
                            value={configForm.app_secret}
                            onChange={e => setConfigForm({ ...configForm, app_secret: e.target.value })}
                            placeholder="输入 App Secret"
                          />
                        </div>
                      </>
                    )}
                    <div className={styles.formGroup}>
                      <label>Webhook URL</label>
                      <input
                        value={configForm.webhook_url}
                        onChange={e => setConfigForm({ ...configForm, webhook_url: e.target.value })}
                        placeholder="Webhook 回调地址（可选）"
                      />
                    </div>
                    <div className={styles.formActions}>
                      <button className={styles.cancelBtn} onClick={() => setEditingChannel(null)}>取消</button>
                      <button className={styles.saveBtn} onClick={handleSaveConfig}>保存并启用</button>
                    </div>
                  </div>
                </section>
              )}

              {/* 消息发送测试 */}
              <section className={styles.section}>
                <h2 className={styles.sectionTitle}>发送测试消息</h2>
                <div className={styles.sendForm}>
                  <div className={styles.formRow}>
                    <select
                      value={sendForm.channel}
                      onChange={e => setSendForm({ ...sendForm, channel: e.target.value })}
                    >
                      <option value="">选择渠道</option>
                      {channels.filter(c => c.enabled).map(c => (
                        <option key={c.channel} value={c.channel}>{CHANNEL_NAMES[c.channel] || c.channel}</option>
                      ))}
                    </select>
                    <input
                      value={sendForm.chat_id}
                      onChange={e => setSendForm({ ...sendForm, chat_id: e.target.value })}
                      placeholder="目标会话 ID"
                    />
                  </div>
                  <textarea
                    value={sendForm.text}
                    onChange={e => setSendForm({ ...sendForm, text: e.target.value })}
                    placeholder="消息内容"
                    rows={3}
                  />
                  <button className={styles.sendBtn} onClick={handleSend} disabled={!sendForm.channel || !sendForm.chat_id || !sendForm.text}>
                    <Send size={14} />
                    发送
                  </button>
                  {sendResult && <p className={styles.sendResult}>{sendResult}</p>}
                </div>
              </section>
            </>
          )}
        </>
      )}

      {/* 微信 Tab：嵌入微信配置模块 */}
      {activeTab === 'wechat' && (
        <section className={styles.section}>
          <Suspense fallback={(
            <div style={{ padding: 'var(--space-4)', display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
              <Skeleton variant="rectangular" height="var(--space-10)" width="40%" />
              <Skeleton.Paragraph lines={6} />
            </div>
          )}>
            <WechatConfigModule />
          </Suspense>
        </section>
      )}
    </div>
  )
}
