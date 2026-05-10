with open('D:/代码/Open-AwA/frontend/src/features/chat/ChatPage.tsx', 'r', encoding='utf-8') as f:
    content = f.read()

content = content.replace("let stopStatus: 'completed' | 'error' = 'completed'", "let stopStatus: string = 'completed'")

with open('D:/代码/Open-AwA/frontend/src/features/chat/ChatPage.tsx', 'w', encoding='utf-8') as f:
    f.write(content)
