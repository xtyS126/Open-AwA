---
name: commit-message-helper
description: "生成符合 Conventional Commits 规范的 Git 提交信息，根据变更内容自动选择合适的 type 与 scope"
version: 1.0.0
execution-mode: prompt
category: development
author: Open-AwA
tags:
  - git
  - commit
  - conventional-commits
---

# Commit Message Helper

## 用途

本技能用于辅助生成符合 [Conventional Commits](https://www.conventionalcommits.org/) 规范的 Git 提交信息。当用户请求生成提交信息、整理 commit、或描述变更内容时，按下方规则产出规范的提交信息，便于后续自动生成 CHANGELOG、版本号管理与历史追溯。

## 格式规范

一条完整的提交信息由「头部」「正文」「脚注」三部分组成，头部必须遵循以下格式：

```
<type>(<scope>): <description>

<body>

<footer>
```

其中：

- `type`：必填，标识本次变更的语义类型（见下方列表）
- `scope`：可选，标识变更影响的模块/作用域，使用 kebab-case
- `description`：必填，用中文简要描述变更内容，句末不加句号
- `body`：可选，详细说明变更动机、与旧实现的差异
- `footer`：可选，用于标注 BREAKING CHANGE 或关闭的 Issue

注意：头部（首行）总长度建议不超过 72 个字符；正文每行不超过 80 个字符。

## type 含义

| type | 含义 | 示例场景 |
|------|------|----------|
| `feat` | 新增功能 | 新增用户登录接口 |
| `fix` | 修复 Bug | 修复分页列表重复数据问题 |
| `docs` | 文档变更 | 更新 README 部署说明 |
| `style` | 代码格式调整（不影响逻辑） | 调整缩进、补全分号 |
| `refactor` | 重构（非新增功能、非修复 Bug） | 抽取公共校验函数 |
| `test` | 测试相关 | 补充分页查询单元测试 |
| `chore` | 构建/工具/依赖等杂项 | 升级依赖版本、调整 CI 配置 |

## 生成规则

1. **判定 type**：根据 staged diff 的语义判定，新增功能用 `feat`，修复缺陷用 `fix`，其余按上表对号入座
2. **提取 scope**：从变更文件路径中提取作用域（如 `auth`、`billing`、`chat`），多模块统一变更时省略 scope
3. **撰写 description**：使用中文，简洁陈述「做了什么」，避免笼统的「update」「fix bug」
4. **判定是否需要 body**：涉及多文件、破坏性变更、动机不明显时必须补充正文
5. **判定是否需要 footer**：包含 BREAKING CHANGE 或关闭 Issue 时必须添加脚注
6. **BREAKING CHANGE 标注**：在脚注中以 `BREAKING CHANGE:` 开头说明，或在 type 后加 `!`（如 `feat(api)!: ...`）

## 示例

### 示例 1：新增功能

```
feat(auth): 用户登录接口增加图形验证码校验

- 新增 /api/auth/captcha 端点生成验证码图片
- 登录请求体新增 captcha 字段，后端强制校验
- 验证码有效期 5 分钟，错误 3 次后刷新
```

### 示例 2：修复 Bug

```
fix(billing): 修复分页订单列表出现重复数据的问题

分页查询未对 order_id 去重，导致跨页时同一订单重复出现。
改为基于游标的 keyset 分页，确保结果集唯一。
```

### 示例 3：破坏性变更

```
feat(api)!: 重构用户资料接口返回结构

BREAKING CHANGE: /api/user/profile 返回字段由扁平结构改为嵌套结构，
profile.basic.name 替代原 user_name，调用方需同步迁移。
```

### 示例 4：文档变更

```
docs: 更新部署说明中的环境变量配置示例
```

### 示例 5：测试补充

```
test(billing): 补充分页订单列表的去重单元测试
```

## 输出要求

- 仅输出提交信息本身，不附加解释性文字
- 若用户提供了多组不相关变更，建议拆分为多条提交信息并提示用户分次提交
- 若变更信息不足以判定 type，向用户询问变更意图后再生成
