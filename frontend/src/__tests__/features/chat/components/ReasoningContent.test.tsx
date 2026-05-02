import { render, screen, fireEvent } from '@testing-library/react'
import { ReasoningContent } from '../features/chat/components/ReasoningContent'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

describe('ReasoningContent', () => {
  beforeEach(() => {
    localStorage.clear()
    vi.spyOn(Storage.prototype, 'getItem')
    vi.spyOn(Storage.prototype, 'setItem')
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('renders nothing if content is empty', () => {
    const { container } = render(<ReasoningContent messageId="msg-1" content="" isStreaming={false} />)
    expect(container.firstChild).toBeNull()
  })

  it('renders collapsed by default when not streaming', () => {
    render(<ReasoningContent messageId="msg-1" content="My thinking process" isStreaming={false} />)
    expect(screen.getByText('思考过程')).toBeInTheDocument()
    
    // Check if it does not have the expanded class
    const contentDiv = screen.getByText('My thinking process')
    expect(contentDiv.className).not.toContain('expanded')
  })

  it('renders expanded by default when streaming', () => {
    render(<ReasoningContent messageId="msg-2" content="My thinking process" isStreaming={true} />)
    expect(screen.getByText('思考过程 (思考中...)')).toBeInTheDocument()
    
    const contentDiv = screen.getByText('My thinking process')
    expect(contentDiv.className).toContain('expanded')
  })

  it('toggles expansion on header click', () => {
    render(<ReasoningContent messageId="msg-3" content="Thinking..." isStreaming={false} />)
    
    const header = screen.getByText('思考过程').closest('div')!
    const contentDiv = screen.getByText('Thinking...')
    
    // Initial state: collapsed
    expect(contentDiv.className).not.toContain('expanded')
    
    // Click to expand
    fireEvent.click(header)
    expect(contentDiv.className).toContain('expanded')
    expect(localStorage.setItem).not.toHaveBeenCalled()
    
    // Click to collapse
    fireEvent.click(header)
    expect(contentDiv.className).not.toContain('expanded')
    expect(localStorage.setItem).not.toHaveBeenCalled()
  })

  it('auto collapses when streaming ends if user did not manually override', () => {
    const { rerender } = render(<ReasoningContent messageId="msg-4" content="Thinking..." isStreaming={true} />)
    
    // Initially expanded
    const contentDiv = screen.getByText('Thinking...')
    expect(contentDiv.className).toContain('expanded')
    
    // Streaming ends
    rerender(<ReasoningContent messageId="msg-4" content="Thinking... Done" isStreaming={false} />)
    
    // Should auto collapse
    expect(contentDiv.className).not.toContain('expanded')
  })

  it('respects user manual override when streaming ends', () => {
    const { rerender } = render(<ReasoningContent messageId="msg-5" content="Thinking..." isStreaming={true} />)
    
    const header = screen.getByText('思考过程 (思考中...)').closest('div')!
    const contentDiv = screen.getByText('Thinking...')
    
    // User clicks to collapse while streaming
    fireEvent.click(header)
    expect(contentDiv.className).not.toContain('expanded')
    
    // User clicks to expand again
    fireEvent.click(header)
    expect(contentDiv.className).toContain('expanded')
    
    // Streaming ends
    rerender(<ReasoningContent messageId="msg-5" content="Thinking... Done" isStreaming={false} />)
    
    // Should stay expanded because user manually overrode it
    expect(contentDiv.className).toContain('expanded')
  })

  it('ignores localStorage and falls back to secure in-memory defaults', () => {
    localStorage.setItem('reasoning_expanded_msg-6', 'true')
    render(<ReasoningContent messageId="msg-6" content="Thinking..." isStreaming={false} />)
    
    const contentDiv = screen.getByText('Thinking...')
    expect(contentDiv.className).not.toContain('expanded')
  })
})
