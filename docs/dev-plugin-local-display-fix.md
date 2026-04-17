# 插件页面本地插件显示修复 - 开发文档

## 1. 现状分析

### 1.1 问题描述

插件管理页面（PluginsPage）当前只显示数据库中已注册的插件，不显示本地文件系统中存在但未注册到数据库的插件。本地插件目录（`plugins/` 和 `backend/plugins/examples/`）中的插件无法被看到和管理。

### 1.2 根因分析

**后端**：
- `GET /plugins` 只查询数据库 `Plugin` 表的记录
- `GET /plugins/discover` 扫描文件系统返回发现的插件，但前端从未调用此接口

**前端**：
- `usePluginList()` hook 只调用 `pluginsAPI.getAll()`（即 `GET /plugins`）
- 没有调用 `pluginsAPI.discover()`（即 `GET /plugins/discover`）
- 页面上没有展示"已发现但未注册"的插件

### 1.3 涉及文件

| 文件 | 说明 |
|------|------|
| `src/features/plugins/PluginsPage.tsx` | 插件管理页面 |
| `src/features/plugins/PluginsPage.module.css` | 插件页面样式 |
| `src/features/plugins/hooks.ts` | 插件 hooks |
| `src/shared/api/api.ts` | pluginsAPI |
| `backend/api/routes/plugins.py` | 后端 discover 和 install 端点 |

## 2. 修复方案

### 2.1 前端改动

#### hooks.ts - 新增 useDiscoveredPlugins hook

```ts
export function useDiscoveredPlugins() {
  const [discovered, setDiscovered] = useState<DiscoveredPlugin[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const fetchDiscovered = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const response = await pluginsAPI.discover()
      setDiscovered(response.data || [])
    } catch (e) {
      setError(getErrorMessage(e, '插件发现失败'))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchDiscovered() }, [fetchDiscovered])

  return { discovered, loading, error, refresh: fetchDiscovered }
}
```

#### PluginsPage.tsx - 合并显示

1. 调用 `useDiscoveredPlugins()` 获取本地插件
2. 将已注册插件和已发现（未注册）插件合并展示
3. 未注册插件卡片显示"安装"按钮取代"启用/禁用"开关
4. 安装操作：调用后端在数据库中创建记录并加载

### 2.2 后端改动

确认 `GET /plugins/discover` 端点能正确扫描以下目录：
- `plugins/`（项目根目录下的示例插件）
- `backend/plugins/examples/`（后端内置示例插件）

如果发现端点的扫描路径不包含上述目录，需扩展 `PluginManager.discover_plugins()` 的扫描范围。

### 2.3 安装流程

点击"安装"按钮时：
1. 前端调用 `POST /plugins/install`，传入插件名称和路径
2. 后端在数据库中创建 Plugin 记录
3. 后端加载插件到运行时
4. 前端刷新插件列表

## 3. UI 设计

### 3.1 分区展示

页面分为两个区域：
- **已注册插件**：当前 grid 布局不变
- **可用的本地插件**：新增区域，显示已发现但未注册的插件

### 3.2 本地插件卡片

```
[插件名称]          [安装]
版本: x.x.x
描述: xxxxx
路径: /plugins/xxx
```

### 3.3 状态标识

- 已加载 + 已启用：绿色标记
- 已注册 + 未启用：灰色标记
- 未注册（本地发现）：蓝色"可安装"标记

## 4. 实施步骤

1. hooks.ts：添加 `useDiscoveredPlugins` hook 和 `DiscoveredPlugin` 类型
2. PluginsPage.tsx：集成 discovered 数据，添加"本地可用插件"区域
3. PluginsPage.tsx：实现安装按钮逻辑
4. PluginsPage.module.css：添加本地插件区域样式
5. 验证安装流程端到端

## 5. 验证标准

- 页面加载后能看到本地存在的插件
- 已注册插件和未注册插件分区展示
- 点击"安装"后插件出现在已注册区域
- 安装后的插件可正常启用/禁用
- 搜索功能覆盖两个区域
- TypeScript 编译无错误
