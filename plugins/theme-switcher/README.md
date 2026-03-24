# theme-switcher 插件

演示 Open-AwA 存储 API 与 UI 扩展点用法的主题切换插件。

## 功能

- 在 `light`、`dark`、`system` 三种主题之间切换
- 通过插件实例变量演示配置持久化（存储 API 模式）
- 注册 `hook` 扩展点，在 UI 渲染前注入 CSS 变量令牌
- 维护主题切换历史记录

## 演示的 API 能力

| 能力 | 说明 |
|------|------|
| 存储 API | 通过 `config` 字典读取持久化配置（`default_theme`、`custom_tokens`） |
| UI 扩展点 | 注册 `hook` 扩展点（`ui.render.before`），在渲染前注入主题 CSS 变量 |
| 多工具注册 | 同时注册 `get_theme` 和 `set_theme` 两个工具扩展点 |

## 安装与配置

```bash
curl -X POST http://localhost:8000/api/plugins/load \
  -H "Content-Type: application/json" \
  -d '{
    "path": "/path/to/plugins/theme-switcher",
    "config": {
      "default_theme": "dark",
      "custom_tokens": {
        "--color-accent": "#ff6b6b"
      }
    }
  }'
```

### 配置项说明

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `default_theme` | string | `"light"` | 初始主题，可选值：`light`、`dark`、`system` |
| `custom_tokens` | object | `{}` | 自定义 CSS 变量，会覆盖默认主题令牌中同名的变量 |

## 使用示例

### 获取当前主题

```bash
curl -X POST http://localhost:8000/api/plugins/theme-switcher/execute \
  -H "Content-Type: application/json" \
  -d '{"params": {"action": "get_theme"}}'
```

返回：

```json
{
  "status": "success",
  "theme": "light",
  "tokens": {
    "--color-bg-primary": "#ffffff",
    "--color-text-primary": "#1a1a1a"
  },
  "history": ["light"]
}
```

### 切换主题

```bash
curl -X POST http://localhost:8000/api/plugins/theme-switcher/execute \
  -H "Content-Type: application/json" \
  -d '{"params": {"action": "set_theme", "theme": "dark"}}'
```

返回：

```json
{
  "status": "success",
  "previous_theme": "light",
  "current_theme": "dark",
  "tokens": {
    "--color-bg-primary": "#1a1a2e",
    "--color-text-primary": "#e0e0e0"
  }
}
```

## 权限

本插件不需要任何特殊权限。

## 文件结构

```
theme-switcher/
  manifest.json    # 插件元数据，声明 tool 和 hook 两类扩展点
  src/
    index.py       # 插件主入口，包含 ThemeSwitcherPlugin 类
  README.md        # 本文件
```
