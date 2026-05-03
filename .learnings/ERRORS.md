## [ERR-20260503-001] git-add-dot-powershell

**Logged**: 2026-05-03T23:16:00+08:00
**Priority**: medium
**Status**: pending
**Area**: config

### Summary
在本项目的 Windows PowerShell 环境中执行 `git add .` 可能异常失败，但按文件显式 `git add <paths>` 可以成功。

### Error
```text
git add .
退出码：1
输出为空
```

### Context
- Command/operation attempted: `git add .`
- Environment: Windows 11, PowerShell, 仓库路径包含中文目录 `d:\代码\Open-AwA`
- Follow-up command: `git add frontend/src/features/settings/SettingsPage.tsx frontend/src/features/settings/SettingsPage.module.css frontend/src/__tests__/features/settings/SettingsPage.test.tsx`
- Result: 按显式路径暂存成功

### Suggested Fix
在该项目的 Windows 环境中，如 `git add .` 无输出失败，优先回退为显式文件路径暂存，并保留一条经验，后续再排查是否与 shell、编码或工作目录状态有关。

### Metadata
- Reproducible: unknown
- Related Files: .gitignore, AGENTS.md

---
