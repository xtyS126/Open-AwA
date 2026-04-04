import { useEffect, useRef, useState } from 'react'
import QRCode from 'qrcode'
import { WeixinConfig, WeixinHealthCheckResult, WeixinQrState, WeixinQrStatus, weixinAPI } from '@/shared/api/api'
import styles from './CommunicationPage.module.css'

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
  const [qrState, setQrState] = useState<WeixinQrState | null>(null)
  const [qrStatusText, setQrStatusText] = useState('')
  const [qrStatusHint, setQrStatusHint] = useState('')
  const [qrBindingResult, setQrBindingResult] = useState<{ userId: string; bindingStatus: string } | null>(null)
  const pollTimerRef = useRef<number | null>(null)
  const qrObjectUrlRef = useRef('')
  const qrCodeValueRef = useRef('')
  const qrPollTokenRef = useRef('')
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

  const normalizeQrState = (rawState?: string, rawStatus?: string, connected?: boolean): WeixinQrState => {
    const normalizedState = String(rawState || '').trim().toLowerCase()
    const normalizedStatus = String(rawStatus || '').trim().toLowerCase()
    if (normalizedState === 'success' || connected || normalizedStatus === 'confirmed') {
      return 'success'
    }
    if (normalizedState === 'failed' || normalizedStatus === 'expired') {
      return 'failed'
    }
    if (normalizedState === 'half_success' || normalizedStatus === 'scaned' || normalizedStatus === 'scanned' || normalizedStatus === 'scaned_but_redirect' || normalizedStatus === 'pending' || normalizedStatus === 'confirming' || normalizedStatus === 'refreshing') {
      return 'half_success'
    }
    return 'pending'
  }

  const buildStatusText = (status: WeixinQrStatus, state: WeixinQrState, fallback: string) => {
    if (fallback.trim()) {
      return fallback
    }
    if (status === 'scaned_but_redirect') {
      return '已扫码，正在切换轮询节点'
    }
    if (status === 'scanned') {
      return state === 'half_success'
        ? '已扫码，请在微信中确认，系统正在等待后端补齐登录信息' : '已扫码，请在微信中确认'
    }
    if (status === 'expired') {
      return '二维码已过期，请重新获取'
    }
    if (status === 'confirmed') {
      return '与微信连接成功'
    }
    if (state === 'half_success') {
      return '扫码流程已推进，正在等待确认或补齐登录信息'
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

  const buildNextStepText = (bindingStatus?: string, userId?: string) => {
    const normalizedStatus = normalizeBindingStatus(bindingStatus, userId)
    if (normalizedStatus === 'bound') {
      return '后续流程：配置已自动回填。建议先点击“测试连接”确认链路可用，再进入聊天页验证消息收发。'
    }
    if (normalizedStatus === 'pending') {
      return '后续流程：当前账号信息已回填，但绑定仍在处理中。请先测试连接，确认后再进入聊天页继续验证。'
    }
    return '后续流程：配置已更新，请先测试连接，确认账号状态无误后再进入聊天页继续后续操作。'
  }

  const normalizeQrStatus = (rawStatus: string, connected: boolean): WeixinQrStatus => {
    if (connected || rawStatus === 'confirmed') {
      return 'confirmed'
    }
    if (rawStatus === 'expired') {
      return 'expired'
    }
    if (rawStatus === 'scaned_but_redirect' || rawStatus === 'refreshing') {
      return 'scaned_but_redirect'
    }
    if (rawStatus === 'scaned' || rawStatus === 'scanned') {
      return 'scanned'
    }
    if (rawStatus === 'waiting' || rawStatus === 'wait' || rawStatus === 'pending') {
      return 'waiting'
    }
    return 'waiting'
  }

  const updateQrCodeValue = (value: string) => {
    qrCodeValueRef.current = value
  }

  const updateQrPollToken = (value: string) => {
    qrPollTokenRef.current = value
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
    updateQrPollToken('')
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
        qrcode: qrPollTokenRef.current || undefined,
        base_url: qrPollBaseUrlRef.current || weixinConfig.base_url || undefined,
      })
      const data = response.data
      const state = normalizeQrState(data.state, data.status, Boolean(data.connected))
      const status = normalizeQrStatus(String(data.status || 'wait').toLowerCase(), state === 'success' || Boolean(data.connected))
      const hintText = [data.hint, data.auth_id, data.ticket, data.redirect_host]
        .filter((item): item is string => Boolean(item && item.trim()))
        .join(' ')

      const effectiveBaseUrl = data.baseurl || data.base_url
      if (effectiveBaseUrl) {
        updateQrPollBaseUrl(effectiveBaseUrl)
      }
      const effectiveQrContent = data.qrcode_content || data.qrcode_url || data.qrcode
      if (effectiveQrContent) {
        setQrRawUrl(effectiveQrContent)
        if (effectiveQrContent !== qrCodeValueRef.current) {
          updateQrCodeValue(effectiveQrContent)
          await loadQrImage(sessionKey, effectiveQrContent)
        }
      }
      if (data.qrcode) {
        updateQrPollToken(data.qrcode)
      }

      setQrState(state)
      setQrStatus(status)
      setQrStatusText(buildStatusText(status, state, data.message || ''))
      setQrStatusHint(hintText)

      if (state === 'success' && (status === 'confirmed' || data.connected)) {
        const effectiveUserId = data.ilink_user_id || data.user_id || ''
        const bindingStatus = normalizeBindingStatus(data.binding_status, effectiveUserId)
        setQrBindingResult({
          userId: effectiveUserId,
          bindingStatus
        })
        clearQrPolling()
        setQrSessionKey('')
        clearQrImage()
        setQrState('success')
        setQrStatus('confirmed')
        setQrStatusText(buildStatusText('confirmed', 'success', data.message || ''))
        setMessage({
          type: 'success',
          text: `微信扫码登录成功，配置已自动更新；${buildBindingResultText(effectiveUserId, bindingStatus)} ${buildNextStepText(bindingStatus, effectiveUserId)}`
        })
        await loadWeixinConfig()
        return false
      }

      if (state === 'failed' || status === 'expired') {
        clearQrPolling()
        setQrSessionKey('')
        clearQrImage()
        setQrState('failed')
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
    setQrState(null)
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
      const qrValue = response.data.qrcode_content || response.data.qrcode_url || response.data.qrcode || ''
      const nextState = normalizeQrState(response.data.state, response.data.status, false)
      setQrSessionKey(response.data.session_key)
      setQrRawUrl(response.data.qrcode_content || response.data.qrcode_url || '')
      updateQrCodeValue(qrValue)
      updateQrPollToken(response.data.qrcode || '')
      const effectiveBaseUrl = response.data.baseurl || weixinConfig.base_url || DEFAULT_BASE_URL
      updateQrPollBaseUrl(effectiveBaseUrl)
      const qrImageReady = await loadQrImage(response.data.session_key, qrValue || undefined)
      setQrState(nextState)
      setQrStatus('waiting')
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
      setQrState(null)
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
      setQrState(null)
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
    <div className={styles['communication-page']}>
      <div className={styles['communication-header']}>
        <h1>通讯配置</h1>
      </div>
      <div className={styles['communication-content']}>
        {message && (
          <div className={`${styles['message']} ${styles[message.type] || message.type}`}>
            {message.text}
          </div>
        )}
        <div className={styles['settings-section']}>
          <p className={`${styles['section-desc']} ${styles['communication-section-desc']}`}>配置外部通讯渠道，如微信 iLink 集成。</p>
          <div className={`${styles['config-card']} ${styles['communication-card']}`}>
            <h3 className={styles['communication-card-title']}>微信通讯配置</h3>
            {loadingWeixin ? (
              <div className={styles['loading']}>加载配置中...</div>
            ) : (
              <>
                <div className={`${styles['setting-item']} ${styles['communication-form-item']}`}>
                  <label className={styles['communication-label']}>Account ID <span className={`${styles['required']} ${styles['communication-required']}`}>*</span></label>
                  <input
                    type="text"
                    value={weixinConfig.account_id}
                    onChange={(e) => setWeixinConfig({ ...weixinConfig, account_id: e.target.value })}
                    placeholder="输入微信通讯账户 ID"
                    className={styles['communication-input']}
                  />
                </div>
                <div className={`${styles['setting-item']} ${styles['communication-form-item']}`}>
                  <label className={styles['communication-label']}>Token <span className={`${styles['required']} ${styles['communication-required']}`}>*</span></label>
                  <input
                    type="password"
                    value={weixinConfig.token}
                    onChange={(e) => setWeixinConfig({ ...weixinConfig, token: e.target.value })}
                    placeholder="输入 iLink Bot Token"
                    className={styles['communication-input']}
                  />
                </div>
                <div className={`${styles['setting-item']} ${styles['communication-form-item']}`}>
                  <label className={styles['communication-label']}>Base URL</label>
                  <input
                    type="text"
                    value={weixinConfig.base_url}
                    onChange={(e) => setWeixinConfig({ ...weixinConfig, base_url: e.target.value })}
                    placeholder="https://ilinkai.weixin.qq.com"
                    className={styles['communication-input']}
                  />
                </div>
                <div className={`${styles['setting-item']} ${styles['communication-form-item']}`}>
                  <label className={styles['communication-label']}>超时时间 (秒)</label>
                  <input
                    type="number"
                    value={weixinConfig.timeout_seconds}
                    onChange={(e) => setWeixinConfig({ ...weixinConfig, timeout_seconds: parseInt(e.target.value, 10) || 15 })}
                    placeholder="15"
                    className={styles['communication-input']}
                  />
                </div>
                <div className={`${styles['actions-row']} ${styles['communication-actions-row']}`}>
                  <button
                    className={`${styles['btn']} ${styles['btn-primary']}`}
                    onClick={handleSaveWeixinConfig}
                    disabled={savingWeixin}
                  >
                      {savingWeixin ? '保存中...' : '保存配置'}
                    </button>
                    <button
                      className={`${styles['btn']} ${styles['btn-secondary']}`}
                      onClick={handleTestWeixinConnection}
                      disabled={testingWeixin}
                    >
                      {testingWeixin ? '测试中...' : '测试连接'}
                    </button>
                  </div>

                  <div className={styles['communication-qr-login']}>
                    <h4 className={styles['communication-qr-login-title']}>扫码登录</h4>
                    <p className={styles['communication-qr-login-desc']}>点击获取二维码后，请用微信扫码并在手机上确认授权。</p>
                    <div className={`${styles['actions-row']} ${styles['communication-actions-row']}`}>
                      <button
                        className={`${styles['btn']} ${styles['btn-primary']}`}
                        onClick={handleStartQrLogin}
                        disabled={startingQrLogin}
                      >
                        {startingQrLogin ? '获取中...' : '获取登录二维码'}
                      </button>
                    <button
                      className={`${styles['btn']} ${styles['btn-secondary']}`}
                      onClick={handleCancelQrLogin}
                      disabled={!qrSessionKey && !pollingQrLogin && !qrCodeUrl}
                    >
                      取消扫码登录
                    </button>
                  </div>
                  {qrCodeUrl && (
                    <div className={styles['communication-qr-preview']}>
                      <img src={qrCodeUrl} alt="微信登录二维码" className={styles['communication-qr-image']} />
                    </div>
                  )}
                  {qrImageLoadError && (
                    <p className={styles['communication-qr-status']}>{qrImageLoadError}</p>
                  )}
                  {(qrStatusText || qrStatus !== 'idle') && (
                    <p className={styles['communication-qr-status']}>
                      当前阶段：{qrState || 'pending'}；当前状态：{qrStatusText || qrStatus}
                      {qrStatusHint ? `（${qrStatusHint}）` : ''}
                    </p>
                  )}
                  {qrBindingResult && (
                    <p className={styles['communication-qr-status']}>
                      绑定结果：{buildBindingResultText(qrBindingResult.userId, qrBindingResult.bindingStatus)}
                    </p>
                  )}
                  {qrState === 'success' && qrBindingResult && (
                    <p className={styles['communication-qr-status']}>
                      {buildNextStepText(qrBindingResult.bindingStatus, qrBindingResult.userId)}
                    </p>
                  )}
                </div>

                {weixinHealthResult && (
                  <div className={`${styles['health-result']} ${weixinHealthResult.ok ? styles['success'] : styles['error']}${styles['communication-health-result']}`}>
                    <h4 className={`${styles['communication-health-title']} ${weixinHealthResult.ok ? styles['success'] : styles['error']}`}>测试结果: {weixinHealthResult.ok ? '成功' : '失败'}</h4>
                    {weixinHealthResult.issues && weixinHealthResult.issues.length > 0 && (
                      <div className={styles['communication-health-section']}>
                        <strong className={styles['communication-health-strong']}>问题发现:</strong>
                        <ul className={styles['communication-health-list']}>
                          {weixinHealthResult.issues.map((issue, i) => (
                            <li key={i} className={styles['communication-health-issue']}>{issue}</li>
                          ))}
                        </ul>
                      </div>
                    )}
                    {weixinHealthResult.suggestions && weixinHealthResult.suggestions.length > 0 && (
                      <div className={styles['communication-health-section']}>
                        <strong className={styles['communication-health-strong']}>建议修复:</strong>
                        <ul className={styles['communication-health-list']}>
                          {weixinHealthResult.suggestions.map((suggestion, i) => (
                            <li key={i}>{suggestion}</li>
                          ))}
                        </ul>
                      </div>
                    )}
                    {weixinHealthResult.ok && (!weixinHealthResult.issues || weixinHealthResult.issues.length === 0) && (
                      <p className={styles['communication-health-ok']}>配置正常，微信适配器健康检查通过。</p>
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
