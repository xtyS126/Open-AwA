import '@testing-library/jest-dom'

// 确保 i18n store 在测试环境中正确初始化（zh-CN）
import { useI18nStore } from '@/i18n'
useI18nStore.setState({ locale: 'zh-CN' })

// 模拟 indexedDB——jsdom 环境不提供 indexedDB，
// 测试中让其 open 失败以覆盖 chatPersistence 的 IndexedDB 不可用路径：
// 读取显式抛错（无 localStorage 降级），由 sessionStore 记录错误并暴露 persistenceAvailable=false
if (typeof indexedDB === 'undefined') {
  // idb 库引用了这些全局类，须在 indexedDB 之前定义
  class MockIDBRequest extends EventTarget {
    result: unknown = undefined
    error: DOMException | null = null
    source: IDBObjectStore | IDBIndex | IDBCursor | null = null
    transaction: IDBTransaction | null = null
    readyState = 'done'
    onsuccess: ((this: MockIDBRequest, event: Event) => unknown) | null = null
    onerror: ((this: MockIDBRequest, event: Event) => unknown) | null = null
    onblocked: ((this: MockIDBRequest, event: Event) => unknown) | null = null
  }
  globalThis.IDBRequest = MockIDBRequest as unknown as typeof IDBRequest
  globalThis.IDBOpenDBRequest = MockIDBRequest as unknown as typeof IDBOpenDBRequest
  globalThis.IDBDatabase = class MockIDBDatabase extends EventTarget {} as unknown as typeof IDBDatabase
  globalThis.IDBTransaction = class MockIDBTransaction extends EventTarget {} as unknown as typeof IDBTransaction
  globalThis.IDBObjectStore = class MockIDBObjectStore {} as unknown as typeof IDBObjectStore
  globalThis.IDBIndex = class MockIDBIndex {} as unknown as typeof IDBIndex
  globalThis.IDBKeyRange = class MockIDBKeyRange {
    static only() { return {} }
    static lowerBound() { return {} }
    static upperBound() { return {} }
    static bound() { return {} }
  } as unknown as typeof IDBKeyRange
  globalThis.IDBCursor = class MockIDBCursor {} as unknown as typeof IDBCursor
  globalThis.IDBCursorWithValue = class MockIDBCursorWithValue {} as unknown as typeof IDBCursorWithValue

  const idbRequestFail = () => {
    const request = new MockIDBRequest()
    // 异步触发 error，模拟真实的打开失败
    setTimeout(() => {
      request.readyState = 'done'
      request.error = new DOMException('IndexedDB 在测试环境中不可用', 'UnknownError')
      if (request.onerror) {
        request.onerror.call(request, new Event('error'))
      }
    }, 0)
    return request
  }
  globalThis.indexedDB = {
    open: idbRequestFail,
    deleteDatabase: () => idbRequestFail(),
    cmp: () => 0,
    databases: () => Promise.resolve([]),
  } as unknown as IDBFactory
}

if (!HTMLElement.prototype.scrollIntoView) {
  HTMLElement.prototype.scrollIntoView = function() {};
}

// jsdom 未实现 Element.scrollTo，自动滚动 hook 在测试中会调用它
if (!HTMLElement.prototype.scrollTo) {
  HTMLElement.prototype.scrollTo = function() {};
}

// jsdom 的 window.scrollTo 仅抛出未实现错误，路由滚动恢复测试需要稳定空实现。
window.scrollTo = function() {}

// 确保 main.tsx 启动时存在 #root 元素
if (!document.getElementById('root')) {
  const root = document.createElement('div')
  root.id = 'root'
  document.body.appendChild(root)
}

if (typeof ResizeObserver === 'undefined') {
  global.ResizeObserver = class ResizeObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
}
