/**
 * UI 组件库统一导出 — 所有基础 UI 组件从此文件导入。
 *
 * 使用示例：
 *   import { Button, Input, Modal, Card, Skeleton, EmptyState, Tabs, Textarea } from '@/shared/components/ui'
 */

export { Button } from './Button'
export type { ButtonProps, ButtonVariant, ButtonSize } from './Button'

export { Input } from './Input'
export type { InputProps } from './Input'

export { Modal } from './Modal'
export type { ModalProps } from './Modal'

export { Card } from './Card'
export type { CardProps } from './Card'

export { Skeleton } from './Skeleton'
export type { SkeletonProps, SkeletonVariant } from './Skeleton'

export { EmptyState } from './EmptyState'
export type { EmptyStateProps } from './EmptyState'

export { Tabs } from './Tabs'
export type { TabsProps, TabItem } from './Tabs'

export { Textarea } from './Textarea'
export type { TextareaProps } from './Textarea'
