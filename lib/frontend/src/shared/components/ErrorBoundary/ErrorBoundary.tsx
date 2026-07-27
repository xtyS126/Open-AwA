import React, { Component, type ErrorInfo, type ReactNode } from 'react'
import { appLogger } from '@/shared/utils/logger'
import styles from './ErrorBoundary.module.css'

type ErrorBoundaryVariant = 'page' | 'compact'

interface Props {
  children: ReactNode
  /** 模块名，用于日志标识与错误展示 */
  name?: string
  /** 展示变体：page=页面级（默认，居中大卡片）；compact=子模块级（内联小条幅，不破坏布局） */
  variant?: ErrorBoundaryVariant
}

interface State {
  hasError: boolean
  error: Error | null
  errorInfo: ErrorInfo | null
  retryCount: number
  retryKey: number
}

const MAX_RETRY_COUNT = 3

class ErrorBoundary extends Component<Props, State> {
  state: State = {
    hasError: false,
    error: null,
    errorInfo: null,
    retryCount: 0,
    retryKey: 0,
  }

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { hasError: true, error }
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo): void {
    this.setState({ errorInfo })
    const moduleName = this.props.name || '应用'
    appLogger.error({
      event: 'frontend_render_error',
      module: moduleName,
      action: 'component_did_catch',
      status: 'failure',
      message: `前端渲染错误捕获于模块: ${moduleName}`,
      extra: {
        error: error.message,
        stack: error.stack || '',
        component_stack: errorInfo.componentStack,
      },
    })
  }

  handleRetry = (): void => {
    const { retryCount } = this.state
    const nextCount = retryCount + 1
    this.setState({
      hasError: false,
      error: null,
      errorInfo: null,
      retryCount: nextCount,
      retryKey: nextCount,
    })
  }

  handleReloadPage = (): void => {
    window.location.reload()
  }

  handleCopyError = async (): Promise<void> => {
    const { error, errorInfo } = this.state
    const details = [
      `模块: ${this.props.name || '未知'}`,
      `错误: ${error?.message || '未知'}`,
      `堆栈: ${error?.stack || '无'}`,
      `组件堆栈: ${errorInfo?.componentStack || '无'}`,
    ].join('\n\n')
    try {
      await navigator.clipboard.writeText(details)
    } catch {
      // fallback: 忽略复制失败
    }
  }

  render(): ReactNode {
    const { hasError, error, retryCount } = this.state
    const moduleName = this.props.name || '应用'
    const variant: ErrorBoundaryVariant = this.props.variant || 'page'

    if (hasError) {
      // 子模块紧凑变体：内联小条幅，避免破坏整体布局
      if (variant === 'compact') {
        return (
          <div className={styles.compactShell} role="alert" aria-live="assertive">
            <div className={styles.compactBody}>
              <span className={styles.compactTitle}>{moduleName} 渲染异常</span>
              <span className={styles.compactErrorText}>{error?.message || '未知错误'}</span>
            </div>
            <div className={styles.compactActions}>
              {retryCount < MAX_RETRY_COUNT ? (
                <button
                  type="button"
                  className={styles.compactBtn}
                  onClick={this.handleRetry}
                  aria-label={`重试 ${moduleName}`}
                >
                  重试（{retryCount}/{MAX_RETRY_COUNT}）
                </button>
              ) : (
                <button
                  type="button"
                  className={styles.compactBtn}
                  onClick={this.handleReloadPage}
                  aria-label="刷新页面"
                >
                  刷新页面
                </button>
              )}
              <button
                type="button"
                className={styles.compactBtnGhost}
                onClick={this.handleCopyError}
                aria-label="复制错误信息"
              >
                复制
              </button>
            </div>
          </div>
        )
      }

      if (retryCount >= MAX_RETRY_COUNT) {
        return (
          <div className={styles.shell}>
            <div className={styles.panel}>
              <h2 className={styles.title}>{moduleName} 发生了意外错误</h2>
              <p className={styles.description}>
                已尝试重试 {MAX_RETRY_COUNT} 次仍无法恢复，建议刷新页面。
              </p>
              <p className={styles.errorText}>{error?.message || '未知错误'}</p>
              <div className={styles.actions}>
                <button className={styles.btnPrimary} onClick={this.handleReloadPage}>
                  刷新页面
                </button>
                <button className={styles.btnSecondary} onClick={this.handleCopyError}>
                  复制错误信息
                </button>
              </div>
            </div>
          </div>
        )

      }

      return (
        <div className={styles.shell}>
          <div className={styles.panel}>
            <h2 className={styles.title}>{moduleName} 发生了意外错误</h2>
            <p className={styles.description}>
              详细信息已自动记录，您可以尝试重试恢复。
            </p>
            <p className={styles.errorText}>{error?.message || '未知错误'}</p>
            <div className={styles.actions}>
              <button className={styles.btnPrimary} onClick={this.handleRetry}>
                重试（{retryCount}/{MAX_RETRY_COUNT}）
              </button>
              <button className={styles.btnSecondary} onClick={this.handleCopyError}>
                复制错误信息
              </button>
            </div>
          </div>
        </div>
      )
    }

    return (
      <React.Fragment key={this.state.retryKey}>
        {this.props.children}
      </React.Fragment>
    )
  }
}

export default ErrorBoundary
