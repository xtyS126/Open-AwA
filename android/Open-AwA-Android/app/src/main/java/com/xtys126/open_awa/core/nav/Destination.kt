package com.xtys126.open_awa.core.nav

import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.AccountCircle
import androidx.compose.material.icons.outlined.Bolt
import androidx.compose.material.icons.outlined.Build
import androidx.compose.material.icons.outlined.CallSplit
import androidx.compose.material.icons.outlined.Chat
import androidx.compose.material.icons.outlined.Code
import androidx.compose.material.icons.outlined.CreditCard
import androidx.compose.material.icons.outlined.Dashboard
import androidx.compose.material.icons.outlined.Engineering
import androidx.compose.material.icons.outlined.Extension
import androidx.compose.material.icons.outlined.Favorite
import androidx.compose.material.icons.outlined.Forum
import androidx.compose.material.icons.outlined.Inbox
import androidx.compose.material.icons.outlined.Login
import androidx.compose.material.icons.outlined.Notifications
import androidx.compose.material.icons.outlined.People
import androidx.compose.material.icons.outlined.Psychology
import androidx.compose.material.icons.outlined.RecordVoiceOver
import androidx.compose.material.icons.outlined.Schedule
import androidx.compose.material.icons.outlined.Settings
import androidx.compose.material.icons.outlined.ShoppingCart
import androidx.compose.material.icons.outlined.Spa
import androidx.compose.material.icons.outlined.Terminal
import androidx.compose.material.icons.outlined.WorkspacePremium
import androidx.compose.ui.graphics.vector.ImageVector

/**
 * 路由定义
 *
 * 对应 frontend/src/router/index.tsx 的 22 个路由
 * 每个路由包含 path、标题、图标，用于导航抽屉与顶栏
 */
sealed class Destination(
    val path: String,
    val titleRes: Int,
    val icon: ImageVector,
) {
    /** 登录页 */
    data object Login : Destination("login", 0, Icons.Outlined.Login)

    /** 聊天 */
    data object Chat : Destination("chat", 0, Icons.Outlined.Chat)

    /** 编码 */
    data object Coding : Destination("coding", 0, Icons.Outlined.Code)

    /** Vibe Coding */
    data object VibeCoding : Destination("vibe-coding", 0, Icons.Outlined.Terminal)

    /** 工作区 */
    data object Workspace : Destination("workspace", 0, Icons.Outlined.WorkspacePremium)

    /** 仪表盘 */
    data object Dashboard : Destination("dashboard", 0, Icons.Outlined.Dashboard)

    /** 计费 */
    data object Billing : Destination("billing", 0, Icons.Outlined.CreditCard)

    /** 收件箱 */
    data object Inbox : Destination("inbox", 0, Icons.Outlined.Inbox)

    /** TTS */
    data object Tts : Destination("tts", 0, Icons.Outlined.RecordVoiceOver)

    /** 角色管理 */
    data object Roles : Destination("roles", 0, Icons.Outlined.People)

    /** 角色市场 */
    data object RoleMarket : Destination("role-market", 0, Icons.Outlined.ShoppingCart)

    /** 技能 */
    data object Skills : Destination("skills", 0, Icons.Outlined.Bolt)

    /** 技能市场 */
    data object SkillMarket : Destination("skills/market", 0, Icons.Outlined.ShoppingCart)

    /** 定时任务 */
    data object ScheduledTasks : Destination("scheduled-tasks", 0, Icons.Outlined.Schedule)

    /** 工作流 */
    data object Workflows : Destination("workflows", 0, Icons.Outlined.Engineering)

    /** 子智能体 */
    data object SubAgents : Destination("subagents", 0, Icons.Outlined.CallSplit)

    /** 讨论 */
    data object Discussions : Destination("discussions", 0, Icons.Outlined.Forum)

    /** 插件 */
    data object Plugins : Destination("plugins/manage", 0, Icons.Outlined.Extension)

    /** 记忆 */
    data object Memory : Destination("memory", 0, Icons.Outlined.Psychology)

    /** 经验 */
    data object Experience : Destination("experience", 0, Icons.Outlined.Spa)

    /** 设置 */
    data object Settings : Destination("settings", 0, Icons.Outlined.Settings)

    /** IM 渠道 */
    data object Im : Destination("im", 0, Icons.Outlined.Notifications)

    /** Live2D 模型 */
    data object Live2D : Destination("live2d", 0, Icons.Outlined.Spa)

    /** 陪伴心智（对象名避开 Kotlin 保留的 Companion，路由 path 仍为 companion） */
    data object CompanionMind : Destination("companion", 0, Icons.Outlined.Favorite)

    /** 用户中心 */
    data object UserCenter : Destination("user", 0, Icons.Outlined.AccountCircle)

    companion object {
        /** 所有路由（按 Sidebar 分组顺序） */
        val all: List<Destination> = listOf(
            // 控制台
            Chat, Coding, VibeCoding, Workspace, Dashboard, Billing, Inbox, ScheduledTasks,
            // 智能体
            Tts, Roles, RoleMarket, Skills, SkillMarket, Workflows,
            SubAgents, Discussions, Plugins, Memory, Experience, Live2D, CompanionMind,
            // 设置
            Settings, Im, UserCenter,
        )

        /** 控制台分组 */
        val controlGroup: List<Destination> = listOf(
            Chat, Coding, VibeCoding, Workspace, Dashboard, Billing, Inbox, ScheduledTasks,
        )

        /** 智能体分组 */
        val agentGroup: List<Destination> = listOf(
            Tts, Roles, RoleMarket, Skills, SkillMarket, Workflows,
            SubAgents, Discussions, Plugins, Memory, Experience, Live2D, CompanionMind,
        )

        /** 设置分组 */
        val settingsGroup: List<Destination> = listOf(
            Settings, Im, UserCenter,
        )

        /**
         * 根据路径解析 Destination
         * @param path 路径（不含前导 /）
         * @return 匹配的 Destination，未匹配返回 null
         */
        fun fromPath(path: String): Destination? {
            val normalized = path.removePrefix("/").trimEnd('/')
            return all.firstOrNull { dest ->
                normalized == dest.path || normalized.startsWith("${dest.path}/")
            }
        }
    }
}
