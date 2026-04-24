# Twitter Monitor 插件作者信息更新计划

## 问题诊断

经过代码分析，发现**前端不显示插件作者和简介**的根本原因：

### 1. 后端 API 响应缺失 author 字段
- **数据库模型** (`db/models.py` 第132行): Plugin 模型**有** `author` 字段
- **API Schema** (`api/schemas.py` 第184-220行): `PluginBase` 和 `PluginResponse` **没有** `author` 字段
- **结果**: API 返回数据中不包含 author，导致前端无法显示

### 2. 前端 TypeScript 接口缺少 author 字段
- **Plugin 类型定义** (`frontend/src/features/dashboard/dashboard.ts` 第50-57行): 缺少 `author` 字段定义
- **前端代码**: `PluginsPage.tsx` 第375行已经有显示作者的代码 `<div className={styles['plugin-meta']}>作者：{author}</div>`
- **问题**: 前端代码会从 `plugin.config.author` 回退获取，但最终来源（API响应）就缺失

### 3. manifest.json 已有 description 字段
- twitter-monitor 插件的 `manifest.json` 中已有 `description` 字段
- 但 API 响应路径未正确传递这个信息

## 修改计划

### 第一阶段：后端修复（确保 API 返回完整数据）

#### 1.1 更新 PluginBase Schema
- **文件**: `backend/api/schemas.py`
- **位置**: 第184-191行 `class PluginBase`
- **操作**: 添加 `author: Optional[str] = None` 和 `description: Optional[str] = None` 字段

#### 1.2 更新 get_plugins API
- **文件**: `backend/api/routes/plugins.py`
- **位置**: 第206-220行 `async def get_plugins`
- **操作**: 确保 Plugin ORM 对象转换为 PluginResponse 时包含 author 和 description 字段
- **注意**: PluginResponse 继承自 PluginBase，会自动获得新字段

### 第二阶段：前端修复（确保正确显示）

#### 2.1 更新 Plugin TypeScript 接口
- **文件**: `frontend/src/features/dashboard/dashboard.ts`
- **位置**: 第50-57行 `export interface Plugin`
- **操作**: 添加 `author?: string` 字段到接口定义

#### 2.2 验证前端显示逻辑
- **文件**: `frontend/src/features/plugins/PluginsPage.tsx`
- **位置**: 第375行和第566-594行 `getPluginAuthor` 函数
- **状态**: 代码逻辑已完整，会正确使用新字段

### 第三阶段：数据库更新（更新 twitter-monitor 的 author 值）

#### 3.1 更新已安装插件的 author
- **操作**: 通过 SQL 或脚本更新数据库中 twitter-monitor 插件的 author 为 "xtyS126"
- **备选方案**: 如果插件通过 import-from-url 重新安装，author 会自动从 manifest.json 读取

### 第四阶段：验证测试

#### 4.1 验证后端 API
- 启动后端服务
- 调用 GET /api/plugins 接口
- 确认返回数据包含 author 和 description 字段

#### 4.2 验证前端显示
- 访问 /plugins 页面
- 确认插件卡片显示作者名称 "xtyS126"
- 确认插件简介正常显示

## 文件修改清单

1. ✅ `backend/api/schemas.py` - 添加 author 和 description 字段到 PluginBase
2. ✅ `frontend/src/features/dashboard/dashboard.ts` - 添加 author 字段到 Plugin 接口
3. ⚠️ `backend/api/routes/plugins.py` - 可能需要调整（取决于 ORM 映射是否自动工作）
4. ⚠️ 数据库更新 - twitter-monitor 插件的 author 值

## 预计工作量
- 后端修改: 10-15 分钟
- 前端修改: 5-10 分钟
- 数据库更新: 5 分钟
- 验证测试: 10 分钟
- **总计**: 约 30-40 分钟

## 注意事项
- 修改后需要重启后端服务
- 前端会自动从新的 API 响应中读取 author 字段
- manifest.json 中的 description 字段已经是正确的，不需要修改
