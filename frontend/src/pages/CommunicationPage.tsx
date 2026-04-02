import { useEffect, useRef, useState } from 'react'
import QRCode from 'qrcode'
import { WeixinConfig, WeixinHealthCheckResult, WeixinQrStatus, weixinAPI } from '../services/api'
import './CommunicationPage.css'

const DEFAULT_BASE_URL = 'https://ilinkai.weixin.qq.com'

function CommunicationPage() {
  const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null)
  const [weixinConfig, setWeixinConfig] = useState<WeixinConfig>({
    account_id: '',
    token: '',
    base_url: DEFAULT_BASE_URL,
    timeout_seconds: 15
  })
  const [loadingWeixin, setLoadingWeixin] = useState(false)
  const [savingWeixin, setSavingWeixin] = useState(false)
  const [testingWeixin, setTestingWeixin] = useState(false)
  const [weixinHealthResult, setWeixinHealthResult] = useState<WeixinHealthCheckResult | null>(null)
  const [startingQrLogin, setStartingQrLogin] = useState(false)
  const [pollingQrLogin, setPollingQrLogin] = useState(false)
  const [qrSessionKey, setQrSessionKey] = useState('')
  const [qrCodeUrl, setQrCodeUrl] = useState('')
  const [qrRawUrl, setQrRawUrl] = useState('')
  const [qrImageLoadError, setQrImageLoadError] = useState('')
  const [qrStatus, setQrStatus] = useState<WeixinQrStatus>('idle')
  const [qrStatusText, setQrStatusText] = useState('')
  const [qrStatusHint, setQrStatusHint] = useState('')
  const [qrBindingResult, setQrBindingResult] = useState<{ userId: string; bindingStatus: string } | null>(null)
  const pollTimerRef = useRef<number | null>(null)
  const qrObjectUrlRef = useRef('')
  const qrCodeValueRef = useRef('')
  const qrPollBaseUrlRef = useRef(DEFAULT_BASE_URL)

  const resolveApiErrorMessage = (error: unknown, fallback: string) => {
    const maybeError = error as { response?: { status?: number, data?: { detail?: string } } }
    const status = maybeError?.response?.status
    const detail = maybeError?.response?.data?.detail
    if (status === 401) {
      return '登录状态已失效，请重新登录系统后再试'
    }
    if (status === 404) {
      return '后端未找到二维码接口，请重启后端服务后重试'
    }
    if (detail && typeof detail === 'string') {
      return `获取二维码失败：${detail}`
    }
    return fallback
  }

  const buildStatusText = (status: WeixinQrStatus, fallback: string) => {
    if (fallback.trim()) {
      return fallback
    }
    if (status === 'scaned_but_redirect') {
      return '已扫码，正在切换轮询节点'
    }
    if (status === 'scaned') {
      return '已扫码，请在微信中确认'
    }
    if (status === 'expired') {
      return '二维码已过期，请重新获取'
    }
    if (status === 'confirmed') {
      return '与微信连接成功'
    }
    return '等待扫码中'
  }

  const normalizeBindingStatus = (bindingStatus?: string, userId?: string) => {
    const normalized = String(bindingStatus || '').trim().toLowerCase()
    if (normalized === 'bound' || normalized === 'confirmed' || normalized === 'linked' || normalized === 'success') {
      return 'bound'
    }
    if (normalized === 'pending' || normalized === 'confirming' || normalized === 'waiting') {
      return 'pending'
    }
    if (userId?.trim()) {
      return 'bound'
    }
    return 'unbound'
  }

  const buildBindingResultText = (userId?: string, bindingStatus?: string) => {
    const normalizedStatus = normalizeBindingStatus(bindingStatus, userId)
    if (normalizedStatus === 'bound') {
      return userId?.trim()
        ? `绑定成功，用户 ID：${userId.trim()}，绑定状态：${normalizedStatus}`
        : `绑定状态：${normalizedStatus}`
    }
    if (normalizedStatus === 'pending') {
      return userId?.trim()
        ? `已获取用户 ID：${userId.trim()}，绑定状态：${normalizedStatus}`
        : `绑定状态：${normalizedStatus}`
    }
    return userId?.trim()
      ? `用户 ID：${userId.trim()}，绑定状态：${normalizedStatus}`
      : `绑定状态：${normalizedStatus}`
  }

  const normalizeQrStatus = (rawStatus: string, connected: boolean): WeixinQrStatus => {
    if (connected || rawStatus === 'confirmed') {
      return 'confirmed'
    }
    if (rawStatus === 'expired') {
      return 'expired'
    }
    if (rawStatus === 'scaned_but_redirect') {
      return 'scaned_but_redirect'
    }
    if (rawStatus === 'scaned' || rawStatus === 'scanned' || rawStatus === 'pending' || rawStatus === 'confirming') {
      return 'scaned'
    }
    return 'wait'
  }

  const updateQrCodeValue = (value: string) => {
    qrCodeValueRef.current = value
  }

  const updateQrPollBaseUrl = (value: string) => {
    qrPollBaseUrlRef.current = value
  }

  useEffect(() => {
    loadWeixinConfig()

    return () => {
      clearQrPolling()
      clearQrImage()
    }
  }, [])

  const clearQrPolling = () => {
    if (pollTimerRef.current !== null) {
      window.clearInterval(pollTimerRef.current)
      pollTimerRef.current = null
    }
    setPollingQrLogin(false)
  }

  const clearQrImage = () => {
    if (qrObjectUrlRef.current) {
      URL.revokeObjectURL(qrObjectUrlRef.current)
      qrObjectUrlRef.current = ''
    }
    setQrCodeUrl('')
    setQrRawUrl('')
    updateQrCodeValue('')
    setQrImageLoadError('')
    setQrStatusHint('')
    updateQrPollBaseUrl(DEFAULT_BASE_URL)
  }

  const loadQrImage = async (_sessionKey: string, qrcodeText?: string) => {
    const qrValue = (qrcodeText || qrCodeValueRef.current || qrRawUrl || '').trim()
    if (!qrValue) {
      setQrImageLoadError('二维码内容为空，请重试获取二维码')
      return false
    }
    try {
      const dataUrl = await QRCode.toDataURL(qrValue, {
        errorCorrectionLevel: 'M',
        margin: 2,
        width: 240,
      })
      if (qrObjectUrlRef.current) {
        URL.revokeObjectURL(qrObjectUrlRef.current)
        qrObjectUrlRef.current = ''
      }
      setQrCodeUrl(dataUrl)
      setQrImageLoadError('')
      return true
    } catch {
      setQrImageLoadError('二维码生成失败，请重试获取二维码')
      return false
    }
  }

  const loadWeixinConfig = async () => {
    setLoadingWeixin(true)
    try {
      const response = await weixinAPI.getConfig()
      if (response.data) {
        const nextConfig = {
          account_id: response.data.account_id || '',
          token: response.data.token || '',
          base_url: response.data.base_url || DEFAULT_BASE_URL,
          timeout_seconds: response.data.timeout_seconds || 15,
          user_id: response.data.user_id || '',
          binding_status: normalizeBindingStatus(response.data.binding_status, response.data.user_id)
        }
        setWeixinConfig(nextConfig)
        setQrBindingResult(nextConfig.user_id || nextConfig.binding_status !== 'unbound'
          ? { userId: nextConfig.user_id || '', bindingStatus: nextConfig.binding_status || 'unbound' }
          : null)
        updateQrPollBaseUrl(nextConfig.base_url || DEFAULT_BASE_URL)
      }
    } catch {
      console.error('Failed to load weixin config')
    } finally {
      setLoadingWeixin(false)
    }
  }

  const pollQrLoginStatus = async (sessionKey: string) => {
    try {
      const response = await weixinAPI.waitQrLogin({
        session_key: sessionKey,
        timeout_seconds: weixinConfig.timeout_seconds,
        qrcode: qrCodeValueRef.current || undefined,
        base_url: qrPollBaseUrlRef.current || weixinConfig.base_url || undefined,
      })
      const data = response.data
      const status = normalizeQrStatus(String(data.status || 'wait').toLowerCase(), Boolean(data.connected))
      const hintText = [data.hint, data.auth_id, data.ticket, data.redirect_host]
        .filter((item): item is string => Boolean(item && item.trim()))
        .join(' ')

      if (data.base_url) {
        updateQrPollBaseUrl(data.base_url)
      }
      if (data.qrcode_url) {
        setQrRawUrl(data.qrcode_url)
      }

      setQrStatus(status)
      setQrStatusText(buildStatusText(status, data.message || ''))
      setQrStatusHint(hintText)

      if (status === 'confirmed' && data.connected) {
        const bindingStatus = normalizeBindingStatus(data.binding_status, data.user_id)
        setQrBindingResult({
          userId: data.user_id || '',
          bindingStatus
        })
        clearQrPolling()
        setQrSessionKey('')
        clearQrImage()
        setQrStatus('confirmed')
        setQrStatusText(buildStatusText('confirmed', data.message || ''))
        setMessage({
          type: 'success',
          text: `微信扫码登录成功，配置已自动更新；${buildBindingResultText(data.user_id, bindingStatus)}`
        })
        await loadWeixinConfig()
        return false
      }

      if (status === 'expired') {
        clearQrPolling()
        setQrSessionKey('')
        clearQrImage()
        setMessage({ type: 'error', text: '二维码已过期，请重新获取二维码' })
        return false
      }

      return true
    } catch {
      clearQrPolling()
      setQrStatusText('轮询登录状态失败，请稍后重试')
      setMessage({ type: 'error', text: '轮询登录状态失败' })
      return false
    }
  }

  const handleStartQrLogin = async () => {
    setStartingQrLogin(true)
    clearQrPolling()
    setQrStatus('idle')
    setQrStatusText('')
    setQrBindingResult(null)
    clearQrImage()
    setQrSessionKey('')
    try {
      const response = await weixinAPI.startQrLogin({
        base_url: weixinConfig.base_url,
        timeout_seconds: weixinConfig.timeout_seconds,
        force: true
      })
      const qrValue = response.data.qrcode || response.data.qrcode_url || ''
      setQrSessionKey(response.data.session_key)
      setQrRawUrl(response.data.qrcode_url || '')
      updateQrCodeValue(qrValue)
      updateQrPollBaseUrl(weixinConfig.base_url || DEFAULT_BASE_URL)
      const qrImageReady = await loadQrImage(response.data.session_key, qrValue || undefined)
      setQrStatus('wait')
      setQrStatusText(response.data.message || (qrImageReady ? '等待扫码中' : '二维码已生成，请重试加载图片'))
      setQrStatusHint('')
      setPollingQrLogin(true)
      const shouldContinuePolling = await pollQrLoginStatus(response.data.session_key)
      if (shouldContinuePolling) {
        pollTimerRef.current = window.setInterval(() => {
          pollQrLoginStatus(response.data.session_key)
        }, 2000)
      }
    } catch (error) {
      setMessage({ type: 'error', text: resolveApiErrorMessage(error, '获取二维码失败，请检查配置后重试') })
      clearQrPolling()
    } finally {
      setStartingQrLogin(false)
    }
  }

  const handleCancelQrLogin = async () => {
    if (!qrSessionKey) {
      clearQrPolling()
      clearQrImage()
      setQrStatus('idle')
      setQrStatusText('')
      return
    }
    try {
      await weixinAPI.exitQrLogin({ session_key: qrSessionKey, clear_config: false })
      setMessage({ type: 'success', text: '已取消当前扫码登录' })
    } catch {
      setMessage({ type: 'error', text: '取消扫码登录失败' })
    } finally {
      clearQrPolling()
      setQrSessionKey('')
      clearQrImage()
      setQrStatus('idle')
      setQrStatusText('')
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
    } catch {
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
    } catch {
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

                <div className="communication-qr-login">
                  <h4 className="communication-qr-login-title">扫码登录</h4>
                  <p className="communication-qr-login-desc">点击获取二维码后，请用微信扫码并在手机上确认授权。</p>
                  <div className="actions-row communication-actions-row">
                    <button
                      className="btn btn-primary"
                      onClick={handleStartQrLogin}
                      disabled={startingQrLogin}
                    >
                      {startingQrLogin ? '获取中...' : '获取登录二维码'}
                    </button>
                    <button
                      className="btn btn-secondary"
                      onClick={handleCancelQrLogin}
                      disabled={!qrSessionKey && !pollingQrLogin && !qrCodeUrl}
                    >
                      取消扫码登录
                    </button>
                  </div>
                  {qrCodeUrl && (
                    <div className="communication-qr-preview">
                      <img src={qrCodeUrl} alt="微信登录二维码" className="communication-qr-image" />
                    </div>
                  )}
                  {qrImageLoadError && (
                    <p className="communication-qr-status">{qrImageLoadError}</p>
                  )}
                  {(qrStatusText || qrStatus !== 'idle') && (
                    <p className="communication-qr-status">
                      当前状态：{qrStatusText || qrStatus}
                      {qrStatusHint ? `（${qrStatusHint}）` : ''}
                    </p>
                  )}
                  {qrBindingResult && (
                    <p className="communication-qr-status">
                      绑定结果：{buildBindingResultText(qrBindingResult.userId, qrBindingResult.bindingStatus)}
                    </p>
                  )}
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
