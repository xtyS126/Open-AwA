import '@testing-library/jest-dom/vitest'
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react'
import { vi, describe, it, expect, beforeEach, afterEach } from 'vitest'
import ChatPage from '../pages/ChatPage'
import { modelsAPI } from '../services/modelsApi'

if (!HTMLElement.prototype.scrollIntoView) {
  Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', {
    value: () => {},
    writable: true
  })
}


vi.mock('../services/modelsApi', () => ({
  modelsAPI: {
    getConfigurations: vi.fn(),
    updateConfiguration: vi.fn()
  }
}))

vi.mock('../stores/chatStore', () => ({
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
          configurations: [
            { id: 1, provider: 'openai', model: 'gpt-4', display_name: 'GPT-4', is_default: true },
            { id: 2, provider: 'anthropic', model: 'claude-3.5-sonnet', display_name: 'Claude', is_default: false }
          ]
        }
      }
      ;(modelsAPI.getConfigurations as any).mockResolvedValue(mockConfigs)

      render(<ChatPage />)

      await waitFor(() => {
        expect(modelsAPI.getConfigurations).toHaveBeenCalled()
      })
    })

    it('should display "加载中..." while loading', () => {
      ;(modelsAPI.getConfigurations as any).mockImplementation(
        () => new Promise(() => {})
      )

      render(<ChatPage />)

      expect(screen.getByText('加载中...')).toBeInTheDocument()
    })

    it('should display "暂无可用模型" when no configurations', async () => {
      const mockConfigs = { data: { configurations: [] } }
      ;(modelsAPI.getConfigurations as any).mockResolvedValue(mockConfigs)

      render(<ChatPage />)

      await waitFor(() => {
        expect(screen.getByText('暂无可用模型')).toBeInTheDocument()
      })
    })

    it('should display error message when API fails', async () => {
      ;(modelsAPI.getConfigurations as any).mockRejectedValue(new Error('Network error'))

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
          configurations: [
            { id: 1, provider: 'openai', model: 'gpt-4', display_name: 'GPT-4', is_default: true }
          ]
        }
      }
      ;(modelsAPI.getConfigurations as any).mockResolvedValue(mockConfigs)

      render(<ChatPage />)

      await waitFor(() => {
        const select = screen.getByRole('combobox') as HTMLSelectElement
        expect(select.value).toBe('openai:gpt-4')
      })
    })

    it('should restore saved model from localStorage', async () => {
      localStorage.setItem('selected_model', 'anthropic:claude-3.5-sonnet')

      const mockConfigs = {
        data: {
          configurations: [
            { id: 1, provider: 'openai', model: 'gpt-4', display_name: 'GPT-4', is_default: true },
            { id: 2, provider: 'anthropic', model: 'claude-3.5-sonnet', display_name: 'Claude', is_default: false }
          ]
        }
      }
      ;(modelsAPI.getConfigurations as any).mockResolvedValue(mockConfigs)

      render(<ChatPage />)

      await waitFor(() => {
        const select = screen.getByRole('combobox') as HTMLSelectElement
        expect(select.value).toBe('anthropic:claude-3.5-sonnet')
      })
    })

    it('should save selected model to localStorage', async () => {
      const mockConfigs = {
        data: {
          configurations: [
            { id: 1, provider: 'openai', model: 'gpt-4', display_name: 'GPT-4', is_default: true },
            { id: 2, provider: 'anthropic', model: 'claude-3.5-sonnet', display_name: 'Claude', is_default: false }
          ]
        }
      }
      ;(modelsAPI.getConfigurations as any).mockResolvedValue(mockConfigs)

      render(<ChatPage />)

      const select = await screen.findByRole('combobox')
      await waitFor(() => {
        expect(screen.getByRole('option', { name: 'Anthropic - Claude' })).toBeInTheDocument()
      })
      fireEvent.change(select, { target: { value: 'anthropic:claude-3.5-sonnet' } })

      await waitFor(() => {
        expect(localStorage.getItem('selected_model')).toBe('anthropic:claude-3.5-sonnet')
      })
    })
  })

  describe('Save Model Button', () => {
    it('should show save button when model is selected', async () => {
      const mockConfigs = {
        data: {
          configurations: [
            { id: 1, provider: 'openai', model: 'gpt-4', display_name: 'GPT-4', is_default: true }
          ]
        }
      }
      ;(modelsAPI.getConfigurations as any).mockResolvedValue(mockConfigs)

      render(<ChatPage />)

      await waitFor(() => {
        expect(screen.getByText('保存模型')).toBeInTheDocument()
      })
    })

    it('should call updateConfiguration when save button is clicked', async () => {
      const mockConfigs = {
        data: {
          configurations: [
            { id: 1, provider: 'openai', model: 'gpt-4', display_name: 'GPT-4', is_default: true }
          ]
        }
      }
      ;(modelsAPI.getConfigurations as any).mockResolvedValue(mockConfigs)
      ;(modelsAPI.updateConfiguration as any).mockResolvedValue({ data: { success: true } })

      render(<ChatPage />)

      await waitFor(() => {
        const saveBtn = screen.getByText('保存模型')
        fireEvent.click(saveBtn)
      })

      await waitFor(() => {
        expect(modelsAPI.updateConfiguration).toHaveBeenCalledWith(1, { is_default: true })
      })
    })

    it('should show success message after saving', async () => {
      const mockConfigs = {
        data: {
          configurations: [
            { id: 1, provider: 'openai', model: 'gpt-4', display_name: 'GPT-4', is_default: true }
          ]
        }
      }
      ;(modelsAPI.getConfigurations as any).mockResolvedValue(mockConfigs)
      ;(modelsAPI.updateConfiguration as any).mockResolvedValue({ data: { success: true } })

      render(<ChatPage />)

      await waitFor(() => {
        const saveBtn = screen.getByText('保存模型')
        fireEvent.click(saveBtn)
      })

      await waitFor(() => {
        expect(screen.getByText('✓ 已保存')).toBeInTheDocument()
      })
    })
  })

  describe('Retry Mechanism', () => {
    it('should show retry button when loading fails', async () => {
      ;(modelsAPI.getConfigurations as any).mockRejectedValue(new Error('Network error'))

      render(<ChatPage />)

      await waitFor(() => {
        expect(screen.getByText(/重试/)).toBeInTheDocument()
      })
    })

    it('should retry loading when retry button is clicked', async () => {
      let callCount = 0
      ;(modelsAPI.getConfigurations as any).mockImplementation(() => {
        callCount++
        if (callCount === 1) {
          return Promise.reject(new Error('Network error'))
        }
        return Promise.resolve({
          data: {
            configurations: [
              { id: 1, provider: 'openai', model: 'gpt-4', display_name: 'GPT-4', is_default: true }
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
