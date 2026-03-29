import { useEffect, useState } from 'react'
import { weixinAPI } from '../services/api'
import './CommunicationPage.css'

function CommunicationPage() {
  const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null)
  const [weixinConfig, setWeixinConfig] = useState({
    account_id: '',
    token: '',
    base_url: 'https://ilinkai.weixin.qq.com',
    timeout_seconds: 15
  })
  const [loadingWeixin, setLoadingWeixin] = useState(false)
  const [savingWeixin, setSavingWeixin] = useState(false)
  const [testingWeixin, setTestingWeixin] = useState(false)
  const [weixinHealthResult, setWeixinHealthResult] = useState<{ ok: boolean, issues: string[], suggestions: string[] } | null>(null)

  useEffect(() => {
    loadWeixinConfig()
  }, [])

  const loadWeixinConfig = async () => {
    setLoadingWeixin(true)
    try {
      const response = await weixinAPI.getConfig()
      if (response.data) {
        setWeixinConfig({
          account_id: response.data.account_id || '',
          token: response.data.token || '',
          base_url: response.data.base_url || 'https://ilinkai.weixin.qq.com',
          timeout_seconds: response.data.timeout_seconds || 15
        })
      }
    } catch (error) {
      console.error('Failed to load weixin config')
    } finally {
      setLoadingWeixin(false)
    }
  }

  const handleSaveWeixinConfig = async () => {
    if (!weixinConfig.account_id || !weixinConfig.token) {
      setMessage({ type: 'error', text: '微信配置不完整，account_id 和 token 为必填项' })
      setTimeout(() => setMessage(null), 3000)
      return
    }
    setSavingWeixin(true)
    try {
      await weixinAPI.saveConfig(weixinConfig)
      setMessage({ type: 'success', text: '微信通讯配置保存成功' })
    } catch (error) {
      setMessage({ type: 'error', text: '微信通讯配置保存失败' })
    } finally {
      setSavingWeixin(false)
      setTimeout(() => setMessage(null), 3000)
    }
  }

  const handleTestWeixinConnection = async () => {
    if (!weixinConfig.account_id || !weixinConfig.token) {
      setMessage({ type: 'error', text: '微信配置不完整，请先填写 account_id 和 token' })
      setTimeout(() => setMessage(null), 3000)
      return
    }
    setTestingWeixin(true)
    setWeixinHealthResult(null)
    try {
      const response = await weixinAPI.healthCheck(weixinConfig)
      setWeixinHealthResult(response.data)
      if (response.data.ok) {
        setMessage({ type: 'success', text: '测试连接成功！' })
      } else {
        setMessage({ type: 'error', text: '测试连接失败，请查看下方详细结果' })
      }
    } catch (error) {
      setMessage({ type: 'error', text: '测试连接请求失败' })
    } finally {
      setTestingWeixin(false)
      setTimeout(() => setMessage(null), 3000)
    }
  }

  return (
    <div className="communication-page">
      <div className="communication-header">
        <h1>通讯配置</h1>
      </div>
      <div className="communication-content">
        {message && (
          <div className={`message ${message.type}`}>
            {message.text}
          </div>
        )}
        <div className="settings-section">
          <p className="section-desc communication-section-desc">配置外部通讯渠道，如微信 Clawbot 插件。</p>
          <div className="config-card communication-card">
            <h3 className="communication-card-title">微信 Clawbot 配置</h3>
            {loadingWeixin ? (
              <div className="loading">加载配置中...</div>
            ) : (
              <>
                <div className="setting-item communication-form-item">
                  <label className="communication-label">Account ID <span className="required communication-required">*</span></label>
                  <input
                    type="text"
                    value={weixinConfig.account_id}
                    onChange={(e) => setWeixinConfig({ ...weixinConfig, account_id: e.target.value })}
                    placeholder="输入微信通讯账户 ID"
                    className="communication-input"
                  />
                </div>
                <div className="setting-item communication-form-item">
                  <label className="communication-label">Token <span className="required communication-required">*</span></label>
                  <input
                    type="password"
                    value={weixinConfig.token}
                    onChange={(e) => setWeixinConfig({ ...weixinConfig, token: e.target.value })}
                    placeholder="输入 iLink Bot Token"
                    className="communication-input"
                  />
                </div>
                <div className="setting-item communication-form-item">
                  <label className="communication-label">Base URL</label>
                  <input
                    type="text"
                    value={weixinConfig.base_url}
                    onChange={(e) => setWeixinConfig({ ...weixinConfig, base_url: e.target.value })}
                    placeholder="https://ilinkai.weixin.qq.com"
                    className="communication-input"
                  />
                </div>
                <div className="setting-item communication-form-item">
                  <label className="communication-label">超时时间 (秒)</label>
                  <input
                    type="number"
                    value={weixinConfig.timeout_seconds}
                    onChange={(e) => setWeixinConfig({ ...weixinConfig, timeout_seconds: parseInt(e.target.value, 10) || 15 })}
                    placeholder="15"
                    className="communication-input"
                  />
                </div>
                <div className="actions-row communication-actions-row">
                  <button
                    className="btn btn-primary"
                    onClick={handleSaveWeixinConfig}
                    disabled={savingWeixin}
                  >
                    {savingWeixin ? '保存中...' : '保存配置'}
                  </button>
                  <button
                    className="btn btn-secondary"
                    onClick={handleTestWeixinConnection}
                    disabled={testingWeixin}
                  >
                    {testingWeixin ? '测试中...' : '测试连接'}
                  </button>
                </div>

                {weixinHealthResult && (
                  <div className={`health-result ${weixinHealthResult.ok ? 'success' : 'error'} communication-health-result`}>
                    <h4 className={`communication-health-title ${weixinHealthResult.ok ? 'success' : 'error'}`}>测试结果: {weixinHealthResult.ok ? '成功' : '失败'}</h4>
                    {weixinHealthResult.issues && weixinHealthResult.issues.length > 0 && (
                      <div className="communication-health-section">
                        <strong className="communication-health-strong">问题发现:</strong>
                        <ul className="communication-health-list">
                          {weixinHealthResult.issues.map((issue, i) => (
                            <li key={i} className="communication-health-issue">{issue}</li>
                          ))}
                        </ul>
                      </div>
                    )}
                    {weixinHealthResult.suggestions && weixinHealthResult.suggestions.length > 0 && (
                      <div className="communication-health-section">
                        <strong className="communication-health-strong">建议修复:</strong>
                        <ul className="communication-health-list">
                          {weixinHealthResult.suggestions.map((suggestion, i) => (
                            <li key={i}>{suggestion}</li>
                          ))}
                        </ul>
                      </div>
                    )}
                    {weixinHealthResult.ok && (!weixinHealthResult.issues || weixinHealthResult.issues.length === 0) && (
                      <p className="communication-health-ok">配置正常，微信适配器健康检查通过。</p>
                    )}
                  </div>
                )}
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

export default CommunicationPage
