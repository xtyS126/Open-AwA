import js from '@eslint/js'
import tsPlugin from '@typescript-eslint/eslint-plugin'
import tsParser from '@typescript-eslint/parser'
import reactHooks from 'eslint-plugin-react-hooks'

export default [
  { ignores: ['dist/**', 'coverage/**', 'test-results/**'] },
  js.configs.recommended,
  {
    files: ['src/**/*.ts', 'src/**/*.tsx'],
    languageOptions: {
      parser: tsParser,
      parserOptions: {
        ecmaVersion: 2020,
        sourceType: 'module',
        ecmaFeatures: { jsx: true },
      },
    },
    plugins: {
      '@typescript-eslint': tsPlugin,
      'react-hooks': reactHooks,
    },
    rules: {
      ...tsPlugin.configs.recommended.rules,
      ...reactHooks.configs.recommended.rules,
      'no-undef': 'off',
      'no-useless-catch': 'off',
      'react-hooks/set-state-in-effect': 'off',
      // 禁止 console.log/info 等调试残留，仅允许 warn/error 用于生产日志
      'no-console': ['warn', { allow: ['warn', 'error'] }],
      // 禁止 debugger 语句
      'no-debugger': 'error',
      // 严格禁止 any 类型，强制使用具体类型或 unknown
      '@typescript-eslint/no-explicit-any': 'error',
      '@typescript-eslint/no-unused-vars': ['warn', { argsIgnorePattern: '^_', varsIgnorePattern: '^_' }],
    },
  },
  {
    // 测试文件允许使用 any（mock 浏览器 API、模拟复杂类型时需要灵活性）
    files: ['src/**/*.test.ts', 'src/**/*.test.tsx', 'src/**/__tests__/**', 'src/setupTests.ts'],
    rules: {
      '@typescript-eslint/no-explicit-any': 'warn',
    },
  },
]
