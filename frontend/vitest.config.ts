import { defineConfig, mergeConfig } from 'vitest/config'
import viteConfig from './vite.config'

export default mergeConfig(
  viteConfig,
  defineConfig({
    test: {
      globals: true,
      environment: 'jsdom',
      setupFiles: './src/setupTests.ts',
      exclude: ['tests/e2e/**', 'node_modules/**'],
      coverage: {
        provider: 'v8',
        reporter: ['text', 'json', 'html'],
        include: ['src/**/*.{ts,tsx}'],
        exclude: [
          'node_modules/',
          'src/setupTests.ts',
          'tests/e2e/**',
          '**/*.d.ts',
          '**/*.test.ts',
          '**/*.test.tsx',
          'src/main.tsx',
          'src/vite-env.d.ts'
        ],
        statements: 90,
        branches: 90,
        functions: 90,
        lines: 90,
      },
    },
  })
)
