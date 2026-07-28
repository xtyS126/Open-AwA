package com.xtys126.open_awa.data

import android.content.Context
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import com.xtys126.open_awa.core.backend.ApiException
import com.xtys126.open_awa.data.model.Message
import com.xtys126.open_awa.data.model.Session
import com.xtys126.open_awa.data.model.User
import com.xtys126.open_awa.data.model.UserPreferences
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/**
 * 通用 UI 状态封装
 *
 * 用于表示接口调用的四态：空闲 / 加载中 / 成功 / 失败
 */
sealed interface UiState<out T> {
    /** 初始空闲态 */
    data object Idle : UiState<Nothing>

    /** 加载中 */
    data object Loading : UiState<Nothing>

    /** 成功，携带数据 */
    data class Success<T>(val data: T) : UiState<T>

    /** 失败，携带错误信息 */
    data class Error(val message: String) : UiState<Nothing>
}

/**
 * 将异常转换为用户可读消息的顶层工具函数
 *
 * 使用顶层函数而非成员扩展函数，避免在 viewModelScope.launch 的 lambda 内
 * 因 this 指向 CoroutineScope 而无法访问扩展函数的问题
 */
private fun errorMessage(e: Throwable): String = when (e) {
    is ApiException.NetworkError -> "网络错误: ${e.message}"
    is ApiException.HttpError -> "HTTP ${e.statusCode}: ${e.responseText.take(200)}"
    else -> e.message ?: "未知错误"
}

/**
 * 认证 ViewModel
 *
 * 暴露登录、注册、登出、获取当前用户的状态流与方法。
 * UI 通过 [loginState] 观察当前操作的状态。
 */
class AuthViewModel(private val repository: AuthRepository) : ViewModel() {

    /** 登录/注册/登出等操作的统一状态流 */
    private val _loginState = MutableStateFlow<UiState<Unit>>(UiState.Idle)
    val loginState: StateFlow<UiState<Unit>> = _loginState.asStateFlow()

    /** 当前登录用户（登录成功后写入） */
    private val _currentUser = MutableStateFlow<User?>(null)
    val currentUser: StateFlow<User?> = _currentUser.asStateFlow()

    /**
     * 登录
     */
    fun login(username: String, password: String) {
        _loginState.value = UiState.Loading
        viewModelScope.launch {
            runCatching {
                repository.login(username, password)
            }.onSuccess {
                _loginState.value = UiState.Success(Unit)
                fetchCurrentUser()
            }.onFailure { e ->
                _loginState.value = UiState.Error(errorMessage(e))
            }
        }
    }

    /**
     * 注册
     */
    fun register(username: String, password: String, email: String) {
        _loginState.value = UiState.Loading
        viewModelScope.launch {
            runCatching {
                repository.register(username, password, email)
            }.onSuccess {
                _loginState.value = UiState.Success(Unit)
                fetchCurrentUser()
            }.onFailure { e ->
                _loginState.value = UiState.Error(errorMessage(e))
            }
        }
    }

    /**
     * 登出
     */
    fun logout() {
        _loginState.value = UiState.Loading
        viewModelScope.launch {
            runCatching {
                repository.logout()
            }.onSuccess {
                _currentUser.value = null
                _loginState.value = UiState.Success(Unit)
            }.onFailure { e ->
                _loginState.value = UiState.Error(errorMessage(e))
            }
        }
    }

    /**
     * 拉取当前用户信息（登录成功后或恢复登录态时调用）
     */
    fun fetchCurrentUser() {
        viewModelScope.launch {
            runCatching {
                repository.getCurrentUser()
            }.onSuccess { user ->
                _currentUser.value = user
            }.onFailure { e ->
                // 拉取用户失败不阻塞主流程，仅记录在 loginState 中
                _loginState.value = UiState.Error(errorMessage(e))
            }
        }
    }

    /**
     * 重置登录状态为 Idle（UI 离开页面时调用避免重复提示错误）
     */
    fun resetState() {
        _loginState.value = UiState.Idle
    }
}

/**
 * 聊天 ViewModel
 *
 * 暴露会话列表、当前会话消息、发送消息等状态流与方法。
 */
class ChatViewModel(private val repository: ChatRepository) : ViewModel() {

    /** 会话列表 */
    private val _sessions = MutableStateFlow<List<Session>>(emptyList())
    val sessions: StateFlow<List<Session>> = _sessions.asStateFlow()

    /** 当前会话的消息列表 */
    private val _currentMessages = MutableStateFlow<List<Message>>(emptyList())
    val currentMessages: StateFlow<List<Message>> = _currentMessages.asStateFlow()

    /** 当前选中的会话 ID */
    private val _currentSessionId = MutableStateFlow<String?>(null)
    val currentSessionId: StateFlow<String?> = _currentSessionId.asStateFlow()

    /** 操作状态（拉取会话/发送消息等） */
    private val _operationState = MutableStateFlow<UiState<Unit>>(UiState.Idle)
    val operationState: StateFlow<UiState<Unit>> = _operationState.asStateFlow()

    /**
     * 拉取会话列表
     */
    fun loadSessions() {
        _operationState.value = UiState.Loading
        viewModelScope.launch {
            runCatching {
                repository.getSessions()
            }.onSuccess { list ->
                _sessions.value = list
                _operationState.value = UiState.Success(Unit)
            }.onFailure { e ->
                _operationState.value = UiState.Error(errorMessage(e))
            }
        }
    }

    /**
     * 创建新会话
     */
    fun createSession(title: String? = null) {
        _operationState.value = UiState.Loading
        viewModelScope.launch {
            runCatching {
                repository.createSession(title)
            }.onSuccess { session ->
                _sessions.update { listOf(session) + it }
                _operationState.value = UiState.Success(Unit)
            }.onFailure { e ->
                _operationState.value = UiState.Error(errorMessage(e))
            }
        }
    }

    /**
     * 删除会话
     */
    fun deleteSession(id: Int) {
        viewModelScope.launch {
            runCatching {
                repository.deleteSession(id)
            }.onSuccess {
                _sessions.update { list -> list.filter { it.id != id } }
                // 若删除的是当前会话，清空消息
                if (_currentSessionId.value == id.toString()) {
                    _currentMessages.value = emptyList()
                    _currentSessionId.value = null
                }
            }.onFailure { e ->
                _operationState.value = UiState.Error(errorMessage(e))
            }
        }
    }

    /**
     * 选择会话并拉取历史消息
     */
    fun selectSession(sessionId: String) {
        _currentSessionId.value = sessionId
        _operationState.value = UiState.Loading
        viewModelScope.launch {
            runCatching {
                repository.getHistory(sessionId)
            }.onSuccess { messages ->
                _currentMessages.value = messages
                _operationState.value = UiState.Success(Unit)
            }.onFailure { e ->
                _currentMessages.value = emptyList()
                _operationState.value = UiState.Error(errorMessage(e))
            }
        }
    }

    /**
     * 发送消息
     */
    fun sendMessage(sessionId: Int, content: String) {
        if (content.isBlank()) return
        _operationState.value = UiState.Loading
        viewModelScope.launch {
            runCatching {
                repository.sendMessage(sessionId, content)
            }.onSuccess { message ->
                _currentMessages.update { it + message }
                _operationState.value = UiState.Success(Unit)
            }.onFailure { e ->
                _operationState.value = UiState.Error(errorMessage(e))
            }
        }
    }

    /**
     * 重置操作状态
     */
    fun resetState() {
        _operationState.value = UiState.Idle
    }
}

/**
 * 用户偏好 ViewModel
 */
class PreferencesViewModel(private val repository: PreferencesRepository) : ViewModel() {

    /** 用户偏好映射 */
    private val _preferences = MutableStateFlow<UserPreferences>(UserPreferences())
    val preferences: StateFlow<UserPreferences> = _preferences.asStateFlow()

    /** 操作状态 */
    private val _operationState = MutableStateFlow<UiState<Unit>>(UiState.Idle)
    val operationState: StateFlow<UiState<Unit>> = _operationState.asStateFlow()

    /**
     * 拉取用户偏好
     */
    fun loadPreferences() {
        _operationState.value = UiState.Loading
        viewModelScope.launch {
            runCatching {
                repository.getPreferences()
            }.onSuccess { prefs ->
                _preferences.value = prefs
                _operationState.value = UiState.Success(Unit)
            }.onFailure { e ->
                _operationState.value = UiState.Error(errorMessage(e))
            }
        }
    }

    /**
     * 更新单个偏好项
     */
    fun updatePreference(key: String, value: String?) {
        val updated = _preferences.value.preferences.toMutableMap().apply {
            this[key] = value
        }
        _operationState.value = UiState.Loading
        viewModelScope.launch {
            runCatching {
                repository.updatePreferences(updated)
            }.onSuccess { prefs ->
                _preferences.value = prefs
                _operationState.value = UiState.Success(Unit)
            }.onFailure { e ->
                _operationState.value = UiState.Error(errorMessage(e))
            }
        }
    }

    /**
     * 批量更新偏好
     */
    fun updatePreferences(prefs: Map<String, String?>) {
        _operationState.value = UiState.Loading
        viewModelScope.launch {
            runCatching {
                repository.updatePreferences(prefs)
            }.onSuccess { updated ->
                _preferences.value = updated
                _operationState.value = UiState.Success(Unit)
            }.onFailure { e ->
                _operationState.value = UiState.Error(errorMessage(e))
            }
        }
    }
}

/**
 * ViewModel 工厂
 *
 * 根据 Application Context 创建三个核心 ViewModel：
 * - [AuthViewModel]（依赖 [AuthRepository]，需要 Context 访问 DataStore）
 * - [ChatViewModel]（依赖 [ChatRepository]）
 * - [PreferencesViewModel]（依赖 [PreferencesRepository]）
 *
 * 使用方式（在 Compose 中）：
 * ```
 * val factory = ViewModelFactory(context)
 * val authVm: AuthViewModel = viewModel(factory = factory)
 * ```
 */
class ViewModelFactory(private val context: Context) : ViewModelProvider.Factory {

    /** 懒加载的 Repository 单例，避免在多次创建 ViewModel 时重复实例化 */
    private val authRepository: AuthRepository by lazy { AuthRepository(context.applicationContext) }
    private val chatRepository: ChatRepository by lazy { ChatRepository() }
    private val preferencesRepository: PreferencesRepository by lazy { PreferencesRepository() }

    @Suppress("UNCHECKED_CAST")
    override fun <T : ViewModel> create(modelClass: Class<T>): T {
        return when {
            modelClass.isAssignableFrom(AuthViewModel::class.java) ->
                AuthViewModel(authRepository) as T

            modelClass.isAssignableFrom(ChatViewModel::class.java) ->
                ChatViewModel(chatRepository) as T

            modelClass.isAssignableFrom(PreferencesViewModel::class.java) ->
                PreferencesViewModel(preferencesRepository) as T

            else -> throw IllegalArgumentException("未知的 ViewModel 类型: ${modelClass.name}")
        }
    }
}
