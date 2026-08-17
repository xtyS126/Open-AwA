/**
 * 经验文件页面 — 列表/编辑/保存经验 Markdown 文件。
 *
 * 改造说明（fix-performance-remaining-issues-v2 模块 C2）：
 *   - 原实现使用 useCallback + useEffect，每次 mount 都触发 /api/experience-files 请求
 *   - 现改用 useQuery + queryClient.invalidateQueries，多页面切换时复用缓存
 *   - queryKey 约定：
 *     - ['experience', 'files']：文件列表
 *     - ['experience', 'files', selectedFileName]：单文件详情，selectedFileName 为空时禁用
 *   - 保存成功后失效详情缓存以触发刷新
 */
import { useEffect, useMemo, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ExperienceFileDetail, ExperienceFileSummary, fileExperiencesApi } from '@/features/experiences/fileExperiencesApi'
import { getErrorMessage } from '@/shared/utils/errorMessages'
import styles from './ExperiencePage.module.css'

interface ExperiencePageProps {
  hideHeader?: boolean
}

function ExperiencePage({ hideHeader = false }: ExperiencePageProps) {
  const queryClient = useQueryClient()
  const [selectedFileName, setSelectedFileName] = useState<string>('')
  const [editorContent, setEditorContent] = useState('')

  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [saveSuccess, setSaveSuccess] = useState<string | null>(null)

  // 文件列表查询：useQuery 自动管理缓存与重试，staleTime=60s 内切换页面不重复请求
  const {
    data: filesResponse,
    isLoading: loadingList,
    error: listErrorObj,
  } = useQuery({
    queryKey: ['experience', 'files'],
    queryFn: () => fileExperiencesApi.listFiles(),
  })
  const files: ExperienceFileSummary[] = useMemo(() => filesResponse?.data || [], [filesResponse])
  const listError = listErrorObj ? getErrorMessage(listErrorObj, '加载经验文件列表失败，请稍后重试') : null

  // 文件详情查询：依赖 selectedFileName，为空时禁用
  const {
    data: detailResponse,
    isLoading: loadingDetail,
    error: detailErrorObj,
  } = useQuery({
    queryKey: ['experience', 'files', selectedFileName],
    queryFn: () => fileExperiencesApi.getFileDetail(selectedFileName),
    enabled: !!selectedFileName,
  })
  const selectedFile: ExperienceFileDetail | null = detailResponse?.data ?? null
  const detailError = detailErrorObj ? getErrorMessage(detailErrorObj, '加载文件内容失败，请稍后重试') : null

  // 首次加载列表时自动选中第一个文件
  useEffect(() => {
    if (files.length === 0) {
      if (selectedFileName !== '') {
        setSelectedFileName('')
      }
      return
    }
    const currentExists = files.some((item) => item.file_name === selectedFileName)
    if (!currentExists) {
      setSelectedFileName(files[0].file_name)
    }
  }, [files, selectedFileName])

  // 详情加载完成后同步编辑器内容与保存状态
  useEffect(() => {
    if (selectedFile) {
      setEditorContent(selectedFile.content)
      setSaveError(null)
      setSaveSuccess(null)
    } else if (!selectedFileName) {
      setEditorContent('')
    }
  }, [selectedFile, selectedFileName])

  const hasUnsavedChanges = useMemo(() => {
    if (!selectedFile) return false
    return editorContent !== selectedFile.content
  }, [editorContent, selectedFile])

  const handleSelectFile = (fileName: string) => {
    if (fileName === selectedFileName) {
      return
    }
    setSelectedFileName(fileName)
  }

  const handleRefreshList = () => {
    queryClient.invalidateQueries({ queryKey: ['experience', 'files'] })
  }

  const handleSave = async () => {
    if (!selectedFileName) {
      return
    }

    setSaving(true)
    setSaveError(null)
    setSaveSuccess(null)

    try {
      await fileExperiencesApi.saveFile(selectedFileName, editorContent)
      setSaveSuccess('保存成功')
      // 失效详情与列表缓存以触发刷新，获取最新 content / updated_at / size / summary / title
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['experience', 'files', selectedFileName] }),
        queryClient.invalidateQueries({ queryKey: ['experience', 'files'] }),
      ])
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
          <button className={styles['btn-secondary']} onClick={handleRefreshList} disabled={loadingList || loadingDetail || saving}>
            刷新列表
          </button>
        </div>
      )}

      {hideHeader && (
        <div className={styles['experience-toolbar']}>
          <button className={styles['btn-secondary']} onClick={handleRefreshList} disabled={loadingList || loadingDetail || saving}>
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
                    {saving ? '保存中...' : '保存'}
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

export default ExperiencePage
