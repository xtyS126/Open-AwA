package com.xtys126.open_awa.data

import com.xtys126.open_awa.core.backend.ApiClient
import com.xtys126.open_awa.core.backend.ApiException
import com.xtys126.open_awa.data.model.UpdatePreferencesRequest
import com.xtys126.open_awa.data.model.UserPreferences
import kotlinx.serialization.json.Json

/**
 * 用户偏好仓库
 *
 * 封装 `/api/user/preferences` 接口的查询与更新。
 * 偏好以 Map<String, String?> 形式存储，前端 UI 直接按 key 读写。
 */
class PreferencesRepository {

    private val json = Json {
        ignoreUnknownKeys = true
        isLenient = true
        encodeDefaults = false
    }

    companion object {
        private const val TAG = "PreferencesRepository"
    }

    /**
     * 获取用户偏好
     *
     * @return 用户偏好映射
     * @throws ApiException 网络或 HTTP 错误时抛出
     */
    suspend fun getPreferences(): UserPreferences {
        val responseText = ApiClient.get("user/preferences")
        android.util.Log.d(TAG, "获取用户偏好: ${responseText.length} 字符")
        return runCatching {
            json.decodeFromString(UserPreferences.serializer(), responseText)
        }.getOrElse {
            // 兼容直接返回 Map 的情况：包装为 UserPreferences
            val element = json.parseToJsonElement(responseText)
            if (element is kotlinx.serialization.json.JsonObject) {
                val map = element.entries.associate { (k, v) ->
                    k to (v as? kotlinx.serialization.json.JsonPrimitive)?.content
                }
                UserPreferences(preferences = map)
            } else {
                UserPreferences()
            }
        }
    }

    /**
     * 更新用户偏好
     *
     * @param prefs 偏好映射
     * @return 更新后的完整偏好
     * @throws ApiException 网络或 HTTP 错误时抛出
     */
    suspend fun updatePreferences(prefs: Map<String, String?>): UserPreferences {
        val request = UpdatePreferencesRequest(preferences = prefs)
        android.util.Log.d(TAG, "更新用户偏好: ${prefs.size} 项")
        val responseText = ApiClient.put("user/preferences", request)
        return runCatching {
            json.decodeFromString(UserPreferences.serializer(), responseText)
        }.getOrElse {
            // 后端可能不返回 body，使用本地传入值兜底
            UserPreferences(preferences = prefs)
        }
    }
}
