import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import './styles/global.css'
import { appLogger } from '@/shared/utils/logger'
import { mark } from '@/shared/perf/metrics'

// P2: Web Vitals 性能指标采集
import { onLCP, onCLS, onINP, onTTFB } from 'web-vitals'

function reportWebVital(metric: { name: string; value: number; rating: string }) {
  const rating = metric.rating
  appLogger.info({
    event: 'web_vital',
    module: 'perf',
    action: metric.name.toLowerCase(),
    status: rating === 'good' ? 'success' : 'warning',
    message: `${metric.name}: ${metric.value.toFixed(1)} (${rating})`,
    extra: { name: metric.name, value: Math.round(metric.value), rating },
  })
}

onLCP(reportWebVital)
onCLS(reportWebVital)
onINP(reportWebVital)
onTTFB((m) => {
  reportWebVital(m)
  mark('ttfb') // TTFB 是后端+TLS 耗时，单独记录
})

window.addEventListener('error', (event) => {
  appLogger.error({
    event: 'frontend_runtime_error',
    module: 'main',
    action: 'window_error',
    status: 'failure',
    message: 'frontend runtime error',
    extra: {
      source: event.filename,
      line: event.lineno,
      column: event.colno,
      error: event.error?.message || event.message,
    },
  })
})

window.addEventListener('unhandledrejection', (event) => {
  appLogger.error({
    event: 'frontend_runtime_error',
    module: 'main',
    action: 'promise_rejection',
    status: 'failure',
    message: 'unhandled promise rejection',
    extra: {
      reason: event.reason instanceof Error ? event.reason.message : String(event.reason),
    },
  })
})

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
