import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes('node_modules')) {
            if (id.includes('/katex/')) return 'vendor-math'
            if (id.includes('/lucide-react/')) return 'vendor-icons'
            if (id.includes('/@tanstack/react-virtual/')) return 'vendor-virtual'
            if (id.includes('/zustand/')) return 'vendor-state'
            if (
              id.includes('/recharts/') ||
              id.includes('/d3-') ||
              id.includes('/react-smooth/') ||
              id.includes('/decimal.js-light/') ||
              id.includes('/victory-vendor/')
            ) return 'vendor-charts'
            if (id.includes('react-syntax-highlighter') || id.includes('shiki')) return 'vendor-highlight'
            if (id.includes('react-markdown') || id.includes('remark') || id.includes('rehype')) return 'vendor-markdown'
            if (id.includes('react-router')) return 'vendor-router'
            if (id.includes('/react/') || id.includes('/react-dom/') || id.includes('/scheduler/')) return 'vendor-react'
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
