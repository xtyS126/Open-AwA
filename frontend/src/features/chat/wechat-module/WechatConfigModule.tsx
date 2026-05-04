import { useWechatConfig } from './useWechatConfig'
import styles from './WechatConfigModule.module.css'

export default function WechatConfigModule() {
  const {
    message,
    weixinConfig, setWeixinConfig,
    loadingWeixin, configLoadError, savingWeixin, testingWeixin, weixinHealthResult,
    startingQrLogin, pollingQrLogin, qrSessionKey, qrCodeUrl, qrImageLoadError, qrStatus, qrState, qrStatusText, qrStatusHint, qrBindingResult,
    bindingInfo, loadingBinding, unbinding, bindingError,
    autoReplyStatus, loadingAutoReplyStatus, autoReplyStatusError, autoReplyAction, autoReplyProcessResult, savingAutoStart,
    paramsConfig, paramsLoadError, editBotType, setEditBotType, editChannelVersion, setEditChannelVersion, savingParams,
    rules, loadingRules, rulesError, editingRule, setEditingRule, savingRule,
    
    currentBindingStatus, isAutoReplyBindingReady, autoReplyBusy, canStartAutoReply, canStopAutoReply, canRestartAutoReply, canProcessAutoReplyOnce,

    formatStatusTime, buildBindingResultText, buildNextStepText, formatAutoReplyBindingStatus, formatAutoReplyPollStatus,
    loadBindingInfo, loadAutoReplyStatus, loadParamsConfig, loadRules,
    handleUnbind, handleSaveParams, handleStartQrLogin, handleCancelQrLogin, handleSaveWeixinConfig, handleTestWeixinConnection,
    handleStartAutoReply, handleStopAutoReply, handleRestartAutoReply, handleProcessAutoReplyOnce, handleToggleAutoStart,
    handleSaveRule, handleDeleteRule, handleToggleRuleActive, handleRestoreDefaultRules
  } = useWechatConfig()

  return (
    <div className={styles['wechat-module']}>
      {message && (
        <div className={`${styles['message']} ${styles[message.type] || message.type}`}>
          {message.text}
        </div>
      )}
      <div className={styles['settings-section']}>
        <p className={styles['section-desc']}>配置外部通讯渠道，如微信 iLink 集成。</p>
        <div className={styles['config-card']}>
          <h3 className={styles['card-title']}>微信通讯配置</h3>
          {loadingWeixin ? (
            <div className={styles['loading']}>加载配置中...</div>
          ) : (
            <>
              <div className={styles['form-item']}>
                {configLoadError && (
                  <div className={`${styles['message']} ${styles['error']}`}>
                    {configLoadError}
                  </div>
                )}
                <label className={styles['label']}>Account ID <span className={styles['required']}>*</span></label>
                <input
                  type="text"
                  value={weixinConfig.account_id}
                  onChange={(e) => setWeixinConfig({ ...weixinConfig, account_id: e.target.value })}
                  placeholder="输入微信通讯账户 ID"
                  className={styles['input']}
                />
              </div>
              <div className={styles['form-item']}>
                <label className={styles['label']}>Token <span className={styles['required']}>*</span></label>
                <input
                  type="password"
                  value={weixinConfig.token}
                  onChange={(e) => setWeixinConfig({ ...weixinConfig, token: e.target.value })}
                  placeholder="输入 iLink Bot Token"
                  className={styles['input']}
                />
              </div>
              <div className={styles['form-item']}>
                <label className={styles['label']}>Base URL</label>
                <input
                  type="text"
                  value={weixinConfig.base_url}
                  onChange={(e) => setWeixinConfig({ ...weixinConfig, base_url: e.target.value })}
                  placeholder="https://ilinkai.weixin.qq.com"
                  className={styles['input']}
                />
              </div>
              <div className={styles['form-item']}>
                <label className={styles['label']}>超时时间 (秒)</label>
                <input
                  type="number"
                  value={weixinConfig.timeout_seconds}
                  onChange={(e) => setWeixinConfig({ ...weixinConfig, timeout_seconds: parseInt(e.target.value, 10) || 15 })}
                  placeholder="15"
                  className={styles['input']}
                />
              </div>
              <div className={styles['actions-row']}>
                <button
                  className={`btn btn-primary`}
                  onClick={() => void handleSaveWeixinConfig()}
                  disabled={savingWeixin}
                >
                  {savingWeixin ? '保存中...' : '保存配置'}
                </button>
                <button
                  className={`btn ${styles['btn-secondary'] || 'btn-secondary'}`}
                  onClick={() => void handleTestWeixinConnection()}
                  disabled={testingWeixin}
                >
                  {testingWeixin ? '测试中...' : '测试连接'}
                </button>
              </div>

              <div className={styles['qr-login']}>
                <h4 className={styles['qr-login-title']}>绑定状态</h4>
                {loadingBinding ? (
                  <p>加载绑定信息中...</p>
                ) : bindingError ? (
                  <div>
                    <p className={styles['qr-status']}>{bindingError}</p>
                    <button className="btn btn-primary" onClick={() => void loadBindingInfo()}>重试</button>
                  </div>
                ) : bindingInfo && bindingInfo.binding_status !== 'unbound' ? (
                  <div>
                    <p className={styles['qr-status']}>
                      {bindingInfo.binding_status === 'bound' ? '[DONE] 已绑定' : bindingInfo.binding_status === 'expired' ? '[!] 已过期' : `状态: ${bindingInfo.binding_status}`}
                      {bindingInfo.weixin_account_id ? ` | 账号: ${bindingInfo.weixin_account_id}` : ''}
                      {bindingInfo.weixin_user_id ? ` | 微信用户: ${bindingInfo.weixin_user_id}` : ''}
                    </p>
                    {bindingInfo.binding_status === 'expired' && (
                      <p className={styles['qr-status']}>Token 已过期，请重新扫码登录</p>
                    )}
                    <div className={styles['actions-row']}>
                      <button
                        className={`btn ${styles['btn-secondary'] || 'btn-secondary'}`}
                        onClick={() => void handleUnbind()}
                        disabled={unbinding}
                      >
                        {unbinding ? '解绑中...' : '解除绑定'}
                      </button>
                      {bindingInfo.binding_status === 'expired' && (
                        <button className="btn btn-primary" onClick={() => void handleStartQrLogin()} disabled={startingQrLogin}>
                          重新扫码登录
                        </button>
                      )}
                    </div>
                  </div>
                ) : (
                  <p className={styles['qr-status']}>未绑定微信账号，请通过扫码登录进行绑定。</p>
                )}
              </div>

              <div className={styles['qr-login']}>
                <h4 className={styles['qr-login-title']}>自动回复</h4>
                <p className={styles['qr-login-desc']}>展示当前自动回复运行状态，并支持启动、停止、重启和单次处理。</p>
                {loadingAutoReplyStatus ? (
                  <p>加载自动回复状态中...</p>
                ) : autoReplyStatusError ? (
                  <div>
                    <p className={styles['qr-status']}>{autoReplyStatusError}</p>
                    <button className="btn btn-primary" onClick={() => void loadAutoReplyStatus()}>重试</button>
                  </div>
                ) : (
                  <>
                    <div className={styles['status-grid']}>
                      <p className={styles['qr-status']}>绑定状态：{formatAutoReplyBindingStatus(autoReplyStatus?.binding_status || currentBindingStatus)}</p>
                      <p className={styles['qr-status']}>运行状态：{autoReplyStatus?.auto_reply_running ? '运行中' : '已停止'}</p>
                      <p className={styles['qr-status']}>启用状态：{autoReplyStatus?.auto_reply_enabled ? '已启用' : '未启用'}</p>
                      <p className={styles['qr-status']}>最近轮询：{formatAutoReplyPollStatus(autoReplyStatus?.last_poll_status)}</p>
                      <p className={styles['qr-status']}>微信账号：{autoReplyStatus?.weixin_account_id || '暂无'}</p>
                      <p className={styles['qr-status']}>微信用户：{autoReplyStatus?.weixin_user_id || '暂无'}</p>
                      <p className={styles['qr-status']}>最近轮询时间：{formatStatusTime(autoReplyStatus?.last_poll_at)}</p>
                      <p className={styles['qr-status']}>最近成功时间：{formatStatusTime(autoReplyStatus?.last_success_at)}</p>
                      <p className={styles['qr-status']}>最近回复时间：{formatStatusTime(autoReplyStatus?.last_reply_at)}</p>
                      <p className={styles['qr-status']}>最近回复对象：{autoReplyStatus?.last_replied_user_id || '暂无'}</p>
                      <p className={styles['qr-status']}>最近处理消息：{autoReplyStatus?.last_processed_message_id || '暂无'}</p>
                      <p className={styles['qr-status']}>当前游标：{autoReplyStatus?.cursor || '暂无'}</p>
                      <p className={styles['qr-status']}>已记录消息数：{autoReplyStatus?.processed_message_count ?? 0}</p>
                      <p className={styles['qr-status']}>最近错误时间：{formatStatusTime(autoReplyStatus?.last_error_at)}</p>
                    </div>
                    {autoReplyStatus?.last_error && (
                      <p className={styles['qr-status']}>最近错误：{autoReplyStatus.last_error}</p>
                    )}
                    {autoReplyProcessResult && (
                      <p className={styles['qr-status']}>
                        单次处理结果：状态 {formatAutoReplyPollStatus(autoReplyProcessResult.status)}，成功 {autoReplyProcessResult.processed} 条，跳过 {autoReplyProcessResult.skipped} 条，重复 {autoReplyProcessResult.duplicates} 条，错误 {autoReplyProcessResult.errors} 条
                      </p>
                    )}
                    {!isAutoReplyBindingReady && (
                      <p className={styles['qr-status']}>当前未完成绑定，自动回复操作暂不可用。</p>
                    )}
                  </>
                )}
                <div className={styles['auto-start-toggle']}>
                  <label className={styles['toggle-label']}>
                    <input
                      type="checkbox"
                      checked={autoReplyStatus?.auto_start_enabled ?? false}
                      disabled={savingAutoStart || !isAutoReplyBindingReady}
                      onChange={(e) => void handleToggleAutoStart(e.target.checked)}
                    />
                    <span className={styles['toggle-text']}>
                      服务启动时自动运行自动回复
                      {savingAutoStart && ' (保存中...)'}
                    </span>
                  </label>
                </div>
                <div className={styles['actions-row']}>
                  <button
                    className="btn btn-primary"
                    onClick={() => void loadAutoReplyStatus()}
                    disabled={loadingAutoReplyStatus || autoReplyBusy}
                  >
                    刷新状态
                  </button>
                  <button
                    className="btn btn-primary"
                    onClick={() => void handleStartAutoReply()}
                    disabled={!canStartAutoReply}
                  >
                    {autoReplyAction === 'start' ? '启动中...' : '启动自动回复'}
                  </button>
                  <button
                    className={`btn ${styles['btn-secondary'] || 'btn-secondary'}`}
                    onClick={() => void handleStopAutoReply()}
                    disabled={!canStopAutoReply}
                  >
                    {autoReplyAction === 'stop' ? '停止中...' : '停止自动回复'}
                  </button>
                  <button
                    className={`btn ${styles['btn-secondary'] || 'btn-secondary'}`}
                    onClick={() => void handleRestartAutoReply()}
                    disabled={!canRestartAutoReply}
                  >
                    {autoReplyAction === 'restart' ? '重启中...' : '重启自动回复'}
                  </button>
                  <button
                    className={`btn ${styles['btn-secondary'] || 'btn-secondary'}`}
                    onClick={() => void handleProcessAutoReplyOnce()}
                    disabled={!canProcessAutoReplyOnce}
                  >
                    {autoReplyAction === 'process' ? '处理中...' : '单次处理'}
                  </button>
                </div>
              </div>

              <div className={styles['qr-login']}>
                <h4 className={styles['qr-login-title']}>自动回复规则配置</h4>
                <p className={styles['qr-login-desc']}>管理微信自动回复的关键词和正则规则。支持实时生效。</p>
                {rulesError && (
                  <div className={`${styles['message']} ${styles['error']}`}>
                    {rulesError}
                  </div>
                )}
                
                {editingRule ? (
                  <div className={styles['form-item']}>
                    <div className={styles['form-item']}>
                      <label className={styles['label']}>规则名称 <span className={styles['required']}>*</span></label>
                      <input
                        type="text"
                        value={editingRule.rule_name || ''}
                        onChange={(e) => setEditingRule({ ...editingRule, rule_name: e.target.value })}
                        placeholder="输入规则名称"
                        className={styles['input']}
                      />
                    </div>
                    <div className={styles['form-item']}>
                      <label className={styles['label']}>匹配类型 <span className={styles['required']}>*</span></label>
                      <select
                        value={editingRule.match_type || 'keyword'}
                        onChange={(e) => setEditingRule({ ...editingRule, match_type: e.target.value as 'keyword' | 'regex' })}
                        className={styles['input']}
                      >
                        <option value="keyword">关键词 (包含)</option>
                        <option value="regex">正则表达式</option>
                      </select>
                    </div>
                    <div className={styles['form-item']}>
                      <label className={styles['label']}>匹配模式 <span className={styles['required']}>*</span></label>
                      <input
                        type="text"
                        value={editingRule.match_pattern || ''}
                        onChange={(e) => setEditingRule({ ...editingRule, match_pattern: e.target.value })}
                        placeholder={editingRule.match_type === 'regex' ? '输入正则表达式' : '输入触发关键词'}
                        className={styles['input']}
                      />
                    </div>
                    <div className={styles['form-item']}>
                      <label className={styles['label']}>回复内容 <span className={styles['required']}>*</span></label>
                      <textarea
                        value={editingRule.reply_content || ''}
                        onChange={(e) => setEditingRule({ ...editingRule, reply_content: e.target.value })}
                        placeholder="输入自动回复内容"
                        className={styles['input']}
                        rows={4}
                      />
                    </div>
                    <div className={styles['form-item']}>
                      <label className={styles['label']}>优先级 (数字越大越优先)</label>
                      <input
                        type="number"
                        value={editingRule.priority ?? 0}
                        onChange={(e) => setEditingRule({ ...editingRule, priority: parseInt(e.target.value, 10) || 0 })}
                        className={styles['input']}
                      />
                    </div>
                    <div className={styles['actions-row']}>
                      <button
                        className={`btn btn-primary`}
                        onClick={() => void handleSaveRule(editingRule as any)}
                        disabled={savingRule || !editingRule.rule_name || !editingRule.match_pattern || !editingRule.reply_content}
                      >
                        {savingRule ? '保存中...' : '保存规则'}
                      </button>
                      <button
                        className={`btn ${styles['btn-secondary'] || 'btn-secondary'}`}
                        onClick={() => setEditingRule(null)}
                        disabled={savingRule}
                      >
                        取消
                      </button>
                    </div>
                  </div>
                ) : (
                  <>
                    <div className={styles['actions-row']} style={{ marginBottom: '16px' }}>
                      <button
                        className={`btn btn-primary`}
                        onClick={() => setEditingRule({ rule_name: '', match_type: 'keyword', match_pattern: '', reply_content: '', is_active: true, priority: 0 })}
                      >
                        添加规则
                      </button>
                      <button
                        className={`btn ${styles['btn-secondary'] || 'btn-secondary'}`}
                        onClick={() => void loadRules()}
                        disabled={loadingRules}
                      >
                        {loadingRules ? '加载中...' : '刷新规则'}
                      </button>
                      <button
                        className={`btn ${styles['btn-secondary'] || 'btn-secondary'}`}
                        onClick={() => void handleRestoreDefaultRules()}
                        disabled={savingRule}
                      >
                        一键恢复默认
                      </button>
                    </div>

                    {rules.length === 0 ? (
                      <p className={styles['qr-status']}>暂无配置任何自动回复规则</p>
                    ) : (
                      <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                        {rules.map(rule => (
                          <div key={rule.id} style={{ padding: '16px', background: 'var(--color-bg)', borderRadius: 'var(--radius-md)', border: '1px solid var(--color-border)' }}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                              <h5 style={{ margin: 0, fontSize: '16px', display: 'flex', alignItems: 'center', gap: '8px' }}>
                                {rule.rule_name}
                                <span style={{ fontSize: '12px', padding: '2px 6px', background: 'var(--color-bg-tertiary)', borderRadius: '4px' }}>
                                  {rule.match_type === 'keyword' ? '关键词' : '正则'}
                                </span>
                              </h5>
                              <div>
                                <label style={{ display: 'inline-flex', alignItems: 'center', gap: '4px', cursor: 'pointer', marginRight: '12px', fontSize: '14px' }}>
                                  <input 
                                    type="checkbox" 
                                    checked={rule.is_active} 
                                    onChange={() => void handleToggleRuleActive(rule)} 
                                  />
                                  启用
                                </label>
                                <button className={`btn ${styles['btn-secondary'] || 'btn-secondary'}`} style={{ padding: '4px 8px', fontSize: '12px', marginRight: '8px' }} onClick={() => setEditingRule(rule)}>编辑</button>
                                <button className={`btn ${styles['btn-secondary'] || 'btn-secondary'}`} style={{ padding: '4px 8px', fontSize: '12px', color: 'var(--color-danger)' }} onClick={() => void handleDeleteRule(rule.id)}>删除</button>
                              </div>
                            </div>
                            <div style={{ fontSize: '14px', color: 'var(--color-text-secondary)', marginBottom: '4px' }}>
                              匹配模式: <code style={{ background: 'var(--color-bg-tertiary)', padding: '2px 4px', borderRadius: '4px' }}>{rule.match_pattern}</code>
                              <span style={{ marginLeft: '12px' }}>优先级: {rule.priority}</span>
                            </div>
                            <div style={{ fontSize: '14px', color: 'var(--color-text)', whiteSpace: 'pre-wrap', marginTop: '8px', padding: '8px', background: 'var(--color-bg-tertiary)', borderRadius: '4px' }}>
                              {rule.reply_content}
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </>
                )}
              </div>

              <div className={styles['qr-login']}>
                <h4 className={styles['qr-login-title']}>连接参数配置</h4>
                <p className={styles['qr-login-desc']}>可修改 bot_type 和 channel_version 等连接参数，需先绑定微信账号。</p>
                {paramsLoadError && (
                  <div className={`${styles['message']} ${styles['error']}`}>
                    {paramsLoadError}
                  </div>
                )}
                <div className={styles['form-item']}>
                  <label className={styles['label']}>Bot Type</label>
                  <input
                    type="text"
                    value={editBotType}
                    onChange={(e) => setEditBotType(e.target.value)}
                    placeholder={paramsConfig?.weixin_default_bot_type || '3'}
                    className={styles['input']}
                  />
                </div>
                <div className={styles['form-item']}>
                  <label className={styles['label']}>Channel Version</label>
                  <input
                    type="text"
                    value={editChannelVersion}
                    onChange={(e) => setEditChannelVersion(e.target.value)}
                    placeholder={paramsConfig?.weixin_default_channel_version || '1.0.2'}
                    className={styles['input']}
                  />
                </div>
                <div className={styles['actions-row']}>
                  <button
                    className="btn btn-primary"
                    onClick={() => void handleSaveParams()}
                    disabled={savingParams}
                  >
                    {savingParams ? '保存中...' : '保存参数'}
                  </button>
                  <button
                    className={`btn ${styles['btn-secondary'] || 'btn-secondary'}`}
                    onClick={() => void loadParamsConfig()}
                    disabled={savingParams}
                  >
                    重新加载参数
                  </button>
                </div>
              </div>

              <div className={styles['qr-login']}>
                <h4 className={styles['qr-login-title']}>扫码登录</h4>
                <p className={styles['qr-login-desc']}>点击获取二维码后，请用微信扫码并在手机上确认授权。</p>
                <div className={styles['actions-row']}>
                  <button
                    className={`btn btn-primary`}
                    onClick={() => void handleStartQrLogin()}
                    disabled={startingQrLogin}
                  >
                    {startingQrLogin ? '获取中...' : '获取登录二维码'}
                  </button>
                  <button
                    className={`btn ${styles['btn-secondary'] || 'btn-secondary'}`}
                    onClick={() => void handleCancelQrLogin()}
                    disabled={!qrSessionKey && !pollingQrLogin && !qrCodeUrl}
                  >
                    取消扫码登录
                  </button>
                </div>
                {qrCodeUrl && (
                  <div className={styles['qr-preview']}>
                    <img src={qrCodeUrl} alt="微信登录二维码" className={styles['qr-image']} />
                  </div>
                )}
                {qrImageLoadError && (
                  <p className={styles['qr-status']}>{qrImageLoadError}</p>
                )}
                {(qrStatusText || qrStatus !== 'idle') && (
                  <p className={styles['qr-status']}>
                    当前阶段：{qrState || 'pending'}；当前状态：{qrStatusText || qrStatus}
                    {qrStatusHint ? `（${qrStatusHint}）` : ''}
                  </p>
                )}
                {qrBindingResult && (
                  <p className={styles['qr-status']}>
                    绑定结果：{buildBindingResultText(qrBindingResult.userId, qrBindingResult.bindingStatus)}
                  </p>
                )}
                {qrState === 'success' && qrBindingResult && (
                  <p className={styles['qr-status']}>
                    {buildNextStepText(qrBindingResult.bindingStatus, qrBindingResult.userId)}
                  </p>
                )}
              </div>

              {weixinHealthResult && (
                <div className={`${styles['health-result']} ${weixinHealthResult.ok ? styles['success'] : styles['error']}`}>
                  <h4 className={`${styles['health-title']} ${weixinHealthResult.ok ? styles['success'] : styles['error']}`}>测试结果: {weixinHealthResult.ok ? '成功' : '失败'}</h4>
                  {weixinHealthResult.issues && weixinHealthResult.issues.length > 0 && (
                    <div className={styles['health-section']}>
                      <strong className={styles['health-strong']}>问题发现:</strong>
                      <ul className={styles['health-list']}>
                        {weixinHealthResult.issues.map((issue, i) => (
                          <li key={i} className={styles['health-issue']}>{issue}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                  {weixinHealthResult.suggestions && weixinHealthResult.suggestions.length > 0 && (
                    <div className={styles['health-section']}>
                      <strong className={styles['health-strong']}>建议修复:</strong>
                      <ul className={styles['health-list']}>
                        {weixinHealthResult.suggestions.map((suggestion, i) => (
                          <li key={i}>{suggestion}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                  {weixinHealthResult.ok && (!weixinHealthResult.issues || weixinHealthResult.issues.length === 0) && (
                    <p className={styles['health-ok']}>配置正常，微信适配器健康检查通过。</p>
                  )}
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  )
}
