import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const mobileChatStyles = [
  'src/features/chat/ChatPage.module.css',
  'src/features/chat/components/AskUserCard.module.css',
  'src/features/chat/components/ChatInput.module.css',
  'src/features/chat/components/ConversationSidebar.module.css',
  'src/features/chat/components/TaskPanel.module.css',
  'src/features/chat/components/TodoPanel.module.css',
] as const

describe('聊天移动断点契约', () => {
  it.each(mobileChatStyles)('%s 与小于 768px 的移动壳层边界一致', (relativePath) => {
    const source = readFileSync(resolve(process.cwd(), relativePath), 'utf8')

    expect(source).not.toContain('@media (max-width: 768px)')
    expect(source).toContain('@media (max-width: 767px)')
  })
})
