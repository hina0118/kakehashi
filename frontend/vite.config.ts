import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// 開発時は `kakehashi serve --no-browser` のAPIへプロキシする
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': 'http://127.0.0.1:8765',
    },
  },
})
