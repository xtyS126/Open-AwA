/* 助手消息 Markdown/数学公式渲染组件 */
import { lazy, memo, Suspense, useMemo } from 'react'
import { parseStream } from '../utils/streamParser'
import { ThinkingProcess } from './ThinkingProcess'
import { FileReference } from './FileReference'
import { TaskTracker } from './TaskTracker'
import { TaskStep } from './TaskStep'
import styles from './MessageContent.module.css'

const AssistantMarkdownContent = lazy(() => import('./AssistantMarkdownContent'))

interface MessageContentProps {
  content: string
  role: 'user' | 'assistant'
  isStreaming?: boolean
}

/**
 * 消息内容渲染组件
 * - 用户消息：纯文本渲染
 * - 助手消息：解析思考过程、文件引用、任务追踪，并渲染 Markdown
 */
function MessageContentInner({ content, role, isStreaming }: MessageContentProps) {
  const parsedState = useMemo(() => {
    if (role === 'user') return null
    return parseStream(content)
  }, [content, role])

  // 用户消息保持纯文本渲染
  if (role === 'user') {
    return <span style={{ whiteSpace: 'pre-wrap' }}>{content}</span>
  }

  if (!parsedState) return null

  const hasMeta = parsedState.thinkingContent || parsedState.fileReferences.length > 0 || parsedState.tasks.length > 0 || parsedState.isThinking

  return (
    <div className={styles.messageContainer}>
      {hasMeta && (
        <ThinkingProcess
          isThinking={isStreaming && parsedState.isThinking}
          defaultExpanded={isStreaming}
        >
          {parsedState.thinkingContent && (
            <div className={styles.thinkingText}>
              {parsedState.thinkingContent}
            </div>
          )}
          
          {parsedState.fileReferences.length > 0 && (
            <div className={styles.fileReferences}>
              <div className={styles.metaTitle}>引用的文件</div>
              <div className={styles.fileList}>
                {parsedState.fileReferences.map((file, index) => (
                  <FileReference
                    key={`${file.path}-${index}`}
                    fileName={file.name}
                    filePath={file.path}
                  />
                ))}
              </div>
            </div>
          )}

          {parsedState.tasks.length > 0 && (
            <div className={styles.taskTrackerWrapper}>
              <TaskTracker title="执行步骤">
                {parsedState.tasks.map(task => (
                  <TaskStep
                    key={task.id}
                    title={task.title}
                    status={task.status}
                  />
                ))}
              </TaskTracker>
            </div>
          )}
        </ThinkingProcess>
      )}

      {parsedState.finalContent && (
        <Suspense fallback={<div className={styles['markdown-body']}><span style={{ whiteSpace: 'pre-wrap' }}>{parsedState.finalContent}</span></div>}>
          <AssistantMarkdownContent content={parsedState.finalContent} />
        </Suspense>
      )}
      
      {/* 底部思考中动画指示器 */}
      {isStreaming && parsedState.isThinking && !parsedState.finalContent && (
        <div className={styles.streamingIndicator}>
          <span className={styles.dot}></span>
          <span className={styles.dot}></span>
          <span className={styles.dot}></span>
        </div>
      )}
    </div>
  )
}

export const MessageContent = memo(MessageContentInner)
