with open("frontend/src/features/chat/utils/executionMeta.ts", "r", encoding="utf-8") as f:
    text = f.read()

old1 = """function appendSubagentLogs(existingLogs: string, chunk: string): Pick<SubagentExecutionState, 'logs' | 'truncated'> {
  const normalizedChunk = String(chunk || '')
  const baseLogs = String(existingLogs || '')
  const nextRawLogs = baseLogs
    ? `${baseLogs}${baseLogs.endsWith('\\n') ? '' : '\\n'}${normalizedChunk}`
    : normalizedChunk"""

new1 = """function appendSubagentLogs(existingLogs: string, chunk: string): Pick<SubagentExecutionState, 'logs' | 'truncated'> {
  const normalizedChunk = String(chunk || '')
  const baseLogs = String(existingLogs || '')
  const nextRawLogs = baseLogs + normalizedChunk"""

text = text.replace(old1, new1)

old2 = """    ? appendSubagentLogs(existing?.subagent?.logs || '', summaryText)"""
new2 = """    ? appendSubagentLogs(existing?.subagent?.logs || '', (existing?.subagent?.logs && !existing.subagent.logs.endsWith('\\n') ? '\\n' : '') + summaryText)"""

text = text.replace(old2, new2)

old3 = """  const nextLogs = appendSubagentLogs(existing?.subagent?.logs || '', `[ERROR] ${timeoutMessage}`)"""
new3 = """  const nextLogs = appendSubagentLogs(existing?.subagent?.logs || '', (existing?.subagent?.logs && !existing.subagent.logs.endsWith('\\n') ? '\\n' : '') + `[ERROR] ${timeoutMessage}`)"""

text = text.replace(old3, new3)

with open("frontend/src/features/chat/utils/executionMeta.ts", "w", encoding="utf-8") as f:
    f.write(text)
print("Done")
