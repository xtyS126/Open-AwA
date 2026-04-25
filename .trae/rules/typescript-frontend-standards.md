# TypeScript/React 前端开发规范

## 类型安全

### 1.1 禁止使用 `any`
```typescript
// 正确: 定义具体类型
interface ApiResponse<T> {
  data: T;
  error?: string;
}

// 正确: 使用 unknown 代替 any，使用时强制类型检查
function processValue(value: unknown): string {
  if (typeof value === 'string') return value;
  return JSON.stringify(value);
}

// 错误: 使用 any
function processValue(value: any): string {
  return value.toString();
}
```

### 1.2 API 响应类型定义
```typescript
// 正确: 所有 API 响应必须有完整类型定义
interface ChatMessageResponse {
  id: string;
  content: string;
  role: 'user' | 'assistant';
  tool_calls?: ToolCall[];
  created_at: string;
}

// 错误: 使用松散类型或不完整定义
interface ChatMessageResponse {
  id: string;
  content: any;  // 禁止 any
  [key: string]: unknown;  // 避免，应精确定义
}
```

### 1.3 泛型使用
```typescript
// 正确: 使用泛型创建可复用类型
interface Result<T> {
  success: boolean;
  data?: T;
  error?: string;
}

async function apiGet<T>(url: string): Promise<Result<T>> { ... }
```

## 状态管理

### 2.1 Zustand Store 规范
```typescript
// 正确: 清晰的 Store 结构
interface ChatState {
  messages: Message[];
  isLoading: boolean;
  error: string | null;
}

interface ChatActions {
  sendMessage: (content: string) => Promise<void>;
  clearMessages: () => void;
}

const useChatStore = create<ChatState & ChatActions>()((set, get) => ({
  messages: [],
  isLoading: false,
  error: null,

  sendMessage: async (content) => {
    set({ isLoading: true, error: null });
    try {
      const response = await api.sendMessage(content);
      set((state) => ({
        messages: [...state.messages, response],
        isLoading: false,
      }));
    } catch (e) {
      set({ error: formatError(e), isLoading: false });
    }
  },

  clearMessages: () => set({ messages: [] }),
}));
```

### 2.2 组件卸载安全
```typescript
// 正确: 使用 AbortController 或 mounted 标志
useEffect(() => {
  const abortController = new AbortController();

  const fetchData = async () => {
    try {
      const result = await api.fetchData({ signal: abortController.signal });
      // 更新状态
    } catch (e) {
      if (e instanceof DOMException && e.name === 'AbortError') return;
      setError(e);
    }
  };

  fetchData();
  return () => abortController.abort();
}, []);
```

### 2.3 Store 选择器优化
```typescript
// 正确: 精确选择，避免不必要渲染
const messages = useChatStore((state) => state.messages);

// 正确: 使用 shallow 进行对象比较
const { messages, isLoading } = useChatStore(
  (state) => ({ messages: state.messages, isLoading: state.isLoading }),
  shallow
);

// 错误: 整个 store 订阅导致全部组件重渲染
const store = useChatStore();
```

## 组件设计

### 3.1 组件拆分原则
- 单一职责：每个组件只做一件事
- 提取可复用 UI 到 `shared/components/`
- 业务组件放在 `features/{module}/components/`

### 3.2 Props 类型定义
```typescript
// 正确: 明确的 Props 接口
interface MessageListProps {
  messages: Message[];
  onRetry?: (messageId: string) => void;
}

// 正确: 组件级 Props 定义在组件文件内
const MessageList: React.FC<MessageListProps> = ({ messages, onRetry }) => { ... };
```

### 3.3 性能优化
```typescript
// 正确: React.memo 用于纯展示组件
export const ChatMessage = React.memo<ChatMessageProps>(
  ({ message, onRetry }) => { ... },
  (prev, next) => prev.message.id === next.message.id
);

// 正确: useMemo 缓存计算
const sortedMessages = useMemo(
  () => [...messages].sort((a, b) => a.timestamp - b.timestamp),
  [messages]
);
```

## 错误边界

### 4.1 ErrorBoundary 使用
- 每个主要功能模块必须有独立的 ErrorBoundary
- 路由级别、数据加载层、组件子树级都要设置
- ErrorBoundary 必须提供降级 UI 和重试按钮

```typescript
// ErrorBoundary 组件
class ErrorBoundary extends React.Component<
  { fallback: React.ReactNode; children: React.ReactNode },
  { hasError: boolean }
> {
  state = { hasError: false };

  static getDerivedStateFromError() {
    return { hasError: true };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    // 记录错误到日志系统
    logger.error('Component error', { error, componentStack: info.componentStack });
  }

  handleRetry = () => {
    this.setState({ hasError: false });
  };

  render() {
    if (this.state.hasError) {
      return (
        <div>
          <p>页面出错了</p>
          <button onClick={this.handleRetry}>重试</button>
        </div>
      );
    }
    return this.props.children;
  }
}
```

## 流式处理

### 5.1 SSE 连接管理
```typescript
// 正确: 自动重连和取消
async function* streamChat(
  messages: Message[],
  signal: AbortSignal
): AsyncGenerator<string> {
  const response = await fetch('/api/chat/stream', {
    method: 'POST',
    body: JSON.stringify({ messages }),
    signal,
  });

  if (!response.ok) throw new ApiError(response.status);

  const reader = response.body?.getReader();
  if (!reader) throw new Error('No response body');

  const decoder = new TextDecoder();
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      yield decoder.decode(value, { stream: true });
    }
  } finally {
    reader.releaseLock();
  }
}
```

### 5.2 取消请求
- 使用 `AbortController` 管理请求生命周期
- 组件卸载时取消所有进行中的请求
- 路由切换时取消未完成的流式请求

## 表单校验

### 6.1 前端校验策略
```typescript
// 正确: 使用 zod 定义校验规则
import { z } from 'zod';

const loginSchema = z.object({
  username: z.string().min(3, '用户名至少3个字符').max(50),
  password: z.string().min(8, '密码至少8个字符'),
});

interface LoginForm {
  username: string;
  password: string;
}

async function handleSubmit(data: LoginForm) {
  const result = loginSchema.safeParse(data);
  if (!result.success) {
    // 显示校验错误
    return;
  }
  // 提交请求
}
```

### 6.2 双重校验
- 前端和后端都必须进行校验
- 前端负责用户体验（即时反馈）
- 后端负责安全（不可绕过）

## Hooks 规范

### 7.1 useEffect 依赖数组
```typescript
// 正确: 依赖数组完整
useEffect(() => {
  fetchMessages(conversationId);
}, [conversationId]);  // 明确声明依赖

// 正确: 空依赖只用于 mount/unmount
useEffect(() => {
  const timer = setInterval(tick, 1000);
  return () => clearInterval(timer);
}, []);
```

### 7.2 自定义 Hooks
- 以 `use` 开头命名
- 提取可复用逻辑到 `shared/hooks/`
- 一个 Hook 只做一件事

```typescript
function useWebSocket(url: string) {
  const [connected, setConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    const ws = new WebSocket(url);
    ws.onopen = () => setConnected(true);
    ws.onclose = () => setConnected(false);

    wsRef.current = ws;
    return () => ws.close();
  }, [url]);

  return { connected, ws: wsRef.current };
}
```

## 测试标准

### 8.1 测试覆盖
- 核心组件必须测试：渲染、交互、错误状态
- Store Action 必须测试：正常执行、异常处理
- API 服务层必须测试：请求格式、错误处理
- 错误边界必须测试：异常捕获、降级渲染

### 8.2 测试命名
```typescript
// 正常路径
describe('ChatMessage', () => {
  it('renders message content correctly', () => { ... });
  it('calls onRetry when retry button clicked', () => { ... });
});

// 异常路径
describe('chatStore', () => {
  it('handles API error gracefully', () => { ... });
  it('clears error state on retry', () => { ... });
});
```

### 8.3 Mock 原则
- mock API 层，不 mock 组件内部状态
- mock 外部模块，不 mock 被测试组件自身的逻辑
- 使用 `vi.fn()` 创建可断言 mock

## 事件与内存泄漏防护

### 9.1 事件清理
```typescript
useEffect(() => {
  const handleResize = () => { ... };
  window.addEventListener('resize', handleResize);
  return () => window.removeEventListener('resize', handleResize);
}, []);
```

### 9.2 定时器清理
```typescript
useEffect(() => {
  const pollTimer = setInterval(pollMessages, 3000);
  return () => clearInterval(pollTimer);
}, []);
```

### 9.3 WebSocket 清理
```typescript
useEffect(() => {
  const ws = new WebSocket(url);
  return () => ws.close();
}, [url]);
```
