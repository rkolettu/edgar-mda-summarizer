import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv } from 'vite'

export default defineConfig(({ command, mode }) => {
  if (command === 'build' && !loadEnv(mode, process.cwd(), 'VITE_').VITE_API_URL) {
    throw new Error('VITE_API_URL must point to the deployed backend before building the frontend.')
  }

  return {
    plugins: [react(), tailwindcss()],
    // The commit being deployed (set by Vercel), compared with the API's X-App-Build header in src/lib/api.js.
    define: { __APP_BUILD__: JSON.stringify(process.env.VERCEL_GIT_COMMIT_SHA || '') },
  }
})
