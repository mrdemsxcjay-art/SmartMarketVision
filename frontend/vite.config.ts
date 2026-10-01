import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

// The dashboard is same-origin with the API in production (the FastAPI process
// serves the build at /app). In development, Vite proxies /api to the backend so
// the browser never needs to know the backend port.
//
// The build output is `dashboard_build/` (not the usual `dist/`) so that it is
// kept with the rest of the project files instead of being treated as a
// throwaway artefact: the single-command run relies on it.
export default defineConfig({
  plugins: [react()],
  base: './',
  server: {
    host: '0.0.0.0',
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        ws: true,
      },
    },
  },
  build: {
    outDir: 'dashboard_build',
    sourcemap: false,
    chunkSizeWarningLimit: 900,
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    css: false,
  },
})
