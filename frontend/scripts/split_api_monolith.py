# -*- coding: utf-8 -*-
"""
api.ts 按域机械拆分脚本（一次性工具）。
原理：按预先侦察好的行段把 api.ts 切割到 13 个领域文件，
导入清单根据代码体中实际引用的符号自动计算，最后把 api.ts 重写为 barrel。
"""
import re
from pathlib import Path

API_DIR = Path(r"D:\代码\Open-AwA\frontend\src\shared\api")
SRC = API_DIR / "api.ts"
lines = SRC.read_text(encoding="utf-8").split("\n")


def seg(a: int, b: int) -> str:
    """取 1-indexed 闭区间行段"""
    return "\n".join(lines[a - 1 : b]).strip("\n")


# 各域文件的行段（依据全部 export 声明行号二次校正，含交错的接口定义）
SEGMENTS = {
    "chatApi.ts": [(90, 102), (104, 193), (262, 320), (350, 421), (423, 894)],
    "authApi.ts": [(63, 78), (195, 260), (322, 348)],
    "skillsApi.ts": [(895, 911)],
    "pluginsApi.ts": [(912, 960), (979, 1018)],
    "opsApi.ts": [(961, 978), (1019, 1133)],
    "memoryApi.ts": [(1134, 1156)],
    "promptsApi.ts": [(1157, 1165)],
    "conversationApi.ts": [(1166, 1204), (1308, 1371)],
    "scheduledTasksApi.ts": [(1205, 1307)],
    "behaviorApi.ts": [(1372, 1380)],
    "weixinApi.ts": [(1381, 1632)],
    "diaryApi.ts": [(1633, 1675)],
    "issueFeedbackApi.ts": [(1676, 1681)],
}

HEADERS = {
    "chatApi.ts": "聊天 API 模块。封装对话发送、SSE 流式、任务断连恢复、消息反馈、文件操作撤销等端点。自 api.ts 拆分而来。",
    "authApi.ts": "认证与用户 API 模块。封装登录、API Key 管理、用户资料、登录设备、用户偏好、密码修改端点。自 api.ts 拆分而来。",
    "skillsApi.ts": "技能 API 模块。封装技能列表、解析上传等端点。自 api.ts 拆分而来。",
    "pluginsApi.ts": "插件 API 模块。封装插件列表、发现、安装端点。自 api.ts 拆分而来。",
    "opsApi.ts": "运维 API 模块。封装行为日志查询、系统信息、测试运行端点。自 api.ts 拆分而来。",
    "memoryApi.ts": "记忆 API 模块。封装短期/长期记忆查询与搜索端点。自 api.ts 拆分而来。",
    "promptsApi.ts": "提示词 API 模块。封装提示词列表与管理端点。自 api.ts 拆分而来。",
    "scheduledTasksApi.ts": "定时任务 API 模块。封装 AI 提示/插件命令类定时任务管理端点。自 api.ts 拆分而来。",
    "conversationApi.ts": "会话管理 API 模块。封装会话列表查询端点。自 api.ts 拆分而来。",
    "behaviorApi.ts": "行为统计 API 模块。封装行为日志与统计端点。自 api.ts 拆分而来。",
    "weixinApi.ts": "微信集成 API 模块。封装微信自动回复与扫码状态端点。自 api.ts 拆分而来。",
    "diaryApi.ts": "日记 API 模块。封装日记生成与查询端点。自 api.ts 拆分而来。",
    "issueFeedbackApi.ts": "问题反馈 API 模块。封装用户问题反馈提交端点。自 api.ts 拆分而来。",
}

# types.ts 已有导出的类型名（用于自动计算 import type）
TYPE_NAMES = [
    "ApiPayload", "ApiObject", "ConversationSortKey", "ConversationSortOrder",
    "WeixinAutoReplyMatchType", "ChatAttachmentType", "ScheduledTaskType",
    "WeixinQrState", "WeixinQrStatus", "ChatStreamTeamPayload",
    "SkillItem", "SkillsListResponse", "SkillParseUploadResponse",
    "PluginItem", "PluginsListResponse", "DiscoveredPluginItem",
    "PluginsDiscoverResponse", "PluginInstallResponse",
    "ShortTermMemoryItem", "LongTermMemoryItem",
    "ShortTermMemoryListResponse", "LongTermMemoryListResponse", "MemorySearchResponse",
    "PromptItem", "PromptsListResponse",
    "BehaviorStatsResponse", "BehaviorLogItem", "BehaviorLogsResponse",
    "ChatHistoryResponse", "ChatUploadResponse", "ChatCancelResponse",
    "ChatTaskSummary", "ChatTaskStatus", "ChatFeedbackResponse", "ChatUndoOperationResponse",
    "IssueFeedbackType", "IssueFeedbackPayload", "IssueFeedbackSubmitResponse",
]

CLIENT_NAMES = [
    "api", "getCachedApiKey", "setTempApiKey", "clearCachedApiKey",
    "refreshCsrfToken", "getCachedCsrfToken", "getApiErrorDetail",
    "logStreamParseWarning", "API_BASE_URL",
]

LOGGER_NAMES = ["appLogger", "generateRequestId", "setCurrentRequestId"]

# 各文件本地定义、不得自动导入的符号
LOCAL_DEFS = {
    "chatApi.ts": {"ChatStreamEvent"},
    "weixinApi.ts": {"WeixinQrState", "WeixinQrStatus"},
}


def used_names(body: str, candidates: list[str], exclude: set[str]) -> list[str]:
    found = []
    for name in candidates:
        if name in exclude:
            continue
        if re.search(rf"\b{re.escape(name)}\b", body):
            found.append(name)
    return found


for fname, ranges in SEGMENTS.items():
    body = "\n\n".join(seg(a, b) for a, b in ranges)
    exclude = LOCAL_DEFS.get(fname, set())

    type_imports = used_names(body, TYPE_NAMES, exclude)
    client_imports = used_names(body, CLIENT_NAMES, exclude)
    logger_imports = used_names(body, LOGGER_NAMES, exclude)

    # authApi.ts 的 persistApiKey 包装器需要 client 的 persistApiKey 别名
    if fname == "authApi.ts":
        client_imports = [c for c in client_imports if c != "api"]
        client_imports.insert(0, "api")
        client_imports.append("persistApiKey as _persistApiKey")

    import_lines = [f"/**\n * {HEADERS[fname]}\n */"]
    if logger_imports:
        import_lines.append(
            "import { " + ", ".join(logger_imports) + " } from '@/shared/utils/logger'"
        )
    if client_imports:
        import_lines.append("import { " + ", ".join(client_imports) + " } from './client'")
    if type_imports:
        import_lines.append("import type { " + ", ".join(type_imports) + " } from './types'")

    content = "\n".join(import_lines) + "\n\n" + body + "\n"
    (API_DIR / fname).write_text(content, encoding="utf-8")
    print(f"[NEW] {fname}: {content.count(chr(10))} 行, "
          f"client={len(client_imports)}, types={len(type_imports)}, logger={len(logger_imports)}")

# api.ts 重写为 barrel
BARREL = '''/**
 * API 模块统一入口（barrel）。
 * 客户端实例和认证逻辑在 client.ts，类型定义在 types.ts，
 * 各业务端点已按域拆分至同目录的 *Api.ts 文件（chatApi/authApi/skillsApi 等）。
 * 本文件仅做聚合再导出，保持既有 `from '@/shared/api/api'` 引用方零改动。
 *
 * 认证策略：
 *   - 单用户模式：使用 API Key (Bearer) 认证
 *   - 状态变更请求自动附加 X-CSRF-Token（CSRF 防御已恢复，对应 P0-9）
 *   - 应用启动或登录成功后调用 refreshCsrfToken() 拉取 per-session CSRF token
 */
import { api } from './client'

// 向后兼容：保持原有命名导出
export {
  getCachedApiKey,
  setTempApiKey,
  clearCachedApiKey,
  getApiErrorDetail,
  logStreamParseWarning,
  refreshCsrfToken,
  getCachedCsrfToken,
} from './client'

// 领域模块聚合再导出
export * from './chatApi'
export * from './authApi'
export * from './skillsApi'
export * from './pluginsApi'
export * from './opsApi'
export * from './memoryApi'
export * from './promptsApi'
export * from './scheduledTasksApi'
export * from './conversationApi'
export * from './behaviorApi'
export * from './weixinApi'
export * from './diaryApi'
export * from './issueFeedbackApi'

// 向后兼容：axios 客户端默认导出（既有领域文件依赖）
export { api as sharedApi }
export default api
'''
SRC.write_text(BARREL, encoding="utf-8")
print(f"[BARREL] api.ts: {BARREL.count(chr(10))} 行")
