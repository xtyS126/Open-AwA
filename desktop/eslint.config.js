// ESLint 配置 - 桌面端主进程
module.exports = {
  root: true,
  parser: '@typescript-eslint/parser',
  parserOptions: {
    ecmaVersion: 2020,
    sourceType: 'module',
  },
  extends: [
    'eslint:recommended',
  ],
  rules: {
    'no-console': ['error', { allow: ['error', 'warn'] }],
    'no-unused-vars': 'off',
  },
  ignorePatterns: ['dist/', 'node_modules/', 'resources/frontend/'],
}
