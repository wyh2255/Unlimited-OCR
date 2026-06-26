import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'

// Vite config for the Unlimited-OCR web UI.
// During `npm run dev`, the dev server listens on :5173. The backend
// (server.py on :10001) must be started separately and CORS must be
// enabled (it is by default in this project).
export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    host: '0.0.0.0',
    port: 5173,
    strictPort: false,
  },
  build: {
    target: 'es2022',
    outDir: 'dist',
    sourcemap: true,
  },
})
