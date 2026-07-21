package com.xtys126.open_awa.core.notification

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.os.Build
import android.provider.Settings
import android.util.Log
import androidx.core.app.NotificationCompat
import com.xtys126.open_awa.MainActivity
import com.xtys126.open_awa.R

/**
 * 系统通知管理器
 *
 * 封装系统通知栏通知能力，用于：
 * 1. 定时任务完成提醒（[showTaskResult]）：收到 category=task_result 的 inbox 推送时调用
 * 2. 通用通知（[showGeneric]）：其他类型的 inbox 推送
 *
 * 实现要点：
 * - Android 8+ 必须创建 [NotificationChannel]，否则通知不显示
 * - 通知点击跳转到 [MainActivity]，由 MainActivity 内的导航图路由到 InboxScreen
 * - 小图标使用 [R.mipmap.ic_launcher]（项目未单独提供 ic_notification 资源）
 * - 自动取消（FLAG_AUTO_CANCEL）：点击后自动消失
 * - 通知 ID 按 category 区分，避免不同类型通知互相覆盖
 *
 * 权限约束：
 * - Android 13+（API 33+）需运行时申请 POST_NOTIFICATIONS 权限
 * - 申请逻辑由 [com.xtys126.open_awa.MainActivity] 在启动时通过
 *   ActivityResultContracts.RequestPermission 完成
 */
object SystemNotifier {
    private const val TAG = "SystemNotifier"

    /** inbox 通知渠道 ID（Android 8+ 必需） */
    private const val CHANNEL_ID_INBOX = "openawa_inbox"

    /** 任务结果通知渠道名称（用户可见） */
    private const val CHANNEL_NAME_INBOX = "收件箱通知"

    /** 任务结果通知 ID 基址（避免与通用通知冲突） */
    private const val NOTIFICATION_ID_TASK_RESULT_BASE = 1000

    /** 通用通知 ID 基址 */
    private const val NOTIFICATION_ID_GENERIC_BASE = 2000

    /** 通知内容最大长度（超出截断，避免通知栏显示过长） */
    private const val MAX_CONTENT_LENGTH = 100

    /**
     * 创建 inbox 通知渠道
     *
     * Android 8+（API 26+）必须创建渠道才能显示通知。
     * 重复调用安全：系统会忽略已存在渠道的重复创建请求。
     *
     * @param context 任意 Context，内部取 applicationContext 避免泄露 Activity
     */
    fun ensureChannel(context: Context) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        val manager = context.applicationContext
            .getSystemService(Context.NOTIFICATION_SERVICE) as? NotificationManager
        if (manager == null) {
            Log.w(TAG, "NotificationManager 不可用，跳过渠道创建")
            return
        }
        val channel = NotificationChannel(
            CHANNEL_ID_INBOX,
            CHANNEL_NAME_INBOX,
            NotificationManager.IMPORTANCE_DEFAULT,
        ).apply {
            description = "Open-AwA 收件箱通知（定时任务完成、审批、系统消息等）"
            enableVibration(true)
            enableLights(true)
        }
        manager.createNotificationChannel(channel)
    }

    /**
     * 显示任务结果通知
     *
     * 收到 category=task_result 的 inbox 推送时调用。
     * 通知 ID 由标题哈希派生，保证不同任务通知不互相覆盖。
     *
     * @param context 任意 Context
     * @param title 通知标题（如 "任务成功: xxx"）
     * @param content 通知内容（任务摘要，超过 [MAX_CONTENT_LENGTH] 字符自动截断）
     */
    fun showTaskResult(context: Context, title: String, content: String) {
        ensureChannel(context)
        val manager = context.applicationContext
            .getSystemService(Context.NOTIFICATION_SERVICE) as? NotificationManager
        if (manager == null) {
            Log.w(TAG, "NotificationManager 不可用，跳过通知显示")
            return
        }
        val notificationId = NOTIFICATION_ID_TASK_RESULT_BASE + (title.hashCode() and 0xFFFF)
        val truncatedContent = truncateContent(content)
        val notification = buildNotification(
            context = context.applicationContext,
            title = title,
            content = truncatedContent,
            priority = NotificationCompat.PRIORITY_DEFAULT,
        )
        manager.notify(notificationId, notification)
        Log.d(TAG, "已显示任务结果通知: title=$title, id=$notificationId")
    }

    /**
     * 显示通用通知
     *
     * 用于 category 不为 task_result 的其他通知（如 notification/approval）。
     *
     * @param context 任意 Context
     * @param title 通知标题
     * @param content 通知内容
     * @param category 通知类别（用于日志区分，不影响通知显示）
     */
    fun showGeneric(context: Context, title: String, content: String, category: String) {
        ensureChannel(context)
        val manager = context.applicationContext
            .getSystemService(Context.NOTIFICATION_SERVICE) as? NotificationManager
        if (manager == null) {
            Log.w(TAG, "NotificationManager 不可用，跳过通知显示")
            return
        }
        val notificationId = NOTIFICATION_ID_GENERIC_BASE + (title.hashCode() and 0xFFFF)
        val truncatedContent = truncateContent(content)
        val notification = buildNotification(
            context = context.applicationContext,
            title = title,
            content = truncatedContent,
            priority = NotificationCompat.PRIORITY_DEFAULT,
        )
        manager.notify(notificationId, notification)
        Log.d(TAG, "已显示通用通知: category=$category, title=$title, id=$notificationId")
    }

    /**
     * 构建 NotificationCompat.Builder 通知对象
     *
     * 统一通知样式：
     * - 小图标使用 [R.mipmap.ic_launcher]
     * - 点击跳转 [MainActivity]，FLAG_IMMUTABLE + FLAG_UPDATE_CURRENT 保证安全且可更新
     * - FLAG_AUTO_CANCEL 点击后自动消失
     *
     * @param context applicationContext
     * @param title 通知标题
     * @param content 通知内容
     * @param priority 通知优先级
     * @return 构建好的 Notification 对象
     */
    private fun buildNotification(
        context: Context,
        title: String,
        content: String,
        priority: Int,
    ): android.app.Notification {
        // 点击通知跳转到 MainActivity（MainActivity 内的导航图会路由到 InboxScreen）
        val intent = Intent(context, MainActivity::class.java).apply {
            // 清除回退栈，确保从通知进入时回到主界面
            flags = Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_SINGLE_TOP
            // 携带跳转目标，MainActivity 可据此路由到 inbox
            putExtra(EXTRA_NAV_TARGET, "inbox")
        }
        val pendingIntentFlags = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
        } else {
            PendingIntent.FLAG_UPDATE_CURRENT
        }
        val pendingIntent = PendingIntent.getActivity(
            context,
            NOTIFICATION_REQUEST_CODE,
            intent,
            pendingIntentFlags,
        )
        return NotificationCompat.Builder(context, CHANNEL_ID_INBOX)
            .setSmallIcon(R.mipmap.ic_launcher)
            .setContentTitle(title)
            .setContentText(content)
            .setStyle(NotificationCompat.BigTextStyle().bigText(content))
            .setPriority(priority)
            .setContentIntent(pendingIntent)
            .setAutoCancel(true)
            .setCategory(NotificationCompat.CATEGORY_MESSAGE)
            .build()
    }

    /**
     * 截断通知内容到 [MAX_CONTENT_LENGTH] 字符
     *
     * @param content 原始内容
     * @return 截断后的内容，超长时追加省略号
     */
    private fun truncateContent(content: String): String {
        if (content.length <= MAX_CONTENT_LENGTH) return content
        return content.take(MAX_CONTENT_LENGTH) + "..."
    }

    /**
     * 跳转到系统通知设置页（对应渠道）
     *
     * 供设置页"通知设置"项调用，让用户调整 Open-AwA 通知行为。
     *
     * @param context 任意 Context
     */
    fun openNotificationSettings(context: Context) {
        val intent = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            Intent(Settings.ACTION_CHANNEL_NOTIFICATION_SETTINGS).apply {
                putExtra(Settings.EXTRA_APP_PACKAGE, context.packageName)
                putExtra(Settings.EXTRA_CHANNEL_ID, CHANNEL_ID_INBOX)
            }
        } else {
            Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS).apply {
                putExtra(Settings.EXTRA_APP_PACKAGE, context.packageName)
            }
        }
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        runCatching {
            context.startActivity(intent)
        }.onFailure { e ->
            Log.w(TAG, "跳转通知设置失败: ${e.message}", e)
        }
    }

    /** 通知 Intent 携带的跳转目标 key（MainActivity 据此路由） */
    const val EXTRA_NAV_TARGET = "extra_nav_target"

    /** PendingIntent 请求码 */
    private const val NOTIFICATION_REQUEST_CODE = 10001
}
