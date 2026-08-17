import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'
import legacy from '@vitejs/plugin-legacy'
import { visualizer } from 'rollup-plugin-visualizer'

const manualChunkGroups: Record<string, string[]> = {
  react: ['react', 'react-dom', '@tanstack/react-router'],
  core: ['zustand', 'axios'],
  query: ['@tanstack/react-query'],
  virtuoso: ['react-virtuoso'],
  icons: ['lucide-react'],
  recharts: ['recharts'],
  markdown: ['react-markdown', 'remark-gfm', 'remark-math', 'rehype-katex', 'katex'],
  markdownRender: ['rehype-highlight', 'highlight.js'],
  sanitize: ['dompurify'],
  monaco: ['@monaco-editor/react'],
  terminal: ['@xterm/xterm', '@xterm/addon-fit'],
  flow: ['reactflow', '@dagrejs/dagre'],
  qrcode: ['qrcode'],
}

function resolveManualChunk(moduleId: string): string | undefined {
  const normalizedId = moduleId.replaceAll('\\', '/')
  for (const [chunkName, packages] of Object.entries(manualChunkGroups)) {
    if (packages.some((packageName) => normalizedId.includes(`/node_modules/${packageName}/`))) {
      return chunkName
    }
  }
  return undefined
}

function normalizeApiProxyTarget(target: string): string {
  // 浏览器请求已经包含 /api；代理目标若也携带该前缀会生成 /api/api/*。
  return target.trim().replace(/\/api\/?$/i, '').replace(/\/$/, '')
}

export default defineConfig(({ mode }) => {
  const configuredApiProxyTarget = mode === 'e2e'
    ? `http://127.0.0.1:${process.env.OPENAWA_E2E_BACKEND_PORT || '18000'}`
    : process.env.OPENAWA_API_PROXY_TARGET || 'http://localhost:8000'
  const apiProxyTarget = normalizeApiProxyTarget(configuredApiProxyTarget)
  const dedupedReactPackages = ['react', 'react-dom', 'react/jsx-runtime', 'react/jsx-dev-runtime']

  return {
    plugins: [
      react(),
      // P0: legacy 仅在明确需要时启用（默认关闭以加速构建）
      ...(process.env.ENABLE_LEGACY === '1' ? [legacy({
        targets: ['defaults', 'not IE 11', 'last 2 versions']
      })] : []),
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
        '@': path.resolve(import.meta.dirname, './src')
      },
      dedupe: dedupedReactPackages,
    },
    optimizeDeps: {
      // 模块 E: 将首屏加载的大依赖加入预构建，避免首次访问页面时按需预构建导致的延迟
      // HAR 抓包显示这些依赖开发模式首屏加载总体积超 9MB，预构建后可显著降低首屏耗时
      // 模块 G: 移除 lucide-react（3.46MB 巨型 chunk，按需预构建更优）
      // 模块 G: 追加 recharts / markdown / katex / highlight.js 等 markdown 渲染与图表依赖
      include: [
        ...dedupedReactPackages,
        'zustand',
        '@xterm/xterm',
        '@tanstack/react-router',
        'reactflow',
        'recharts',
        'react-markdown',
        'remark-gfm',
        'remark-math',
        'rehype-katex',
        'rehype-highlight',
        'katex',
        'highlight.js',
      ],
    },
    // 使用前端专用且已被 .gitignore 覆盖的缓存目录。
    // 禁止与后端或构建任务共享 var/cache，避免 Windows 下 results.json 文件锁冲突。
    cacheDir: path.resolve(import.meta.dirname, '.vite-cache'),
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
          // Rollup 5 使用函数式分组；包映射保持原有首屏与按路由拆分边界。
          manualChunks: resolveManualChunk,
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
          ws: true,
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
