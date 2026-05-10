with open("frontend/src/features/chat/ChatPage.tsx", "r", encoding="utf-8") as f:
    text = f.read()

import re
old = """                if (event?.type === 'agent_message' && event.agent_id) {
                  const agentId = event.agent_id as string
                  const agentType = typeof event.agent_type === 'string' ? event.agent_type : undefined
                  const toolMeta = applySubagentMessage(createEmptyExecutionMeta(), {
                    agentId,
                    agentType,
                    message: typeof event.message === 'string' ? event.message : '子代理消息',
                  }).toolEvents[0]
                  updateAssistantMeta(assistantMessageId, (current) => applySubagentMessage(current, {
                    agentId,
                    agentType,
                    message: typeof event.message === 'string' ? event.message : '子代理消息',
                  }))
                  if (toolMeta) {
                    updateAssistantSegments(assistantMessageId, (segments) => applyToolEventToSegments(segments, toolMeta))
                  }"""

new_text = """                if (event?.type === 'agent_message' && event.agent_id) {
                  const agentId = event.agent_id as string
                  const agentType = typeof event.agent_type === 'string' ? event.agent_type : undefined
                  const messageText = typeof event.message === 'string' ? event.message : '子代理消息'
                  
                  updateAssistantMeta(assistantMessageId, (current) => applySubagentMessage(current, {
                    agentId,
                    agentType,
                    message: messageText,
                  }))
                  
                  updateAssistantSegments(assistantMessageId, (segments) => {
                    const currentTool = segments.flatMap(s => s.toolEvents).find(t => t.id === agentId)
                    const tempMeta = { toolEvents: currentTool ? [currentTool] : [], isThinking: false } as any
                    const toolMeta = applySubagentMessage(tempMeta, {
                      agentId,
                      agentType,
                      message: messageText,
                    }).toolEvents[0]
                    return applyToolEventToSegments(segments, toolMeta)
                  })"""

if old in text:
    print("Found! Replacing...")
    with open("frontend/src/features/chat/ChatPage.tsx", "w", encoding="utf-8") as f:
        f.write(text.replace(old, new_text))
else:
    print("Not found... Trying soft match")
    # try replacing line 1195 to 1209
