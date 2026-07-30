import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach } from 'vitest'

function createMemoryStorage(): Storage {
  const values = new Map<string, string>()
  return {
    get length() {
      return values.size
    },
    clear: () => values.clear(),
    getItem: (key) => values.get(key) ?? null,
    key: (index) => Array.from(values.keys())[index] ?? null,
    removeItem: (key) => values.delete(key),
    setItem: (key, value) => values.set(key, value),
  }
}

// Node 可能暴露缺少 Storage 方法的实验性 localStorage，测试统一使用完整的内存实现。
Object.defineProperty(globalThis, 'localStorage', {
  configurable: true,
  value: createMemoryStorage(),
})

afterEach(() => {
  cleanup()
  localStorage.clear()
})
