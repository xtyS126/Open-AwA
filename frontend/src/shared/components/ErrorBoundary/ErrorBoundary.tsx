import { Component, ErrorInfo, ReactNode } from 'react'
import { appLogger } from '@/shared/utils/logger'

interface Props {
  children: ReactNode
}

interface State {
  hasError: boolean
  error: Error | null
}

/**
 * 全局错误边界组件，捕获子组件树中未处理的渲染异常，防止整个应用白屏崩溃。
 */
class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props)
    this.state = { hasError: false, error: null }
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error }
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    appLogger.error({
      event: 'frontend_render_error',
      module: 'error-boundary',
      action: 'component_did_catch',
      status: 'failure',
      message: 'frontend render error captured',
      extra: {
        error: error.message,
        stack: error.stack || '',
        component_stack: errorInfo.componentStack,
      },
    })
  }

  handleReload = () => {
    this.setState({ hasError: false, error: null })
    window.location.reload()
  }

  render() {
    if (this.state.hasError) {
      return (
        <div style={{
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'center',
          alignItems: 'center',
          height: '100vh',
          padding: '24px',
          textAlign: 'center',
          color: 'var(--color-text-secondary, #666)',
          fontFamily: 'system-ui, sans-serif',
        }}>
          <h2 style={{ color: 'var(--color-text-primary, #333)', marginBottom: '12px' }}>
            应用发生了意外错误
          </h2>
          <p style={{ maxWidth: '480px', lineHeight: 1.6, marginBottom: '20px' }}>
            页面遇到了未处理异常。详细信息已记录，建议重新加载后重试。
          </p>
          <button
            onClick={this.handleReload}
            style={{
              padding: '10px 24px',
              fontSize: '14px',
              borderRadius: '6px',
              border: 'none',
              backgroundColor: 'var(--color-primary, #4f46e5)',
              color: '#fff',
              cursor: 'pointer',
            }}
          >
            重新加载
          </button>
        </div>
      )
    }

    return this.props.children
  }
}

export default ErrorBoundary
