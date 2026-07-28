package com.xtys126.open_awa.core.backend

import android.Manifest
import android.content.pm.PackageManager
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.platform.LocalContext
import androidx.core.content.ContextCompat
import com.journeyapps.barcodescanner.ScanContract
import com.journeyapps.barcodescanner.ScanIntentResult
import com.journeyapps.barcodescanner.ScanOptions

/**
 * 扫码链接后端
 *
 * 使用 ZXing Android Embedded 的 [ScanContract] 启动二维码扫描 Activity，
 * 扫到 URL 后校验并写入 [BackendManager]。
 *
 * 校验规则（[BackendUrlValidator.validate]）：
 * 1. 必须以 `http://` 或 `https://` 开头
 * 2. 不能指向 localhost / 127.0.0.1（手机无法访问宿主机本地服务）
 * 3. 必须包含端口号（如 :8000），避免默认 80/443 端口被误用
 *
 * 权限约束：
 * - 摄像头权限需运行时申请（Android 6+）
 * - 通过 [ActivityResultContracts.RequestPermission] 申请，授权后才启动扫描
 */

/**
 * 扫码结果
 *
 * @param url 扫描到的 URL（校验通过后非空）
 * @param success 是否成功（true=已写入 BackendManager）
 * @param errorMessage 失败原因（success=false 时非空）
 */
data class QrScanResult(
    val url: String? = null,
    val success: Boolean,
    val errorMessage: String? = null,
)

/**
 * 校验后端 URL 合法性
 *
 * 校验逻辑：
 * 1. 非空且以 `http://` 或 `https://` 开头
 * 2. 不允许 localhost / 127.0.0.1 / 0.0.0.0（手机无法访问宿主机本地服务）
 * 3. 必须包含端口号（含 `:` 在 host 之后）
 *
 * @param url 待校验的 URL 字符串
 * @return 校验通过返回 [UrlValidationResult.Valid]，
 *         否则返回 [UrlValidationResult.Invalid] 携带错误原因
 */
object BackendUrlValidator {

    /**
     * 校验结果
     */
    sealed class UrlValidationResult {
        /** 校验通过 */
        data object Valid : UrlValidationResult()

        /**
         * 校验失败
         *
         * @param reason 失败原因（用于 UI 展示）
         */
        data class Invalid(val reason: String) : UrlValidationResult()
    }

    /**
     * 执行校验
     *
     * @param url 待校验的 URL 字符串
     * @return 校验结果
     */
    fun validate(url: String): UrlValidationResult {
        if (url.isBlank()) {
            return UrlValidationResult.Invalid("URL 不能为空")
        }
        val trimmed = url.trim()
        if (!trimmed.startsWith("http://") && !trimmed.startsWith("https://")) {
            return UrlValidationResult.Invalid("URL 必须以 http:// 或 https:// 开头")
        }
        // 提取 host 部分（去掉 scheme 后到第一个 / 或结尾）
        val withoutScheme = trimmed.substringAfter("://")
        val host = withoutScheme.substringBefore("/").substringBefore(":")
        if (host.isBlank()) {
            return UrlValidationResult.Invalid("URL 缺少主机地址")
        }
        // 禁止本地回环地址（手机无法访问宿主机本地服务）
        if (host == "localhost" || host == "127.0.0.1" || host == "0.0.0.0" || host == "::1") {
            return UrlValidationResult.Invalid(
                "URL 不能指向 localhost 或 127.0.0.1，手机无法访问宿主机本地服务，请使用电脑局域网 IP",
            )
        }
        // 必须包含端口号（避免默认 80/443 误用，Open-AwA 后端默认 8000）
        if (!withoutScheme.contains(":")) {
            return UrlValidationResult.Invalid("URL 必须包含端口号（如 :8000）")
        }
        return UrlValidationResult.Valid
    }
}

/**
 * 创建扫码启动器
 *
 * 返回一个 `launch()` 函数，调用即启动扫码流程：
 * 1. 检查 CAMERA 权限，未授权则申请
 * 2. 已授权则启动 ZXing 扫码 Activity
 * 3. 扫码结果回调到 [onResult]
 *
 * 使用方式（在 Composable 中）：
 * ```
 * val launchScan = rememberQrScannerLauncher { result ->
 *     if (result.success) {
 *         // 已写入 BackendManager，可刷新 UI
 *     } else {
 *         // 显示 result.errorMessage
 *     }
 * }
 * Button(onClick = { launchScan() }) { Text("扫码链接后端") }
 * ```
 *
 * @param onResult 扫码结果回调（成功时已调用 [BackendManager.setRemoteUrl]）
 * @return 启动扫码的函数
 */
@Composable
fun rememberQrScannerLauncher(onResult: (QrScanResult) -> Unit): () -> Unit {
    val context = LocalContext.current

    // ZXing 扫码结果 Launcher
    val scanLauncher = rememberLauncherForActivityResult(ScanContract()) { result: ScanIntentResult ->
        handleScanResult(result, onResult)
    }

    // CAMERA 权限申请 Launcher
    val cameraPermissionLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestPermission(),
    ) { granted ->
        if (granted) {
            // 权限授予，启动扫码
            scanLauncher.launch(buildScanOptions())
        } else {
            onResult(
                QrScanResult(
                    success = false,
                    errorMessage = "摄像头权限被拒绝，无法扫码",
                ),
            )
        }
    }

    // 返回启动函数：检查权限 → 启动扫码
    return remember(scanLauncher, cameraPermissionLauncher) {
        {
            val granted = ContextCompat.checkSelfPermission(
                context,
                Manifest.permission.CAMERA,
            ) == PackageManager.PERMISSION_GRANTED
            if (granted) {
                scanLauncher.launch(buildScanOptions())
            } else {
                cameraPermissionLauncher.launch(Manifest.permission.CAMERA)
            }
        }
    }
}

/**
 * 构建 ZXing 扫码配置
 *
 * 配置项：
 * - 仅识别 QR_CODE（提速，避免误识别条形码）
 * - 提示文案"将后端地址二维码对准取景框"
 * - 关闭蜂鸣声（避免打扰）
 * - 启用条码图像返回（用于调试，结果中不会使用）
 *
 * @return 扫码配置
 */
private fun buildScanOptions(): ScanOptions {
    return ScanOptions().apply {
        setDesiredBarcodeFormats(ScanOptions.QR_CODE)
        setPrompt("将后端地址二维码对准取景框")
        setBeepEnabled(false)
        setBarcodeImageEnabled(false)
        setOrientationLocked(false)
    }
}

/**
 * 处理扫码结果
 *
 * 三种情况：
 * 1. 用户取消（contents == null）：返回失败 + "取消扫码"
 * 2. 扫到 URL 但校验失败：返回失败 + 校验错误原因
 * 3. 扫到 URL 且校验通过：写入 [BackendManager]，返回成功
 *
 * @param result ZXing 扫码结果
 * @param onResult 回调上层
 */
private fun handleScanResult(
    result: ScanIntentResult,
    onResult: (QrScanResult) -> Unit,
) {
    if (result.contents == null) {
        onResult(
            QrScanResult(
                success = false,
                errorMessage = "取消扫码",
            ),
        )
        return
    }
    val scannedUrl = result.contents.trim()
    when (val validation = BackendUrlValidator.validate(scannedUrl)) {
        is BackendUrlValidator.UrlValidationResult.Valid -> {
            // 校验通过，写入 BackendManager
            BackendManager.setRemoteUrl(scannedUrl)
            onResult(
                QrScanResult(
                    url = scannedUrl,
                    success = true,
                ),
            )
        }

        is BackendUrlValidator.UrlValidationResult.Invalid -> {
            onResult(
                QrScanResult(
                    url = scannedUrl,
                    success = false,
                    errorMessage = validation.reason,
                ),
            )
        }
    }
}
