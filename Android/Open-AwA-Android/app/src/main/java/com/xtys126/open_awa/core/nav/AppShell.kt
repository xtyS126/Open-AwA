package com.xtys126.open_awa.core.nav

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyListScope
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Menu
import androidx.compose.material3.CenterAlignedTopAppBar
import androidx.compose.material3.DrawerValue
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalDrawerSheet
import androidx.compose.material3.ModalNavigationDrawer
import androidx.compose.material3.NavigationDrawerItem
import androidx.compose.material3.NavigationDrawerItemDefaults
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.rememberDrawerState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.navigation.NavHostController
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import com.xtys126.open_awa.R
import kotlinx.coroutines.launch

/**
 * 应用外壳
 *
 * 包含：
 * 1. 抽屉式导航（ModalNavigationDrawer）
 * 2. 顶栏（CenterAlignedTopAppBar）
 * 3. 内容区域（AppNavGraph）
 *
 * 对应 frontend/src/layouts/AppShell.tsx + Sidebar.tsx 的功能
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AppShell() {
    val drawerState = rememberDrawerState(initialValue = DrawerValue.Closed)
    val scope = rememberCoroutineScope()
    val navController = rememberNavController()

    // 当前路由路径
    val backStackEntry by navController.currentBackStackEntryAsState()
    val currentPath = backStackEntry?.destination?.route?.substringAfter("/") ?: "chat"
    val currentDestination = remember(currentPath) {
        Destination.fromPath(currentPath) ?: Destination.Chat
    }

    ModalNavigationDrawer(
        drawerState = drawerState,
        drawerContent = {
            AppDrawer(
                currentPath = currentPath,
                onNavigate = { dest ->
                    navController.navigate(dest.path) {
                        // 避免回退栈堆积
                        launchSingleTop = true
                        restoreState = true
                    }
                    scope.launch { drawerState.close() }
                },
            )
        },
    ) {
        Scaffold(
            topBar = {
                CenterAlignedTopAppBar(
                    title = {
                        Text(
                            text = destinationTitle(currentDestination),
                            style = MaterialTheme.typography.titleMedium,
                            fontWeight = FontWeight.SemiBold,
                        )
                    },
                    navigationIcon = {
                        IconButton(onClick = { scope.launch { drawerState.open() } }) {
                            Icon(
                                imageVector = Icons.Outlined.Menu,
                                contentDescription = stringResource(R.string.action_menu),
                            )
                        }
                    },
                )
            },
        ) { innerPadding ->
            Box(modifier = Modifier.padding(innerPadding)) {
                AppNavGraph(navController = navController)
            }
        }
    }
}

/**
 * 应用抽屉
 *
 * 三组菜单：控制台 / 智能体 / 设置
 * 对应 frontend/src/shared/components/Sidebar/Sidebar.tsx 的 menuGroups
 */
@Composable
private fun AppDrawer(
    currentPath: String,
    onNavigate: (Destination) -> Unit,
) {
    ModalDrawerSheet {
        // 使用单个 LazyColumn 渲染抽屉内容，避免嵌套滚动组件导致无限高度约束崩溃
        // 结构：Header + 控制台分组 + 分隔线 + 智能体分组 + 分隔线 + 设置分组
        LazyColumn(
            modifier = Modifier
                .fillMaxSize()
                .padding(16.dp),
        ) {
            item {
                DrawerHeader()
                Spacer(modifier = Modifier.height(16.dp))
            }

            // 控制台分组
            item { DrawerGroupTitle(title = stringResource(R.string.nav_group_control)) }
            drawerGroupItems(
                items = Destination.controlGroup,
                currentPath = currentPath,
                onNavigate = onNavigate,
            )

            item {
                Spacer(modifier = Modifier.height(8.dp))
                HorizontalDivider()
                Spacer(modifier = Modifier.height(8.dp))
            }

            // 智能体分组
            item { DrawerGroupTitle(title = stringResource(R.string.nav_group_agent)) }
            drawerGroupItems(
                items = Destination.agentGroup,
                currentPath = currentPath,
                onNavigate = onNavigate,
            )

            item {
                Spacer(modifier = Modifier.height(8.dp))
                HorizontalDivider()
                Spacer(modifier = Modifier.height(8.dp))
            }

            // 设置分组
            item { DrawerGroupTitle(title = stringResource(R.string.nav_group_settings)) }
            drawerGroupItems(
                items = Destination.settingsGroup,
                currentPath = currentPath,
                onNavigate = onNavigate,
            )
        }
    }
}

/**
 * 抽屉头部
 *
 * Logo 占位（圆形品牌色背景）+ 应用名 + 副标题
 */
@Composable
private fun DrawerHeader() {
    Row(
        verticalAlignment = Alignment.CenterVertically,
        modifier = Modifier.padding(vertical = 8.dp),
    ) {
        // Logo 占位（圆形品牌色背景）
        Box(
                modifier = Modifier
                    .size(40.dp)
                    .background(
                        color = MaterialTheme.colorScheme.primary,
                        shape = CircleShape,
                    ),
            contentAlignment = Alignment.Center,
        ) {
            Text(
                text = "A",
                color = MaterialTheme.colorScheme.onPrimary,
                style = MaterialTheme.typography.titleLarge,
                fontWeight = FontWeight.Bold,
            )
        }
        Spacer(modifier = Modifier.width(12.dp))
        Column {
            Text(
                text = "Open-AwA",
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.Bold,
            )
            Text(
                text = "AI Agent 平台",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

@Composable
private fun DrawerGroupTitle(title: String) {
    Text(
        text = title,
        style = MaterialTheme.typography.labelMedium,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
        modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp),
    )
}

/**
 * 在 [LazyListScope] 中渲染一组导航抽屉项
 *
 * 使用 [LazyListScope.items] 直接插入到外层 [LazyColumn]，避免嵌套独立的 LazyColumn。
 *
 * @param items 该分组下的 Destination 列表
 * @param currentPath 当前路由路径，用于高亮选中项
 * @param onNavigate 点击导航回调
 */
private fun LazyListScope.drawerGroupItems(
    items: List<Destination>,
    currentPath: String,
    onNavigate: (Destination) -> Unit,
) {
    items(
        items = items,
        key = { it.path },
    ) { dest ->
        val selected = currentPath == dest.path || currentPath.startsWith("${dest.path}/")
        NavigationDrawerItem(
            icon = {
                Icon(
                    imageVector = dest.icon,
                    contentDescription = null,
                )
            },
            label = { Text(text = destinationTitle(dest)) },
            selected = selected,
            onClick = { onNavigate(dest) },
            colors = NavigationDrawerItemDefaults.colors(),
            modifier = Modifier.padding(horizontal = 12.dp),
        )
    }
}

/**
 * 根据 Destination 获取标题
 * 直接用 stringResource 会有 composable 限制，这里改为返回字符串
 */
private fun destinationTitle(dest: Destination): String {
    // 直接用类名作为标题（简化版，避免 stringResource 在非 composable 上下文调用）
    return when (dest) {
        Destination.Login -> "登录"
        Destination.Chat -> "聊天"
        Destination.Coding -> "编码"
        Destination.VibeCoding -> "Vibe Coding"
        Destination.Workspace -> "工作区"
        Destination.Dashboard -> "仪表盘"
        Destination.Billing -> "计费"
        Destination.Inbox -> "收件箱"
        Destination.Tts -> "TTS"
        Destination.Roles -> "角色管理"
        Destination.RoleMarket -> "角色市场"
        Destination.Skills -> "技能"
        Destination.SkillMarket -> "技能市场"
        Destination.ScheduledTasks -> "定时任务"
        Destination.Workflows -> "工作流"
        Destination.SubAgents -> "子智能体"
        Destination.Discussions -> "讨论"
        Destination.Plugins -> "插件"
        Destination.Memory -> "记忆"
        Destination.Experience -> "经验"
        Destination.Settings -> "设置"
        Destination.Im -> "IM 渠道"
        Destination.UserCenter -> "用户中心"
    }
}
