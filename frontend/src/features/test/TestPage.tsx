import { useState, useEffect, useCallback, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Activity, ShieldCheck, ShieldX, Server, Globe,
  RefreshCw, CheckCircle2, XCircle, AlertTriangle,
  Play, ListChecks, FlaskConical,
} from 'lucide-react'
import { systemAPI, chatAPI, conversationAPI, testRunnerAPI } from '@/shared/api/api'
import type { SysDiagnosticsResponse } from '@/shared/api/api'
import type { ScenarioRunResponse, ScenarioDef } from '@/shared/api/api'
import { appLogger } from '@/shared/utils/logger'
import styles from './TestPage.module.css'

interface FeatureTest {
  name: string
  label: string
  category: 'backend' | 'frontend'
  status: 'idle' | 'running' | 'ok' | 'fail'
  message: string
  detail: Record<string, unknown> | null
}

interface ScenarioTest extends ScenarioDef {
  status: 'idle' | 'running' | 'ok' | 'fail'
  message: string
  detail: Record<string, unknown> | null
}

function getStatusIcon(status: FeatureTest['status'] | ScenarioTest['status']) {
  switch (status) {
    case 'ok': return <CheckCircle2 size={18} className={styles['icon-ok']} />
    case 'fail': return <XCircle size={18} className={styles['icon-fail']} />
    case 'running': return <RefreshCw size={18} className={styles['icon-running']} />
    default: return <span className={styles['dot-idle']} />
  }
}

function getCategoryIcon(category: string) {
  return category === '前端功能' ? <Globe size={14} /> : <Server size={14} />
}

export default function TestPage() {
  const navigate = useNavigate()
  const [tests, setTests] = useState<FeatureTest[]>([
    { name: 'server-ping', label: '服务器连通性', category: 'backend', status: 'idle', message: '待检测', detail: null },
    { name: 'database', label: '数据库连接', category: 'backend', status: 'idle', message: '待检测', detail: null },
    { name: 'plugins', label: '插件系统', category: 'backend', status: 'idle', message: '待检测', detail: null },
    { name: 'skills', label: '技能系统', category: 'backend', status: 'idle', message: '待检测', detail: null },
    { name: 'mcp', label: 'MCP服务', category: 'backend', status: 'idle', message: '待检测', detail: null },
    { name: 'chat-api', label: '聊天API', category: 'backend', status: 'idle', message: '待检测', detail: null },
    { name: 'conversation-api', label: '对话管理API', category: 'backend', status: 'idle', message: '待检测', detail: null },
    { name: 'page-render', label: '页面渲染', category: 'frontend', status: 'idle', message: '待检测', detail: null },
    { name: 'navigation', label: '路由导航', category: 'frontend', status: 'idle', message: '待检测', detail: null },
  ])
  const [scenarios, setScenarios] = useState<ScenarioTest[]>([])
  const [scenariosLoaded, setScenariosLoaded] = useState(false)
  const [running, setRunning] = useState(false)
  const [scenariosRunning, setScenariosRunning] = useState(false)
  const [overall, setOverall] = useState<'idle' | 'healthy' | 'degraded' | 'error'>('idle')
  const [, setScenarioOverall] = useState<'idle' | 'healthy' | 'degraded'>('idle')
  const overallRef = useRef(overall)
  useEffect(() => {
    overallRef.current = overall
  }, [overall])
  const [lastRun, setLastRun] = useState<string | null>(null)

  const updateTest = useCallback((name: string, update: Partial<FeatureTest>) => {
    setTests((prev) => prev.map((t) => (t.name === name ? { ...t, ...update } : t)))
  }, [])

  const setAllTests = useCallback((updater: (t: FeatureTest) => Partial<FeatureTest>) => {
    setTests((prev) => prev.map((t) => ({ ...t, ...updater(t) })))
  }, [])

  // [NEW] 加载可用场景列表
  useEffect(() => {
    testRunnerAPI.listScenarios().then((res) => {
      const items: ScenarioTest[] = (res.data.scenarios || []).map((s: ScenarioDef) => ({
        ...s,
        status: 'idle' as const,
        message: '待运行',
        detail: null,
      }))
      setScenarios(items)
      setScenariosLoaded(true)
    }).catch(() => {
      setScenariosLoaded(true)
    })
  }, [])

  // [NEW] 运行所有场景
  const runAllScenarios = useCallback(async () => {
    setScenariosRunning(true)
    setScenarios((prev) => prev.map((s) => ({ ...s, status: 'idle' as const, message: '等待执行...', detail: null })))

    try {
      const res = await testRunnerAPI.runAllScenarios()
      const data = res.data as ScenarioRunResponse
      const resultMap = new Map(data.results.map((r) => [r.name, r]))
      setScenarios((prev) =>
        prev.map((s) => {
          const r = resultMap.get(s.name)
          if (r) {
            return {
              ...s,
              status: r.status as 'ok' | 'fail',
              message: r.message,
              detail: r.detail,
            }
          }
          return { ...s, status: 'fail' as const, message: '未返回结果', detail: null }
        })
      )
      setScenarioOverall(data.passed === data.total ? 'healthy' : 'degraded')
    } catch {
      setScenarios((prev) => prev.map((s) => ({ ...s, status: 'fail' as const, message: '场景运行请求失败', detail: null })))
      setScenarioOverall('degraded')
    }

    setScenariosRunning(false)
    appLogger.info({
      event: 'test_scenarios_run_all',
      module: 'test_page',
      action: 'run_scenarios',
      status: 'success',
      message: 'all scenarios completed',
    })
  }, [])

  // [NEW] 运行单个场景
  const runScenario = useCallback(async (name: string) => {
    setScenarios((prev) =>
      prev.map((s) => (s.name === name ? { ...s, status: 'running' as const, message: '执行中...', detail: null } : s))
    )

    try {
      const res = await testRunnerAPI.runScenario(name)
      const data = res.data as ScenarioRunResponse
      const result = data.results[0]
      if (result) {
        setScenarios((prev) =>
          prev.map((s) =>
            s.name === name
              ? { ...s, status: result.status as 'ok' | 'fail', message: result.message, detail: result.detail }
              : s
          )
        )
      }
    } catch {
      setScenarios((prev) =>
        prev.map((s) => (s.name === name ? { ...s, status: 'fail' as const, message: '请求失败', detail: null } : s))
      )
    }
  }, [])

  const runDiagnostics = useCallback(async () => {
    setRunning(true)
    setAllTests((t) => (t.status === 'ok' ? { status: 'idle', message: '检测中...' } : { status: t.status === 'idle' ? 'idle' : t.status }))
    setAllTests(() => ({ status: 'idle', message: '检测中...' }))

    // [NEW] 前端测试：页面渲染
    updateTest('page-render', { status: 'ok', message: '组件正常挂载并渲染', detail: { timestamp: Date.now() } })

    // [NEW] 前端测试：路由导航
    try {
      const currentPath = window.location.pathname
      updateTest('navigation', { status: 'ok', message: `当前路由: ${currentPath}`, detail: { path: currentPath } })
    } catch {
      updateTest('navigation', { status: 'fail', message: '路由信息获取失败', detail: null })
    }

    // [NEW] 后端诊断
    try {
      const diagRes = await systemAPI.diagnostics()
      const diagData = diagRes.data as SysDiagnosticsResponse

      for (const check of diagData.checks) {
        const testName = check.name === 'server' ? 'server-ping' : check.name
        updateTest(testName, {
          status: check.ok ? 'ok' : 'fail',
          message: check.ok ? `${check.label}正常` : `${check.label}异常`,
          detail: check.detail,
        })
      }

      if (diagData.overall === 'healthy') {
        setOverall('healthy')
      } else {
        setOverall('degraded')
      }
    } catch {
      updateTest('server-ping', { status: 'fail', message: '后端诊断接口不可达', detail: null })
      setAllTests((t) =>
        t.name.startsWith('server') || ['database', 'plugins', 'skills', 'mcp'].includes(t.name)
          ? { status: 'fail', message: '后端不可达', detail: null }
          : {}
      )
      setOverall('error')
    }

    // [NEW] 聊天API检测
    try {
      const chatRes = await chatAPI.getHistory('test-probe-session')
      if (chatRes.status === 200 || chatRes.status === 404) {
        updateTest('chat-api', { status: 'ok', message: '聊天API响应正常', detail: { status_code: chatRes.status } })
      } else {
        updateTest('chat-api', { status: 'fail', message: `聊天API异常状态码: ${chatRes.status}`, detail: null })
      }
    } catch (err: unknown) {
      const statusCode = (err as { response?: { status?: number } })?.response?.status
      if (statusCode === 404) {
        updateTest('chat-api', { status: 'ok', message: '聊天API响应正常(404 预期)', detail: { status_code: 404 } })
      } else {
        updateTest('chat-api', { status: 'fail', message: `聊天API检测失败: ${(err as Error)?.message || String(err)}`, detail: null })
      }
    }

    // [NEW] 对话管理API检测
    try {
      const convRes = await conversationAPI.listSessions({ page: 1, page_size: 1 })
      updateTest('conversation-api', { status: 'ok', message: '对话管理API响应正常', detail: { total: convRes.data?.total } })
    } catch (err: unknown) {
      updateTest('conversation-api', { status: 'fail', message: `对话管理API检测失败: ${(err as Error)?.message || String(err)}`, detail: null })
    }

    setRunning(false)
    setLastRun(new Date().toLocaleString('zh-CN'))
    appLogger.info({
      event: 'test_diagnostics_run',
      module: 'test_page',
      action: 'diagnostics',
      status: 'success',
      message: 'test diagnostics completed',
      extra: { overall: overallRef.current },
    })
  }, [updateTest, setAllTests])

  useEffect(() => {
    runDiagnostics()
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const passedCount = tests.filter((t) => t.status === 'ok').length
  const failedCount = tests.filter((t) => t.status === 'fail').length
  const runningCount = tests.filter((t) => t.status === 'running').length
  const scenarioPassed = scenarios.filter((s) => s.status === 'ok').length
  const scenarioFailed = scenarios.filter((s) => s.status === 'fail').length

  return (
    <div className={styles['test-page']}>
      <div className={styles['test-header']}>
        <div className={styles['test-header-left']}>
          <Activity size={22} />
          <h1>系统功能检测面板</h1>
        </div>
        <div className={styles['test-header-right']}>
          {lastRun && <span className={styles['last-run']}>上次检测: {lastRun}</span>}
          <button
            className={styles['btn-refresh']}
            onClick={runDiagnostics}
            disabled={running}
            title="重新检测"
          >
            <RefreshCw size={16} className={running ? styles['spin'] : ''} />
            {running ? '检测中...' : '重新检测'}
          </button>
          <button
            className={styles['btn-back']}
            onClick={() => navigate('/chat')}
            title="返回AI聊天"
          >
            返回聊天
          </button>
        </div>
      </div>

      <div className={styles['test-summary']}>
        <div className={styles['summary-card']}>
          <span className={styles['summary-label']}>总体状态</span>
          {overall === 'healthy' && <span className={styles['badge-ok']}><ShieldCheck size={16} /> 一切正常</span>}
          {overall === 'degraded' && <span className={styles['badge-warn']}><AlertTriangle size={16} /> 部分异常</span>}
          {overall === 'error' && <span className={styles['badge-fail']}><ShieldX size={16} /> 严重故障</span>}
          {overall === 'idle' && <span className={styles['badge-idle']}>等待检测</span>}
        </div>
        <div className={styles['summary-card']}>
          <span className={styles['summary-label']}>基础检测</span>
          <span className={styles['summary-counts']}>
            <span className={styles['count-ok']}>{passedCount} 通过</span>
            {failedCount > 0 && <span className={styles['count-fail']}>{failedCount} 失败</span>}
            {runningCount > 0 && <span className={styles['count-running']}>{runningCount} 检测中</span>}
            <span className={styles['count-total']}>/ {tests.length} 项</span>
          </span>
        </div>
        {scenarios.length > 0 && (
          <div className={styles['summary-card']}>
            <span className={styles['summary-label']}>场景测试</span>
            <span className={styles['summary-counts']}>
              <span className={styles['count-ok']}>{scenarioPassed} 通过</span>
              {scenarioFailed > 0 && <span className={styles['count-fail']}>{scenarioFailed} 失败</span>}
              <span className={styles['count-total']}>/ {scenarios.length} 项</span>
            </span>
          </div>
        )}
      </div>

      <div className={styles['test-grid']}>
        <div className={styles['test-section']}>
          <div className={styles['section-header']}>
            <Server size={16} />
            <span>后端服务</span>
          </div>
          <div className={styles['test-list']}>
            {tests.filter((t) => t.category === 'backend').map((test) => (
              <div key={test.name} className={`${styles['test-item']} ${styles[`status-${test.status}`]}`}>
                <div className={styles['test-item-left']}>
                  {getStatusIcon(test.status)}
                  <div className={styles['test-item-info']}>
                    <span className={styles['test-item-label']}>{test.label}</span>
                    <span className={styles['test-item-msg']}>{test.message}</span>
                  </div>
                </div>
                <div className={styles['test-item-right']}>
                  {getCategoryIcon(test.category)}
                  <span className={styles['test-item-name']}>{test.name}</span>
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className={styles['test-section']}>
          <div className={styles['section-header']}>
            <Globe size={16} />
            <span>前端功能</span>
          </div>
          <div className={styles['test-list']}>
            {tests.filter((t) => t.category === 'frontend').map((test) => (
              <div key={test.name} className={`${styles['test-item']} ${styles[`status-${test.status}`]}`}>
                <div className={styles['test-item-left']}>
                  {getStatusIcon(test.status)}
                  <div className={styles['test-item-info']}>
                    <span className={styles['test-item-label']}>{test.label}</span>
                    <span className={styles['test-item-msg']}>{test.message}</span>
                  </div>
                </div>
                <div className={styles['test-item-right']}>
                  {getCategoryIcon(test.category)}
                  <span className={styles['test-item-name']}>{test.name}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* [NEW] 真实场景测试区域 */}
      <div className={styles['scenario-section']}>
        <div className={styles['scenario-header']}>
          <div className={styles['scenario-header-left']}>
            <FlaskConical size={18} />
            <h2>真实场景测试</h2>
            <span className={styles['scenario-desc']}>通过API运行端到端功能场景，验证各子系统在真实调用链路中的表现</span>
          </div>
          <button
            className={styles['btn-run-all']}
            onClick={runAllScenarios}
            disabled={scenariosRunning || !scenariosLoaded}
            title="运行所有场景"
          >
            <Play size={14} />
            {scenariosRunning ? '执行中...' : '运行全部场景'}
          </button>
        </div>
        <div className={styles['scenario-grid']}>
          {scenarios.map((scenario) => (
            <div
              key={scenario.name}
              className={`${styles['scenario-card']} ${styles[`scenario-${scenario.status}`]}`}
            >
              <div className={styles['scenario-card-top']}>
                <span className={styles['scenario-category']}>
                  <ListChecks size={12} />
                  {scenario.category}
                </span>
                {getStatusIcon(scenario.status)}
              </div>
              <div className={styles['scenario-card-body']}>
                <span className={styles['scenario-label']}>{scenario.label}</span>
                <span className={styles['scenario-name']}>{scenario.name}</span>
                <p className={styles['scenario-desc-text']}>{scenario.description}</p>
                {scenario.message && scenario.status !== 'idle' && (
                  <span className={`${styles['scenario-msg']} ${styles[`msg-${scenario.status}`]}`}>
                    {scenario.message}
                  </span>
                )}
              </div>
              <div className={styles['scenario-card-actions']}>
                <button
                  className={styles['btn-run-one']}
                  onClick={() => runScenario(scenario.name)}
                  disabled={scenario.status === 'running' || scenariosRunning}
                >
                  <Play size={12} />
                  {scenario.status === 'running' ? '执行中...' : '运行'}
                </button>
                {scenario.detail && (
                  <details className={styles['scenario-detail']}>
                    <summary>详情</summary>
                    <pre>{JSON.stringify(scenario.detail, null, 2)}</pre>
                  </details>
                )}
              </div>
            </div>
          ))}
          {!scenariosLoaded && (
            <div className={styles['scenario-loading']}>
              <RefreshCw size={20} className={styles['spin']} />
              <span>加载场景列表...</span>
            </div>
          )}
          {scenariosLoaded && scenarios.length === 0 && (
            <div className={styles['scenario-empty']}>
              <span>暂无可用的测试场景</span>
            </div>
          )}
        </div>
      </div>

      <div className={styles['test-footer']}>
        <span>检测项说明：基础检测验证子系统连通性，场景测试验证真实API调用链路。检测结果仅反映当前时刻状态。</span>
      </div>
    </div>
  )
}
