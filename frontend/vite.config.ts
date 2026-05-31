import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'
import viteCompression from 'vite-plugin-compression'
import legacy from '@vitejs/plugin-legacy'
import { visualizer } from 'rollup-plugin-visualizer'

export default defineConfig(({ mode }) => {
  const apiProxyTarget = mode === 'e2e'
    ? `http://127.0.0.1:${process.env.OPENAWA_E2E_BACKEND_PORT || '18000'}`
    : process.env.OPENAWA_API_PROXY_TARGET || 'http://localhost:8000'
  const dedupedReactPackages = ['react', 'react-dom', 'react/jsx-runtime', 'react/jsx-dev-runtime']

  return {
    plugins: [
      react(),
      // P0: legacy 仅在明确需要时启用（默认关闭以加速构建）
      ...(process.env.ENABLE_LEGACY === '1' ? [legacy({
        targets: ['defaults', 'not IE 11', 'last 2 versions']
      })] : []),
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
      }),
      // P0: 构建产物分析（仅在需要时生成）
      ...(process.env.ANALYZE === '1' ? [visualizer({
        open: false,
        gzipSize: true,
        brotliSize: true,
        filename: 'dist/stats.html',
      })] : []),
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
    // 移到 node_modules 外部，避免 Windows 文件锁 EPERM
    cacheDir: path.resolve(__dirname, '..', '.vite-cache'),
    build: {
      // P0: target 升级到 es2020，减少 polyfill 体积
      target: 'es2020',
      // P0: chunk 大小警告阈值从 500KB 降到 300KB
      chunkSizeWarningLimit: 300,
      minify: 'terser',
      terserOptions: {
        compress: {
          drop_debugger: true,
          // 保留 console.error 和 console.warn 用于生产环境错误日志
          // 仅移除 debug/info/log 级别的控制台输出
          pure_funcs: ['console.log', 'console.debug', 'console.info'],
        },
      },
      rollupOptions: {
        output: {
          manualChunks: {
            react: ['react', 'react-dom', 'react-router-dom'],
            recharts: ['recharts'],
            core: ['zustand', 'axios'],
            virtuoso: ['react-virtuoso'],
            // P0: markdown 拆分为更细粒度，避免单 chunk 过大
            markdown: ['react-markdown', 'remark-gfm', 'remark-math'],
            markdownMath: ['rehype-katex', 'katex'],
            markdownRender: ['rehype-highlight', 'highlight.js'],
            // P0: lucide 图标单独分包
            icons: ['lucide-react'],
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
