# 聊天页面文件上传功能 - 开发文档

## 1. 现状分析

### 1.1 当前状态

聊天页面仅支持纯文本输入，不支持任何文件上传（图片、文档等）。

### 1.2 涉及文件

| 文件 | 说明 |
|------|------|
| `src/features/chat/ChatPage.tsx` | 聊天页面，输入区域 |
| `src/features/chat/ChatPage.module.css` | 聊天页面样式 |
| `src/features/chat/store/chatStore.ts` | 聊天状态管理 |
| `src/shared/api/api.ts` | API 层 |
| `backend/api/routes/chat.py` | 后端聊天路由 |

## 2. 功能需求

### 2.1 前端功能

1. 输入框左侧添加"附件"按钮（回形针图标）
2. 点击按钮弹出文件选择器，支持多选
3. 支持文件类型：图片（jpg/png/gif/webp）、文档（pdf/txt/md/csv）
4. 文件大小限制：单文件最大 10MB
5. 选中文件后显示缩略图/文件名预览条
6. 支持拖拽上传（拖拽到聊天区域）
7. 图片支持粘贴上传（Ctrl+V）
8. 支持发送前取消某个附件

### 2.2 后端功能

1. 新增 `POST /api/chat/upload` 端点，接收 multipart 文件
2. 将文件保存到 `backend/uploads/` 目录 
3. 返回文件 URL 供前端引用
4. 新增 `GET /api/chat/uploads/{filename}` 端点提供文件访问
5. 聊天消息中附带文件引用，构造多模态 LLM 请求

## 3. 实现方案

### 3.1 前端 - 附件按钮与预览

在 ChatPage 输入区域添加附件功能：

```tsx
// 附件状态
const [attachments, setAttachments] = useState<FileAttachment[]>([])
const fileInputRef = useRef<HTMLInputElement>(null)

interface FileAttachment {
  id: string         // 唯一标识
  file: File         // 原始文件对象
  preview?: string   // 图片预览 URL（blob URL）
  uploading: boolean // 上传状态
  uploaded?: string  // 上传后的服务端 URL
}
```

### 3.2 前端 - 拖拽和粘贴

```tsx
// 拖拽事件
const handleDragOver = (e: React.DragEvent) => { e.preventDefault() }
const handleDrop = (e: React.DragEvent) => {
  e.preventDefault()
  const files = Array.from(e.dataTransfer.files)
  addAttachments(files)
}

// 粘贴事件
const handlePaste = (e: React.ClipboardEvent) => {
  const files = Array.from(e.clipboardData.files)
  if (files.length > 0) addAttachments(files)
}
```

### 3.3 前端 - API 层

在 `api.ts` chatAPI 中添加：

```ts
upload: (file: File) => {
  const formData = new FormData()
  formData.append('file', file)
  return api.post('/chat/upload', formData, {
    headers: { 'Content-Type': 'multipart/form-data' }
  })
}
```

### 3.4 后端 - 上传端点

```python
@router.post("/upload")
async def upload_chat_file(
    file: UploadFile = File(...),
    current_user=Depends(get_current_user)
):
    # 校验文件大小和类型
    # 保存文件并返回访问 URL
    pass

@router.get("/uploads/{filename}")
async def get_uploaded_file(filename: str):
    # 返回静态文件
    pass
```

### 3.5 消息结构扩展

扩展消息格式以支持附件：

```ts
interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  reasoning_content?: string
  timestamp: number
  attachments?: Array<{
    type: 'image' | 'file'
    name: string
    url: string
    size: number
  }>
}
```

### 3.6 附件预览栏样式

```css
.attachments-preview {
  display: flex;
  gap: 8px;
  padding: 8px 0;
  overflow-x: auto;
}

.attachment-item {
  position: relative;
  width: 64px;
  height: 64px;
  border-radius: var(--radius-sm);
  overflow: hidden;
  border: 1px solid var(--color-border);
}

.attachment-remove {
  position: absolute;
  top: -4px;
  right: -4px;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: var(--color-error);
  color: white;
  cursor: pointer;
}
```

## 4. 实施步骤

1. 后端：创建 uploads 目录和上传/访问路由
2. 前端 API：添加 upload 方法
3. chatStore：扩展 Message 类型
4. ChatPage：添加附件按钮、预览条、拖拽区域
5. ChatPage：发送消息时上传文件并附加到消息
6. 样式：附件预览栏和拖拽状态

## 5. 安全考虑

- 文件类型白名单校验（前端 + 后端双重校验）
- 文件大小限制（10MB）
- 文件名转义，防止路径遍历
- 上传文件存储隔离
- 访问需要认证

## 6. 验证标准

- 点击附件按钮可选择文件
- 图片文件显示缩略图预览
- 非图片文件显示文件名和图标
- 可取消已选附件
- 拖拽文件到聊天区域触发上传
- 粘贴图片触发上传
- 发送消息携带文件引用
- 文件大小超限提示错误
- 不支持的文件类型提示错误
- TypeScript 编译无错误
