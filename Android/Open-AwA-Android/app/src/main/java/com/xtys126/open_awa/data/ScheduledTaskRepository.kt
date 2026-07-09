package com.xtys126.open_awa.data

import android.util.Log
import com.xtys126.open_awa.core.backend.ApiClient
import com.xtys126.open_awa.data.model.CreateScheduledTaskRequest
import com.xtys126.open_awa.data.model.ScheduledTask
import com.xtys126.open_awa.data.model.ScheduledTaskExecution
import com.xtys126.open_awa.data.model.UpdateScheduledTaskRequest
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject

/**
 * 定时任务仓库
 *
 * 对接后端 `/api/scheduled-tasks` 系列接口，提供 6 个 REST 方法：
 * 1. [listTasks]：GET /api/scheduled-tasks —— 列表查询（支持 status 筛选与 limit 限制）
 * 2. [listExecutions]：GET /api/scheduled-tasks/executions —— 执行历史
 * 3. [createTask]：POST /api/scheduled-tasks —— 创建任务
 * 4. [triggerTask]：POST /api/scheduled-tasks/{id}/trigger —— 手动触发
 * 5. [cancelTask]：DELETE /api/scheduled-tasks/{id} —— 取消任务
 * 6. [updateTask]：PUT /api/scheduled-tasks/{id} —— 更新任务
 *
 * 后端响应格式约定：
 * - 列表接口：直接返回数组 `[ScheduledTask, ...]`（或包装在 `{tasks: [...]}` 中，
 *   本仓库兼容两种格式，优先按数组解析）
 * - 单条接口：返回 `ScheduledTask` 对象
 *
 * 所有方法在失败时抛 [com.xtys126.open_awa.core.backend.ApiException]，
 * 调用方应在 `runCatching` 中处理。
 */
class ScheduledTaskRepository {

    private val json = Json { ignoreUnknownKeys = true }

    /**
     * 拉取定时任务列表
     *
     * 对应后端 `GET /api/scheduled-tasks?status={status}&limit={limit}`。
     *
     * @param status 状态筛选（pending / running / completed / failed / cancelled），为空表示不筛选
     * @param limit 返回条数上限（默认 50）
     * @return 任务列表（按 created_at 倒序）
     * @throws com.xtys126.open_awa.core.backend.ApiException 网络或 HTTP 错误时抛出
     */
    suspend fun listTasks(status: String? = null, limit: Int = 50): List<ScheduledTask> {
        val query = buildString {
            var hasParam = false
            if (!status.isNullOrBlank()) {
                append("status=").append(status)
                hasParam = true
            }
            if (limit > 0) {
                if (hasParam) append("&")
                append("limit=").append(limit)
            }
        }
        val path = if (query.isEmpty()) "scheduled-tasks" else "scheduled-tasks?$query"
        val text = ApiClient.get(path)
        return parseTaskList(text)
    }

    /**
     * 拉取执行历史
     *
     * 对应后端 `GET /api/scheduled-tasks/executions?task_id={taskId}&limit={limit}`。
     *
     * @param taskId 任务 ID 筛选（为空表示拉取所有任务的执行历史）
     * @param limit 返回条数上限（默认 50）
     * @return 执行历史列表（按 started_at 倒序）
     * @throws com.xtys126.open_awa.core.backend.ApiException 网络或 HTTP 错误时抛出
     */
    suspend fun listExecutions(taskId: Int? = null, limit: Int = 50): List<ScheduledTaskExecution> {
        val query = buildString {
            var hasParam = false
            if (taskId != null) {
                append("task_id=").append(taskId)
                hasParam = true
            }
            if (limit > 0) {
                if (hasParam) append("&")
                append("limit=").append(limit)
            }
        }
        val path = if (query.isEmpty()) "scheduled-tasks/executions" else "scheduled-tasks/executions?$query"
        val text = ApiClient.get(path)
        return parseExecutionList(text)
    }

    /**
     * 创建定时任务
     *
     * 对应后端 `POST /api/scheduled-tasks`。
     *
     * @param request 创建请求体（必填：title、prompt、scheduledAt 或 isDaily+dailyTime）
     * @return 创建后的任务对象（含后端分配的 id）
     * @throws com.xtys126.open_awa.core.backend.ApiException 网络或 HTTP 错误时抛出
     */
    suspend fun createTask(request: CreateScheduledTaskRequest): ScheduledTask {
        val text = ApiClient.post("scheduled-tasks", request)
        return json.decodeFromString(ScheduledTask.serializer(), text)
    }

    /**
     * 手动触发任务
     *
     * 对应后端 `POST /api/scheduled-tasks/{id}/trigger`。
     *
     * @param taskId 任务 ID
     * @return 触发后的任务对象（status 通常变为 running）
     * @throws com.xtys126.open_awa.core.backend.ApiException 网络或 HTTP 错误时抛出
     */
    suspend fun triggerTask(taskId: Int): ScheduledTask {
        val text = ApiClient.post("scheduled-tasks/$taskId/trigger")
        return json.decodeFromString(ScheduledTask.serializer(), text)
    }

    /**
     * 取消任务
     *
     * 对应后端 `DELETE /api/scheduled-tasks/{id}`。
     * 取消后 status 变为 cancelled，cancelled_at 字段被填充。
     *
     * @param taskId 任务 ID
     * @throws com.xtys126.open_awa.core.backend.ApiException 网络或 HTTP 错误时抛出
     */
    suspend fun cancelTask(taskId: Int) {
        ApiClient.delete("scheduled-tasks/$taskId")
    }

    /**
     * 更新任务
     *
     * 对应后端 `PUT /api/scheduled-tasks/{id}`。
     * 支持部分更新，仅传入需要修改的字段。
     *
     * @param taskId 任务 ID
     * @param request 更新请求体
     * @return 更新后的任务对象
     * @throws com.xtys126.open_awa.core.backend.ApiException 网络或 HTTP 错误时抛出
     */
    suspend fun updateTask(taskId: Int, request: UpdateScheduledTaskRequest): ScheduledTask {
        val text = ApiClient.put("scheduled-tasks/$taskId", request)
        return json.decodeFromString(ScheduledTask.serializer(), text)
    }

    /**
     * 解析任务列表响应
     *
     * 兼容两种后端响应格式：
     * 1. 直接数组：`[{id: 1, ...}, {id: 2, ...}]`
     * 2. 包装对象：`{tasks: [{id: 1, ...}, ...]}` 或 `{data: [...]}`
     *
     * @param text HTTP 响应文本
     * @return 任务列表
     */
    private fun parseTaskList(text: String): List<ScheduledTask> {
        return try {
            // 优先按数组解析
            json.decodeFromString(
                kotlinx.serialization.builtins.ListSerializer(ScheduledTask.serializer()),
                text,
            )
        } catch (e: Exception) {
            // 数组解析失败，尝试从对象中提取 tasks / data 字段
            try {
                val obj = json.parseToJsonElement(text).jsonObject
                val arr = obj["tasks"] ?: obj["data"] ?: obj["items"]
                if (arr != null) {
                    json.decodeFromString(
                        kotlinx.serialization.builtins.ListSerializer(ScheduledTask.serializer()),
                        arr.toString(),
                    )
                } else {
                    Log.w(TAG, "无法识别的任务列表格式: ${text.take(200)}")
                    emptyList()
                }
            } catch (e2: Exception) {
                Log.w(TAG, "解析任务列表失败: ${e2.message}", e2)
                emptyList()
            }
        }
    }

    /**
     * 解析执行历史列表响应
     *
     * 同 [parseTaskList]，兼容数组与包装对象两种格式。
     *
     * @param text HTTP 响应文本
     * @return 执行历史列表
     */
    private fun parseExecutionList(text: String): List<ScheduledTaskExecution> {
        return try {
            json.decodeFromString(
                kotlinx.serialization.builtins.ListSerializer(ScheduledTaskExecution.serializer()),
                text,
            )
        } catch (e: Exception) {
            try {
                val obj = json.parseToJsonElement(text).jsonObject
                val arr = obj["executions"] ?: obj["data"] ?: obj["items"]
                if (arr != null) {
                    json.decodeFromString(
                        kotlinx.serialization.builtins.ListSerializer(ScheduledTaskExecution.serializer()),
                        arr.toString(),
                    )
                } else {
                    Log.w(TAG, "无法识别的执行历史格式: ${text.take(200)}")
                    emptyList()
                }
            } catch (e2: Exception) {
                Log.w(TAG, "解析执行历史失败: ${e2.message}", e2)
                emptyList()
            }
        }
    }

    companion object {
        private const val TAG = "ScheduledTaskRepo"
    }
}
