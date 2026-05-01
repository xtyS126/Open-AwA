# 微信自动回复模块版本回滚方案

本文档描述在微信自动回复模块 (v2.0.0) 升级后，若出现严重的不可恢复故障，如何平滑回滚至上一个稳定版本。

## 1. 触发回滚的条件 (Rollback Triggers)

出现以下任一情况，且在 30 分钟内无法通过常规 Hotfix 修复时，应立即启动回滚流程：
- 自动回复服务发生大面积核心异常，导致轮询任务崩溃且无法重启（如死锁、无限重试导致 CPU 100%）。
- 消息处理存在严重泄漏，用户收到重复消息超过阈值。
- 洗稿与过滤逻辑失效，向微信终端用户大规模泄漏 `<think>` 推理过程或敏感的后端调试信息。
- 与上游微信官方接口 `ilinkai.weixin.qq.com` 出现不可预知的不兼容，导致 `400/401/500` 错误突增。

## 2. 回滚前的数据备份 (Backup Before Rollback)

在执行回滚操作前，**务必备份**当前的运行时状态，以便后续排查问题：

1. **备份状态目录**：
   打包备份 `.openawa/weixin/accounts/` 目录下的所有 `.json` 文件。
   ```bash
   cp -r .openawa/weixin/accounts /path/to/backup/weixin_accounts_backup_$(date +%Y%m%d%H%M)
   ```
2. **备份应用日志**：
   保留当天的业务日志文件，供开发人员离线分析。

## 3. 回滚步骤 (Rollback Procedure)

### 3.1 停止现有服务
暂停所有的后端服务实例，切断流量与后台任务。
```bash
# 假设使用 supervisor/systemd/docker 启动
systemctl stop openawa-backend
# 或 docker-compose stop backend
```

### 3.2 代码版本回退
将代码仓库强制签出到 v2.0.0 更新前的稳定 Commit 节点。
```bash
git checkout <PREVIOUS_STABLE_COMMIT_HASH>
```

### 3.3 数据库数据降级 (可选)
如果新版本新增了强制依赖的数据库结构，且老代码无法兼容，需要进行 Schema 降级：
```bash
cd backend
alembic downgrade <PREVIOUS_STABLE_MIGRATION_VERSION>
```
*注：`WeixinAutoReplyRule` 表如果是新版本专属且旧版本未访问，则可选择不降级数据库直接复用。*

### 3.4 清理新版本状态残留
v2.0.0 引入了独立的 `.auto-reply.json` 状态文件。老版本可能使用不同的持久化逻辑。为了防止新老逻辑冲突，建议清除旧版本不认识的运行时状态文件（此时游标文件 `.sync.json` 可以保留，避免重复拉取已读消息）：
```bash
rm -f .openawa/weixin/accounts/*.auto-reply.json
```

### 3.5 重新启动服务
重新启动后端服务。
```bash
systemctl start openawa-backend
```

## 4. 回滚后的验证 (Post-Rollback Verification)

1. **状态检查**：确认后台服务正常启动，日志中无报错。
2. **功能冒烟测试**：
   - 在前端尝试对测试账号重新扫码或激活。
   - 向测试微信账号发送消息，确认旧版本的自动回复能正常返回文本（虽无最新的规则引擎与幂等强控制，但核心链路应跑通）。
3. **监控观察**：
   持续观察日志 15 分钟，确认没有大量未处理的堆积请求与循环报错。

## 5. 故障复盘 (Post-Mortem)

回滚成功后，开发团队需要基于第二步备份的日志与状态文件，排查并修复 `v2.0.0` 中的致命 Bug，撰写复盘报告后，重新进入测试及发布流程。
