import { useEffect, useRef, useState, useCallback } from 'react'
import QRCode from 'qrcode'
import {
  WeixinAutoReplyProcessResult,
  WeixinAutoReplyRule,
  WeixinAutoReplyRuleCreate,
  WeixinAutoReplyRuleUpdate,
  WeixinAutoReplyStatus,
  WeixinBindingInfo,
  WeixinConfig,
  WeixinHealthCheckResult,
  WeixinParamsConfig,
  WeixinQrState,
  WeixinQrStatus,
  weixinAPI
} from '@/shared/api/api'
import { appLogger } from '@/shared/utils/logger'

const DEFAULT_BASE_URL = 'https://ilinkai.weixin.qq.com'

export function useWechatConfig() {
  const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null)
  const [weixinConfig, setWeixinConfig] = useState<WeixinConfig>({
    account_id: '',
    token: '',
    base_url: DEFAULT_BASE_URL,
    timeout_seconds: 15
  })
  const [loadingWeixin, setLoadingWeixin] = useState(false)
  const [configLoadError, setConfigLoadError] = useState<string | null>(null)
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
  const pollGenerationRef = useRef(0)
  const pollInFlightRef = useRef(false)

  const [bindingInfo, setBindingInfo] = useState<WeixinBindingInfo | null>(null)
  const [loadingBinding, setLoadingBinding] = useState(false)
  const [unbinding, setUnbinding] = useState(false)
  const [bindingError, setBindingError] = useState<string | null>(null)
  const [autoReplyStatus, setAutoReplyStatus] = useState<WeixinAutoReplyStatus | null>(null)
  const [loadingAutoReplyStatus, setLoadingAutoReplyStatus] = useState(false)
  const [autoReplyStatusError, setAutoReplyStatusError] = useState<string | null>(null)
  const [autoReplyAction, setAutoReplyAction] = useState<'start' | 'stop' | 'restart' | 'process' | null>(null)
  const [autoReplyProcessResult, setAutoReplyProcessResult] = useState<WeixinAutoReplyProcessResult | null>(null)
  const [paramsConfig, setParamsConfig] = useState<WeixinParamsConfig | null>(null)
  const [paramsLoadError, setParamsLoadError] = useState<string | null>(null)
  const [editBotType, setEditBotType] = useState('')
  const [editChannelVersion, setEditChannelVersion] = useState('')
  const [savingParams, setSavingParams] = useState(false)

  const [rules, setRules] = useState<WeixinAutoReplyRule[]>([])
  const [loadingRules, setLoadingRules] = useState(false)
  const [rulesError, setRulesError] = useState<string | null>(null)
  const [editingRule, setEditingRule] = useState<WeixinAutoReplyRule | Partial<WeixinAutoReplyRuleCreate> | null>(null)
  const [savingRule, setSavingRule] = useState(false)

  const getApiErrorDetail = (error: unknown, fallback: string) => {
    const maybeError = error as { response?: { data?: { detail?: string } } }
    const detail = maybeError?.response?.data?.detail
    return typeof detail === 'string' && detail.trim() ? detail : fallback
  }

  const showTimedMessage = useCallback((type: 'success' | 'error', text: string) => {
    setMessage({ type, text })
    setTimeout(() => setMessage(null), 3000)
  }, [])

  const isValidHttpUrl = (value?: string) => {
    const normalized = String(value || '').trim()
    return !normalized || normalized.startsWith('http://') || normalized.startsWith('https://')
  }

  const formatStatusTime = (value?: string) => {
    const normalized = String(value || '').trim()
    if (!normalized) {
      return '暂无'
    }
    const parsed = new Date(normalized)
    return Number.isNaN(parsed.getTime())
      ? normalized
      : parsed.toLocaleString('zh-CN', { hour12: false })
  }

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

  const formatAutoReplyBindingStatus = (status?: string) => {
    const normalized = normalizeBindingStatus(status)
    if (normalized === 'bound') {
      return '已绑定'
    }
    if (normalized === 'pending') {
      return '处理中'
    }
    return '未绑定'
  }

  const formatAutoReplyPollStatus = (status?: string) => {
    const normalized = String(status || '').trim().toLowerCase()
    if (!normalized || normalized === 'idle') {
      return '空闲'
    }
    if (normalized === 'ok') {
      return '正常'
    }
    if (normalized === 'timeout') {
      return '超时'
    }
    if (normalized === 'partial_error') {
      return '部分失败'
    }
    if (normalized === 'error') {
      return '失败'
    }
    return status || '未知'
  }

  const validateWeixinConfig = () => {
    if (!weixinConfig.account_id || !weixinConfig.token) {
      return '微信配置不完整，account_id 和 token 为必填项'
    }
    if (!isValidHttpUrl(weixinConfig.base_url)) {
      return 'Base URL 必须以 http:// 或 https:// 开头'
    }
    if (!Number.isInteger(weixinConfig.timeout_seconds) || weixinConfig.timeout_seconds <= 0) {
      return '超时时间必须是大于 0 的整数'
    }
    return ''
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

  const clearQrPolling = useCallback(() => {
    pollGenerationRef.current += 1
    pollInFlightRef.current = false
    if (pollTimerRef.current !== null) {
      window.clearTimeout(pollTimerRef.current)
      pollTimerRef.current = null
    }
    setPollingQrLogin(false)
  }, [])

  const clearQrImage = useCallback(() => {
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
  }, [])

  const loadBindingInfo = useCallback(async () => {
    setLoadingBinding(true)
    setBindingError(null)
    try {
      const response = await weixinAPI.getBinding()
      if (response.data) {
        setBindingInfo(response.data)
      }
    } catch (error) {
      setBindingError(getApiErrorDetail(error, '加载绑定状态失败'))
      appLogger.error({
        event: 'weixin_binding_load_failed',
        message: '加载绑定状态失败',
        module: 'communication',
        extra: { error: error instanceof Error ? error.message : String(error) },
      })
    } finally {
      setLoadingBinding(false)
    }
  }, [])

  const loadAutoReplyStatus = useCallback(async (options?: { silent?: boolean }) => {
    const silent = options?.silent === true
    if (!silent) {
      setLoadingAutoReplyStatus(true)
    }
    setAutoReplyStatusError(null)
    try {
      const response = await weixinAPI.getAutoReplyStatus()
      if (response.data) {
        setAutoReplyStatus(response.data)
      }
    } catch (error) {
      setAutoReplyStatusError(getApiErrorDetail(error, '加载自动回复状态失败'))
      appLogger.error({
        event: 'weixin_auto_reply_status_load_failed',
        message: '加载自动回复状态失败',
        module: 'communication',
        extra: { error: error instanceof Error ? error.message : String(error) },
      })
    } finally {
      if (!silent) {
        setLoadingAutoReplyStatus(false)
      }
    }
  }, [])

  const loadParamsConfig = useCallback(async () => {
    setParamsLoadError(null)
    try {
      const response = await weixinAPI.getParams()
      if (response.data) {
        setParamsConfig(response.data)
        setEditBotType(response.data.bot_type || '')
        setEditChannelVersion(response.data.channel_version || '')
      }
    } catch (error) {
      setParamsLoadError(getApiErrorDetail(error, '加载连接参数失败，请稍后重试'))
      appLogger.error({
        event: 'weixin_params_load_failed',
        message: '加载微信参数失败',
        module: 'communication',
        extra: { error: error instanceof Error ? error.message : String(error) },
      })
    }
  }, [])

  const loadRules = useCallback(async (silent = false) => {
    if (!silent) {
      setLoadingRules(true)
    }
    setRulesError(null)
    try {
      const response = await weixinAPI.getRules()
      if (response.data) {
        setRules(response.data)
      }
    } catch (error) {
      setRulesError(getApiErrorDetail(error, '加载自动回复规则失败'))
      appLogger.error({
        event: 'weixin_auto_reply_rules_load_failed',
        message: '加载自动回复规则失败',
        module: 'communication',
        extra: { error: error instanceof Error ? error.message : String(error) },
      })
    } finally {
      if (!silent) {
        setLoadingRules(false)
      }
    }
  }, [])

  const loadWeixinConfig = useCallback(async () => {
    setLoadingWeixin(true)
    setConfigLoadError(null)
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
    } catch (error) {
      setConfigLoadError(getApiErrorDetail(error, '加载微信配置失败，请稍后重试'))
      appLogger.error({
        event: 'weixin_config_load_failed',
        message: '加载微信配置失败',
        module: 'communication',
        extra: { error: error instanceof Error ? error.message : String(error) },
      })
    } finally {
      setLoadingWeixin(false)
    }
  }, [])

  useEffect(() => {
    void loadWeixinConfig()
    void loadBindingInfo()
    void loadAutoReplyStatus()
    void loadParamsConfig()
    void loadRules()

    return () => {
      clearQrPolling()
      clearQrImage()
    }
  }, [loadWeixinConfig, loadBindingInfo, loadAutoReplyStatus, loadParamsConfig, clearQrPolling, clearQrImage])

  const handleUnbind = async () => {
    setUnbinding(true)
    try {
      await weixinAPI.deleteBinding()
      setBindingInfo(null)
      setAutoReplyProcessResult(null)
      showTimedMessage('success', '微信绑定已解除')
    } catch {
      showTimedMessage('error', '解除绑定失败')
    } finally {
      setUnbinding(false)
      void loadAutoReplyStatus({ silent: true })
    }
  }

  const handleSaveParams = async () => {
    setSavingParams(true)
    try {
      const response = await weixinAPI.updateParams({
        bot_type: editBotType || undefined,
        channel_version: editChannelVersion || undefined,
      })
      if (response.data) {
        setParamsConfig(response.data)
      }
      showTimedMessage('success', '连接参数已更新')
    } catch {
      showTimedMessage('error', '更新连接参数失败，请先绑定微信账号')
    } finally {
      setSavingParams(false)
    }
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

  const pollQrLoginStatus = async (sessionKey: string, generation: number = pollGenerationRef.current) => {
    if (generation !== pollGenerationRef.current) {
      return false
    }

    try {
      const response = await weixinAPI.waitQrLogin({
        session_key: sessionKey,
        timeout_seconds: weixinConfig.timeout_seconds,
        qrcode: qrPollTokenRef.current || undefined,
        base_url: qrPollBaseUrlRef.current || weixinConfig.base_url || undefined,
      })
      if (generation !== pollGenerationRef.current) {
        return false
      }
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
        await loadBindingInfo()
        await loadAutoReplyStatus({ silent: true })
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
      if (generation !== pollGenerationRef.current) {
        return false
      }
      clearQrPolling()
      setQrStatusText('轮询登录状态失败，请稍后重试')
      setMessage({ type: 'error', text: '轮询登录状态失败' })
      return false
    }
  }

  const scheduleNextQrPoll = (sessionKey: string, generation: number) => {
    if (pollTimerRef.current !== null) {
      window.clearTimeout(pollTimerRef.current)
    }

    pollTimerRef.current = window.setTimeout(async () => {
      if (generation !== pollGenerationRef.current || pollInFlightRef.current) {
        return
      }

      pollInFlightRef.current = true
      try {
        const shouldContinuePolling = await pollQrLoginStatus(sessionKey, generation)
        if (shouldContinuePolling && generation === pollGenerationRef.current) {
          scheduleNextQrPoll(sessionKey, generation)
        }
      } finally {
        pollInFlightRef.current = false
      }
    }, 2000)
  }

  const handleStartQrLogin = async () => {
    setStartingQrLogin(true)
    clearQrPolling()
    const pollingGeneration = pollGenerationRef.current
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
      const shouldContinuePolling = await pollQrLoginStatus(response.data.session_key, pollingGeneration)
      if (shouldContinuePolling && pollingGeneration === pollGenerationRef.current) {
        scheduleNextQrPoll(response.data.session_key, pollingGeneration)
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
    appLogger.info({
      event: 'weixin_config_click',
      module: 'communication',
      action: 'save_config',
      status: 'start',
      message: '用户点击保存微信配置',
    })
    const validationMessage = validateWeixinConfig()
    if (validationMessage) {
      showTimedMessage('error', validationMessage)
      return
    }
    setSavingWeixin(true)
    try {
      await weixinAPI.saveConfig(weixinConfig)
      showTimedMessage('success', '微信通讯配置保存成功')
    } catch {
      showTimedMessage('error', '微信通讯配置保存失败')
    } finally {
      setSavingWeixin(false)
    }
  }

  const handleTestWeixinConnection = async () => {
    appLogger.info({
      event: 'weixin_config_click',
      module: 'communication',
      action: 'test_connection',
      status: 'start',
      message: '用户点击测试连接',
    })
    const validationMessage = validateWeixinConfig()
    if (validationMessage) {
      showTimedMessage('error', validationMessage)
      return
    }
    setTestingWeixin(true)
    setWeixinHealthResult(null)
    try {
      const response = await weixinAPI.healthCheck(weixinConfig)
      setWeixinHealthResult(response.data)
      if (response.data.ok) {
        showTimedMessage('success', '测试连接成功！')
      } else {
        showTimedMessage('error', '测试连接失败，请查看下方详细结果')
      }
    } catch {
      showTimedMessage('error', '测试连接请求失败')
    } finally {
      setTestingWeixin(false)
    }
  }

  const currentBindingStatus = normalizeBindingStatus(
    autoReplyStatus?.binding_status || bindingInfo?.binding_status || weixinConfig.binding_status,
    autoReplyStatus?.weixin_user_id || bindingInfo?.weixin_user_id || weixinConfig.user_id
  )
  const isAutoReplyBindingReady = autoReplyStatus?.binding_ready ?? currentBindingStatus === 'bound'
  const autoReplyBusy = autoReplyAction !== null
  const canStartAutoReply = isAutoReplyBindingReady && !autoReplyBusy && !autoReplyStatus?.auto_reply_running
  const canStopAutoReply = !autoReplyBusy && Boolean(autoReplyStatus?.auto_reply_running || autoReplyStatus?.auto_reply_enabled)
  const canRestartAutoReply = isAutoReplyBindingReady && !autoReplyBusy
  const canProcessAutoReplyOnce = isAutoReplyBindingReady && !autoReplyBusy

  const ensureAutoReplyReady = (actionLabel: string) => {
    if (!isAutoReplyBindingReady) {
      showTimedMessage('error', `请先完成微信绑定后再${actionLabel}`)
      return false
    }
    return true
  }

  const handleStartAutoReply = async () => {
    appLogger.info({
      event: 'weixin_auto_reply_click',
      module: 'communication',
      action: 'start_auto_reply',
      status: 'start',
      message: '用户点击启动自动回复',
    })
    if (!ensureAutoReplyReady('启动自动回复')) {
      return
    }
    setAutoReplyAction('start')
    try {
      const response = await weixinAPI.startAutoReply()
      setAutoReplyStatus(response.data)
      appLogger.info({
        event: 'weixin_auto_reply_click',
        module: 'communication',
        action: 'start_auto_reply',
        status: 'success',
        message: '自动回复启动成功',
      })
      showTimedMessage('success', '自动回复已启动')
    } catch (error) {
      showTimedMessage('error', getApiErrorDetail(error, '启动自动回复失败'))
    } finally {
      setAutoReplyAction(null)
      void loadAutoReplyStatus({ silent: true })
    }
  }

  const handleStopAutoReply = async () => {
    appLogger.info({
      event: 'weixin_auto_reply_click',
      module: 'communication',
      action: 'stop_auto_reply',
      status: 'start',
      message: '用户点击停止自动回复',
    })
    setAutoReplyAction('stop')
    try {
      const response = await weixinAPI.stopAutoReply()
      setAutoReplyStatus(response.data)
      appLogger.info({
        event: 'weixin_auto_reply_click',
        module: 'communication',
        action: 'stop_auto_reply',
        status: 'success',
        message: '自动回复停止成功',
      })
      showTimedMessage('success', '自动回复已停止')
    } catch (error) {
      showTimedMessage('error', getApiErrorDetail(error, '停止自动回复失败'))
    } finally {
      setAutoReplyAction(null)
      void loadAutoReplyStatus({ silent: true })
    }
  }

  const handleRestartAutoReply = async () => {
    appLogger.info({
      event: 'weixin_auto_reply_click',
      module: 'communication',
      action: 'restart_auto_reply',
      status: 'start',
      message: '用户点击重启自动回复',
    })
    if (!ensureAutoReplyReady('重启自动回复')) {
      return
    }
    setAutoReplyAction('restart')
    try {
      const response = await weixinAPI.restartAutoReply()
      setAutoReplyStatus(response.data)
      appLogger.info({
        event: 'weixin_auto_reply_click',
        module: 'communication',
        action: 'restart_auto_reply',
        status: 'success',
        message: '自动回复重启成功',
      })
      showTimedMessage('success', '自动回复已重启')
    } catch (error) {
      showTimedMessage('error', getApiErrorDetail(error, '重启自动回复失败'))
    } finally {
      setAutoReplyAction(null)
      void loadAutoReplyStatus({ silent: true })
    }
  }

  const handleProcessAutoReplyOnce = async () => {
    appLogger.info({
      event: 'weixin_auto_reply_click',
      module: 'communication',
      action: 'process_once',
      status: 'start',
      message: '用户点击单次处理',
    })
    if (!ensureAutoReplyReady('执行单次处理')) {
      return
    }
    setAutoReplyAction('process')
    try {
      const response = await weixinAPI.processAutoReplyOnce()
      setAutoReplyProcessResult(response.data)
      if (response.data.ok) {
        showTimedMessage(
          'success',
          `单次处理完成：成功 ${response.data.processed} 条，跳过 ${response.data.skipped} 条，重复 ${response.data.duplicates} 条`
        )
      } else {
        showTimedMessage('error', response.data.error || '单次处理失败')
      }
    } catch (error) {
      showTimedMessage('error', getApiErrorDetail(error, '执行单次处理失败'))
    } finally {
      setAutoReplyAction(null)
      void loadAutoReplyStatus({ silent: true })
    }
  }

  const handleSaveRule = async (ruleData: WeixinAutoReplyRule | WeixinAutoReplyRuleCreate) => {
    setSavingRule(true)
    try {
      if ('id' in ruleData) {
        await weixinAPI.updateRule(ruleData.id, ruleData as WeixinAutoReplyRuleUpdate)
        showTimedMessage('success', '规则更新成功')
      } else {
        await weixinAPI.createRule(ruleData as WeixinAutoReplyRuleCreate)
        showTimedMessage('success', '规则创建成功')
      }
      setEditingRule(null)
      await loadRules(true)
    } catch (error) {
      showTimedMessage('error', getApiErrorDetail(error, '保存规则失败'))
    } finally {
      setSavingRule(false)
    }
  }

  const handleDeleteRule = async (id: number) => {
    if (!window.confirm('确定要删除这条规则吗？')) return
    try {
      await weixinAPI.deleteRule(id)
      showTimedMessage('success', '规则删除成功')
      await loadRules(true)
    } catch (error) {
      showTimedMessage('error', getApiErrorDetail(error, '删除规则失败'))
    }
  }

  const handleToggleRuleActive = async (rule: WeixinAutoReplyRule) => {
    try {
      await weixinAPI.updateRule(rule.id, { is_active: !rule.is_active })
      await loadRules(true)
    } catch (error) {
      showTimedMessage('error', getApiErrorDetail(error, '切换规则状态失败'))
    }
  }

  const handleRestoreDefaultRules = async () => {
    if (!window.confirm('这将清空所有当前规则并恢复为系统默认规则，确定要继续吗？')) return
    setSavingRule(true)
    try {
      // Delete all existing rules
      for (const rule of rules) {
        await weixinAPI.deleteRule(rule.id)
      }
      // Create a default rule
      await weixinAPI.createRule({
        rule_name: '默认回复',
        match_type: 'regex',
        match_pattern: '.*',
        reply_content: '我暂时无法生成合适的回复，请稍后再试。',
        is_active: true,
        priority: -100
      })
      showTimedMessage('success', '已恢复默认规则')
      await loadRules(true)
    } catch (error) {
      showTimedMessage('error', getApiErrorDetail(error, '恢复默认规则失败'))
    } finally {
      setSavingRule(false)
    }
  }

  return {
    message,
    weixinConfig, setWeixinConfig,
    loadingWeixin, configLoadError, savingWeixin, testingWeixin, weixinHealthResult,
    startingQrLogin, pollingQrLogin, qrSessionKey, qrCodeUrl, qrImageLoadError, qrStatus, qrState, qrStatusText, qrStatusHint, qrBindingResult,
    bindingInfo, loadingBinding, unbinding, bindingError,
    autoReplyStatus, loadingAutoReplyStatus, autoReplyStatusError, autoReplyAction, autoReplyProcessResult,
    paramsConfig, paramsLoadError, editBotType, setEditBotType, editChannelVersion, setEditChannelVersion, savingParams,
    rules, loadingRules, rulesError, editingRule, setEditingRule, savingRule,
    
    currentBindingStatus, isAutoReplyBindingReady, autoReplyBusy, canStartAutoReply, canStopAutoReply, canRestartAutoReply, canProcessAutoReplyOnce,

    formatStatusTime, buildBindingResultText, buildNextStepText, formatAutoReplyBindingStatus, formatAutoReplyPollStatus,
    loadBindingInfo, loadAutoReplyStatus, loadParamsConfig, loadWeixinConfig, loadRules,
    handleUnbind, handleSaveParams, handleStartQrLogin, handleCancelQrLogin, handleSaveWeixinConfig, handleTestWeixinConnection,
    handleStartAutoReply, handleStopAutoReply, handleRestartAutoReply, handleProcessAutoReplyOnce,
    handleSaveRule, handleDeleteRule, handleToggleRuleActive, handleRestoreDefaultRules
  }
}
