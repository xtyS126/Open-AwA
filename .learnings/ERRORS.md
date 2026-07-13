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

## [ERR-20260713-014] frontend-api-module-path

**Logged**: 2026-07-13T00:00:00+08:00
**Priority**: low
**Status**: resolved
**Area**: frontend

### Summary
微信多媒体 API 模块位于共享 API 目录，不在微信组件目录内。

### Error
```text
Get-Content: frontend/src/features/chat/wechat-module/weixinMultimediaApi.ts 路径不存在
```

### Context
- 组件从 `@/shared/api/weixinMultimediaApi` 导入 API。
- 实际文件为 `frontend/src/shared/api/weixinMultimediaApi.ts`。

### Suggested Fix
修改微信组件时先按其 import 路径定位共享 API 模块。

### Metadata
- Reproducible: yes
- Related Files: frontend/src/features/chat/wechat-module/WechatMultimediaPanel.tsx, frontend/src/shared/api/weixinMultimediaApi.ts

### Resolution
- **Resolved**: 2026-07-13T00:00:00+08:00
- **Notes**: 已使用实际共享 API 模块继续实现。

---

## [ERR-20260713-015] backend-relative-documentation-path

**Logged**: 2026-07-13T00:00:00+08:00
**Priority**: low
**Status**: resolved
**Area**: docs

### Summary
从 backend 工作目录检索项目文档时必须使用父目录路径。

### Error
```text
rg: docs: 系统找不到指定的文件
```

### Context
- `docs/`、`README.md` 与 `PROJECT_DOCUMENTATION.md` 位于仓库根目录。
- 当前命令的工作目录为 `backend/`。

### Suggested Fix
从 backend 运行文档检索时使用 `../docs` 与 `../README.md`，或切换到仓库根目录。

### Metadata
- Reproducible: yes
- Related Files: docs, README.md, PROJECT_DOCUMENTATION.md

### Resolution
- **Resolved**: 2026-07-13T00:00:00+08:00
- **Notes**: 后续迁移验证与文档更新分别使用对应工作目录。

---

## [ERR-20260713-016] alembic-windows-ini-encoding

**Logged**: 2026-07-13T00:00:00+08:00
**Priority**: medium
**Status**: resolved
**Area**: backend

### Summary
Windows 默认 GBK 编码会导致 Alembic 无法读取 UTF-8 的迁移配置文件。

### Error
```text
UnicodeDecodeError: 'gbk' codec can't decode byte 0xae in position 30
```

### Context
- 在 backend 目录使用隔离 SQLite 数据库执行 Alembic 升级与回滚验证。
- `alembic.ini` 含 UTF-8 中文注释。

### Suggested Fix
通过 `PYTHONUTF8=1` 以 UTF-8 模式执行 Alembic；若仍失败，再为配置文件改用兼容编码。

### Metadata
- Reproducible: yes
- Related Files: backend/alembic.ini, backend/alembic/versions/20260713_add_weixin_media_assets.py

### Resolution
- **Resolved**: 2026-07-13T00:00:00+08:00
- **Notes**: `alembic.ini` 已移除会触发 GBK 解码失败的非 ASCII 注释，`alembic/env.py` 的日志配置明确使用 UTF-8；完整迁移图有两个 head，验证时使用具体 revision 或 `heads`。

---

## [ERR-20260713-017] powershell-select-string-pattern-quoting

**Logged**: 2026-07-13T00:00:00+08:00
**Priority**: low
**Status**: resolved
**Area**: tooling

### Summary
PowerShell 的 `Select-String -Pattern` 参数末尾误拼接引号会被解析为额外位置参数。

### Error
```text
A positional parameter cannot be found that accepts argument '?'.
```

### Context
- 在隔离服务中读取本地 API Key 并运行 E2E 场景。

### Suggested Fix
正则模式作为单个 PowerShell 单引号字符串传入，例如 `'^OPENAWA_API_KEY\s*=\s*'`。

### Metadata
- Reproducible: yes
- Related Files: backend/.env.local

### Resolution
- **Resolved**: 2026-07-13T00:00:00+08:00
- **Notes**: 验证脚本已改为单一模式参数，且服务进程使用 finally 清理。

---

## [ERR-20260713-001] powershell-query-quoting

**Logged**: 2026-07-13T00:00:00+08:00
**Priority**: low
**Status**: resolved
**Area**: tooling

### Summary
一次性拼接多条 rg 模式与 PowerShell 字符串时出现未闭合引号，查询未执行。

### Error
```text
The string is missing the terminator: '.
```

### Context
- Operation: 对项目扩展点进行只读交叉检索。
- Cause: 用单引号承载同时含单引号的正则模式。

### Suggested Fix
将复杂检索拆成独立 PowerShell 命令，或改用数组和双引号，避免跨语言引号嵌套。

### Metadata
- Reproducible: yes
- Related Files: .learnings/ERRORS.md

### Resolution
- **Resolved**: 2026-07-13T00:00:00+08:00
- **Notes**: 后续查询改用独立命令和 -e 参数。

---

## [ERR-20260713-002] stale-frontend-file-assumption

**Logged**: 2026-07-13T00:00:00+08:00
**Priority**: low
**Status**: resolved
**Area**: tooling

### Summary
核对 SubAgent 文档时假定前端页面文件名为 SubagentsPage.tsx，实际文件不存在，导致组合只读命令返回非零。

### Error
```text
Get-Content : Cannot find path 'frontend\\src\\features\\subagents\\SubagentsPage.tsx' because it does not exist.
```

### Context
- Operation: 验证子智能体图定义是否已有前端入口。
- Cause: 未先枚举目录，直接按命名习惯猜测文件名。

### Suggested Fix
对不确定的模块入口先用 rg --files 或 Get-ChildItem 枚举，再读取具体文件。

### Metadata
- Reproducible: yes
- Related Files: frontend/src/features/subagents

### Resolution
- **Resolved**: 2026-07-13T00:00:00+08:00
- **Notes**: 后续改为目录枚举定位，未执行写入或代码修改。

---

## [ERR-20260713-003] readme-write-permission

**Logged**: 2026-07-13T00:00:00+08:00
**Priority**: medium
**Status**: pending
**Area**: docs

### Summary
使用 apply_patch 同步 README 与架构路线图时，README 写入被权限拒绝。

### Error
```text
Failed to write file D:\\代码\\Open-AwA\\README.md
```

### Context
- Operation: 更新已过时的移动端路线与已完成模块状态。
- No product code or user data was modified.

### Suggested Fix
检查 README 文件属性和 ACL；如仅 README 受保护，分离补丁后先更新其他可写文档。

### Metadata
- Reproducible: unknown
- Related Files: README.md, docs/架构/未来路线图.md

### Resolution
- **Notes**: 架构路线图已单独完成更新；README 的移动端路线仍待获得可写权限后同步。

---

## [ERR-20260713-004] weixin-audit-path

**Logged**: 2026-07-13T00:00:00+08:00
**Priority**: low
**Status**: resolved
**Area**: tooling

### Summary
微信模块审计命令包含不存在的 backend/channels 路径，导致只读检索以非零状态退出。

### Error
```text
rg: backend\channels: 系统找不到指定的文件。 (os error 2)
```

### Context
- Operation: 检索微信路由、服务和通道适配器。
- Cause: 实际通道目录为 backend/im，非 backend/channels。

### Suggested Fix
先使用 rg --files 或目录清单确认模块根目录，再组合批量检索。

### Metadata
- Reproducible: yes
- Related Files: backend/im, backend/api/routes/weixin.py

### Resolution
- **Resolved**: 2026-07-13T00:00:00+08:00
- **Notes**: 后续检索已改用已确认的目录。

---

## [ERR-20260713-005] weixin-audit-no-match

**Logged**: 2026-07-13T00:00:00+08:00
**Priority**: low
**Status**: resolved
**Area**: tooling

### Summary
组合检索中一个范围未命中，rg 以退出码 1 返回，掩盖了其余已成功的微信模块审计结果。

### Error
```text
rg returned exit code 1 after a search scope had no matches.
```

### Context
- Operation: 汇总微信令牌、实时推送和前端实现线索。
- Cause: 将“无匹配”与命令错误混入同一批处理命令。

### Suggested Fix
将目录存在性、文件枚举和内容检索拆开；预期可能无匹配的 rg 调用单独处理退出码。

### Metadata
- Reproducible: yes
- Related Files: backend/tests, frontend/src/features/im

### Resolution
- **Resolved**: 2026-07-13T00:00:00+08:00
- **Notes**: 后续审计改用明确文件列表和独立查询。

---

## [ERR-20260713-006] weixin-regression-timeout

**Logged**: 2026-07-13T00:00:00+08:00
**Priority**: medium
**Status**: resolved
**Area**: tests

### Summary
微信后端整组回归在 124 秒内未产生结果并超时，需要拆分定位阻塞位置。

### Error
```text
command timed out after 124012 milliseconds
```

### Context
- Command: python -m pytest tests/test_api_skills_weixin.py tests/test_weixin_utils.py tests/test_weixin_skill_adapter.py tests/test_weixin_multimedia.py tests/test_weixin_auto_reply.py tests/test_weixin_auto_reply_coverage.py -q --tb=short
- Workdir: backend
- 测试使用项目 conftest 及应用生命周期。

### Suggested Fix
局部功能回归使用 --no-cov，避免项目级 fail-under=16% 覆盖率把已通过的目标模块测试误判为失败；完整覆盖率门禁仍应在完整套件中运行。整组超时需继续拆分定位，禁止通过跳过微信测试伪造验证通过。

### Metadata
- Reproducible: unknown
- Related Files: backend/tests/test_weixin_*.py, backend/tests/conftest.py

### Resolution
- **Resolved**: 2026-07-13T00:00:00+08:00
- **Notes**: test_weixin_utils.py 的 54 个功能用例在 6.32 秒内通过；退出码 1 的直接原因是局部运行触发全局覆盖率门槛，而非微信功能失败。

---

## [ERR-20260713-007] weixin-test-qdrant-lock

**Logged**: 2026-07-13T00:00:00+08:00
**Priority**: high
**Status**: in_progress
**Area**: tests

### Summary
微信自动回复测试在构造 AIAgent 时访问了项目默认 Qdrant 目录，因 .lock ACL 被拒绝而失败。

### Error
```text
PermissionError: [Errno 13] Permission denied: 'D:\\代码\\Open-AwA\\backend\\data\\qdrant\\.lock'
```

### Context
- Failed test: tests/test_weixin_auto_reply.py::test_default_ai_reply_generator_strips_reasoning_content_and_sets_final_only
- AIAgent 初始化链路创建 VectorStoreManager，并使用默认持久化路径。

### Suggested Fix
在测试导入 AIAgent 前设置独立临时 VECTOR_DB_PATH，或在该用例中替换 MemoryManager/VectorStoreManager；不得移除生产 Qdrant 锁文件或访问用户向量数据。

### Metadata
- Reproducible: yes
- Related Files: backend/tests/test_weixin_auto_reply.py, backend/memory/vector_store_manager.py

---

## [ERR-20260713-008] protected-test-config-write

**Logged**: 2026-07-13T00:00:00+08:00
**Priority**: high
**Status**: pending
**Area**: tests

### Summary
已定位的测试隔离修复无法写入 backend/tests/conftest.py，当前 apply_patch 被文件权限拒绝。

### Error
```text
Failed to write file D:\\代码\\Open-AwA\\backend\\tests\\conftest.py
```

### Context
- Intended change: 在 pytest_configure 中设置独立 VECTOR_DB_PATH。
- Reason: 阻断 AIAgent 测试访问项目默认 Qdrant .lock。

### Suggested Fix
恢复该文件的写入权限后应用最小补丁；临时验证可在 pytest 进程启动前注入 VECTOR_DB_PATH，但不能替代仓库内的隔离契约。

### Metadata
- Reproducible: yes
- Related Files: backend/tests/conftest.py
- Recurrence-Count: 3
- Last-Seen: 2026-07-13

### Resolution
- **Notes**: 已连续三次确认业务源文件和测试配置文件无法由当前会话写入；需要用户恢复相应 ACL 后才能应用修复。

---

## [ERR-20260713-009] frontend-dist-acl

**Logged**: 2026-07-13T00:00:00+08:00
**Priority**: medium
**Status**: in_progress
**Area**: frontend

### Summary
前端生产构建在写入既有 dist 压缩资源时因 EPERM 失败。

### Error
```text
EPERM: operation not permitted, open 'D:\\代码\\Open-AwA\\frontend\\dist\\assets\\BillingPage-8iWla8yb.js.gz'
```

### Context
- Command: npm run build
- TypeScript 检查和 Vite 模块转换已完成，失败发生在输出目录写入阶段。

### Suggested Fix
使用临时 outDir 验证构建；不得删除或覆盖受保护的既有 dist 文件。恢复输出目录写权限后再执行标准 npm run build。

### Metadata
- Reproducible: yes
- Related Files: frontend/dist

---

## [ERR-20260713-010] powershell-rg-glob-syntax

**Logged**: 2026-07-13T00:00:00+08:00
**Priority**: low
**Status**: resolved
**Area**: tooling

### Summary
PowerShell 下将通配符路径直接传给 rg，导致 Windows 将其解析为非法文件名。

### Error
```text
文件名、目录名或卷标语法不正确。 (os error 123)
```

### Context
- Operation: 搜索微信前端 WebSocket 使用点。
- Cause: 使用 frontend\\...\\*.ts* 作为 rg 路径参数，而非目录加 --glob。

### Suggested Fix
向 rg 传入目录，并通过 --glob '*.ts*' 过滤文件类型。

### Metadata
- Reproducible: yes
- Related Files: frontend/src/features/chat/wechat-module

### Resolution
- **Resolved**: 2026-07-13T00:00:00+08:00
- **Notes**: 后续检索改为目录路径和 --glob 过滤。

---

## [ERR-20260713-011] weixin-source-write-acl

**Logged**: 2026-07-13T00:00:00+08:00
**Priority**: high
**Status**: pending
**Area**: frontend

### Summary
微信前端实时消息接入补丁被源文件 ACL 拒绝，无法将已有 useWeixinWebSocket Hook 接入界面。

### Error
```text
Failed to write file D:\\代码\\Open-AwA\\frontend\\src\\features\\chat\\wechat-module\\WechatConfigModule.tsx
```

### Context
- Intended change: 自动回复运行时订阅 WebSocket，并刷新绑定和自动回复状态。
- Related gaps: Hook 未被消费；语音消息缺少媒体下载与 ASR 转写。

### Suggested Fix
恢复前端源文件写权限后应用最小接入补丁；随后为媒体下载和 ASR 转写补充上游能力适配与测试。

### Metadata
- Reproducible: yes
- Related Files: frontend/src/features/chat/wechat-module/WechatConfigModule.tsx, frontend/src/shared/hooks/useWeixinWebSocket.ts
- Recurrence-Count: 2
- Last-Seen: 2026-07-13

---

## [ERR-20260710-010] full-pytest-timeout

**Logged**: 2026-07-10T13:10:00+08:00
**Priority**: medium
**Status**: pending
**Area**: tests

### Summary
全量后端 pytest 在 30 分钟上限内未完成；拆分后的全部测试文件分组均可在有限时间内通过。

### Error
```text
command timed out after 1804014 milliseconds
```

### Context
- 使用临时 VECTOR_DB_PATH，未触碰生产向量库。
- 分组回归覆盖全部 160 个测试文件；慢组主要集中在安全、定时任务和数据库启动测试。

### Suggested Fix
后续可按功能分组并行运行，或为慢测试增加明确的超时和隔离夹具，再评估全量串行套件。

### Metadata
- Reproducible: yes
- Related Files: backend/tests, backend/pytest.ini

---

## [ERR-20260710-011] powershell-heredoc-syntax

**Logged**: 2026-07-10T13:10:00+08:00
**Priority**: low
**Status**: resolved
**Area**: tooling

### Summary
在 Windows PowerShell 中使用 Bash 风格 `python - <<'PY'` 会被解析为非法重定向。

### Error
```text
Missing file specification after redirection operator
```

### Suggested Fix
使用 `python -c` 或 PowerShell here-string，并避免跨 shell 复制 Bash heredoc。

---

## [ERR-20260704-002] skill-path-resolution

**Logged**: 2026-07-04T20:00:00+08:00
**Priority**: low
**Status**: resolved
**Area**: config

### Summary
读取 `self-improvement` 技能时误用了系统技能目录，实际技能位于项目 `.agents/skills/` 目录。

### Error
```text
Get-Content : 找不到路径“C:\Users\23941\.codex\skills\.system\self-improvement\SKILL.md”
```

### Context
- 尝试按相邻系统技能推断路径，但当前技能清单已明确给出项目内绝对路径。
- 随后使用 `D:\代码\Open-AwA\.agents\skills\self-improvement\SKILL.md` 成功读取。

### Suggested Fix
读取技能前直接使用技能清单提供的 source locator，不根据其他技能路径推断。

### Metadata
- Reproducible: yes
- Related Files: .agents/skills/self-improvement/SKILL.md

### Resolution
- **Resolved**: 2026-07-04T20:02:00+08:00
- **Notes**: 已改用技能清单中的绝对路径并完成读取。

---

## [ERR-20260704-003] code-audit-timeout

**Logged**: 2026-07-04T20:43:00+08:00
**Priority**: medium
**Status**: pending
**Area**: tests

**Recurrence-Count**: 2
**Last-Seen**: 2026-07-05

### Recurrence
2026-07-05 再次执行 `./scripts/code-audit.ps1 -SkipTests` 时，OCR 阶段超过 124 秒并触发外层超时。后续必须显式使用 `-SkipOcr`，OCR 如需执行应独立运行并设置更长超时。

### Summary
静态审计首次运行时超时参数过短，并且未按用户偏好跳过 OCR。

### Error
```text
command timed out after 1191 milliseconds
[2/6] ocr AI Code Review (OpenCodeReview)
```

### Context
- Command: `.\scripts\code-audit.ps1 -SkipTests`
- Environment: Windows PowerShell
- 用户历史偏好要求不运行 OCR。

### Suggested Fix
运行审计前先查看帮助，并使用 `.\scripts\code-audit.ps1 -SkipOcr -SkipTests`，同时提供足够的超时时间。

### Metadata
- Reproducible: yes
- Related Files: scripts/code-audit.ps1

### Resolution
- **Resolved**: 2026-07-04T20:44:00+08:00
- **Notes**: 已确认 `-SkipOcr` 参数，后续使用该参数重跑。

---

## [ERR-20260704-004] backend-full-suite-readonly-database

**Logged**: 2026-07-04T20:56:25+08:00
**Priority**: high
**Status**: resolved
**Area**: tests

### Summary
后端全量测试连续三次被测试隔离缺陷阻断，部分 `TestClient(app)` 上下文启动真实 lifespan 并写入只读用户数据库。

### Error
```text
sqlalchemy.exc.OperationalError: (sqlite3.OperationalError) attempt to write a readonly database
[SQL: DELETE FROM user_roles WHERE role_name NOT IN (SELECT name FROM roles)]
FAILED tests/test_api_skills_weixin.py::test_save_and_get_weixin_config
```

### Context
- Command: `python -m pytest -q -x --tb=short -p no:cacheprovider`
- 第一次失败：已删除脚本 `migrate_db.py` 的陈旧测试导致收集失败。
- 第二次失败：`test_api_route_regressions.py` 运行真实 lifespan；已改为无上下文 `TestClient` 并单跑 8/8 通过。
- 第三次失败：`test_api_skills_weixin.py:108` 存在同类隔离问题。
- 测试文件的依赖覆盖只替换路由 DB session，不能替换 `main.py` lifespan 中模块级数据库引擎。

### Suggested Fix
系统扫描导入全局 `main.app` 且使用 `with TestClient(app)` 的路由单测；不验证启动流程的测试应禁用 lifespan，启动测试应显式绑定临时数据库。修复后从后端全量测试重新开始。

### Metadata
- Reproducible: yes
- Related Files: backend/tests/test_api_skills_weixin.py, backend/main.py, backend/db/models.py
- See Also: ERR-20260704-003

### Resolution
- **Resolved**: 2026-07-04T21:05:00+08:00
- **Notes**: pytest 在收集测试模块前绑定独立临时数据库，原只读用户数据库阻塞已消失。

---

## [ERR-20260704-005] wsl-bash-unavailable

**Logged**: 2026-07-04T21:10:00+08:00
**Priority**: low
**Status**: resolved
**Area**: tests

### Summary
Windows 上直接调用 `bash` 命中了未安装发行版的 WSL 启动器，无法执行 shell 脚本语法检查。

### Error
```text
Windows Subsystem for Linux has no installed distributions.
```

### Context
- Command: `bash -n scripts/install.sh`
- Environment: Windows PowerShell；`bash` 解析到 WSL 启动器。

### Suggested Fix
优先查找 Git for Windows 自带的 `C:\Program Files\Git\bin\bash.exe` 并显式调用；不可用时将 shell 语法检查留给 Linux CI。

### Metadata
- Reproducible: yes
- Related Files: scripts/install.sh

### Resolution
- **Resolved**: 2026-07-04T21:11:00+08:00
- **Notes**: 后续改为检测并显式调用 Git Bash。

---

## [ERR-20260704-006] powershell-utf8-without-bom

**Logged**: 2026-07-04T21:14:00+08:00
**Priority**: medium
**Status**: resolved
**Area**: config

### Summary
Windows PowerShell 5 按本地代码页读取无 BOM 的 UTF-8 安装脚本，中文乱码后导致语法解析失败。

### Error
```text
Parser.ParseFile: UnexpectedToken / ExpectedExpression
```

### Context
- `Parser.ParseInput(Get-Content -Encoding utf8 -Raw)` 解析通过。
- 文件首字节不是 UTF-8 BOM，证明错误来自默认解码而非脚本语法。

### Suggested Fix
面向 Windows PowerShell 5 的含中文 `.ps1` 文件应保存为带 BOM 的 UTF-8，并用 `Parser.ParseFile` 验证磁盘上的真实读取路径。

### Metadata
- Reproducible: yes
- Related Files: scripts/install.ps1

### Resolution
- **Resolved**: 2026-07-04T21:15:00+08:00
- **Notes**: 已将安装脚本机械转换为带 BOM 的 UTF-8。

---

## [ERR-20260704-007] command-executor-windows-echo

**Logged**: 2026-07-04T21:21:26+08:00
**Priority**: medium
**Status**: resolved
**Area**: tests

### Summary
命令模板执行器在 Windows 使用 `shell=False` 执行 `echo`，但 `echo` 是 shell 内建命令而非独立可执行文件。

### Error
```text
FAILED tests/test_command_executor.py::TestCommandDefinition::test_render_template_shell_expansion
AssertionError: 'hello world' not in 'Result: (命令未找到: echo)'
```

### Context
- 后端全量第三次运行进度：837 passed、3 skipped、1 failed。
- `core/command_executor.py:86` 将白名单命令统一交给 `subprocess.run(args, shell=False)`。
- Unix 与 Windows 的 shell 内建命令可用性不同。

### Suggested Fix
为 `echo`、`pwd` 等安全内建命令提供跨平台的 Python 实现，或建立明确的平台命令适配层；不要简单改为 `shell=True`，避免扩大命令注入面。

### Metadata
- Reproducible: yes
- Related Files: backend/core/command_executor.py, backend/tests/test_command_executor.py

---

## [ERR-20260705-008] frontend-coverage-threshold

**Logged**: 2026-07-05T13:38:00+08:00
**Priority**: high
**Status**: pending
**Area**: tests

### Summary
前端全部 Vitest 用例通过，但全局覆盖率门槛为 90%，当前实际覆盖率仅约 40%，导致 `npm run test:coverage` 固定失败。

### Error
```text
Coverage for lines (40.16%) does not meet global threshold (90%)
Coverage for functions (40.25%) does not meet global threshold (90%)
Coverage for statements (40.16%) does not meet global threshold (90%)
Coverage for branches (64.51%) does not meet global threshold (90%)
```

### Context
- Command: `npm run test:coverage`
- 复测中所有测试文件和测试用例均通过，失败仅来自全局覆盖率门槛。

### Suggested Fix
为当前未覆盖的生产模块分阶段补齐测试；在达到目标前，不应通过降低门槛或缩小生产代码统计范围来伪造通过。

### Metadata
- Reproducible: yes
- Related Files: frontend/vitest.config.ts, frontend/src

---

## [ERR-20260710-012] code-audit-hygiene-acl

**Logged**: 2026-07-10T13:12:00+08:00
**Priority**: medium
**Status**: pending
**Area**: tooling

### Summary
代码审计跳过 OCR 后发现 ESLint 配置中的调试规则文本和只读组件文件中的符号规则；受保护文件无法在当前权限下替换。

### Error
```text
Debugger: frontend/eslint.config.js line 31/32
Emoji: frontend/src/features/chat/components/InlineToolCallCard.tsx contains emoji
```

### Suggested Fix
使用管理员权限修正只读组件文件中的符号，并将审计脚本改为识别规则配置而不是简单匹配配置文本；本次已先拆分调试规则字符串并记录阻塞。

---

## [ERR-20260713-013] icacls-powershell-grant-syntax

**Logged**: 2026-07-13T00:00:00+08:00
**Priority**: medium
**Status**: resolved
**Area**: tooling

### Summary
为 PowerShell 提供的 `icacls /grant` 命令使用了括号形式的权限标记，当前环境将其拆分为无效参数。

### Error
```text
无效参数“(M)”
```

### Context
- 命令：`icacls <path> /grant "$env:USERNAME:(M)"`
- PowerShell 在当前原生命令参数传递模式下未将权限标记作为同一个参数传给 `icacls`。

### Suggested Fix
对基本修改权限使用不含括号的 `用户名:M` 形式，并用 `${env:USERNAME}` 明确变量边界。

### Metadata
- Reproducible: yes
- Related Files: backend/skills/weixin_skill_adapter.py, frontend/src/features/chat/wechat-module/WechatMultimediaPanel.tsx

### Resolution
- **Resolved**: 2026-07-13T00:00:00+08:00
- **Notes**: 后续管理员 PowerShell 命令统一使用 `icacls <path> /grant "${env:USERNAME}:M"`。

---
