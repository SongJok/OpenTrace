import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes('node_modules')) {
            if (id.includes('recharts')) return 'vendor-charts'
            if (id.includes('react-syntax-highlighter') || id.includes('shiki')) return 'vendor-highlight'
            if (id.includes('react-markdown') || id.includes('remark') || id.includes('rehype')) return 'vendor-markdown'
            if (id.includes('react-router')) return 'vendor-router'
            return 'vendor'
          }
        },
      },
    },
    chunkSizeWarningLimit: 600,
  },
  test: {
    environment: 'jsdom',
    setupFiles: './src/test/setup.ts',
  },
  server: {
    port: 14108,
    proxy: {
      '/api': 'http://localhost:14100',
    },
  },
})
