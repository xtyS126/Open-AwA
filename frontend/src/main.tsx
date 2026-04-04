import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import './styles/global.css'
import { appLogger } from '@/shared/utils/logger'

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
