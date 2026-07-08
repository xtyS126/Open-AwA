package com.xtys126.open_awa.data

import com.xtys126.open_awa.core.backend.ApiClient
import com.xtys126.open_awa.core.backend.ApiException
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject

/**
 * ACP Agent 信息
 *
 * 对应后端 `GET /api/acp/agents` 返回的 AgentInfo 结构。
 * available 字段由后端探测本地 CLI 是否安装后给出。
 */
@Serializable
data class AcpAgent(
    val id: String,
    val name: String,
    val command: String = "",
    val enabled: Boolean = true,
    val available: Boolean = false,
)

/**
 * Agent 列表响应
 *
 * 对应后端 `GET /api/acp/agents` 的 AgentListResponse。
 */
@Serializable
data class AgentListResponse(
    val agents: List<AcpAgent> = emptyList(),
    val count: Int = 0,
)

/**
 * ACP 会话信息
 *
 * 对应后端 `GET /api/acp/sessions` 返回的 SessionInfo 结构。
 */
@Serializable
data class AcpSession(
    @SerialName("session_id") val sessionId: String,
    val agent: String,
    val cwd: String = "",
    @SerialName("created_at") val createdAt: String = "",
)

/**
 * 会话列表响应
 */
@Serializable
data class SessionListResponse(
    val sessions: List<AcpSession> = emptyList(),
    val count: Int = 0,
)

/**
 * 创建会话请求体
 */
@Serializable
data class SessionCreateRequest(
    val agent: String,
    val cwd: String,
)

/**
 * 创建会话响应
 *
 * 对应后端 `POST /api/acp/sessions` 的 SessionCreateResponse。
 */
@Serializable
data class SessionCreateResponse(
    @SerialName("session_id") val sessionId: String,
    @SerialName("config_options") val configOptions: List<JsonObject> = emptyList(),
)

/**
 * 发起 prompt 请求体
 */
@Serializable
data class PromptRequest(
    val prompt: String,
    val restart: Boolean = false,
)

/**
 * 权限审批选项
 *
 * 对应后端 permission 事件 options 数组中的元素结构（对齐 acp.schema.PermissionOption）。
 */
@Serializable
data class AcpPermissionOption(
    @SerialName("optionId") val optionId: String,
    val name: String = "",
    val kind: String = "",
)

/**
 * 权限审批请求体
 */
@Serializable
data class PermissionResponseRequest(
    @SerialName("option_id") val optionId: String,
)

/**
 * ACP 事件
 *
 * 对应后端 SSE 推送的事件帧。后端 event 头取值：
 * text / tool / status / permission / usage / result / error。
 * data 字段为 JSON 对象，包含 type / text / name / call_id / kind / status /
 * detail / target / summary / tool_name / tool_kind / options / message 等字段。
 *
 * sseType 字段保存 SSE event 头的值（用于 UI 路由事件类型），
 * 其余字段从 data JSON 中按需解析，缺失时使用默认空值。
 * 注意：status 字段在不同事件中含义不同：
 * - tool 事件：pending/completed/failed（工具执行状态）
 * - result 事件：completed/permission_required（本轮整体结束状态）
 */
@Serializable
data class AcpEvent(
    /** SSE event 头的值：text/tool/status/permission/usage/result/error */
    val sseType: String = "",
    /** payload.type 字段：text/tool_start/tool_end/tool_update/permission_request 等 */
    val type: String = "",
    /** text 事件的文本内容（增量片段） */
    val text: String = "",
    /** 工具名称（tool 事件的 name 字段） */
    val name: String = "",
    /** 工具调用 ID（tool 事件用于去重/更新同一调用） */
    @SerialName("call_id") val callId: String = "",
    /** 工具标题（tool 事件） */
    val title: String = "",
    /** 工具类别：execute/read/search/edit/other */
    val kind: String = "",
    /** 工具状态：pending/completed/failed */
    val status: String = "",
    /** 工具详细描述（tool 事件） */
    val detail: String = "",
    /** 工具目标路径（tool 事件） */
    val target: String = "",
    /** 工具输出摘要（tool 事件） */
    val summary: String = "",
    /** 权限请求标题（permission 事件） */
    val toolName: String = "",
    /** 权限请求工具类别（permission 事件） */
    val toolKind: String = "",
    /** 权限审批选项列表（permission 事件） */
    val options: List<AcpPermissionOption> = emptyList(),
    /** 错误消息（error 事件） */
    val message: String = "",
)

/**
 * ACP 仓库
 *
 * 封装后端 `/api/acp/` 下的 ACP vibe coding 接口：
 * 1. Agent 列表查询（[listAgents]）
 * 2. 会话创建/查询/关闭（[createSession] / [listSessions] / [closeSession]）
 * 3. 流式发送 prompt（[streamPrompt]，通过 SSE 接收 Agent 事件）
 * 4. 权限审批（[resolvePermission]）
 * 5. 取消当前轮次（[cancelTurn]）
 *
 * 所有接口通过 [ApiClient] 调用后端，鉴权头由 ApiClient 统一注入。
 */
class AcpRepository {

    private val json = Json {
        ignoreUnknownKeys = true
        isLenient = true
        encodeDefaults = false
    }

    /**
     * 列出所有已注册的 ACP Agent
     *
     * @return Agent 列表（含 available 字段标识本地 CLI 是否安装）
     * @throws ApiException 网络或 HTTP 错误时抛出
     */
    suspend fun listAgents(): List<AcpAgent> {
        val text = ApiClient.get("acp/agents")
        val resp = json.decodeFromString(AgentListResponse.serializer(), text)
        return resp.agents
    }

    /**
     * 列出当前用户的活动 ACP 会话
     *
     * @return 会话列表
     * @throws ApiException 网络或 HTTP 错误时抛出
     */
    suspend fun listSessions(): List<AcpSession> {
        val text = ApiClient.get("acp/sessions")
        val resp = json.decodeFromString(SessionListResponse.serializer(), text)
        return resp.sessions
    }

    /**
     * 创建 ACP 会话
     *
     * @param agentId Agent 标识（claude_code/codex/openclaw/opencode）
     * @param cwd 工作目录，为空时后端使用默认白名单目录
     * @return 新建的会话对象（sessionId 由后端生成）
     * @throws ApiException 网络或 HTTP 错误时抛出
     */
    suspend fun createSession(agentId: String, cwd: String = ""): AcpSession {
        val request = SessionCreateRequest(agent = agentId, cwd = cwd)
        val text = ApiClient.post("acp/sessions", request)
        val resp = json.decodeFromString(SessionCreateResponse.serializer(), text)
        // 后端创建会话只返回 session_id，agent 与 cwd 由前端补全
        return AcpSession(
            sessionId = resp.sessionId,
            agent = agentId,
            cwd = cwd,
            createdAt = "",
        )
    }

    /**
     * 关闭并移除指定 ACP 会话
     *
     * @param sessionId 会话 ID
     * @throws ApiException 网络或 HTTP 错误时抛出
     */
    suspend fun closeSession(sessionId: String) {
        ApiClient.delete("acp/sessions/$sessionId")
    }

    /**
     * 流式发送 prompt
     *
     * 调用后端 `POST /api/acp/sessions/{id}/prompt`，通过 SSE 接收 Agent 事件流。
     * 每个 SSE 帧转为 [AcpEvent] 推送给调用方。
     *
     * 事件类型说明（sseType 字段）：
     * - text: 文本输出，追加到当前 AI 消息
     * - tool: 工具调用事件，更新工具调用列表
     * - permission: 权限审批请求，弹出审批对话框
     * - result: 一轮 prompt 结束
     * - error: 错误信息
     * - status/usage: 状态变更与用量统计（UI 可忽略或显示）
     *
     * @param sessionId 会话 ID
     * @param message 用户 prompt 内容
     * @return ACP 事件流
     */
    fun streamPrompt(sessionId: String, message: String): Flow<AcpEvent> {
        val request = PromptRequest(prompt = message)
        val requestJson = json.encodeToString(PromptRequest.serializer(), request)
        val path = "acp/sessions/$sessionId/prompt"

        return ApiClient.streamSSE(path = path, requestJson = requestJson).map { (sseType, data) ->
            // SSE data 字段为 JSON 字符串，解析为 AcpEvent 后补全 sseType
            if (data.isBlank()) {
                AcpEvent(sseType = sseType)
            } else {
                val parsed = json.decodeFromString(AcpEvent.serializer(), data)
                parsed.copy(sseType = sseType)
            }
        }
    }

    /**
     * 响应权限审批请求
     *
     * 调用后端 `POST /api/acp/sessions/{id}/permission`，传入用户选择的 option_id。
     * 后端通过 ACPService.resume_permission 恢复 Agent 执行。
     *
     * @param sessionId 会话 ID
     * @param optionId 用户选择的审批选项 ID（来自 [AcpEvent.options] 的 optionId 字段）
     * @throws ApiException 网络或 HTTP 错误时抛出
     */
    suspend fun resolvePermission(sessionId: String, optionId: String) {
        val request = PermissionResponseRequest(optionId = optionId)
        ApiClient.post("acp/sessions/$sessionId/permission", request)
    }

    /**
     * 取消当前正在进行的 prompt 轮次
     *
     * 调用后端 `POST /api/acp/sessions/{id}/cancel`，触发 ACPService.cancel_turn
     * 终止 Agent 子进程当前任务。
     *
     * @param sessionId 会话 ID
     * @throws ApiException 网络或 HTTP 错误时抛出
     */
    suspend fun cancelTurn(sessionId: String) {
        ApiClient.post("acp/sessions/$sessionId/cancel")
    }
}
