import re

with open('D:/代码/Open-AwA/frontend/src/features/chat/utils/executionMeta.ts', 'r', encoding='utf-8') as f:
    content = f.read()

# Fix the newline injection on every streaming chunk
old_code = "const logSeparator = existingLogs && !existingLogs.endsWith('\\n') ? '\\n' : ''"
new_code = "const isNewBlock = payload.message.startsWith('[') && (payload.message.startsWith('[状态]') || payload.message.startsWith('[思考]')); const logSeparator = (isNewBlock && existingLogs && !existingLogs.endsWith('\\n')) ? '\\n' : ''"

content = content.replace(old_code, new_code)

with open('D:/代码/Open-AwA/frontend/src/features/chat/utils/executionMeta.ts', 'w', encoding='utf-8') as f:
    f.write(content)
