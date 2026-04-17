import { Component, ErrorInfo, ReactNode } from 'react'

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
    // 记录错误信息到控制台，生产环境可替换为日志上报
    console.error('[ErrorBoundary] 捕获到未处理的渲染异常:', error, errorInfo)
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
            {this.state.error?.message || '未知错误'}
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
