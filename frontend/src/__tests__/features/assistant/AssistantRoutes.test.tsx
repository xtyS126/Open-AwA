import React from 'react'
import { describe, expect, it } from 'vitest'
import { routeDefinitions } from '@/router'

function unwrapLazyType(path: string): unknown {
  const route = routeDefinitions.find((entry) => entry.path === path)
  if (!route) {
    throw new Error(`缺少路由：${path}`)
  }

  const suspense = (route.element.props as { children?: React.ReactElement }).children
  const lazyElement = suspense
    ? (suspense.props as { children?: React.ReactElement }).children
    : undefined
  return lazyElement?.type
}

describe('助手域路由', () => {
  it('当前对话、会话管理和上下文使用三个真实页面', () => {
    const chatType = unwrapLazyType('/assistant')
    const sessionsType = unwrapLazyType('/assistant/sessions')
    const contextType = unwrapLazyType('/assistant/context')

    expect(sessionsType).not.toBe(chatType)
    expect(contextType).not.toBe(chatType)
    expect(contextType).not.toBe(sessionsType)
  })

  it('会话深链继续复用聊天详情页', () => {
    expect(unwrapLazyType('/assistant/sessions/$conversationId'))
      .toBe(unwrapLazyType('/assistant'))
  })
})
