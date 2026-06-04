/**
 * 用户画像 Zustand Store——管理画像事实、统计、提取状态和 UI 状态。
 */

import { create } from 'zustand'
import {
  type ProfileFact,
  type ProfileStats,
  type ProfileSummary,
  type ExtractionLog,
  type ExtractResult,
  getProfileFacts,
  getProfileStats,
  getProfileSummary,
  getExtractionLogs,
  extractProfile,
  updateProfileFact,
  createProfileFact,
  deleteProfileFact,
  verifyProfileFact,
  disputeProfileFact,
  refreshProfile,
} from '@/shared/api/profileApi'

interface ProfileState {
  /* ── 数据状态 ── */
  facts: ProfileFact[]
  factsTotal: number
  factsCategories: Record<string, number>
  stats: ProfileStats | null
  summary: ProfileSummary | null
  extractionLogs: ExtractionLog[]
  logsTotal: number

  /* ── UI 状态 ── */
  loading: boolean
  extracting: boolean
  error: string | null
  selectedCategory: string | null
  minConfidenceFilter: number

  /* ── 操作 ── */
  fetchFacts: (params?: { category?: string; min_confidence?: number }) => Promise<void>
  fetchStats: () => Promise<void>
  fetchSummary: () => Promise<void>
  fetchExtractionLogs: (limit?: number, offset?: number) => Promise<void>

  triggerExtraction: (sessionIds?: string[]) => Promise<ExtractResult | null>
  editFact: (factId: string, value: string) => Promise<void>
  addFact: (category: string, key: string, value: string) => Promise<void>
  removeFact: (factId: string) => Promise<void>
  confirmFact: (factId: string) => Promise<void>
  disputeFactItem: (factId: string) => Promise<void>
  refreshAllFacts: () => Promise<void>

  setSelectedCategory: (category: string | null) => void
  setMinConfidenceFilter: (min: number) => void
  clearError: () => void
}

export const useProfileStore = create<ProfileState>((set, get) => ({
  /* ── 初始状态 ── */
  facts: [],
  factsTotal: 0,
  factsCategories: {},
  stats: null,
  summary: null,
  extractionLogs: [],
  logsTotal: 0,
  loading: false,
  extracting: false,
  error: null,
  selectedCategory: null,
  minConfidenceFilter: 0,

  /* ── 数据获取 ── */

  fetchFacts: async (params) => {
    set({ loading: true, error: null })
    try {
      const res = await getProfileFacts({
        category: params?.category ?? get().selectedCategory ?? undefined,
        min_confidence: params?.min_confidence ?? get().minConfidenceFilter,
        active_only: true,
      })
      set({
        facts: res.facts,
        factsTotal: res.total,
        factsCategories: res.categories,
        loading: false,
      })
    } catch (e: unknown) {
      set({ error: (e as Error).message || '获取画像事实失败', loading: false })
    }
  },

  fetchStats: async () => {
    try {
      const res = await getProfileStats()
      set({ stats: res })
    } catch (e: unknown) {
      set({ error: (e as Error).message || '获取画像统计失败' })
    }
  },

  fetchSummary: async () => {
    try {
      const res = await getProfileSummary()
      set({ summary: res })
    } catch (e: unknown) {
      set({ error: (e as Error).message || '获取画像摘要失败' })
    }
  },

  fetchExtractionLogs: async (limit = 20, offset = 0) => {
    try {
      const res = await getExtractionLogs({ limit, offset })
      set({ extractionLogs: res.logs, logsTotal: res.total })
    } catch (e: unknown) {
      set({ error: (e as Error).message || '获取提取日志失败' })
    }
  },

  /* ── 操作 ── */

  triggerExtraction: async (sessionIds) => {
    set({ extracting: true, error: null })
    try {
      const result = await extractProfile({ session_ids: sessionIds })
      set({ extracting: false })
      // 提取后自动刷新数据
      await get().fetchFacts()
      await get().fetchStats()
      await get().fetchExtractionLogs()
      return result
    } catch (e: unknown) {
      set({ error: (e as Error).message || '画像提取失败', extracting: false })
      return null
    }
  },

  editFact: async (factId, value) => {
    try {
      await updateProfileFact(factId, { fact_value: value })
      await get().fetchFacts()
    } catch (e: unknown) {
      set({ error: (e as Error).message || '编辑画像事实失败' })
    }
  },

  addFact: async (category, key, value) => {
    try {
      await createProfileFact({ category, fact_key: key, fact_value: value })
      await get().fetchFacts()
      await get().fetchStats()
    } catch (e: unknown) {
      set({ error: (e as Error).message || '添加画像事实失败' })
    }
  },

  removeFact: async (factId) => {
    try {
      await deleteProfileFact(factId)
      await get().fetchFacts()
      await get().fetchStats()
    } catch (e: unknown) {
      set({ error: (e as Error).message || '删除画像事实失败' })
    }
  },

  confirmFact: async (factId) => {
    try {
      await verifyProfileFact(factId)
      await get().fetchFacts()
    } catch (e: unknown) {
      set({ error: (e as Error).message || '确认画像事实失败' })
    }
  },

  disputeFactItem: async (factId) => {
    try {
      await disputeProfileFact(factId)
      await get().fetchFacts()
    } catch (e: unknown) {
      set({ error: (e as Error).message || '否定画像事实失败' })
    }
  },

  refreshAllFacts: async () => {
    set({ loading: true })
    try {
      await refreshProfile()
      await get().fetchFacts()
      await get().fetchStats()
      set({ loading: false })
    } catch (e: unknown) {
      set({ error: (e as Error).message || '刷新画像失败', loading: false })
    }
  },

  /* ── UI 状态 ── */

  setSelectedCategory: (category) => set({ selectedCategory: category }),
  setMinConfidenceFilter: (min) => set({ minConfidenceFilter: min }),
  clearError: () => set({ error: null }),
}))
