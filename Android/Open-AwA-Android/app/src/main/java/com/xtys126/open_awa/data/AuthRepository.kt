package com.xtys126.open_awa.data

import android.content.Context
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import com.xtys126.open_awa.core.backend.ApiClient
import com.xtys126.open_awa.core.backend.ApiException
import com.xtys126.open_awa.data.model.LoginRequest
import com.xtys126.open_awa.data.model.RegisterRequest
import com.xtys126.open_awa.data.model.TokenResponse
import com.xtys126.open_awa.data.model.User
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map
import kotlinx.serialization.json.Json

/**
 * AuthRepository 局部 DataStore 实例
 *
 * 文件名 "auth_prefs"，存储 access_token / csrf_token
 */
private val Context.authDataStore: DataStore<Preferences> by preferencesDataStore(name = "auth_prefs")

/**
 * 认证仓库
 *
 * 封装登录、注册、登出、获取当前用户等认证相关接口：
 * 1. 通过 [ApiClient] 调用后端 `/api/auth/` 下的认证接口
 * 2. 通过 DataStore 持久化 access_token / csrf_token
 * 3. 在登录成功后调用 [ApiClient.setAccessToken] 与 [ApiClient.setCsrfToken] 注入请求头
 */
class AuthRepository(private val context: Context) {

    private val json = Json {
        ignoreUnknownKeys = true
        isLenient = true
        encodeDefaults = false
    }

    companion object {
        private const val TAG = "AuthRepository"
        private val KEY_ACCESS_TOKEN = stringPreferencesKey("access_token")
        private val KEY_CSRF_TOKEN = stringPreferencesKey("csrf_token")
    }

    /** 已保存的 access_token 流（用于在 UI 层观察登录状态） */
    val accessTokenFlow: Flow<String?> = context.authDataStore.data.map { it[KEY_ACCESS_TOKEN] }

    /** 已保存的 csrf_token 流 */
    private val csrfTokenFlow: Flow<String?> = context.authDataStore.data.map { it[KEY_CSRF_TOKEN] }

    /**
     * 登录
     *
     * @param username 用户名
     * @param password 密码
     * @return 登录成功后的令牌响应
     * @throws ApiException 网络或 HTTP 错误时抛出
     */
    suspend fun login(username: String, password: String): TokenResponse {
        val request = LoginRequest(username = username, password = password)
        // 按任务约定调用 ApiClient.post，请求体为 LoginRequest
        val responseText = ApiClient.post("auth/login", request)
        val token = json.decodeFromString<TokenResponse>(responseText)
        saveTokens(token.access_token, token.csrf_token)
        return token
    }

    /**
     * 注册
     *
     * @param username 用户名
     * @param password 密码
     * @param email 邮箱（可选）
     * @return 注册成功后的登录令牌（若后端直接返回令牌）
     * @throws ApiException 网络或 HTTP 错误时抛出
     */
    suspend fun register(username: String, password: String, email: String): TokenResponse {
        val request = RegisterRequest(username = username, password = password, email = email)
        val responseText = ApiClient.post("auth/register", request)
        // 兼容两种后端实现：返回 TokenResponse 或返回 User（注册后需另行登录）
        return runCatching {
            json.decodeFromString<TokenResponse>(responseText)
        }.getOrElse {
            // 若后端不返回令牌，则直接登录
            login(username, password)
        }
    }

    /**
     * 登出
     *
     * 通知后端清理会话，并清除本地持久化的令牌。
     * 即使后端登出接口调用失败也必须清除本地令牌，避免用户停留在已登录态。
     */
    suspend fun logout() {
        runCatching {
            ApiClient.post("auth/logout")
        }.onFailure { e ->
            // 后端登出失败不阻塞本地清理，仅记录警告
            android.util.Log.w(TAG, "后端登出接口调用失败: ${e.message}", e)
        }
        clearTokens()
    }

    /**
     * 获取当前登录用户
     *
     * @return 当前用户信息
     * @throws ApiException 网络或 HTTP 错误时抛出
     */
    suspend fun getCurrentUser(): User {
        val responseText = ApiClient.get("auth/me")
        return json.decodeFromString<User>(responseText)
    }

    /**
     * 判断是否已登录
     *
     * 通过 DataStore 中是否持久化了 access_token 判断
     */
    suspend fun isAuthenticated(): Boolean {
        return accessTokenFlow.first() != null
    }

    /**
     * 应用启动时恢复令牌到 ApiClient
     *
     * 应在 Application.onCreate 或 MainActivity 启动时调用
     */
    suspend fun restoreTokens() {
        val token = accessTokenFlow.first()
        val csrf = csrfTokenFlow.first()
        ApiClient.setAccessToken(token)
        ApiClient.setCsrfToken(csrf)
    }

    /**
     * 保存令牌到 DataStore 并同步到 ApiClient
     */
    private suspend fun saveTokens(accessToken: String, csrfToken: String?) {
        context.authDataStore.edit { prefs ->
            prefs[KEY_ACCESS_TOKEN] = accessToken
            csrfToken?.let { prefs[KEY_CSRF_TOKEN] = it }
        }
        ApiClient.setAccessToken(accessToken)
        ApiClient.setCsrfToken(csrfToken)
    }

    /**
     * 清除所有令牌
     */
    private suspend fun clearTokens() {
        context.authDataStore.edit { prefs ->
            prefs.remove(KEY_ACCESS_TOKEN)
            prefs.remove(KEY_CSRF_TOKEN)
        }
        ApiClient.setAccessToken(null)
        ApiClient.setCsrfToken(null)
    }
}
