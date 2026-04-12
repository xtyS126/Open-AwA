import '@testing-library/jest-dom/vitest'
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react'
import { vi, describe, it, expect, beforeEach, afterEach } from 'vitest'
import ChatPage from '@/features/chat/ChatPage'
import { modelsAPI } from '@/features/settings/modelsApi'

if (!HTMLElement.prototype.scrollIntoView) {
  Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', {
    value: () => {},
    writable: true
  })
}


vi.mock('@/features/settings/modelsApi', () => ({
  modelsAPI: {
    getProviders: vi.fn(),
    updateConfiguration: vi.fn()
  }
}))

vi.mock('@/features/chat/store/chatStore', () => ({
  useChatStore: vi.fn(() => ({
    messages: [],
    addMessage: vi.fn(),
    setLoading: vi.fn(),
    isLoading: false,
    clearMessages: vi.fn()
  }))
}))

describe('ChatPage Model Selector', () => {
  beforeEach(() => {
    localStorage.clear()
    vi.clearAllMocks()
    vi.spyOn(console, 'error').mockImplementation(() => {})
  })

  afterEach(() => {
    cleanup()
    vi.restoreAllMocks()
  })

  describe('Model Loading', () => {
    it('should load configurations on mount', async () => {
      const mockConfigs = {
        data: {
          providers: [
            { id: 'openai', name: 'OpenAI', display_name: 'OpenAI', selected_models: ['gpt-4'] },
            { id: 'anthropic', name: 'Anthropic', display_name: 'Anthropic', selected_models: ['claude-3.5-sonnet'] }
          ]
        }
      }
      ;(modelsAPI.getProviders as any).mockResolvedValue(mockConfigs)

      render(<ChatPage />)

      await waitFor(() => {
        expect(modelsAPI.getProviders).toHaveBeenCalled()
      })
    })

    it('should display "加载中..." while loading', () => {
      ;(modelsAPI.getProviders as any).mockImplementation(
        () => new Promise(() => {})
      )

      render(<ChatPage />)

      expect(screen.getByText('加载中...')).toBeInTheDocument()
    })

    it('should display "暂无可用模型" when no configurations', async () => {
      const mockConfigs = { data: { providers: [] } }
      ;(modelsAPI.getProviders as any).mockResolvedValue(mockConfigs)

      render(<ChatPage />)

      await waitFor(() => {
        expect(screen.getByText('暂无可用模型')).toBeInTheDocument()
      })
    })

    it('should display error message when API fails', async () => {
      ;(modelsAPI.getProviders as any).mockRejectedValue(new Error('Network error'))

      render(<ChatPage />)

      await waitFor(() => {
        expect(screen.getByText(/加载模型失败/)).toBeInTheDocument()
      })
    })
  })

  describe('Model Selection', () => {
    it('should select default model on load', async () => {
      const mockConfigs = {
        data: {
          providers: [
            { id: 'openai', name: 'OpenAI', display_name: 'OpenAI', selected_models: ['gpt-4'] }
          ]
        }
      }
      ;(modelsAPI.getProviders as any).mockResolvedValue(mockConfigs)

      render(<ChatPage />)

      await waitFor(() => {
        const select = screen.getAllByRole('combobox')[1] as HTMLSelectElement
        expect(select.value).toBe('openai:gpt-4')
      })
    })

    it('should ignore insecure localStorage persisted model selection', async () => {
      localStorage.setItem('selected_model', 'anthropic:claude-3.5-sonnet')

      const mockConfigs = {
        data: {
          providers: [
            { id: 'openai', name: 'OpenAI', display_name: 'OpenAI', selected_models: ['gpt-4'] },
            { id: 'anthropic', name: 'Anthropic', display_name: 'Anthropic', selected_models: ['claude-3.5-sonnet'] }
          ]
        }
      }
      ;(modelsAPI.getProviders as any).mockResolvedValue(mockConfigs)

      render(<ChatPage />)

      await waitFor(() => {
        const select = screen.getAllByRole('combobox')[1] as HTMLSelectElement
        expect(select.value).toBe('openai:gpt-4')
      })
    })

    it('should not persist selected model into localStorage', async () => {
      const mockConfigs = {
        data: {
          providers: [
            { id: 'openai', name: 'OpenAI', display_name: 'OpenAI', selected_models: ['gpt-4'] },
            { id: 'anthropic', name: 'Anthropic', display_name: 'Anthropic', selected_models: ['claude-3.5-sonnet'] }
          ]
        }
      }
      ;(modelsAPI.getProviders as any).mockResolvedValue(mockConfigs)

      render(<ChatPage />)

      const selects = await screen.findAllByRole('combobox')
      const modelSelect = selects[1]
      
      await waitFor(() => {
        expect(screen.getByRole('option', { name: 'Anthropic - claude-3.5-sonnet' })).toBeInTheDocument()
      })
      
      fireEvent.change(modelSelect, { target: { value: 'anthropic:claude-3.5-sonnet' } })

      await waitFor(() => {
        expect(localStorage.getItem('selected_model')).toBeNull()
      })
    })
  })

  describe('Save Model Button', () => {
    it('should show save button when model is selected', async () => {
      const mockConfigs = {
        data: {
          providers: [
            { id: 'openai', name: 'OpenAI', display_name: 'OpenAI', selected_models: ['gpt-4'] }
          ]
        }
      }
      ;(modelsAPI.getProviders as any).mockResolvedValue(mockConfigs)

      render(<ChatPage />)

      await waitFor(() => {
        expect(screen.getByText('保存模型')).toBeInTheDocument()
      })
    })

    it('should show success message after saving', async () => {
      const mockConfigs = {
        data: {
          providers: [
            { id: 'openai', name: 'OpenAI', display_name: 'OpenAI', selected_models: ['gpt-4'] }
          ]
        }
      }
      ;(modelsAPI.getProviders as any).mockResolvedValue(mockConfigs)
      ;(modelsAPI.updateConfiguration as any).mockResolvedValue({ data: { success: true } })

      render(<ChatPage />)

      await waitFor(() => {
        const saveBtn = screen.getByText('保存模型')
        fireEvent.click(saveBtn)
      })

      await waitFor(() => {
        expect(screen.getByText('已保存')).toBeInTheDocument()
      })
    })
  })

  describe('Retry Mechanism', () => {
    it('should show retry button when loading fails', async () => {
      ;(modelsAPI.getProviders as any).mockRejectedValue(new Error('Network error'))

      render(<ChatPage />)

      await waitFor(() => {
        expect(screen.getByText(/重试/)).toBeInTheDocument()
      })
    })

    it('should retry loading when retry button is clicked', async () => {
      let callCount = 0
      ;(modelsAPI.getProviders as any).mockImplementation(() => {
        callCount++
        if (callCount === 1) {
          return Promise.reject(new Error('Network error'))
        }
        return Promise.resolve({
          data: {
            providers: [
              { id: 'openai', name: 'OpenAI', display_name: 'OpenAI', selected_models: ['gpt-4'] }
            ]
          }
        })
      })

      render(<ChatPage />)

      await waitFor(() => {
        const retryBtn = screen.getByText(/重试/)
        fireEvent.click(retryBtn)
      })

      await waitFor(() => {
        expect(callCount).toBeGreaterThan(1)
      })
    })
  })
})
