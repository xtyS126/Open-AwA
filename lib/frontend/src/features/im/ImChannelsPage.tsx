/**
 * IM 渠道管理页面 — 提供渠道列表、配置编辑、消息发送测试等功能。
 * 合并了原 CommunicationPage 的微信配置能力，作为「微信」Tab 嵌入。
 */
import { useState, useEffect, useCallback, Suspense, lazy } from 'react'
import { Send, Settings, Power, PowerOff } from 'lucide-react'
import { getChannels, updateChannelConfig, sendMessage, getIMStatus } from '@/shared/api/imApi'
import type { IMChannel, IMStatus } from '@/shared/api/imApi'
import { Skeleton } from '@/shared/components/ui/Skeleton'
import { useI18nStore } from '@/i18n'
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
  const t = useI18nStore(s => s.t)
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
      setSendResult(t('im.sendForm.sending'))
      const result = await sendMessage(sendForm.channel, sendForm.chat_id, sendForm.text)
      setSendResult(result.ok ? t('im.sendForm.success') : t('im.sendForm.failed'))
    } catch (e) {
      // 严格模式下 catch 变量为 unknown，需安全提取错误信息
      const errMsg = e instanceof Error ? e.message : String(e)
      setSendResult(t('im.sendForm.failedWithMsg', { message: errMsg }))
    }
  }

  const startEdit = (channel: string) => {
    setEditingChannel(channel)
    setConfigForm({ bot_token: '', app_id: '', app_secret: '', webhook_url: '' })
  }

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <h1>{t('im.title')}</h1>
        {activeTab === 'channels' && status && (
          <span className={`${styles.statusBadge} ${status.running ? styles.active : styles.inactive}`}>
            {status.running ? t('im.status.running') : t('im.status.stopped')}
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
          {t('im.tab.channels')}
        </button>
        <button
          type="button"
          className={`${styles.tab} ${activeTab === 'wechat' ? styles.tabActive : ''}`}
          onClick={() => setActiveTab('wechat')}
        >
          {t('im.tab.wechat')}
        </button>
      </div>

      {activeTab === 'channels' && (
        <>
          {loading ? (
            <div className={styles.loading}>{t('im.loading')}</div>
          ) : (
            <>
              {/* 渠道列表 */}
              <section className={styles.section}>
                <h2 className={styles.sectionTitle}>{t('im.channelList')}</h2>
                <div className={styles.channelGrid}>
                  {channels.map(ch => (
                    <div key={ch.channel} className={styles.channelCard}>
                      <div className={styles.channelHeader}>
                        <h3>{CHANNEL_NAMES[ch.channel] || ch.channel}</h3>
                        <span className={`${styles.channelStatus} ${ch.enabled ? styles.active : styles.inactive}`}>
                          {ch.enabled ? t('im.channel.enabled') : t('im.channel.disabled')}
                        </span>
                      </div>
                      <div className={styles.channelInfo}>
                        <span>{t('im.configStatus', { status: ch.configured ? t('im.channel.configured') : t('im.channel.notConfigured') })}</span>
                      </div>
                      <div className={styles.channelActions}>
                        <button className={styles.actionBtn} onClick={() => startEdit(ch.channel)}>
                          <Settings size={14} />
                          {t('im.channel.config')}
                        </button>
                        <button
                          className={`${styles.actionBtn} ${ch.enabled ? styles.dangerBtn : styles.successBtn}`}
                          onClick={() => handleToggleChannel(ch.channel, ch.enabled)}
                        >
                          {ch.enabled ? <PowerOff size={14} /> : <Power size={14} />}
                          {ch.enabled ? t('im.channel.disable') : t('im.channel.enable')}
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
                    {t('im.configTitle', { name: CHANNEL_NAMES[editingChannel] || editingChannel })}
                  </h2>
                  <div className={styles.configForm}>
                    {editingChannel === 'telegram' && (
                      <div className={styles.formGroup}>
                        <label>{t('im.form.botToken')}</label>
                        <input
                          type="password"
                          value={configForm.bot_token}
                          onChange={e => setConfigForm({ ...configForm, bot_token: e.target.value })}
                          placeholder={t('im.form.botTokenPlaceholder')}
                        />
                      </div>
                    )}
                    {(editingChannel === 'feishu' || editingChannel === 'dingtalk') && (
                      <>
                        <div className={styles.formGroup}>
                          <label>{t('im.form.appId')}</label>
                          <input
                            value={configForm.app_id}
                            onChange={e => setConfigForm({ ...configForm, app_id: e.target.value })}
                            placeholder={t('im.form.appIdPlaceholder')}
                          />
                        </div>
                        <div className={styles.formGroup}>
                          <label>{t('im.form.appSecret')}</label>
                          <input
                            type="password"
                            value={configForm.app_secret}
                            onChange={e => setConfigForm({ ...configForm, app_secret: e.target.value })}
                            placeholder={t('im.form.appSecretPlaceholder')}
                          />
                        </div>
                      </>
                    )}
                    <div className={styles.formGroup}>
                      <label>{t('im.form.webhookUrl')}</label>
                      <input
                        value={configForm.webhook_url}
                        onChange={e => setConfigForm({ ...configForm, webhook_url: e.target.value })}
                        placeholder={t('im.form.webhookUrlPlaceholder')}
                      />
                    </div>
                    <div className={styles.formActions}>
                      <button className={styles.cancelBtn} onClick={() => setEditingChannel(null)}>{t('im.form.cancel')}</button>
                      <button className={styles.saveBtn} onClick={handleSaveConfig}>{t('im.form.saveAndEnable')}</button>
                    </div>
                  </div>
                </section>
              )}

              {/* 消息发送测试 */}
              <section className={styles.section}>
                <h2 className={styles.sectionTitle}>{t('im.sendTest')}</h2>
                <div className={styles.sendForm}>
                  <div className={styles.formRow}>
                    <select
                      value={sendForm.channel}
                      onChange={e => setSendForm({ ...sendForm, channel: e.target.value })}
                    >
                      <option value="">{t('im.sendForm.selectChannel')}</option>
                      {channels.filter(c => c.enabled).map(c => (
                        <option key={c.channel} value={c.channel}>{CHANNEL_NAMES[c.channel] || c.channel}</option>
                      ))}
                    </select>
                    <input
                      value={sendForm.chat_id}
                      onChange={e => setSendForm({ ...sendForm, chat_id: e.target.value })}
                      placeholder={t('im.sendForm.chatIdPlaceholder')}
                    />
                  </div>
                  <textarea
                    value={sendForm.text}
                    onChange={e => setSendForm({ ...sendForm, text: e.target.value })}
                    placeholder={t('im.sendForm.textPlaceholder')}
                    rows={3}
                  />
                  <button className={styles.sendBtn} onClick={handleSend} disabled={!sendForm.channel || !sendForm.chat_id || !sendForm.text}>
                    <Send size={14} />
                    {t('im.sendForm.send')}
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
