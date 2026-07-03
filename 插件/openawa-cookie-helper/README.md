# OpenAwA Cookie 助手

OpenAwA 浏览器扩展 - 获取 B 站/X/抖音等平台 Cookie 并同步到 OpenAwA 后端的 `openbiliclaw-builtin` 插件配置。

## 认证方式

**API Key 认证**（无需用户名密码登录）。

OpenAwA 后端 `get_current_user` 路径 1 为 API Key 优先：`Authorization: Bearer <OPENAWA_API_KEY>` 匹配后直接返回 owner 用户，自动获得管理员权限。

API Key 来源：
- 后端 `backend/.env.local` 中的 `OPENAWA_API_KEY`
- 或环境变量 `OPENAWA_API_KEY`
- 运行 `cd backend && python generate_api_key.py` 可生成新 Key（至少 32 字符）

## 功能

- 配置 OpenAwA 后端地址（默认 `127.0.0.1:8000`）
- 保存 OpenAwA API Key（存入 `chrome.storage.local`，仅扩展作用域可读）
- 获取浏览器中目标平台的 Cookie（bilibili / X / 抖音 / 小红书 / YouTube / 知乎 / Reddit）
- 将 B 站 Cookie 一键同步到后端 `openbiliclaw-builtin` 插件的 `bilibili_cookie` 字段
- 其他平台 Cookie 支持获取与掩码预览（同步功能随插件 schema 字段扩展）

## 安装（开发者模式）

1. 打开 Edge / Chrome，访问 `edge://extensions` 或 `chrome://extensions`
2. 开启右上角「开发者模式」
3. 点击「加载已解压的扩展」
4. 选择本目录 `插件/openawa-cookie-helper`

## 使用流程

1. **配置后端**：在「后端配置」区填写 OpenAwA 后端地址与端口，点击「保存后端配置」
2. **保存 API Key**：
   - 从 `backend/.env.local` 复制 `OPENAWA_API_KEY` 的值
   - 粘贴到「API Key 认证」区，点击「保存 API Key」
   - 勾选「显示明文」可查看粘贴内容
3. **获取 Cookie**：
   - 在浏览器中先登录目标平台（如 bilibili.com）
   - 在「Cookie 获取与同步」区选择目标平台
   - 点击「获取 Cookie」，下方显示掩码预览与字符数
4. **同步到后端**（仅 B 站支持）：
   - 确认已保存 API Key
   - 点击「同步到后端」，Cookie 将写入 `openbiliclaw-builtin` 插件的 `bilibili_cookie` 字段
   - 同步采用合并策略，不会覆盖插件的其他配置项

## 同步目标

| 平台 | 后端插件 | 配置字段 | 状态 |
|------|----------|----------|------|
| bilibili | openbiliclaw-builtin | `bilibili_cookie` | 已支持同步 |
| x / twitter | openbiliclaw-builtin | `x_cookie` | 已支持同步 |
| douyin | openbiliclaw-builtin | `douyin_cookie` | 已支持同步 |
| xiaohongshu | openbiliclaw-builtin | `xiaohongshu_cookie` | 已支持同步 |
| youtube | openbiliclaw-builtin | `youtube_cookie` | 已支持同步 |
| zhihu | openbiliclaw-builtin | `zhihu_cookie` | 已支持同步 |
| reddit | openbiliclaw-builtin | `reddit_cookie` | 已支持同步 |

> 所有平台的 Cookie 均同步到 `openbiliclaw-builtin` 插件的对应字段。插件仅作为内容接入渠道，AI 能力由 OpenAwA 主平台统一提供。

## 后端 API 约定

扩展通过以下 OpenAwA 后端 API 联动（均使用 API Key 认证）：

- `GET /api/plugins` - 查询插件列表，定位 `openbiliclaw-builtin`
- `GET /api/plugins/{id}/config/export` - 获取插件当前配置（注意：非 `/config`，后者不存在）
- `PUT /api/plugins/{id}/config` - 保存插件配置（API Key 自动获得 owner 权限）

> 无需调用 `/api/auth/login`，API Key 直接通过 `Authorization: Bearer` 头认证。

## 安全说明

- Cookie 为敏感信息，popup 预览采用掩码处理（仅显示前后各 20 字符）
- API Key 存储在 `chrome.storage.local`，仅在扩展作用域内可读
- API Key 输入框默认掩码，勾选「显示明文」才显示
- 后端地址变更后，缓存的插件 ID 自动失效，下次同步时重新查询
- 401/403 错误会提示 API Key 可能失效，需重新保存

## 目录结构

```
openawa-cookie-helper/
├── manifest.json          # MV3 扩展清单
├── popup/
│   ├── popup.html         # popup UI
│   ├── popup.css          # popup 样式
│   └── popup.js           # popup 主逻辑（API Key 认证/获取/同步）
├── icons/
│   ├── icon16.png
│   ├── icon48.png
│   └── icon128.png
└── README.md
```

## 版本更新

本扩展采用 MV3 清单，修改代码后在 `edge://extensions` 点击「重新加载」即可生效。版本号在 `manifest.json` 的 `version` 字段维护。

### v1.1.0

- 改为 API Key 认证（移除用户名密码登录）
- 认证流程简化：直接使用 `OPENAWA_API_KEY`，无需 `/api/auth/login`
- 与后端 `get_current_user` 路径 1（API Key 优先）对齐
