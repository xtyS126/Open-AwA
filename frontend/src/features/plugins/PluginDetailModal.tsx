/**
 * 插件详情 Modal 组件 — 展示插件完整信息、评分分布、评论列表与评论表单。
 * 支持发表、编辑、删除评论，以及查看评分汇总。
 */
import { useState, useEffect, useCallback } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Modal, Button, Textarea, EmptyState, Badge } from '@/shared/components/ui'
import { useAuthStore } from '@/shared/store/authStore'
import { getApiErrorDetail } from '@/shared/api/client'
import {
  getPluginRating,
  listReviews,
  createReview,
  updateReview,
  deleteReview,
  ratePlugin,
  type MarketplacePlugin,
  type PluginRatingSummary,
  type PluginReview,
} from './marketplaceApi'
import styles from './MarketplacePage.module.css'

interface PluginDetailModalProps {
  open: boolean
  onClose: () => void
  plugin: MarketplacePlugin | null
}

/** 评论分页大小 */
const REVIEW_PAGE_SIZE = 10

/** 实心星与空心星 Unicode 字符 */
const STAR_FILLED = '\u2605'
const STAR_EMPTY = '\u2606'

/**
 * 根据评分渲染 5 颗星（实心/空心），用于评论项与汇总展示。
 * @param score 评分（1-5）
 */
function renderStars(score: number): string {
  const rounded = Math.round(score)
  let result = ''
  for (let i = 1; i <= 5; i++) {
    result += i <= rounded ? STAR_FILLED : STAR_EMPTY
  }
  return result
}

function PluginDetailModal({ open, onClose, plugin }: PluginDetailModalProps) {
  const user = useAuthStore((state) => state.user)
  const queryClient = useQueryClient()

  /* ---- 评分汇总 ---- */
  const [ratingSummary, setRatingSummary] = useState<PluginRatingSummary | null>(null)
  const [ratingLoading, setRatingLoading] = useState(false)

  /* ---- 评论列表 ---- */
  const [reviews, setReviews] = useState<PluginReview[]>([])
  const [reviewsTotal, setReviewsTotal] = useState(0)
  const [reviewsPage, setReviewsPage] = useState(1)
  const [reviewsLoading, setReviewsLoading] = useState(false)

  /* ---- 评论表单 ---- */
  const [formContent, setFormContent] = useState('')
  const [formRating, setFormRating] = useState(0)
  const [submitting, setSubmitting] = useState(false)
  const [editingReviewId, setEditingReviewId] = useState<number | null>(null)
  const [formError, setFormError] = useState('')

  // 使用 React Query 管理评分汇总缓存：queryKey 与 PluginsPage 共享，
  // 打开 Modal 时直接复用列表已加载的评分数据，避免重复请求
  // enabled: !!open && !!plugin 确保 Modal 关闭时不发起查询
  const ratingQuery = useQuery({
    queryKey: ['marketplace', 'plugins', plugin?.id ?? '', 'rating'],
    queryFn: () => getPluginRating(plugin!.id),
    enabled: !!(open && plugin),
  })

  // 同步查询数据到本地 state（保留原有 UI 渲染逻辑）
  useEffect(() => {
    if (ratingQuery.data) {
      setRatingSummary(ratingQuery.data.data)
    }
  }, [ratingQuery.data])

  useEffect(() => {
    setRatingLoading(ratingQuery.isLoading)
  }, [ratingQuery.isLoading])

  useEffect(() => {
    if (ratingQuery.error) {
      console.error('加载评分汇总失败:', ratingQuery.error)
    }
  }, [ratingQuery.error])

  // 手动刷新评分汇总的回调（评论提交/删除/快速评分后调用）
  const loadRating = useCallback(async (pluginId: string) => {
    await queryClient.invalidateQueries({ queryKey: ['marketplace', 'plugins', pluginId, 'rating'] })
  }, [queryClient])

  /** 加载评论列表 */
  const loadReviews = useCallback(async (pluginId: string, page: number) => {
    setReviewsLoading(true)
    try {
      const response = await listReviews(pluginId, page, REVIEW_PAGE_SIZE)
      setReviews(response.data.reviews)
      setReviewsTotal(response.data.total)
      setReviewsPage(response.data.page)
    } catch (error) {
      console.error('加载评论列表失败:', error)
    } finally {
      setReviewsLoading(false)
    }
  }, [])

  /** 打开时加载评论（评分由 useQuery 自动拉取） */
  useEffect(() => {
    if (!open || !plugin) return
    setFormContent('')
    setFormRating(0)
    setEditingReviewId(null)
    setFormError('')
    loadReviews(plugin.id, 1)
  }, [open, plugin, loadReviews])

  /** 提交评论（新建或更新） */
  const handleSubmit = async () => {
    if (!plugin) return
    if (!formContent.trim()) {
      setFormError('请输入评论内容')
      return
    }
    setSubmitting(true)
    setFormError('')
    try {
      if (editingReviewId !== null) {
        await updateReview(editingReviewId, {
          content: formContent.trim(),
          rating: formRating > 0 ? formRating : undefined,
        })
      } else {
        await createReview(plugin.id, {
          content: formContent.trim(),
          rating: formRating > 0 ? formRating : undefined,
        })
      }
      setFormContent('')
      setFormRating(0)
      setEditingReviewId(null)
      // 刷新评论列表与评分汇总
      await Promise.all([loadReviews(plugin.id, 1), loadRating(plugin.id)])
    } catch (error) {
      setFormError(getApiErrorDetail(error) || '提交评论失败')
    } finally {
      setSubmitting(false)
    }
  }

  /** 进入编辑模式 */
  const handleEdit = (review: PluginReview) => {
    setEditingReviewId(review.id)
    setFormContent(review.content)
    setFormRating(review.rating)
    setFormError('')
  }

  /** 取消编辑 */
  const handleCancelEdit = () => {
    setEditingReviewId(null)
    setFormContent('')
    setFormRating(0)
    setFormError('')
  }

  /** 删除评论 */
  const handleDelete = async (reviewId: number) => {
    if (!plugin) return
    if (!window.confirm('确定要删除这条评论吗？')) return
    try {
      await deleteReview(reviewId)
      // 删除后若当前页空了且不是第一页，回退一页
      const remaining = reviews.length - 1
      const targetPage = remaining === 0 && reviewsPage > 1 ? reviewsPage - 1 : reviewsPage
      await Promise.all([loadReviews(plugin.id, targetPage), loadRating(plugin.id)])
    } catch (error) {
      alert(getApiErrorDetail(error) || '删除评论失败')
    }
  }

  /** 快速评分（点击星级直接提交评分，不影响评论） */
  const handleQuickRate = async (score: number) => {
    if (!plugin) return
    try {
      await ratePlugin(plugin.id, score)
      await loadRating(plugin.id)
    } catch (error) {
      alert(getApiErrorDetail(error) || '评分失败')
    }
  }

  if (!plugin) return null

  const reviewsTotalPages = Math.ceil(reviewsTotal / REVIEW_PAGE_SIZE) || 1

  /** 计算指定星级的占比宽度（百分比字符串） */
  const getDistributionWidth = (star: number): string => {
    if (!ratingSummary || ratingSummary.total_count === 0) return '0%'
    const count = ratingSummary.distribution[star] || 0
    return `${(count / ratingSummary.total_count) * 100}%`
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={plugin.name}
      width="720px"
    >
      <div className={styles['detail-container']}>
        {/* 基础信息区 */}
        <section className={styles['detail-section']}>
          <div className={styles['detail-header']}>
            <div className={styles['detail-icon']}>
              {plugin.name.charAt(0).toUpperCase()}
            </div>
            <div className={styles['detail-info']}>
              <p className={styles['detail-description']}>{plugin.description}</p>
              <div className={styles['detail-meta']}>
                <span className={styles['detail-author']}>作者: {plugin.author}</span>
                <span className={styles['detail-version']}>版本: v{plugin.version}</span>
                <span className={styles['detail-category']}>分类: {plugin.category}</span>
                <span className={styles['detail-installs']}>{plugin.install_count} 次安装</span>
              </div>
              {plugin.tags && plugin.tags.length > 0 && (
                <div className={styles['detail-tags']}>
                  {plugin.tags.map((tag) => (
                    <Badge key={tag} variant="primary" text={tag} />
                  ))}
                </div>
              )}
            </div>
          </div>
        </section>

        {/* 评分汇总区 */}
        <section className={styles['detail-section']}>
          <h4 className={styles['section-title']}>评分</h4>
          {ratingLoading ? (
            <div className={styles['detail-loading']}>加载中...</div>
          ) : ratingSummary ? (
            <div className={styles['rating-summary']}>
              {/* 左侧：平均分与总人数 */}
              <div className={styles['rating-overview']}>
                <span className={styles['rating-average']}>
                  {ratingSummary.average_score.toFixed(1)}
                </span>
                <span className={styles['rating-stars']}>
                  {renderStars(ratingSummary.average_score)}
                </span>
                <span className={styles['rating-count']}>
                  共 {ratingSummary.total_count} 人评分
                </span>
                {/* 当前用户快速评分 */}
                <div className={styles['rating-user']}>
                  <span className={styles['rating-user-label']}>我的评分:</span>
                  <div className={styles['rating-user-stars']}>
                    {[1, 2, 3, 4, 5].map((star) => (
                      <button
                        key={star}
                        type="button"
                        className={styles['rating-star-btn']}
                        onClick={() => handleQuickRate(star)}
                        aria-label={`评 ${star} 星`}
                      >
                        {star <= (ratingSummary.user_score || 0) ? STAR_FILLED : STAR_EMPTY}
                      </button>
                    ))}
                  </div>
                </div>
              </div>
              {/* 右侧：分布柱状图（5 星到 1 星） */}
              <div className={styles['rating-distribution']}>
                {[5, 4, 3, 2, 1].map((star) => (
                  <div key={star} className={styles['distribution-row']}>
                    <span className={styles['distribution-label']}>{star}{STAR_FILLED}</span>
                    <div className={styles['distribution-bar']}>
                      <div
                        className={styles['distribution-fill']}
                        style={{ width: getDistributionWidth(star) }}
                      />
                    </div>
                    <span className={styles['distribution-count']}>
                      {ratingSummary.distribution[star] || 0}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <div className={styles['detail-loading']}>暂无评分</div>
          )}
        </section>

        {/* 评论列表区 */}
        <section className={styles['detail-section']}>
          <h4 className={styles['section-title']}>
            评论 ({reviewsTotal})
          </h4>
          {reviewsLoading ? (
            <div className={styles['detail-loading']}>加载中...</div>
          ) : reviews.length === 0 ? (
            <EmptyState
              title="暂无评论"
              description="成为第一个评论此插件的人"
            />
          ) : (
            <>
              <ul className={styles['review-list']}>
                {reviews.map((review) => {
                  const isAuthor = !!user && user.id === review.user_id
                  return (
                    <li key={review.id} className={styles['review-item']}>
                      <div className={styles['review-header']}>
                        <span className={styles['review-author']}>{review.username}</span>
                        <span className={styles['review-stars']}>
                          {renderStars(review.rating)}
                        </span>
                        <span className={styles['review-time']}>
                          {review.updated_at}
                        </span>
                        {/* 作者可见的编辑/删除按钮 */}
                        {isAuthor && (
                          <div className={styles['review-actions']}>
                            <button
                              type="button"
                              className={styles['review-action-btn']}
                              onClick={() => handleEdit(review)}
                              disabled={editingReviewId !== null}
                            >
                              编辑
                            </button>
                            <button
                              type="button"
                              className={`${styles['review-action-btn']} ${styles['review-action-danger']}`}
                              onClick={() => handleDelete(review.id)}
                              disabled={editingReviewId !== null}
                            >
                              删除
                            </button>
                          </div>
                        )}
                      </div>
                      <p className={styles['review-content']}>{review.content}</p>
                    </li>
                  )
                })}
              </ul>
              {/* 评论分页 */}
              {reviewsTotalPages > 1 && (
                <div className={styles['review-pagination']}>
                  <button
                    type="button"
                    className={styles['pagination-btn']}
                    disabled={reviewsPage <= 1}
                    onClick={() => plugin && loadReviews(plugin.id, reviewsPage - 1)}
                  >
                    上一页
                  </button>
                  <span className={styles['pagination-info']}>
                    {reviewsPage} / {reviewsTotalPages}
                  </span>
                  <button
                    type="button"
                    className={styles['pagination-btn']}
                    disabled={reviewsPage >= reviewsTotalPages}
                    onClick={() => plugin && loadReviews(plugin.id, reviewsPage + 1)}
                  >
                    下一页
                  </button>
                </div>
              )}
            </>
          )}
        </section>

        {/* 评论表单区 */}
        <section className={styles['detail-section']}>
          <h4 className={styles['section-title']}>
            {editingReviewId !== null ? '编辑评论' : '发表评论'}
          </h4>
          <div className={styles['review-form']}>
            {/* 星级选择器：5 个按钮，点击选择 1-5 星 */}
            <div className={styles['form-rating']}>
              <span className={styles['form-rating-label']}>评分:</span>
              <div className={styles['form-rating-stars']}>
                {[1, 2, 3, 4, 5].map((star) => (
                  <button
                    key={star}
                    type="button"
                    className={styles['rating-star-btn']}
                    onClick={() => setFormRating(star)}
                    aria-label={`选择 ${star} 星`}
                  >
                    {star <= formRating ? STAR_FILLED : STAR_EMPTY}
                  </button>
                ))}
                {formRating > 0 && (
                  <button
                    type="button"
                    className={styles['form-rating-clear']}
                    onClick={() => setFormRating(0)}
                  >
                    清除
                  </button>
                )}
              </div>
            </div>
            <Textarea
              value={formContent}
              onChange={(e) => setFormContent(e.target.value)}
              placeholder="写下你对这个插件的看法..."
              rows={4}
              maxLength={1000}
            />
            {formError && <p className={styles['form-error']}>{formError}</p>}
            <div className={styles['form-actions']}>
              {editingReviewId !== null && (
                <Button variant="ghost" onClick={handleCancelEdit} disabled={submitting}>
                  取消
                </Button>
              )}
              <Button
                variant="primary"
                onClick={handleSubmit}
                loading={submitting}
                disabled={!formContent.trim()}
              >
                {editingReviewId !== null ? '更新' : '发表'}
              </Button>
            </div>
          </div>
        </section>
      </div>
    </Modal>
  )
}

export default PluginDetailModal
