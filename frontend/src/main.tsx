import React from 'react'
import ReactDOM from 'react-dom/client'
import { QueryClientProvider } from '@tanstack/react-query'
import App from './App'
import './styles/tokens.css'
import './styles/global.css'
import { appLogger } from '@/shared/utils/logger'
import { disableExternalFontsInNativeApp } from '@/shared/utils/platform'
import { mark } from '@/shared/perf/metrics'
import { queryClient } from '@/shared/api/queryClient'

// APP 模式（Capacitor 原生容器）下移除 Google Fonts 外部引用：
// 消除首屏外部网络依赖，字体回退到系统字体栈
disableExternalFontsInNativeApp()

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

const handleWindowError = (event: ErrorEvent) => {
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
}

const handleUnhandledRejection = (event: PromiseRejectionEvent) => {
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
}

window.addEventListener('error', handleWindowError)
window.addEventListener('unhandledrejection', handleUnhandledRejection)

if (import.meta.hot) {
  import.meta.hot.dispose(() => {
    window.removeEventListener('error', handleWindowError)
    window.removeEventListener('unhandledrejection', handleUnhandledRejection)
  })
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </React.StrictMode>,
)
