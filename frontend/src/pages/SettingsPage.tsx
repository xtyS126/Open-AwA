import { useState, useEffect } from 'react'
import { promptsAPI } from '../services/api'
import { billingAPI, ModelPricing, RetentionConfig } from '../services/billingApi'
import { modelsAPI, ModelConfiguration, ModelProvider, ProviderModel } from '../services/modelsApi'
import './SettingsPage.css'

interface Settings {
  theme: string
  language: string
  apiProvider: string
  apiKey: string
  promptContent: string
  requireConfirm: boolean
  enableAudit: boolean
}

function SettingsPage() {
  const [activeTab, setActiveTab] = useState('general')
  const [settings, setSettings] = useState<Settings>({
    theme: 'light',
    language: 'zh',
    apiProvider: 'openai',
    apiKey: '',
    promptContent: '',
    requireConfirm: true,
    enableAudit: true,
  })
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null)
  const [models, setModels] = useState<ModelPricing[]>([])
  const [loadingModels, setLoadingModels] = useState(false)
  const [editingModel, setEditingModel] = useState<number | null>(null)
  const [editPrices, setEditPrices] = useState({ input_price: '', output_price: '' })
  const [retentionConfig, setRetentionConfig] = useState<RetentionConfig | null>(null)
  const [retentionDays, setRetentionDays] = useState(365)
  const [cleanupOld, setCleanupOld] = useState(false)
  const [loadingRetention, setLoadingRetention] = useState(false)

  const [configurations, setConfigurations] = useState<ModelConfiguration[]>([])
  const [loadingConfigs, setLoadingConfigs] = useState(false)
  const [providers, setProviders] = useState<ModelProvider[]>([])
  const [providerModels, setProviderModels] = useState<ProviderModel[]>([])
  const [showAddForm, setShowAddForm] = useState(false)
  const [newConfig, setNewConfig] = useState({
    provider: '',
    model: '',
    display_name: '',
    description: '',
    is_default: false,
  })

  useEffect(() => {
    loadSettings()
    loadPrompts()
    if (activeTab === 'billing') {
      loadBillingData()
    }
    if (activeTab === 'data-retention') {
      loadRetentionConfig()
    }
    if (activeTab === 'models') {
      loadModelsData()
    }
  }, [activeTab])

  const loadRetentionConfig = async () => {
    setLoadingRetention(true)
    try {
      const response = await billingAPI.getRetention()
      setRetentionConfig(response.data)
      setRetentionDays(response.data.retention_days)
    } catch (error) {
      console.error('Failed to load retention config')
    } finally {
      setLoadingRetention(false)
    }
  }

  const handleSaveRetention = async () => {
    setSaving(true)
    try {
      const response = await billingAPI.updateRetention({
        retention_days: retentionDays,
        cleanup: cleanupOld
      })
      setMessage({ type: 'success', text: `保存成功${cleanupOld && response.data.deleted_records > 0 ? `，已删除${response.data.deleted_records}条过期记录` : ''}` })
      loadRetentionConfig()
      setCleanupOld(false)
    } catch (error) {
      setMessage({ type: 'error', text: '保存失败' })
    } finally {
      setSaving(false)
      setTimeout(() => setMessage(null), 3000)
    }
  }

  const loadSettings = () => {
    const savedSettings = localStorage.getItem('app_settings')
    if (savedSettings) {
      try {
        setSettings(JSON.parse(savedSettings))
      } catch (e) {
        console.error('Failed to load settings')
      }
    }
  }

  const loadPrompts = async () => {
    try {
      const response = await promptsAPI.getActive()
      if (response.data && response.data.content) {
        setSettings(prev => ({ ...prev, promptContent: response.data.content }))
      }
    } catch (error) {
      console.error('Failed to load prompts')
    }
  }

  const loadBillingData = async () => {
    setLoadingModels(true)
    try {
      const [modelsRes] = await Promise.all([
        billingAPI.getModels()
      ])
      setModels(modelsRes.data.models || [])
    } catch (error) {
      console.error('Failed to load billing data')
    } finally {
      setLoadingModels(false)
    }
  }

  const loadModelsData = async () => {
    setLoadingConfigs(true)
    try {
      const [configsRes, providersRes] = await Promise.all([
        modelsAPI.getConfigurations(),
        modelsAPI.getProviders()
      ])
      setConfigurations(configsRes.data.configurations || [])
      setProviders(providersRes.data.providers || [])
    } catch (error) {
      console.error('Failed to load models data')
    } finally {
      setLoadingConfigs(false)
    }
  }

  const handleProviderChange = async (provider: string) => {
    setNewConfig(prev => ({ ...prev, provider, model: '' }))
    if (provider) {
      try {
        const response = await modelsAPI.getModelsByProvider(provider)
        setProviderModels(response.data.models || [])
      } catch (error) {
        console.error('Failed to load provider models')
      }
    } else {
      setProviderModels([])
    }
  }

  const handleAddConfiguration = async () => {
    if (!newConfig.provider || !newConfig.model) {
      setMessage({ type: 'error', text: '请选择提供商和模型' })
      setTimeout(() => setMessage(null), 3000)
      return
    }

    try {
      await modelsAPI.createConfiguration({
        provider: newConfig.provider,
        model: newConfig.model,
        display_name: newConfig.display_name || undefined,
        description: newConfig.description || undefined,
        is_default: newConfig.is_default,
      })
      setMessage({ type: 'success', text: '添加成功' })
      setNewConfig({ provider: '', model: '', display_name: '', description: '', is_default: false })
      setShowAddForm(false)
      loadModelsData()
    } catch (error) {
      setMessage({ type: 'error', text: '添加失败' })
    }
    setTimeout(() => setMessage(null), 3000)
  }

  const handleDeleteConfiguration = async (configId: number) => {
    if (!confirm('确定要删除这个模型配置吗？')) return

    try {
      await modelsAPI.deleteConfiguration(configId)
      setMessage({ type: 'success', text: '删除成功' })
      loadModelsData()
    } catch (error) {
      setMessage({ type: 'error', text: '删除失败' })
    }
    setTimeout(() => setMessage(null), 3000)
  }

  const handleSetDefault = async (configId: number) => {
    try {
      await modelsAPI.setDefaultConfiguration(configId)
      setMessage({ type: 'success', text: '设置成功' })
      loadModelsData()
    } catch (error) {
      setMessage({ type: 'error', text: '设置失败' })
    }
    setTimeout(() => setMessage(null), 3000)
  }

  const saveSettings = async () => {
    setSaving(true)
    setMessage(null)

    try {
      localStorage.setItem('app_settings', JSON.stringify(settings))
      
      if (settings.promptContent) {
        const existingPrompts = await promptsAPI.getAll()
        if (existingPrompts.data && existingPrompts.data.length > 0) {
          await promptsAPI.update(existingPrompts.data[0].id, {
            name: 'System Prompt',
            content: settings.promptContent,
            variables: '{}',
            is_active: true
          })
        } else {
          await promptsAPI.create({
            name: 'System Prompt',
            content: settings.promptContent,
            variables: '{}',
          })
        }
      }

      setMessage({ type: 'success', text: '设置保存成功' })
    } catch (error) {
      setMessage({ type: 'error', text: '保存失败，请重试' })
    } finally {
      setSaving(false)
      setTimeout(() => setMessage(null), 3000)
    }
  }

  const handleChange = (key: keyof Settings, value: any) => {
    setSettings(prev => ({ ...prev, [key]: value }))
  }

  const handleEditModel = (model: ModelPricing) => {
    setEditingModel(model.id)
    setEditPrices({
      input_price: model.input_price.toString(),
      output_price: model.output_price.toString()
    })
  }

  const handleSaveModelPrice = async (modelId: number) => {
    try {
      await billingAPI.updateModelPricing(modelId, {
        input_price: parseFloat(editPrices.input_price),
        output_price: parseFloat(editPrices.output_price)
      })
      setEditingModel(null)
      loadBillingData()
      setMessage({ type: 'success', text: '价格更新成功' })
    } catch (error) {
      setMessage({ type: 'error', text: '价格更新失败' })
    }
    setTimeout(() => setMessage(null), 3000)
  }

  const formatPrice = (price: number, currency: string) => {
    const symbol = currency === 'CNY' ? '¥' : '$'
    return `${symbol}${price.toFixed(4)}`
  }

  const groupedModels = models.reduce((acc, model) => {
    if (!acc[model.provider]) {
      acc[model.provider] = []
    }
    acc[model.provider].push(model)
    return acc
  }, {} as Record<string, ModelPricing[]>)

  const getProviderName = (providerId: string) => {
    const provider = providers.find(p => p.id === providerId)
    return provider ? provider.name : providerId
  }

  return (
    <div className="settings-page">
      <div className="settings-header">
        <h1>设置</h1>
      </div>

      <div className="settings-tabs">
        <button
          className={`tab-btn ${activeTab === 'general' ? 'active' : ''}`}
          onClick={() => setActiveTab('general')}
        >
          通用设置
        </button>
        <button
          className={`tab-btn ${activeTab === 'api' ? 'active' : ''}`}
          onClick={() => setActiveTab('api')}
        >
          API配置
        </button>
        <button
          className={`tab-btn ${activeTab === 'prompts' ? 'active' : ''}`}
          onClick={() => setActiveTab('prompts')}
        >
          提示词
        </button>
        <button
          className={`tab-btn ${activeTab === 'billing' ? 'active' : ''}`}
          onClick={() => setActiveTab('billing')}
        >
          计费配置
        </button>
        <button
          className={`tab-btn ${activeTab === 'models' ? 'active' : ''}`}
          onClick={() => setActiveTab('models')}
        >
          模型管理
        </button>
        <button
          className={`tab-btn ${activeTab === 'data-retention' ? 'active' : ''}`}
          onClick={() => setActiveTab('data-retention')}
        >
          数据保留
        </button>
        <button
          className={`tab-btn ${activeTab === 'security' ? 'active' : ''}`}
          onClick={() => setActiveTab('security')}
        >
          安全设置
        </button>
      </div>

      <div className="settings-content">
        {message && (
          <div className={`message ${message.type}`}>
            {message.text}
          </div>
        )}

        {activeTab === 'general' && (
          <div className="settings-section">
            <h2>通用设置</h2>
            <div className="setting-item">
              <label>主题</label>
              <select
                value={settings.theme}
                onChange={(e) => handleChange('theme', e.target.value)}
              >
                <option value="light">浅色</option>
                <option value="dark">深色</option>
              </select>
            </div>
            <div className="setting-item">
              <label>语言</label>
              <select
                value={settings.language}
                onChange={(e) => handleChange('language', e.target.value)}
              >
                <option value="zh">中文</option>
                <option value="en">English</option>
              </select>
            </div>
            <button
              className="btn btn-primary"
              onClick={saveSettings}
              disabled={saving}
            >
              {saving ? '保存中...' : '保存设置'}
            </button>
          </div>
        )}

        {activeTab === 'api' && (
          <div className="settings-section">
            <h2>API配置</h2>
            <div className="setting-item">
              <label>API Provider</label>
              <select
                value={settings.apiProvider}
                onChange={(e) => handleChange('apiProvider', e.target.value)}
              >
                <option value="openai">OpenAI</option>
                <option value="anthropic">Anthropic</option>
                <option value="deepseek">DeepSeek</option>
                <option value="zhipu">智谱AI</option>
                <option value="kimi">Kimi</option>
              </select>
            </div>
            <div className="setting-item">
              <label>API Key</label>
              <input
                type="password"
                value={settings.apiKey}
                onChange={(e) => handleChange('apiKey', e.target.value)}
                placeholder="输入你的API Key"
              />
            </div>
            <div className="setting-item">
              <label>API Endpoint (可选)</label>
              <input
                type="text"
                placeholder="自定义API地址"
              />
            </div>
            <button
              className="btn btn-primary"
              onClick={saveSettings}
              disabled={saving}
            >
              {saving ? '保存中...' : '保存API配置'}
            </button>
          </div>
        )}

        {activeTab === 'prompts' && (
          <div className="settings-section">
            <h2>提示词配置</h2>
            <p className="section-desc">
              自定义AI助手的行为和角色提示词
            </p>
            <textarea
              className="prompt-editor"
              value={settings.promptContent}
              onChange={(e) => handleChange('promptContent', e.target.value)}
              placeholder="输入系统提示词..."
              rows={12}
            />
            <div className="prompt-helper">
              <p>支持的变量：{'{user_name}'} - 用户名，{'{current_time}'} - 当前时间</p>
            </div>
            <button
              className="btn btn-primary"
              onClick={saveSettings}
              disabled={saving}
            >
              {saving ? '保存中...' : '保存提示词'}
            </button>
          </div>
        )}

        {activeTab === 'billing' && (
          <div className="settings-section">
            <h2>模型价格配置</h2>
            <p className="section-desc">
              配置各AI厂商的模型API价格（单位：百万tokens）
            </p>
            
            {loadingModels ? (
              <div className="loading">加载中...</div>
            ) : (
              <div className="pricing-table-container">
                {Object.entries(groupedModels).map(([provider, providerModels]) => (
                  <div key={provider} className="pricing-provider-group">
                    <h3 className="provider-title">{provider.toUpperCase()}</h3>
                    <table className="pricing-table">
                      <thead>
                        <tr>
                          <th>模型</th>
                          <th>输入价格</th>
                          <th>输出价格</th>
                          <th>缓存价格</th>
                          <th>上下文窗口</th>
                          <th>操作</th>
                        </tr>
                      </thead>
                      <tbody>
                        {providerModels.map((model) => (
                          <tr key={model.id}>
                            <td className="model-name">{model.model}</td>
                            <td>
                              {editingModel === model.id ? (
                                <input
                                  type="number"
                                  value={editPrices.input_price}
                                  onChange={(e) => setEditPrices(prev => ({ ...prev, input_price: e.target.value }))}
                                  className="price-input"
                                  step="0.0001"
                                />
                              ) : (
                                formatPrice(model.input_price, model.currency)
                              )}
                            </td>
                            <td>
                              {editingModel === model.id ? (
                                <input
                                  type="number"
                                  value={editPrices.output_price}
                                  onChange={(e) => setEditPrices(prev => ({ ...prev, output_price: e.target.value }))}
                                  className="price-input"
                                  step="0.0001"
                                />
                              ) : (
                                formatPrice(model.output_price, model.currency)
                              )}
                            </td>
                            <td>
                              {model.cache_hit_price 
                                ? formatPrice(model.cache_hit_price, model.currency)
                                : '-'
                              }
                            </td>
                            <td>
                              {model.context_window 
                                ? `${(model.context_window / 1000).toFixed(0)}K`
                                : '-'
                              }
                            </td>
                            <td>
                              {editingModel === model.id ? (
                                <div className="action-buttons">
                                  <button 
                                    className="btn btn-small btn-primary"
                                    onClick={() => handleSaveModelPrice(model.id)}
                                  >
                                    保存
                                  </button>
                                  <button 
                                    className="btn btn-small"
                                    onClick={() => setEditingModel(null)}
                                  >
                                    取消
                                  </button>
                                </div>
                              ) : (
                                <button 
                                  className="btn btn-small"
                                  onClick={() => handleEditModel(model)}
                                >
                                  编辑
                                </button>
                              )}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {activeTab === 'models' && (
          <div className="settings-section">
            <div className="section-header">
              <h2>模型管理</h2>
              <button 
                className="btn btn-primary"
                onClick={() => setShowAddForm(!showAddForm)}
              >
                {showAddForm ? '取消' : '+ 添加模型'}
              </button>
            </div>
            <p className="section-desc">
              配置可用的AI模型，设置的默认模型将自动在聊天页面选中
            </p>

            {showAddForm && (
              <div className="add-config-form">
                <div className="form-row">
                  <div className="form-group">
                    <label>提供商</label>
                    <select
                      value={newConfig.provider}
                      onChange={(e) => handleProviderChange(e.target.value)}
                    >
                      <option value="">选择提供商</option>
                      {providers.map(p => (
                        <option key={p.id} value={p.id}>{p.name}</option>
                      ))}
                    </select>
                  </div>
                  <div className="form-group">
                    <label>模型</label>
                    <select
                      value={newConfig.model}
                      onChange={(e) => setNewConfig(prev => ({ ...prev, model: e.target.value }))}
                      disabled={!newConfig.provider}
                    >
                      <option value="">选择模型</option>
                      {providerModels.map(m => (
                        <option key={m.id} value={m.model}>{m.model}</option>
                      ))}
                    </select>
                  </div>
                </div>
                <div className="form-row">
                  <div className="form-group">
                    <label>显示名称（可选）</label>
                    <input
                      type="text"
                      value={newConfig.display_name}
                      onChange={(e) => setNewConfig(prev => ({ ...prev, display_name: e.target.value }))}
                      placeholder="例如：GPT-4.1"
                    />
                  </div>
                </div>
                <div className="form-row">
                  <div className="form-group">
                    <label>描述（可选）</label>
                    <input
                      type="text"
                      value={newConfig.description}
                      onChange={(e) => setNewConfig(prev => ({ ...prev, description: e.target.value }))}
                      placeholder="模型描述"
                    />
                  </div>
                </div>
                <div className="form-row">
                  <div className="form-group checkbox-group">
                    <input
                      type="checkbox"
                      id="is-default-new"
                      checked={newConfig.is_default}
                      onChange={(e) => setNewConfig(prev => ({ ...prev, is_default: e.target.checked }))}
                    />
                    <label htmlFor="is-default-new">设为默认模型</label>
                  </div>
                </div>
                <button className="btn btn-primary" onClick={handleAddConfiguration}>
                  添加
                </button>
              </div>
            )}

            {loadingConfigs ? (
              <div className="loading">加载中...</div>
            ) : configurations.length === 0 ? (
              <div className="empty-state">
                <p>暂无配置的模型</p>
                <p className="hint">点击上方"添加模型"按钮来配置第一个模型</p>
              </div>
            ) : (
              <div className="configs-list">
                {configurations.map(config => (
                  <div key={config.id} className={`config-card ${config.is_default ? 'default' : ''}`}>
                    <div className="config-info">
                      <div className="config-header">
                        <span className="config-provider">{getProviderName(config.provider)}</span>
                        {config.is_default && <span className="default-badge">默认</span>}
                      </div>
                      <div className="config-model">{config.display_name || config.model}</div>
                      {config.description && (
                        <div className="config-description">{config.description}</div>
                      )}
                      <div className="config-meta">
                        模型：{config.model}
                      </div>
                    </div>
                    <div className="config-actions">
                      {!config.is_default && (
                        <button 
                          className="btn btn-small"
                          onClick={() => handleSetDefault(config.id)}
                        >
                          设为默认
                        </button>
                      )}
                      <button 
                        className="btn btn-small btn-danger"
                        onClick={() => handleDeleteConfiguration(config.id)}
                      >
                        删除
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {activeTab === 'data-retention' && (
          <div className="settings-section">
            <h2>数据保留设置</h2>
            <p className="section-desc">
              配置计费数据的保留天数，超出保留期限的数据将被自动清理
            </p>

            {loadingRetention ? (
              <div className="loading">加载中...</div>
            ) : (
              <>
                <div className="setting-item">
                  <label>最大保存天数</label>
                  <input
                    type="number"
                    value={retentionDays}
                    onChange={(e) => setRetentionDays(parseInt(e.target.value) || 365)}
                    min={1}
                    max={3650}
                    style={{ width: '150px' }}
                  />
                  <span style={{ marginLeft: '8px', color: '#666', fontSize: '14px' }}>
                    天（范围：1-3650）
                  </span>
                </div>

                {retentionConfig && (
                  <div className="setting-item">
                    <label>当前数据状态</label>
                    <div style={{ fontSize: '14px', color: '#666', marginTop: '8px' }}>
                      <p>总记录数：{retentionConfig.total_records}</p>
                      <p>
                        数据范围：{retentionConfig.oldest_record
                          ? new Date(retentionConfig.oldest_record).toLocaleDateString('zh-CN')
                          : '无'}
                        {' - '}
                        {retentionConfig.newest_record
                          ? new Date(retentionConfig.newest_record).toLocaleDateString('zh-CN')
                          : '无'}
                      </p>
                    </div>
                  </div>
                )}

                <div className="setting-item checkbox">
                  <input
                    type="checkbox"
                    id="cleanup-old"
                    checked={cleanupOld}
                    onChange={(e) => setCleanupOld(e.target.checked)}
                  />
                  <label htmlFor="cleanup-old">
                    保存后清理超出保留期限的旧数据
                  </label>
                </div>

                <button
                  className="btn btn-primary"
                  onClick={handleSaveRetention}
                  disabled={saving}
                >
                  {saving ? '保存中...' : '保存设置'}
                </button>
              </>
            )}
          </div>
        )}

        {activeTab === 'security' && (
          <div className="settings-section">
            <h2>安全设置</h2>
            <div className="setting-item checkbox">
              <input
                type="checkbox"
                id="require-confirm"
                checked={settings.requireConfirm}
                onChange={(e) => handleChange('requireConfirm', e.target.checked)}
              />
              <label htmlFor="require-confirm">敏感操作需要确认</label>
            </div>
            <div className="setting-item checkbox">
              <input
                type="checkbox"
                id="enable-audit"
                checked={settings.enableAudit}
                onChange={(e) => handleChange('enableAudit', e.target.checked)}
              />
              <label htmlFor="enable-audit">启用审计日志</label>
            </div>
            <button
              className="btn btn-primary"
              onClick={saveSettings}
              disabled={saving}
            >
              {saving ? '保存中...' : '保存安全设置'}
            </button>
          </div>
        )}
      </div>
    </div>
  )
}

export default SettingsPage
