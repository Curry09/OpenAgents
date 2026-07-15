// Spec-0073/T3: 独立 vitest 配置（脱离 electron-vite/electron，供 CI-free 的组件与纯函数单测直接跑）。
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

export default defineConfig({
  plugins: [react()],
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./vitest.setup.ts'],
    include: ['src/**/*.test.{ts,tsx}']
  }
})
