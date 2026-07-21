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
    // lib/frontend/vite.config.ts 上溯 2 级到项目根 .vite-cache
    cacheDir: path.resolve(__dirname, '..', '..', '.vite-cache'),
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
            // 首屏必需：React 核心 + 路由
            react: ['react', 'react-dom', 'react-router-dom'],
            // 首屏必需：状态管理 + HTTP 客户端
            core: ['zustand', 'axios'],
            // 首屏必需：服务端数据查询
            query: ['@tanstack/react-query'],
            // 首屏必需：长列表虚拟滚动
            virtuoso: ['react-virtuoso'],
            // 首屏必需：图标库
            icons: ['lucide-react'],
            // 以下分组仅在特定路由用到，通过路由懒加载按需加载，不进入首屏
            // recharts：仅 DashboardPage 用到
            recharts: ['recharts'],
            // P0: markdown 全家桶合并到同一 chunk，避免 rehype-katex/katat 跨 chunk 引用触发 TDZ
            // （katex.mjs 内部模块间引用在 rollup manualChunks 拆分后会形成 "Cannot access 'x' before initialization"）
            // markdown：仅 ChatPage 用到
            markdown: ['react-markdown', 'remark-gfm', 'remark-math', 'rehype-katex', 'katex'],
            // markdownRender：仅 ChatPage 用到
            markdownRender: ['rehype-highlight', 'highlight.js'],
            // sanitize：dompurify 仅 markdown 渲染用到
            sanitize: ['dompurify'],
            // monaco：仅 CodingPage/VibeCodingPage 用到
            monaco: ['@monaco-editor/react'],
            // terminal：仅 VibeCodingPage/CodingPage 用到
            terminal: ['@xterm/xterm', '@xterm/addon-fit'],
            // flow：仅 SubAgentPage/WorkflowPage 用到
            flow: ['reactflow', '@dagrejs/dagre'],
            // qrcode：仅 SettingsPage/IM 用到
            qrcode: ['qrcode'],
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
          // SSE 流式响应必须禁用代理缓冲，否则 Vite 开发代理会攒满整个响应再转发
          configure: (proxy) => {
            proxy.on('proxyRes', (proxyRes) => {
              // 检测 SSE 响应，移除可能导致代理缓冲的响应头
              if (proxyRes.headers['content-type']?.includes('text/event-stream')) {
                // 移除 content-length 以防止代理等待完整响应体
                delete proxyRes.headers['content-length']
                // 移除 content-encoding 以防止代理尝试解压缓冲
                delete proxyRes.headers['content-encoding']
              }
            })
          },
        },
      },
    },
  }
})
