import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'
import viteCompression from 'vite-plugin-compression'
import legacy from '@vitejs/plugin-legacy'

export default defineConfig(({ mode }) => {
  const apiProxyTarget = mode === 'e2e'
    ? `http://127.0.0.1:${process.env.OPENAWA_E2E_BACKEND_PORT || '18000'}`
    : process.env.OPENAWA_API_PROXY_TARGET || 'http://localhost:8000'
  const dedupedReactPackages = ['react', 'react-dom', 'react/jsx-runtime', 'react/jsx-dev-runtime']

  return {
    plugins: [
      react(),
      legacy({
        targets: ['defaults', 'not IE 11', 'last 2 versions']
      }),
      viteCompression({
        verbose: true,
        disable: false,
        threshold: 10240,
        algorithm: 'gzip',
        ext: '.gz',
      }),
      viteCompression({
        verbose: true,
        disable: false,
        threshold: 10240,
        algorithm: 'brotliCompress',
        ext: '.br',
      })
    ],
    resolve: {
      alias: {
        '@': path.resolve(__dirname, './src')
      },
      dedupe: dedupedReactPackages,
    },
    optimizeDeps: {
      include: [...dedupedReactPackages, 'zustand'],
    },
    build: {
      minify: 'terser',
      terserOptions: {
        compress: {
          drop_console: true,
          drop_debugger: true,
        },
      },
      rollupOptions: {
        output: {
          manualChunks: {
            react: ['react', 'react-dom', 'react-router-dom'],
            recharts: ['recharts'],
            core: ['zustand', 'axios'],
            markdown: ['react-markdown', 'remark-gfm', 'remark-math', 'rehype-katex', 'katex'],
            markdownRender: ['rehype-highlight', 'highlight.js'],
          }
        }
      }
    },
    server: {
      host: '0.0.0.0',
      port: 5173,
      proxy: {
        '/api': {
          target: apiProxyTarget,
          changeOrigin: true,
        },
      },
    },
  }
})
