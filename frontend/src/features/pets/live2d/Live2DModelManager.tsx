/**
 * Live2DModelManager —— Live2D 模型管理页面。
 *
 * 功能：
 *   - 上传 Live2D 模型 zip 包（调用 POST /api/pets/live2d/upload）
 *   - 模型列表展示（调用 GET /api/pets/live2d/models）
 *   - 每个模型卡片：名称、文件数、预览按钮、删除按钮
 *   - 点击预览在新弹窗中展示 Live2DViewer，支持表情切换和口型同步测试
 */
import { useEffect, useCallback, useState, useRef, type ChangeEvent } from 'react'
import {
  Upload,
  Trash2,
  Eye,
  X,
  Loader2,
  AlertCircle,
  FileArchive,
  Smile,
  Frown,
  AlertTriangle,
  Flame,
  Meh,
} from 'lucide-react'
import Live2DViewer from './Live2DViewer'
import type { Live2DViewerHandle } from './Live2DViewer'
import {
  listLive2DModels,
  uploadLive2DModel,
  deleteLive2DModel,
} from '@/shared/api/live2dApi'
import type { Live2DModelResponse } from '@/shared/api/live2dApi'
import { getErrorMessage } from '@/shared/utils/errorMessages'
import styles from './Live2DModelManager.module.css'

/** 表情配置：名称 -> 图标 */
const EXPRESSION_OPTIONS = [
  { id: 'neutral', label: '中性', Icon: Meh },
  { id: 'happy', label: '开心', Icon: Smile },
  { id: 'sad', label: '难过', Icon: Frown },
  { id: 'surprised', label: '惊讶', Icon: AlertTriangle },
  { id: 'angry', label: '生气', Icon: Flame },
] as const

export default function Live2DModelManager() {
  const [models, setModels] = useState<Live2DModelResponse[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [pendingId, setPendingId] = useState<string | null>(null)

  // 上传模态框
  const [uploadOpen, setUploadOpen] = useState(false)
  const [archiveFile, setArchiveFile] = useState<File | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [uploadError, setUploadError] = useState<string | null>(null)

  // 预览模态框
  const [previewModel, setPreviewModel] = useState<Live2DModelResponse | null>(null)
  const [previewExpression, setPreviewExpression] = useState('neutral')
  const [previewLipSync, setPreviewLipSync] = useState(0)
  const viewerRef = useRef<Live2DViewerHandle>(null)

  // 加载模型列表
  const loadModels = useCallback(async () => {
    setLoading(true)
    setLoadError(null)
    try {
      const result = await listLive2DModels()
      setModels(result.models)
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : '加载模型列表失败')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void loadModels()
  }, [loadModels])

  // 上传模型
  const handleUpload = useCallback(async () => {
    if (!archiveFile) return
    setUploadError(null)
    setSubmitting(true)
    try {
      const formData = new FormData()
      formData.append('archive', archiveFile)
      await uploadLive2DModel(formData)
      setUploadOpen(false)
      setArchiveFile(null)
      await loadModels()
    } catch (err) {
      setUploadError(getErrorMessage(err, '上传失败，请检查 zip 包内容'))
    } finally {
      setSubmitting(false)
    }
  }, [archiveFile, loadModels])

  // 删除模型
  const handleDelete = useCallback(
    async (model: Live2DModelResponse) => {
      if (!window.confirm(`确定删除模型 ${model.model_name}？`)) return
      setPendingId(model.id)
      try {
        await deleteLive2DModel(model.id)
        setModels((prev) => prev.filter((m) => m.id !== model.id))
      } catch (err) {
        setLoadError(err instanceof Error ? err.message : '删除失败')
      } finally {
        setPendingId(null)
      }
    },
    [],
  )

  // 打开预览
  const handlePreview = useCallback((model: Live2DModelResponse) => {
    setPreviewModel(model)
    setPreviewExpression('neutral')
    setPreviewLipSync(0)
  }, [])

  // 切换表情
  const handleExpressionChange = useCallback(
    (expressionId: string) => {
      setPreviewExpression(expressionId)
      viewerRef.current?.setExpression(expressionId)
    },
    [],
  )

  // 口型同步变化
  const handleLipSyncChange = useCallback((e: ChangeEvent<HTMLInputElement>) => {
    const value = parseFloat(e.target.value)
    setPreviewLipSync(value)
    viewerRef.current?.setLipSync(value)
  }, [])

  const onPickArchive = (e: ChangeEvent<HTMLInputElement>) => {
    setUploadError(null)
    setArchiveFile(e.target.files?.[0] ?? null)
  }

  return (
    <div className={styles.page}>
      {/* 头部 */}
      <div className={styles.header}>
        <div className={styles.titleBar}>
          <Smile size={20} className={styles.titleIcon} />
          <h1 className={styles.title}>Live2D 模型</h1>
          <span className={styles.subtitle}>二次元 Live2D 角色管理</span>
        </div>
        <button
          type="button"
          className={styles.btnPrimary}
          onClick={() => {
            setUploadOpen(true)
            setUploadError(null)
            setArchiveFile(null)
          }}
        >
          <Upload size={14} /> 上传模型
        </button>
      </div>

      {/* 错误提示 */}
      {loadError && (
        <p className={styles.errorBanner}>
          <AlertCircle size={14} /> {loadError}
        </p>
      )}

      {/* 加载中 */}
      {loading ? (
        <div className={styles.loading}>
          <Loader2 size={20} className="pet-spin" /> 加载中
        </div>
      ) : models.length === 0 ? (
        <div className={styles.empty}>
          暂无 Live2D 模型，点击右上角"上传模型"导入 Live2D Cubism 模型 zip 包
        </div>
      ) : (
        <div className={styles.grid}>
          {models.map((model) => (
            <div key={model.id} className={styles.card}>
              {/* 预览缩略图 */}
              <div className={styles.previewBox}>
                <div className={styles.previewPlaceholder}>
                  <Smile size={32} />
                  <span>{model.model_name}</span>
                </div>
              </div>

              {/* 模型信息 */}
              <div className={styles.cardInfo}>
                <h3 className={styles.name}>{model.model_name}</h3>
                <div className={styles.meta}>
                  <span className={styles.metaItem}>
                    <FileArchive size={12} />
                    {model.texture_paths.length} 个纹理
                  </span>
                  <span>·</span>
                  <span>{new Date(model.created_at).toLocaleDateString('zh-CN')}</span>
                </div>
              </div>

              {/* 操作按钮 */}
              <div className={styles.cardActions}>
                <button
                  type="button"
                  className={styles.btnPreview}
                  onClick={() => handlePreview(model)}
                >
                  <Eye size={14} /> 预览
                </button>
                <button
                  type="button"
                  className={styles.btnDelete}
                  onClick={() => void handleDelete(model)}
                  disabled={pendingId === model.id}
                  aria-label="删除"
                >
                  {pendingId === model.id ? (
                    <Loader2 size={14} className="pet-spin" />
                  ) : (
                    <Trash2 size={14} />
                  )}
                  删除
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* 上传模态框 */}
      {uploadOpen && (
        <div
          className={styles.overlay}
          role="dialog"
          aria-modal="true"
          onClick={() => setUploadOpen(false)}
        >
          <div className={styles.modal} onClick={(e) => e.stopPropagation()}>
            <div className={styles.modalHeader}>
              <h2 className={styles.modalTitle}>上传 Live2D 模型</h2>
              <button
                type="button"
                className={styles.closeBtn}
                onClick={() => setUploadOpen(false)}
                aria-label="关闭"
              >
                <X size={18} />
              </button>
            </div>

            <div className={styles.modalBody}>
              <label className={styles.field}>
                <span className={styles.fieldLabel}>
                  <FileArchive size={14} /> Live2D 模型 zip 包
                </span>
                <input
                  type="file"
                  accept="application/zip,.zip"
                  onChange={onPickArchive}
                  className={styles.fileInput}
                />
                {archiveFile && (
                  <span className={styles.fileName}>{archiveFile.name}</span>
                )}
              </label>
              <p className={styles.tip}>
                zip 包需包含 Live2D Cubism 模型文件（.moc3, .model3.json, 贴图等）
              </p>
              {uploadError && <p className={styles.errorBanner}>{uploadError}</p>}
            </div>

            <div className={styles.modalFooter}>
              <button
                type="button"
                className={styles.btnGhost}
                onClick={() => setUploadOpen(false)}
                disabled={submitting}
              >
                取消
              </button>
              <button
                type="button"
                className={styles.btnPrimary}
                onClick={() => void handleUpload()}
                disabled={!archiveFile || submitting}
              >
                {submitting ? (
                  <Loader2 size={14} className="pet-spin" />
                ) : (
                  <Upload size={14} />
                )}
                {submitting ? '上传中...' : '开始上传'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 预览模态框 */}
      {previewModel && (
        <div
          className={styles.overlay}
          role="dialog"
          aria-modal="true"
          onClick={() => setPreviewModel(null)}
        >
          <div className={styles.previewModal} onClick={(e) => e.stopPropagation()}>
            <div className={styles.previewHeader}>
              <h2 className={styles.previewTitle}>预览：{previewModel.model_name}</h2>
              <button
                type="button"
                className={styles.closeBtn}
                onClick={() => setPreviewModel(null)}
                aria-label="关闭"
              >
                <X size={18} />
              </button>
            </div>

            <div className={styles.previewBody}>
              <Live2DViewer
                ref={viewerRef}
                modelId={previewModel.id}
                width={320}
                height={400}
              />
            </div>

            <div className={styles.previewFooter}>
              {/* 表情切换 */}
              <div className={styles.expressionRow}>
                {EXPRESSION_OPTIONS.map(({ id, label, Icon }) => (
                  <button
                    key={id}
                    type="button"
                    className={
                      previewExpression === id
                        ? `${styles.expressionBtn} ${styles.expressionBtnActive}`
                        : styles.expressionBtn
                    }
                    onClick={() => handleExpressionChange(id)}
                  >
                    <Icon size={14} /> {label}
                  </button>
                ))}
              </div>

              {/* 口型同步测试 */}
              <div className={styles.lipSyncRow}>
                <span className={styles.lipSyncLabel}>口型</span>
                <input
                  type="range"
                  min={0}
                  max={1}
                  step={0.01}
                  value={previewLipSync}
                  onChange={handleLipSyncChange}
                  className={styles.lipSyncSlider}
                />
                <span className={styles.lipSyncLabel}>
                  {Math.round(previewLipSync * 100)}%
                </span>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}