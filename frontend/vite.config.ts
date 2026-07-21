import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  build: {
    chunkSizeWarningLimit: 600,
  },
  test: {
    environment: 'jsdom',
    setupFiles: './src/test/setup.ts',
  },
  server: {
    port: 14108,
    warmup: {
      // 开发启动时预编译首访主链，避免第一位访问者承担冷启动转换成本。
      clientFiles: ['./src/main.tsx', './src/pages/LoginPage.tsx', './src/pages/ChatPage.tsx'],
    },
    proxy: {
      '/api': 'http://localhost:14100',
    },
  },
})
