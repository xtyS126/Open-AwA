/**
 * TTS 状态管理（Zustand）。
 * 管理音色选择、合成参数、流式状态、复刻进度。
 */
import { createWithEqualityFn } from 'zustand/traditional'
import { queryClient } from '@/shared/api/queryClient'
import { ttsApi } from '../ttsApi'
import type { SpeakerInfo } from '../ttsApi'

interface TtsStore {
  // 音色
  speakers: SpeakerInfo[]
  selectedSpeakerId: string | null
  speakersLoading: boolean

  // 合成参数
  text: string
  speedRatio: number
  volumeRatio: number
  pitchRatio: number
  emotion: string | null
  emotionScale: number
  audioFormat: string
  language: string

  // 合成状态
  isSynthesizing: boolean
  isStreaming: boolean
  audioUrl: string | null
  audioBlob: Blob | null

  // 复刻状态
  cloneProgress: number
  cloneStatus: string | null
  cloneSpeakerId: string | null
  cloneError: string | null

  // 操作
  setSpeakers: (speakers: SpeakerInfo[]) => void
  setSelectedSpeaker: (id: string | null) => void
  setText: (text: string) => void
  setSpeedRatio: (v: number) => void
  setVolumeRatio: (v: number) => void
  setPitchRatio: (v: number) => void
  setEmotion: (e: string | null) => void
  setEmotionScale: (v: number) => void
  setAudioFormat: (f: string) => void
  setLanguage: (l: string) => void
  setIsSynthesizing: (v: boolean) => void
  setIsStreaming: (v: boolean) => void
  setAudioUrl: (url: string | null) => void
  setAudioBlob: (blob: Blob | null) => void
  setCloneProgress: (p: number) => void
  setCloneStatus: (s: string | null) => void
  setCloneSpeakerId: (id: string | null) => void
  setCloneError: (e: string | null) => void
  loadSpeakers: () => Promise<void>
  resetCloneState: () => void
}

export const useTtsStore = createWithEqualityFn<TtsStore>((set, get) => ({
  speakers: [],
  selectedSpeakerId: 'zh_female_qingxin',
  speakersLoading: false,

  text: '',
  speedRatio: 1.0,
  volumeRatio: 1.0,
  pitchRatio: 0.0,
  emotion: null,
  emotionScale: 1.0,
  audioFormat: 'mp3',
  language: 'zh',

  isSynthesizing: false,
  isStreaming: false,
  audioUrl: null,
  audioBlob: null,

  cloneProgress: 0,
  cloneStatus: null,
  cloneSpeakerId: null,
  cloneError: null,

  setSpeakers: (speakers) => set({ speakers }),
  setSelectedSpeaker: (id) => set({ selectedSpeakerId: id }),
  setText: (text) => set({ text }),
  setSpeedRatio: (v) => set({ speedRatio: v }),
  setVolumeRatio: (v) => set({ volumeRatio: v }),
  setPitchRatio: (v) => set({ pitchRatio: v }),
  setEmotion: (e) => set({ emotion: e }),
  setEmotionScale: (v) => set({ emotionScale: v }),
  setAudioFormat: (f) => set({ audioFormat: f }),
  setLanguage: (l) => set({ language: l }),
  setIsSynthesizing: (v) => set({ isSynthesizing: v }),
  setIsStreaming: (v) => set({ isStreaming: v }),
  setAudioUrl: (url) => set({ audioUrl: url }),
  setAudioBlob: (blob) => set({ audioBlob: blob }),
  setCloneProgress: (p) => set({ cloneProgress: p }),
  setCloneStatus: (s) => set({ cloneStatus: s }),
  setCloneSpeakerId: (id) => set({ cloneSpeakerId: id }),
  setCloneError: (e) => set({ cloneError: e }),

  loadSpeakers: async () => {
    set({ speakersLoading: true })
    try {
      // 通过 React Query 共享缓存（与 AssistantContextPage / TtsPage 共用同一 queryKey）
      // 避免多组件同时挂载时重复请求 /tts/speakers 端点
      const data = await queryClient.fetchQuery({
        queryKey: ['tts', 'speakers'],
        queryFn: () => ttsApi.listSpeakers(),
      })
      const speakers = data.speakers || []
      set({ speakers, speakersLoading: false })
      // 自动选择第一个可用音色
      const { selectedSpeakerId } = get()
      if (!selectedSpeakerId && speakers.length > 0) {
        set({ selectedSpeakerId: speakers[0].speaker_id })
      }
    } catch {
      set({ speakersLoading: false })
    }
  },

  resetCloneState: () => set({
    cloneProgress: 0,
    cloneStatus: null,
    cloneSpeakerId: null,
    cloneError: null,
  }),
}))
