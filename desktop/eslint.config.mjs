// ESLint 9 flat config - 桌面端主进程
// 注意：ESLint 9 强制使用 flat config（导出数组），旧的 CommonJS module.exports 已不支持
// 使用 .mjs 扩展名：desktop 包为 CommonJS（主进程/preload 编译为 CJS），ESM 配置需显式 .mjs
import js from '@eslint/js'
import tseslint from 'typescript-eslint'

export default tseslint.config(
  // 忽略目录
  {
    ignores: ['dist/', 'node_modules/', 'resources/frontend/', 'scripts/'],
  },
  // 基础规则
  js.configs.recommended,
  // TypeScript 推荐规则
  ...tseslint.configs.recommended,
  // 项目自定义规则
  {
    rules: {
      // 允许 console.error/warn（用于主进程日志兜底），禁止 console.log/info/debug
      'no-console': ['error', { allow: ['error', 'warn'] }],
      // 使用 @typescript-eslint/no-unused-vars 替代原生规则
      'no-unused-vars': 'off',
      '@typescript-eslint/no-unused-vars': ['error', { argsIgnorePattern: '^_' }],
      // 禁止 eval
      'no-eval': 'error',
      // 禁止 debugger
      'no-debugger': 'error',
    },
  },
)
