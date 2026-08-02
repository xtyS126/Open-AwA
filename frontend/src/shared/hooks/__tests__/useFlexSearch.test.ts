import { renderHook } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { useFlexSearch } from '../useFlexSearch'

describe('useFlexSearch 回调稳定性', () => {
  it('相同非中文分词选项重新渲染时保持 init 引用稳定', () => {
    const { result, rerender } = renderHook(
      ({ renderVersion }) => {
        void renderVersion
        return useFlexSearch({ cjk: false })
      },
      { initialProps: { renderVersion: 1 } }
    )
    const firstInit = result.current.init

    rerender({ renderVersion: 2 })

    expect(result.current.init).toBe(firstInit)
  })
})
