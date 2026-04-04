import { useCallback, useEffect, useMemo, useState } from 'react'
import { ExperienceFileDetail, ExperienceFileSummary, fileExperiencesApi } from '@/features/experiences/fileExperiencesApi'
import styles from './ExperiencePage.module.css'

interface ExperiencePageProps {
  hideHeader?: boolean
}

function ExperiencePage({ hideHeader = false }: ExperiencePageProps) {
  const [files, setFiles] = useState<ExperienceFileSummary[]>([])
  const [selectedFileName, setSelectedFileName] = useState<string>('')
  const [selectedFile, setSelectedFile] = useState<ExperienceFileDetail | null>(null)
  const [editorContent, setEditorContent] = useState('')

  const [loadingList, setLoadingList] = useState(false)
  const [loadingDetail, setLoadingDetail] = useState(false)
  const [saving, setSaving] = useState(false)

  const [listError, setListError] = useState<string | null>(null)
  const [detailError, setDetailError] = useState<string | null>(null)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [saveSuccess, setSaveSuccess] = useState<string | null>(null)

  const hasUnsavedChanges = useMemo(() => {
    if (!selectedFile) return false
    return editorContent !== selectedFile.content
  }, [editorContent, selectedFile])

  const loadFileDetail = useCallback(async (fileName: string) => {
    setLoadingDetail(true)
    setDetailError(null)
    setSaveError(null)
    setSaveSuccess(null)

    try {
      const response = await fileExperiencesApi.getFileDetail(fileName)
      setSelectedFile(response.data)
      setEditorContent(response.data.content)
      setSelectedFileName(fileName)
    } catch (error) {
      setDetailError(getErrorMessage(error, '加载文件内容失败，请稍后重试'))
      setSelectedFile(null)
      setEditorContent('')
    } finally {
      setLoadingDetail(false)
    }
  }, [])

  const loadFiles = useCallback(async () => {
    setLoadingList(true)
    setListError(null)

    try {
      const response = await fileExperiencesApi.listFiles()
      const fileList = response.data
      setFiles(fileList)

      if (fileList.length === 0) {
        setSelectedFileName('')
        setSelectedFile(null)
        setEditorContent('')
        return
      }

      const currentExists = fileList.some((item: ExperienceFileSummary) => item.file_name === selectedFileName)
      const targetFileName = currentExists ? selectedFileName : fileList[0].file_name
      await loadFileDetail(targetFileName)
    } catch (error) {
      setListError(getErrorMessage(error, '加载经验文件列表失败，请稍后重试'))
    } finally {
      setLoadingList(false)
    }
  }, [loadFileDetail, selectedFileName])

  useEffect(() => {
    loadFiles()
  }, [loadFiles])

  const handleSelectFile = async (fileName: string) => {
    if (fileName === selectedFileName) {
      return
    }
    await loadFileDetail(fileName)
  }

  const handleSave = async () => {
    if (!selectedFileName) {
      return
    }

    setSaving(true)
    setSaveError(null)
    setSaveSuccess(null)

    try {
      const response = await fileExperiencesApi.saveFile(selectedFileName, editorContent)
      setSaveSuccess('保存成功')

      if (selectedFile) {
        setSelectedFile({
          ...selectedFile,
          content: editorContent,
          updated_at: response.data.updated_at,
          size: response.data.size,
        })
      }

      setFiles((prev) =>
        prev.map((item) =>
          item.file_name === selectedFileName
            ? {
                ...item,
                updated_at: response.data.updated_at,
                size: response.data.size,
                summary: extractSummary(editorContent),
                title: extractTitle(editorContent, item.title),
              }
            : item,
        ),
      )
    } catch (error) {
      setSaveError(getErrorMessage(error, '保存失败，请稍后重试'))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className={styles['experience-page']}>
      {!hideHeader && (
        <div className={styles['page-header']}>
          <h1>经验文件</h1>
          <button className={styles['btn-secondary']} onClick={loadFiles} disabled={loadingList || loadingDetail || saving}>
            刷新列表
          </button>
        </div>
      )}

      {hideHeader && (
        <div className={styles['experience-toolbar']}>
          <button className={styles['btn-secondary']} onClick={loadFiles} disabled={loadingList || loadingDetail || saving}>
            刷新列表
          </button>
        </div>
      )}

      {listError && <div className={styles['error-message']}>{listError}</div>}

      {loadingList ? (
        <div className={styles['loading']}>正在加载经验文件列表...</div>
      ) : files.length === 0 ? (
        <div className={styles['empty-state']}>当前没有可用经验文件，请先通过提取流程生成 Markdown 文件。</div>
      ) : (
        <div className={styles['file-experience-layout']}>
          <aside className={styles['file-list-panel']}>
            {files.map((file) => (
              <button
                key={file.file_name}
                className={`${styles['file-item']} ${selectedFileName === file.file_name ? styles['active'] : ''}`}
                onClick={() => handleSelectFile(file.file_name)}
                disabled={loadingDetail || saving}
              >
                <div className={styles['file-item-title']}>{file.title || file.file_name}</div>
                <div className={styles['file-item-meta']}>
                  <span>{formatDate(file.updated_at)}</span>
                  <span>{formatFileSize(file.size)}</span>
                </div>
                {file.summary && <div className={styles['file-item-summary']}>{file.summary}</div>}
              </button>
            ))}
          </aside>

          <section className={styles['file-editor-panel']}>
            {loadingDetail ? (
              <div className={styles['loading']}>正在加载文件内容...</div>
            ) : !selectedFile ? (
              <div className={styles['empty-state']}>请选择左侧文件查看内容。</div>
            ) : (
              <>
                <div className={styles['editor-header']}>
                  <div>
                    <h3>{selectedFile.title || selectedFile.file_name}</h3>
                    <div className={styles['editor-meta']}>
                      最近更新：{formatDate(selectedFile.updated_at)} · 大小：{formatFileSize(selectedFile.size)}
                    </div>
                  </div>
                  <button className={styles['btn-primary']} onClick={handleSave} disabled={!hasUnsavedChanges || saving}>
                    {saving ? styles['保存中...'] : styles['保存']}
                  </button>
                </div>

                {detailError && <div className={styles['error-message']}>{detailError}</div>}
                {saveError && <div className={styles['error-message']}>{saveError}</div>}
                {saveSuccess && <div className={styles['success-message']}>{saveSuccess}</div>}

                <textarea
                  className={styles['file-editor']}
                  value={editorContent}
                  onChange={(e) => {
                    setEditorContent(e.target.value)
                    setSaveSuccess(null)
                    setSaveError(null)
                  }}
                  spellCheck={false}
                />
              </>
            )}
          </section>
        </div>
      )}
    </div>
  )
}

function formatDate(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return value
  }
  return date.toLocaleString('zh-CN', { hour12: false })
}

function formatFileSize(size: number): string {
  if (size < 1024) {
    return `${size} B`
  }
  if (size < 1024 * 1024) {
    return `${(size / 1024).toFixed(1)} KB`
  }
  return `${(size / (1024 * 1024)).toFixed(1)} MB`
}

function getErrorMessage(error: unknown, fallback: string): string {
  if (typeof error === 'object' && error !== null) {
    const responseData = (error as { response?: { data?: { detail?: string } } }).response?.data
    if (responseData?.detail && typeof responseData.detail === 'string') {
      return responseData.detail
    }

    const message = (error as { message?: string }).message
    if (message) {
      return message
    }
  }

  return fallback
}

function extractSummary(content: string): string {
  const lines = content.split('\n')
  for (const line of lines) {
    const text = line.trim()
    if (!text || text.startsWith('#')) {
      continue
    }
    return text.slice(0, 160)
  }
  return ''
}

function extractTitle(content: string, fallback: string): string {
  const lines = content.split('\n')
  for (const line of lines) {
    const text = line.trim()
    if (!text.startsWith('#')) {
      continue
    }
    const title = text.replace(/^#+/, '').trim()
    if (title) {
      return title
    }
  }
  return fallback
}

export default ExperiencePage
