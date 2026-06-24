import { describe, it, expect, beforeEach } from 'vitest'
import { getConfigStore, getBackendUrl, setBackendUrl, getWindowBounds, setWindowBounds } from '../src/shared/config-store'

describe('config-store', () => {
  beforeEach(() => {
    // 每个测试前清空 store
    getConfigStore().clear()
  })

  describe('getBackendUrl / setBackendUrl', () => {
    it('默认返回空字符串', () => {
      expect(getBackendUrl()).toBe('')
    })

    it('设置后返回设置的值', () => {
      setBackendUrl('http://localhost:8000/api')
      expect(getBackendUrl()).toBe('http://localhost:8000/api')
    })

    it('覆盖设置后返回新值', () => {
      setBackendUrl('http://old:8000/api')
      setBackendUrl('http://new:9000/api')
      expect(getBackendUrl()).toBe('http://new:9000/api')
    })
  })

  describe('getWindowBounds / setWindowBounds', () => {
    it('默认返回 1280x800', () => {
      const bounds = getWindowBounds()
      expect(bounds.width).toBe(1280)
      expect(bounds.height).toBe(800)
    })

    it('设置后返回设置的值', () => {
      setWindowBounds({ x: 100, y: 200, width: 1024, height: 768 })
      const bounds = getWindowBounds()
      expect(bounds.x).toBe(100)
      expect(bounds.y).toBe(200)
      expect(bounds.width).toBe(1024)
      expect(bounds.height).toBe(768)
    })
  })
})
