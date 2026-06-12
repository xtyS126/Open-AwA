import '@testing-library/jest-dom'
import { createElement } from 'react'
import { vi } from 'vitest'

// 确保 i18n store 在测试环境中正确初始化（zh-CN）
import { useI18nStore } from '@/i18n'
useI18nStore.setState({ locale: 'zh-CN' })

// 模拟 indexedDB——jsdom 环境不提供 indexedDB，
// 测试中让其 open 失败以触发 chatPersistence 的 localStorage 降级路径
if (typeof indexedDB === 'undefined') {
  // idb 库引用了这些全局类，须在 indexedDB 之前定义
  class MockIDBRequest extends EventTarget {
    result: any = undefined
    error: DOMException | null = null
    source: any = null
    transaction: any = null
    readyState = 'done'
    onsuccess: ((this: any, ev: Event) => any) | null = null
    onerror: ((this: any, ev: Event) => any) | null = null
    onblocked: ((this: any, ev: Event) => any) | null = null
  }
  ;(globalThis as any).IDBRequest = MockIDBRequest
  ;(globalThis as any).IDBOpenDBRequest = MockIDBRequest
  ;(globalThis as any).IDBDatabase = class MockIDBDatabase extends EventTarget {}
  ;(globalThis as any).IDBTransaction = class MockIDBTransaction extends EventTarget {}
  ;(globalThis as any).IDBObjectStore = class MockIDBObjectStore {}
  ;(globalThis as any).IDBIndex = class MockIDBIndex {}
  ;(globalThis as any).IDBKeyRange = class MockIDBKeyRange {
    static only() { return {} }
    static lowerBound() { return {} }
    static upperBound() { return {} }
    static bound() { return {} }
  }
  ;(globalThis as any).IDBCursor = class MockIDBCursor {}
  ;(globalThis as any).IDBCursorWithValue = class MockIDBCursorWithValue {}

  const idbRequestFail = () => {
    const request = new MockIDBRequest()
    // 异步触发 error，模拟真实的打开失败
    setTimeout(() => {
      request.readyState = 'done'
      request.error = new DOMException('IndexedDB 在测试环境中不可用', 'UnknownError')
      if (request.onerror) {
        request.onerror({ target: request, type: 'error' } as any)
      }
    }, 0)
    return request
  }
  ;(globalThis as any).indexedDB = {
    open: idbRequestFail,
    deleteDatabase: () => idbRequestFail(),
    cmp: () => 0,
    databases: () => Promise.resolve([]),
  }
}

const routerFutureConfig = {
  v7_startTransition: true,
  v7_relativeSplatPath: true,
};

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');

  return {
    ...actual,
    BrowserRouter: ({ future, ...props }: React.ComponentProps<typeof actual.BrowserRouter>) =>
      createElement(actual.BrowserRouter, {
        ...props,
        future: future ?? routerFutureConfig,
      }),
    MemoryRouter: ({ future, ...props }: React.ComponentProps<typeof actual.MemoryRouter>) =>
      createElement(actual.MemoryRouter, {
        ...props,
        future: future ?? routerFutureConfig,
      }),
  };
});

if (!HTMLElement.prototype.scrollIntoView) {
  HTMLElement.prototype.scrollIntoView = function() {};
}

// Ensure a #root element exists for main.tsx bootstrap
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
