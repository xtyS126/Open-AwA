package com.xtys126.open_awa.features.live2d

import android.annotation.SuppressLint
import android.util.Log
import android.webkit.WebChromeClient
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Spa
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import com.xtys126.open_awa.core.backend.BackendManager
import com.xtys126.open_awa.core.ui.EmptyBox

private const val TAG = "Live2DScreen"

/**
 * Live2D 预览页
 *
 * 通过 Android WebView 加载前端 React 应用的 Live2D 模型管理页面，
 * 前端已有的 Live2DViewer 组件（基于 pixi.js + pixi-live2d-display）
 * 在 WebView 中自动获得 WebGL 渲染能力，无需额外 Android 原生代码。
 *
 * WebView 配置要点：
 * - 启用 JavaScript 与 DOM 存储（pixi.js 动态加载需要）
 * - 启用 WebGL（通过 setRenderPriority + 注入检测脚本）
 * - 启用缓存（利用 HTTP 缓存头减少 Live2D 模型文件重复下载）
 * - 加载后端服务器上的前端应用页面
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun Live2DScreen() {
    val context = LocalContext.current
    val baseUrl = remember { BackendManager.resolveBaseUrl() }
    // 加载前端的 Live2D 模型管理页面
    val live2dUrl = remember(baseUrl) { "$baseUrl/roles" }

    var isLoading by remember { mutableStateOf(true) }
    var loadError by remember { mutableStateOf<String?>(null) }

    Scaffold(
        topBar = {
            TopAppBar(
                title = {
                    Text(
                        text = "Live2D 模型",
                        style = MaterialTheme.typography.titleMedium,
                        fontWeight = FontWeight.SemiBold,
                    )
                },
            )
        },
    ) { innerPadding ->
        Box(
            modifier = Modifier
                .fillMaxSize()
                .padding(innerPadding),
            contentAlignment = Alignment.Center,
        ) {
            if (loadError != null) {
                EmptyBox(
                    icon = Icons.Outlined.Spa,
                    title = "Live2D 加载失败",
                    actionText = "重试",
                    onAction = {
                        loadError = null
                        isLoading = true
                    },
                )
            } else {
                AndroidView(
                    factory = { ctx ->
                        createLive2DWebView(ctx, live2dUrl) { url, error ->
                            if (error) {
                                loadError = "页面加载失败: $url"
                            }
                            isLoading = false
                        }
                    },
                    modifier = Modifier.fillMaxSize(),
                )

                // 加载中指示器
                if (isLoading) {
                    CircularProgressIndicator(
                        modifier = Modifier.padding(16.dp),
                        color = MaterialTheme.colorScheme.primary,
                    )
                }
            }
        }
    }
}

/**
 * 创建并配置 Live2D 专用 WebView
 *
 * 配置项：
 * - JavaScript 启用（pixi.js 动态脚本加载需要）
 * - DOM 存储启用（LocalStorage/SessionStorage）
 * - WebGL 加速（setRenderPriority + 硬件加速）
 * - HTTP 缓存启用（复用 Live2D 模型文件缓存头）
 * - 注入 WebGL 检测脚本
 * - 设置缓存目录到应用私有目录
 *
 * @param ctx Android Context
 * @param url 要加载的前端页面 URL
 * @param onPageFinished 页面加载完成回调（url, isError）
 * @return 配置好的 WebView 实例
 */
@SuppressLint("SetJavaScriptEnabled")
private fun createLive2DWebView(
    ctx: android.content.Context,
    url: String,
    onPageFinished: (url: String, isError: Boolean) -> Unit,
): WebView {
    return WebView(ctx).apply {
        // 基本 WebView 配置
        settings.apply {
            // 启用 JavaScript（pixi.js 与 Live2D SDK 必须）
            javaScriptEnabled = true

            // 启用 DOM 存储（pixi.js 可能使用 LocalStorage）
            domStorageEnabled = true

            // 启用 WebGL 加速渲染
            setRenderPriority(WebSettings.RenderPriority.HIGH)

            // 启用 HTTP 缓存（复用 Live2D 模型文件缓存头，减少重复下载）
            cacheMode = WebSettings.LOAD_DEFAULT

            // 注：setAppCacheEnabled/setAppCachePath 已在 compileSdk 36 中移除，
            // WebView 默认使用应用私有缓存目录，无需显式设置
            databaseEnabled = true

            // 允许混合内容（HTTP 图片等资源，前端开发环境可能需要）
            mixedContentMode = WebSettings.MIXED_CONTENT_ALWAYS_ALLOW

            // 允许文件访问（Live2D 模型文件通过 file:// 协议加载时可能需要）
            allowFileAccess = true

            // 启用视口支持
            useWideViewPort = true
            loadWithOverviewMode = true

            // 启用硬件加速（WebGL 渲染必须）
            setSupportZoom(false)
            builtInZoomControls = false
            displayZoomControls = false

            Log.d(TAG, "WebView 配置完成: WebGL=HIGH, 缓存=${cacheMode}, JS=${javaScriptEnabled}")
        }

        // 设置 WebChromeClient（处理 JS 对话框、console 等）
        webChromeClient = object : WebChromeClient() {
            override fun onConsoleMessage(consoleMessage: android.webkit.ConsoleMessage): Boolean {
                Log.d(TAG, "[WebView Console] ${consoleMessage.message()}")
                return true
            }
        }

        // 设置 WebViewClient（处理页面加载事件）
        webViewClient = object : WebViewClient() {
            override fun onPageFinished(view: WebView, finishedUrl: String) {
                super.onPageFinished(view, finishedUrl)
                Log.d(TAG, "页面加载完成: $finishedUrl")

                // 注入 WebGL 检测脚本
                injectWebGLDetection(view)

                onPageFinished(finishedUrl, false)
            }

            override fun onReceivedError(
                view: WebView,
                request: android.webkit.WebResourceRequest?,
                error: android.webkit.WebResourceError?,
            ) {
                super.onReceivedError(view, request, error)
                val errorUrl = request?.url?.toString() ?: url
                Log.e(TAG, "页面加载错误: $errorUrl, error=${error?.description}")
                onPageFinished(errorUrl, true)
            }
        }

        // 加载前端页面
        Log.d(TAG, "开始加载 Live2D 页面: $url")
        loadUrl(url)
    }
}

/**
 * 注入 JavaScript 检测 WebGL 支持
 *
 * 在页面加载完成后执行，检测 WebGL 1.0 和 2.0 是否可用，
 * 并将检测结果通过 console 输出，方便调试。
 *
 * @param webView 目标 WebView
 */
private fun injectWebGLDetection(webView: WebView) {
    val script = """
        (function() {
            var canvas = document.createElement('canvas');
            var gl = canvas.getContext('webgl') || canvas.getContext('experimental-webgl');
            var gl2 = canvas.getContext('webgl2');
            var webglSupported = !!(gl || gl2);
            var webglVersion = gl2 ? '2.0' : (gl ? '1.0' : '不支持');
            console.log('[Live2D WebGL 检测] WebGL 支持: ' + webglSupported + ', 版本: ' + webglVersion);
            if (!webglSupported) {
                console.warn('[Live2D WebGL 检测] WebGL 不可用，Live2D 将降级为模拟模式');
            }
            if (gl) {
                var debugInfo = gl.getExtension('WEBGL_debug_renderer_info');
                if (debugInfo) {
                    console.log('[Live2D WebGL 检测] GPU: ' + gl.getParameter(debugInfo.UNMASKED_RENDERER_WEBGL));
                }
            }
        })();
    """.trimIndent()

    webView.evaluateJavascript(script, null)
    Log.d(TAG, "WebGL 检测脚本已注入")
}