package com.xtys126.open_awa.data

import android.util.Log
import com.xtys126.open_awa.core.backend.ApiClient
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json

/**
 * 陪伴者信念维度状态
 *
 * 对应后端 `BeliefNetwork.to_dict()` 的单个信念条目，
 * 三个字段均为 [0, 1] 区间的连续心理变量：
 * - [value] 信念当前值（如 0.5 表示中立）
 * - [strain] 应变：可恢复的心理压力，随时间指数衰减
 * - [load] 负荷：不可逆的心理损伤（疤痕组织），永不衰减
 */
@Serializable
data class CompanionBeliefNode(
    val value: Float = 0.5f,
    val strain: Float = 0f,
    val load: Float = 0f,
)

/**
 * 陪伴者情绪状态
 *
 * 对应后端 `EmotionState.to_dict()`（OCC 评估模型推导）：
 * - [primary] 主情绪（joy / sadness / anger / surprise / neutral 等）
 * - [secondary] 副情绪
 * - [intensity] 强度 [0, 1]，决定情感通道占比
 * - [valence] 效价 [-1, 1]，正值积极、负值消极
 * - [ambivalence] 情绪矛盾标记
 */
@Serializable
data class CompanionEmotion(
    val primary: String = "neutral",
    val secondary: String = "neutral",
    val intensity: Float = 0f,
    val valence: Float = 0f,
    val ambivalence: Boolean = false,
)

/**
 * 涌现弧线条目
 *
 * 对应后端观察者（observer.detect_arcs）检测到的信念演化轨迹弧线。
 */
@Serializable
data class CompanionArc(
    val belief: String = "",
    val arc: String = "",
)

/**
 * 陪伴者心智状态响应
 *
 * 对应后端 `GET /api/companion/state` 返回结构：
 * 羁绊等级、轮次、总对话数、信念网络、情绪、引导文本、涌现弧线与时间线。
 */
@Serializable
data class CompanionStateResponse(
    @SerialName("user_id") val userId: String = "",
    @SerialName("role_id") val roleId: String = "",
    @SerialName("bond_level") val bondLevel: Int = 1,
    val turn: Int = 0,
    @SerialName("total_conversations") val totalConversations: Int = 0,
    val beliefs: Map<String, CompanionBeliefNode> = emptyMap(),
    val emotion: CompanionEmotion = CompanionEmotion(),
    val guidance: String = "",
    val arcs: List<CompanionArc> = emptyList(),
    @SerialName("first_met_at") val firstMetAt: String? = null,
    @SerialName("last_interaction_at") val lastInteractionAt: String? = null,
)

/**
 * 睡眠整合响应
 *
 * 对应后端 `POST /api/companion/sleep` 返回结构：
 * 执行应变恢复、情绪衰减、记忆整合、人格存档、观察者分析后的状态摘要。
 */
@Serializable
data class CompanionSleepResponse(
    val success: Boolean = false,
    val turn: Int = 0,
    val emotion: CompanionEmotion = CompanionEmotion(),
    val arcs: List<CompanionArc> = emptyList(),
)

/**
 * 陪伴事件条目
 *
 * 对应后端 `GET /api/companion/check-events` 返回的事件：
 * 纪念日（相识天数命中特殊节点）与心智灾变里程碑。
 */
@Serializable
data class CompanionEvent(
    val type: String = "",
    val title: String = "",
    val body: String = "",
    @SerialName("navigate_to") val navigateTo: String? = null,
)

/**
 * 陪伴事件检查响应
 *
 * 对应后端 `GET /api/companion/check-events` 返回结构。
 */
@Serializable
data class CompanionCheckEventsResponse(
    val success: Boolean = true,
    val events: List<CompanionEvent> = emptyList(),
    @SerialName("checked_at") val checkedAt: String = "",
)

/**
 * 陪伴心智仓库
 *
 * 对接后端陪伴系统（`/api/companion`）三大能力：
 * 1. [getState]：查询陪伴者心智状态（信念/情绪/羁绊）
 * 2. [triggerSleep]：触发睡眠整合（应变恢复/情绪衰减/记忆整合）
 * 3. [checkEvents]：检查待通知的陪伴事件（纪念日/心智灾变）
 *
 * 对应后端 backend/api/routes/companion.py（commit 199ea5be 引入）。
 */
class CompanionRepository {

    private val json = Json { ignoreUnknownKeys = true }

    /**
     * 查询陪伴者心智状态
     *
     * 对应后端 `GET /api/companion/state`。
     *
     * @param roleId 角色 ID（空字符串表示默认陪伴状态）
     * @return 心智状态（羁绊等级、轮次、信念网络、情绪、引导文本、涌现弧线）
     * @throws com.xtys126.open_awa.core.backend.ApiException 网络或 HTTP 错误时抛出
     */
    suspend fun getState(roleId: String = ""): CompanionStateResponse {
        val text = ApiClient.get("companion/state?role_id=$roleId")
        return json.decodeFromString(CompanionStateResponse.serializer(), text)
    }

    /**
     * 触发睡眠整合
     *
     * 对应后端 `POST /api/companion/sleep`：
     * 执行应变恢复、情绪衰减、记忆整合、人格存档与观察者分析。
     *
     * @param roleId 角色 ID（空字符串表示默认陪伴状态）
     * @return 整合后的状态摘要（轮次、情绪、涌现弧线）
     * @throws com.xtys126.open_awa.core.backend.ApiException 网络或 HTTP 错误时抛出
     */
    suspend fun triggerSleep(roleId: String = ""): CompanionSleepResponse {
        val text = ApiClient.post("companion/sleep?role_id=$roleId")
        return json.decodeFromString(CompanionSleepResponse.serializer(), text)
    }

    /**
     * 检查陪伴事件
     *
     * 对应后端 `GET /api/companion/check-events`：
     * 检查当前用户是否有需要通知的陪伴事件（纪念日、心智灾变）。
     *
     * @return 事件检查响应（事件列表与检查时间）
     * @throws com.xtys126.open_awa.core.backend.ApiException 网络或 HTTP 错误时抛出
     */
    suspend fun checkEvents(): CompanionCheckEventsResponse {
        val text = ApiClient.get("companion/check-events")
        return json.decodeFromString(CompanionCheckEventsResponse.serializer(), text)
    }

    companion object {
        private const val TAG = "CompanionRepository"

        /** 信念维度的中文显示名映射（对应后端 DEFAULT_BELIEFS 五个维度） */
        val BELIEF_LABELS: Map<String, String> = mapOf(
            "people_are_trustworthy" to "人际信赖",
            "self_worth" to "自我价值",
            "duty_above_desire" to "责任优先",
            "vulnerability_is_weakness" to "脆弱防御",
            "affection_for_user" to "对你的好感",
        )

        /**
         * 获取信念维度的中文显示名
         *
         * @param key 信念维度英文键名
         * @return 中文显示名，未收录的维度原样返回
         */
        fun beliefLabel(key: String): String = BELIEF_LABELS[key] ?: key

        /** 情绪的中文显示名映射（对应后端 OCC 评估推导的主/副情绪） */
        private val EMOTION_LABELS: Map<String, String> = mapOf(
            "joy" to "喜悦",
            "sadness" to "难过",
            "anger" to "生气",
            "surprise" to "惊讶",
            "neutral" to "平静",
        )

        /**
         * 获取情绪的中文显示名
         *
         * @param key 情绪英文键名
         * @return 中文显示名，未收录的情绪原样返回
         */
        fun emotionLabel(key: String): String = EMOTION_LABELS[key] ?: key

        /** 记录仓库级日志标记（预留调试用） */
        @Suppress("unused")
        private fun logTag(): String = TAG
    }
}
