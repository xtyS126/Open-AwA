import { readdirSync, readFileSync } from 'node:fs'
import { relative, resolve } from 'node:path'

import ts from 'typescript'
import { describe, expect, it } from 'vitest'


const SOURCE_ROOT = resolve(process.cwd(), 'src')
const LEGACY_ROUTER_FILE = 'router/index.tsx'
const LEGACY_PAGE_ROUTE = /^\/(?:chat|workspace|coding|vibe-coding|workflows|scheduled-tasks|subagents|discussions|skills(?:\/market)?|plugins(?:\/manage|\/config)?|memory|experience|roles|role-market|tts|dashboard|inbox|billing|user-profile|user|im|pets)(?:\/|\?|#|$)/
const NAVIGATION_PROPERTIES = new Set(['href', 'path', 'to'])

function collectProductionSources(directory: string): string[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const absolutePath = resolve(directory, entry.name)
    const relativePath = relative(SOURCE_ROOT, absolutePath).replaceAll('\\', '/')

    if (entry.isDirectory()) {
      return entry.name === '__tests__' ? [] : collectProductionSources(absolutePath)
    }

    const isTypeScriptSource = /\.(?:ts|tsx)$/.test(entry.name)
    const isExplicitTest = /\.(?:test|spec)\.(?:ts|tsx)$/.test(entry.name)
    return isTypeScriptSource && !isExplicitTest && relativePath !== LEGACY_ROUTER_FILE
      ? [absolutePath]
      : []
  })
}

function getRouteStart(node: ts.Node): string | null {
  if (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)) {
    return node.text
  }
  if (ts.isTemplateExpression(node)) {
    return node.head.text
  }
  return null
}

function propertyNameText(name: ts.PropertyName): string | null {
  if (ts.isIdentifier(name) || ts.isStringLiteral(name)) {
    return name.text
  }
  return null
}

function isNavigationTarget(node: ts.Node): boolean {
  let current: ts.Node | undefined = node

  while (current?.parent) {
    const parent = current.parent

    if (ts.isJsxAttribute(parent)) {
      return NAVIGATION_PROPERTIES.has(parent.name.getText())
    }

    if (ts.isPropertyAssignment(parent)) {
      const propertyName = propertyNameText(parent.name)
      return propertyName !== null && NAVIGATION_PROPERTIES.has(propertyName)
    }

    if (ts.isCallExpression(parent)) {
      const callee = parent.expression
      if (ts.isIdentifier(callee)) {
        return callee.text === 'navigate'
      }
      if (ts.isPropertyAccessExpression(callee)) {
        const owner = callee.expression.getText()
        const method = callee.name.text
        return method === 'navigate'
          || ((owner === 'location' || owner.endsWith('.location')) && (method === 'assign' || method === 'replace'))
          || ((owner === 'history' || owner.endsWith('.history')) && (method === 'push' || method === 'replace'))
      }
      return false
    }

    if (ts.isBinaryExpression(parent)) {
      const expression = parent.left.getText()
      if (expression === 'location.pathname' || expression.endsWith('.location.pathname')) {
        return true
      }
    }

    if (ts.isStatement(parent)) {
      return false
    }
    current = parent
  }

  return false
}

function findLegacyNavigationTargets(filePath: string): string[] {
  const source = readFileSync(filePath, 'utf8')
  const sourceFile = ts.createSourceFile(
    filePath,
    source,
    ts.ScriptTarget.Latest,
    true,
    filePath.endsWith('.tsx') ? ts.ScriptKind.TSX : ts.ScriptKind.TS,
  )
  const findings: string[] = []

  function visit(node: ts.Node) {
    const routeStart = getRouteStart(node)
    if (routeStart && LEGACY_PAGE_ROUTE.test(routeStart) && isNavigationTarget(node)) {
      const { line, character } = sourceFile.getLineAndCharacterOfPosition(node.getStart(sourceFile))
      findings.push(`${relative(SOURCE_ROOT, filePath).replaceAll('\\', '/')}:${line + 1}:${character + 1} ${routeStart}`)
    }
    ts.forEachChild(node, visit)
  }

  visit(sourceFile)
  return findings
}

describe('旧页面 URL 退场守卫', () => {
  it('生产导航只生成规范路由，旧 URL 仅保留在兼容路由和显式测试中', () => {
    const findings = collectProductionSources(SOURCE_ROOT)
      .flatMap(findLegacyNavigationTargets)

    expect(findings).toEqual([])
  })
})
