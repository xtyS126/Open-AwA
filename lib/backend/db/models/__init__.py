"""
数据库 ORM 模型包：按域拆分的模型统一通过本模块 re-export，
保持 `from db.models import User, Conversation, ...` 调用方零修改。

包结构：
- base.py: 声明式基类 Base、引擎、会话工厂、事件监听、init_db、get_db
- user.py: 用户、登录设备、角色、用户画像、兴趣探针等
- conversation.py: 会话、记忆、对话数据收集、执行轨迹等
- skill.py: 技能、技能执行日志、经验记忆等
- plugin.py: 插件、插件版本、评分、评论、下载日志等
- task.py: 工作流、定时任务、Task Agent、子智能体、讨论任务等
- security.py: 审计日志、登录限流、行为埋点、CSRF token、推理审计等
- billing.py: LLM 用量、API 用量明细、模型定价、预算、Provider 凭据等
- wechat.py: 微信绑定、自动回复规则
- workspace.py: 智能体工作区、搜索 Provider 配置
- migrations.py: 启动时执行的 15+ 个幂等 _migrate_xxx 函数

外部依赖模型（PermissionSaved / EventLog）通过本模块 import 触发
Base.metadata 注册，保证 init_db 的 create_all 能创建全部表。
"""

# ---- 基础设施：Base / engine / SessionLocal / get_db / init_db / logger ----
from db.models.base import (
    Base,
    SessionLocal,
    engine,
    get_db,
    init_db,
    logger,
)

# ---- 用户域 ----
from db.models.user import (
    AgentRole,
    InterestProbe,
    LoginDevice,
    MemoryDecayConfig,
    ProfileExtractionLog,
    ProfileExtractionState,
    ProfileFact,
    Role,
    User,
    UserFeedback,
    UserProfile,
    UserProfileOverride,
    UserRole,
)

# ---- 会话域 ----
from db.models.conversation import (
    Conversation,
    ConversationData,
    ConversationRecord,
    ExecutionTrace,
    LongTermMemory,
    PromptConfig,
    RoleSwitchEvent,
    ShortTermMemory,
    ToolCallData,
)

# ---- 技能域 ----
from db.models.skill import (
    ExperienceExtractionLog,
    ExperienceMemory,
    Skill,
    SkillExecutionLog,
)

# ---- 插件域 ----
from db.models.plugin import (
    Plugin,
    PluginDownloadLog,
    PluginExecutionLog,
    PluginRating,
    PluginReview,
    PluginVersion,
)

# ---- 任务域 ----
from db.models.task import (
    DiscussionTask,
    DiscussionVote,
    ScheduledTask,
    ScheduledTaskExecution,
    SubagentDefinition,
    SubagentExecutionHistory,
    TaskAgentDefinition,
    TaskAgentSession,
    TaskEvent,
    TaskItem,
    TaskMailboxMessage,
    TaskTeam,
    TaskTeamMember,
    Workflow,
    WorkflowExecution,
    WorkflowStep,
)

# ---- 安全域 ----
from db.models.security import (
    AnomalyEvent,
    AuditLog,
    BehaviorLog,
    CsrfToken,
    CustomRole,
    IpAccessList,
    LoginRateLimit,
    ReasoningAudit,
    TokenBlacklist,
)

# ---- 计费域 ----
from db.models.billing import (
    BudgetConfig,
    LLMUsage,
    ModelConfiguration,
    ModelPricing,
    ProviderCredential,
    UsageRecord,
    UserUsageSummary,
)

# ---- 微信域 ----
from db.models.wechat import (
    WeixinAutoReplyRule,
    WeixinBinding,
    WeixinMediaAsset,
)

# ---- 工作区与系统配置域 ----
from db.models.workspace import (
    SearchProviderConfig,
    Workspace,
)

# ---- 外部依赖模型注册 ----
# PermissionSaved 与 EventLog 定义在独立模块中，但共享本包的 Base.metadata。
# 此处 import 触发模型注册，确保 init_db 的 create_all 能创建对应表。
# 放在所有域模型 import 之后，与原 db/models.py 文件末尾的注册顺序保持一致。
# ---- 宠物域 ----
from db.models.pet import (
    Pet,
    UserActivePet,
)

from db.models.event_log import EventLog
from db.permission_models import PermissionSaved  # noqa: E402


__all__ = [
    # 基础设施
    "Base",
    "SessionLocal",
    "engine",
    "get_db",
    "init_db",
    "logger",
    # 用户域
    "User",
    "LoginDevice",
    "Role",
    "UserRole",
    "AgentRole",
    "UserFeedback",
    "UserProfile",
    "UserProfileOverride",
    "InterestProbe",
    "MemoryDecayConfig",
    "ProfileFact",
    "ProfileExtractionLog",
    "ProfileExtractionState",
    # 会话域
    "Conversation",
    "ShortTermMemory",
    "LongTermMemory",
    "ConversationRecord",
    "ConversationData",
    "ToolCallData",
    "ExecutionTrace",
    "RoleSwitchEvent",
    "PromptConfig",
    # 技能域
    "Skill",
    "SkillExecutionLog",
    "ExperienceMemory",
    "ExperienceExtractionLog",
    # 插件域
    "Plugin",
    "PluginExecutionLog",
    "PluginVersion",
    "PluginRating",
    "PluginReview",
    "PluginDownloadLog",
    # 任务域
    "Workflow",
    "WorkflowStep",
    "WorkflowExecution",
    "ScheduledTask",
    "ScheduledTaskExecution",
    "TaskAgentDefinition",
    "TaskAgentSession",
    "SubagentDefinition",
    "SubagentExecutionHistory",
    "TaskItem",
    "TaskEvent",
    "TaskTeam",
    "TaskTeamMember",
    "TaskMailboxMessage",
    "DiscussionTask",
    "DiscussionVote",
    # 安全域
    "AuditLog",
    "LoginRateLimit",
    "BehaviorLog",
    "TokenBlacklist",
    "CustomRole",
    "IpAccessList",
    "AnomalyEvent",
    "CsrfToken",
    "ReasoningAudit",
    # 计费域
    "LLMUsage",
    "UsageRecord",
    "ModelPricing",
    "BudgetConfig",
    "UserUsageSummary",
    "ProviderCredential",
    "ModelConfiguration",
    # 微信域
    "WeixinBinding",
    "WeixinAutoReplyRule",
    "WeixinMediaAsset",
    # 工作区与系统配置域
    "Workspace",
    "SearchProviderConfig",
    # 宠物域
    "Pet",
    "UserActivePet",
    # 外部依赖模型
    "PermissionSaved",
    "EventLog",
]
