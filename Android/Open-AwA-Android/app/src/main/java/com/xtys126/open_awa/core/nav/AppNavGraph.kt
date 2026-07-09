package com.xtys126.open_awa.core.nav

import androidx.compose.runtime.Composable
import androidx.navigation.NavHostController
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import com.xtys126.open_awa.features.auth.LoginScreen
import com.xtys126.open_awa.features.billing.BillingScreen
import com.xtys126.open_awa.features.chat.ChatScreen
import com.xtys126.open_awa.features.coding.CodingScreen
import com.xtys126.open_awa.features.dashboard.DashboardScreen
import com.xtys126.open_awa.features.discussions.DiscussionsScreen
import com.xtys126.open_awa.features.experience.ExperienceScreen
import com.xtys126.open_awa.features.im.ImChannelsScreen
import com.xtys126.open_awa.features.inbox.InboxScreen
import com.xtys126.open_awa.features.memory.MemoryScreen
import com.xtys126.open_awa.features.plugins.PluginsScreen
import com.xtys126.open_awa.features.roles.RolesScreen
import com.xtys126.open_awa.features.scheduled.ScheduledTaskScreen
import com.xtys126.open_awa.features.settings.SettingsScreen
import com.xtys126.open_awa.features.skills.SkillsScreen
import com.xtys126.open_awa.features.subagents.SubAgentScreen
import com.xtys126.open_awa.features.tts.TtsScreen
import com.xtys126.open_awa.features.user.UserCenterScreen
import com.xtys126.open_awa.features.vibecoding.VibeCodingScreen
import com.xtys126.open_awa.features.workflow.WorkflowScreen
import com.xtys126.open_awa.features.workspace.WorkspaceScreen

/**
 * 导航图
 *
 * 对应 frontend/src/router/index.tsx 的 22 个路由
 * 每个路由对应一个 Composable Screen
 *
 * @param navController 导航控制器
 */
@Composable
fun AppNavGraph(navController: NavHostController) {
    NavHost(
        navController = navController,
        startDestination = "chat",
    ) {
        // 控制台分组
        composable("chat") { ChatScreen() }
        composable("coding") { CodingScreen() }
        composable("vibe-coding") { VibeCodingScreen() }
        composable("workspace") { WorkspaceScreen() }
        composable("dashboard") { DashboardScreen() }
        composable("billing") { BillingScreen() }
        composable("inbox") { InboxScreen() }

        // 智能体分组
        composable("tts") { TtsScreen() }
        composable("roles") { RolesScreen() }
        composable("role-market") {
            PlaceholderScreen(title = "角色市场", icon = Destination.RoleMarket.icon)
        }
        composable("skills") { SkillsScreen() }
        composable("skills/market") { SkillsScreen() }
        composable("scheduled-tasks") {
            ScheduledTaskScreen()
        }
        composable("workflows") { WorkflowScreen() }
        composable("subagents") { SubAgentScreen() }
        composable("discussions") { DiscussionsScreen() }
        composable("plugins/manage") { PluginsScreen() }
        composable("memory") { MemoryScreen() }
        composable("experience") { ExperienceScreen() }

        // 设置分组
        composable("settings") { SettingsScreen() }
        composable("im") { ImChannelsScreen() }
        composable("user") { UserCenterScreen() }

        // 登录页
        composable("login") { LoginScreen(navController) }
    }
}
