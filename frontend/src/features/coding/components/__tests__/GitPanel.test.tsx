import { act, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import GitPanel from '../GitPanel'
import { useCodingStore } from '../../store/codingStore'

const { gitStatusMock, gitLogMock, gitCommitMock } = vi.hoisted(() => ({
  gitStatusMock: vi.fn(),
  gitLogMock: vi.fn(),
  gitCommitMock: vi.fn(),
}))

vi.mock('../../codingApi', () => ({
  codingApi: {
    gitStatus: gitStatusMock,
    gitLog: gitLogMock,
    gitCommit: gitCommitMock,
  },
}))

vi.mock('@/shared/utils/logger', () => ({
  appLogger: {
    warning: vi.fn(),
    error: vi.fn(),
  },
}))

describe('GitPanel 状态加载', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    useCodingStore.setState({
      gitBranch: '',
      gitChanges: [],
      projectDir: 'D:/repo-one',
    })
    gitStatusMock.mockResolvedValue({
      branch: 'main',
      changes: [],
      changed_count: 0,
      is_clean: true,
      is_repo: true,
    })
    gitLogMock.mockResolvedValue({ commits: [], count: 0 })
  })

  it('项目目录变化时只为新目录重新加载状态', async () => {
    render(<GitPanel />)

    await waitFor(() => {
      expect(screen.getByText('git:main')).toBeInTheDocument()
    })
    expect(gitStatusMock).toHaveBeenCalledTimes(1)
    expect(gitStatusMock).toHaveBeenLastCalledWith('D:/repo-one')

    act(() => {
      useCodingStore.getState().setProjectDir('D:/repo-two')
    })

    await waitFor(() => {
      expect(gitStatusMock).toHaveBeenCalledTimes(2)
    })
    expect(gitStatusMock).toHaveBeenLastCalledWith('D:/repo-two')
  })
})
