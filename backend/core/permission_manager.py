"""
Agent 级运行时权限管理器，实现 ask/assert/reply 权限模型。

参考 OpenCode PermissionV2 设计：
- 代理拥有独立的 permissions 规则（Ruleset）
- 工具执行前通过 assert_permission 进行权限检查
- 三种决策结果：allow（自动放行）、deny（拒绝）、ask（阻塞等待用户确认）
- 用户可通过 WebSocket/SSE 回复权限请求
- 权限决策可持久化（always），跨会话生效
"""

import asyncio
import json
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set

from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy.exc import SQLAlchemyError

from core.denial_tracking import (
    DENIAL_LIMITS,
    DenialTrackingState,
    record_denial,
    record_success,
    should_fallback_to_prompting,
)


class PermissionEffect(str, Enum):
    """权限决策结果"""
    ALLOW = "allow"
    DENY = "deny"
    ASK = "ask"


class PermissionRule(BaseModel):
    """单条权限规则，定义 action/resource/effect 三元组"""
    action: str = Field(description="操作名称，支持通配符 * 和前缀通配符 action:*")
    resource: str = Field(description="资源标识，支持通配符 *")
    effect: PermissionEffect = Field(description="决策结果")


class PermissionRuleset(BaseModel):
    """权限规则集合，由多条 Rule 按顺序组成"""
    rules: List[PermissionRule] = Field(default_factory=list)

    @classmethod
    def from_list(cls, rules: List[Dict[str, str]]) -> "PermissionRuleset":
        """从字典列表构建规则集合"""
        parsed = []
        for rule in rules:
            parsed.append(PermissionRule(
                action=rule.get("action", "*"),
                resource=rule.get("resource", "*"),
                effect=PermissionEffect(rule.get("effect", "ask")),
            ))
        return cls(rules=parsed)


class PermissionRequest(BaseModel):
    """待处理的权限请求"""
    id: str = Field(description="请求唯一标识")
    session_id: str = Field(description="会话 ID")
    action: str = Field(description="请求的操作")
    resources: List[str] = Field(description="涉及的资源列表")
    save: Optional[List[str]] = Field(default=None, description="可选持久化的资源")
    metadata: Optional[Dict[str, Any]] = Field(default=None, description="额外元数据")
    agent: Optional[str] = Field(default=None, description="发起请求的代理 ID")


class PermissionReply(BaseModel):
    """用户对权限请求的回复"""
    request_id: str = Field(description="请求 ID")
    reply: str = Field(description="回复类型: once/always/reject")
    message: Optional[str] = Field(default=None, description="拒绝时的反馈消息")


def wildcard_match(pattern: str, value: str) -> bool:
    """
    通配符匹配函数，参考 OpenCode Wildcard.match 设计。

    规则：
    - * 匹配任意字符串（含空串）
    - prefix:* 匹配 prefix: 开头的任意值
    - 完全相同时也算匹配
    - [NEW] mcp__server1__* 匹配 mcp__server1__tool1（MCP 服务级通配符）
    - [NEW] mcp__server1* 匹配 mcp__server1__tool1（MCP 前缀通配符）
    """
    if pattern == "*" or value == "*":
        return True
    if pattern == value:
        return True
    # 前缀通配符匹配（如 skill:* 匹配 skill:read）
    if pattern.endswith(":*"):
        prefix = pattern[:-2] + ":"
        if value.startswith(prefix):
            return True
    # 值的前缀通配符（如 *:read 匹配 skill:read）
    if pattern.startswith("*:"):
        suffix = pattern[1:]
        if value.endswith(suffix):
            return True
    # [NEW] MCP 服务级通配符匹配：mcp__server1__* 匹配 mcp__server1__tool1
    if pattern.endswith("__*"):
        prefix = pattern[:-3]  # 去掉 __*，保留 mcp__server1
        if value.startswith(prefix + "__"):
            return True
    # [NEW] MCP 前缀通配符匹配：mcp__server1* 匹配 mcp__server1__tool1
    # 排除已处理的 :* 与 __* 情况，避免重复匹配
    elif pattern.endswith("*") and not pattern.endswith(":*"):
        prefix = pattern[:-1]  # 去掉末尾 *
        if value.startswith(prefix):
            return True
    return False


def matches_mcp_server(pattern: str, tool_name: str) -> bool:
    """
    判断 MCP 服务级权限规则是否匹配工具全限定名。

    匹配规则：
    - pattern 为两段（mcp__server1）：匹配该服务下所有工具（mcp__server1__*）
    - pattern 为三段（mcp__server1__tool1）：精确匹配
    - 完全相同时也算匹配

    :param pattern: 权限规则模式（两段或三段）
    :param tool_name: 工具全限定名（三段式 mcp__<server>__<tool>）
    :return: 是否匹配
    """
    # 完全相同直接匹配
    if pattern == tool_name:
        return True

    # 非 MCP 前缀的模式不参与服务级匹配
    if not pattern.startswith("mcp__"):
        return False

    pattern_parts = pattern.split("__")
    # 两段式（mcp__server1）：服务级匹配，匹配 mcp__server1__* 的所有工具
    if len(pattern_parts) == 2:
        return tool_name.startswith(pattern + "__")

    # 三段式（mcp__server1__tool1）：已由完全相等判断处理，此处不匹配
    return False


def evaluate_permission(
    action: str,
    resource: str,
    *rulesets: List[PermissionRule],
) -> PermissionRule:
    """
    评估权限：按顺序查找最后一条匹配的规则。

    优先级（后匹配覆盖前匹配）：
    1. 遍历所有规则集合（代理规则 → 全局规则 → 已保存规则）
    2. 找到最后一条同时匹配 action 和 resource 的规则
    3. 若无匹配规则，返回默认 ASK

    这遵循 OpenCode 的 "last match wins" 策略，
    使得更具体的规则（通常添加在后面）可以覆盖更一般的规则。
    """
    matched_rule: Optional[PermissionRule] = None
    all_rules: List[PermissionRule] = []
    for ruleset in rulesets:
        all_rules.extend(ruleset)

    for rule in all_rules:
        if wildcard_match(rule.action, action) and wildcard_match(rule.resource, resource):
            matched_rule = rule

    if matched_rule is None:
        return PermissionRule(action=action, resource=resource, effect=PermissionEffect.ASK)

    return matched_rule


def evaluate_effect(
    action: str,
    resource: str,
    *rulesets: List[PermissionRule],
) -> PermissionEffect:
    """评估权限并返回 effect 结果（便捷方法）"""
    return evaluate_permission(action, resource, *rulesets).effect


class PermissionDeniedError(Exception):
    """权限被拒绝时抛出的异常"""
    def __init__(self, message: str, rules: Optional[List[PermissionRule]] = None):
        super().__init__(message)
        self.rules = rules or []


class PermissionRejectedError(Exception):
    """用户拒绝权限请求时抛出的异常"""
    pass


class PermissionCorrectedError(Exception):
    """用户拒绝并附带反馈时抛出的异常"""
    def __init__(self, feedback: str):
        super().__init__(feedback)
        self.feedback = feedback


@dataclass
class PendingPermission:
    """待处理的权限请求状态"""
    request: PermissionRequest
    agent: Optional[str] = None
    deferred: asyncio.Future = field(default_factory=asyncio.Future)


class PermissionManager:
    """
    运行时权限管理器。

    核心职责：
    1. 评估权限规则（代理规则 + 全局规则 + 持久化规则）
    2. 管理待处理的权限请求（ask 模式）
    3. 处理用户回复（allow/deny/always）
    4. 持久化 "always" 决策
    5. 追踪权限拒绝次数，auto 模式下超限回退到人工模式
    """

    def __init__(self, db_session=None):
        self._db_session = db_session
        # 待处理的权限请求 keyed by request_id
        self._pending: Dict[str, PendingPermission] = {}
        # 持久化的权限决策缓存（按 cache_key 区分用户作用域）
        self._saved_cache: Optional[Dict[str, List[PermissionRule]]] = None
        # 事件回调：当有新权限请求时通知前端
        self._on_permission_asked: Optional[callable] = None
        # 全局默认规则
        self._global_rules: List[PermissionRule] = []
        # 全局权限拒绝追踪状态
        self.denial_state: DenialTrackingState = DenialTrackingState()
        # 是否处于 auto 模式（自动授权，超限回退到人工模式）
        self.auto_mode: bool = False

    def set_event_callback(self, callback: callable) -> None:
        """设置权限请求事件回调（用于 WebSocket/SSE 推送）"""
        self._on_permission_asked = callback

    def set_global_rules(self, rules: List[PermissionRule]) -> None:
        """设置全局权限规则"""
        self._global_rules = rules

    def set_auto_mode(self, enabled: bool) -> None:
        """设置 auto 模式开关（auto 模式下自动授权，超限回退到人工模式）"""
        self.auto_mode = enabled

    def _get_active_denial_state(
        self,
        local_denial_tracking: Optional[DenialTrackingState],
    ) -> DenialTrackingState:
        """获取当前生效的拒绝追踪状态：local 优先于全局"""
        if local_denial_tracking is not None:
            return local_denial_tracking
        return self.denial_state

    def _update_denial_state(
        self,
        new_state: DenialTrackingState,
        local_denial_tracking: Optional[DenialTrackingState],
    ) -> None:
        """
        更新拒绝追踪状态。

        若传入 local_denial_tracking，则原地更新其字段（保持引用不变）；
        否则更新全局 self.denial_state。
        """
        if local_denial_tracking is not None:
            # 原地更新 local 状态字段，保持调用方引用可见
            local_denial_tracking.consecutive_denials = new_state.consecutive_denials
            local_denial_tracking.total_denials = new_state.total_denials
        else:
            self.denial_state = new_state

    def _check_and_fallback(
        self,
        state: DenialTrackingState,
        local_denial_tracking: Optional[DenialTrackingState],
    ) -> None:
        """
        在 auto 模式下检查是否需要回退到人工模式。

        触发条件：should_fallback_to_prompting(state) 返回 True。
        回退动作：关闭 auto_mode 并记录 warning 日志。
        """
        if not self.auto_mode:
            return
        if should_fallback_to_prompting(state):
            self.auto_mode = False
            logger.warning(
                f"连续拒绝超限，回退到人工模式: consecutive={state.consecutive_denials}"
            )

    def _get_agent_rules(self, agent_id: Optional[str] = None) -> List[PermissionRule]:
        """
        获取指定代理的权限规则。

        代理权限规则定义：
        - build（默认全权限代理）：允许所有操作
        - plan（只读代理）：仅允许读操作
        - general-purpose（通用代理）：需要用户确认写操作
        """
        if agent_id == "plan" or agent_id == "Explore":
            # 只读代理：catch-all deny 在前，具体 allow 规则在后覆盖（last-match-wins）
            return [
                PermissionRule(action="*", resource="*", effect=PermissionEffect.DENY),
                PermissionRule(action="read", resource="*", effect=PermissionEffect.ALLOW),
                PermissionRule(action="glob", resource="*", effect=PermissionEffect.ALLOW),
                PermissionRule(action="grep", resource="*", effect=PermissionEffect.ALLOW),
                PermissionRule(action="web_search", resource="*", effect=PermissionEffect.ALLOW),
                PermissionRule(action="web_fetch", resource="*", effect=PermissionEffect.ALLOW),
                PermissionRule(action="skill", resource="*", effect=PermissionEffect.ALLOW),
            ]
        elif agent_id == "build":
            # 全权限代理：允许所有操作
            return [
                PermissionRule(action="*", resource="*", effect=PermissionEffect.ALLOW),
            ]
        elif agent_id == "general-purpose":
            # 通用代理：基调是 ALLOW，但对写操作覆写为 ASK 要求用户确认
            # 使用 last-match-wins：宽规则在前，具体覆写在后面
            return [
                PermissionRule(action="*", resource="*", effect=PermissionEffect.ALLOW),
                PermissionRule(action="edit", resource="*", effect=PermissionEffect.ASK),
                PermissionRule(action="write", resource="*", effect=PermissionEffect.ASK),
                PermissionRule(action="bash", resource="*", effect=PermissionEffect.ASK),
            ]
        else:
            # 未知代理类型，回退到空规则（全部 ASK）
            return []

    async def _get_saved_rules(self, user_id: Optional[str] = None) -> List[PermissionRule]:
        """
        从数据库加载持久化的权限规则。

        当提供 user_id 时，仅加载该用户保存的规则（按 created_by 过滤），
        防止用户 A 保存的 always allow 规则影响用户 B 的权限决策。
        user_id 为 None 时加载所有规则（向后兼容）。
        """
        # 缓存按 user_id 区分（防止用户 A 的规则被缓存到用户 B 的查询中）
        cache_key = user_id or "__global__"
        if self._saved_cache is not None and cache_key in self._saved_cache:
            return self._saved_cache[cache_key]

        if not self._db_session:
            return []

        try:
            from db.permission_models import PermissionSaved

            def _sync_load():
                query = self._db_session.query(PermissionSaved)
                if user_id is not None:
                    query = query.filter(PermissionSaved.created_by == user_id)
                records = query.all()
                return [
                    PermissionRule(
                        action=record.action,
                        resource=record.resource,
                        effect=PermissionEffect.ALLOW,
                    )
                    for record in records
                ]

            if self._saved_cache is None:
                self._saved_cache = {}
            self._saved_cache[cache_key] = await asyncio.to_thread(_sync_load)
            return self._saved_cache[cache_key]
        except (SQLAlchemyError, asyncio.TimeoutError, ImportError) as e:
            logger.warning(f"加载已保存权限失败: {e}")
            return []

    async def evaluate(self, action: str, resource: str, agent_id: Optional[str] = None, user_id: Optional[str] = None) -> PermissionEffect:
        """
        评估权限，返回决策效果。

        评估链：代理规则 → 全局规则 → 已保存规则（按 user_id 过滤）
        """
        agent_rules = self._get_agent_rules(agent_id)
        saved_rules = await self._get_saved_rules(user_id)
        return evaluate_effect(action, resource, agent_rules, self._global_rules, saved_rules)

    async def ask(
        self,
        session_id: str,
        action: str,
        resources: List[str],
        save: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        agent_id: Optional[str] = None,
        user_id: Optional[str] = None,
        local_denial_tracking: Optional[DenialTrackingState] = None,
    ) -> Dict[str, Any]:
        """
        发起权限请求。

        评估权限规则后：
        - allow → 直接返回 {effect: "allow"}，并记录一次成功（重置连续拒绝）
        - deny → 抛出 PermissionDeniedError，并记录一次拒绝
        - ask → 创建待处理请求，返回 {id, effect: "ask"}

        user_id 用于过滤已保存的权限规则（仅加载当前用户的规则）。
        待处理请求需要通过 reply() 完成。

        local_denial_tracking 用于子 Agent 本地拒绝追踪，优先于全局 self.denial_state。
        在 auto 模式下，若拒绝超限将自动回退到人工模式。
        """
        import uuid

        request_id = f"per_{uuid.uuid4().hex[:12]}"

        # 防御：resources 不能为空
        if not resources:
            raise ValueError("resources 不能为空")

        # 先评估每条资源的权限
        effects: Set[PermissionEffect] = set()
        for resource in resources:
            effect = await self.evaluate(action, resource, agent_id, user_id)
            effects.add(effect)

        # 决定最终效果（deny 优先，ask 其次）
        if PermissionEffect.DENY in effects:
            # 记录一次拒绝并检查是否需要回退到人工模式
            active_state = self._get_active_denial_state(local_denial_tracking)
            new_state = record_denial(active_state)
            self._update_denial_state(new_state, local_denial_tracking)
            self._check_and_fallback(new_state, local_denial_tracking)

            relevant_rules = [
                rule for rule in (self._get_agent_rules(agent_id) + self._global_rules)
                if wildcard_match(rule.action, action)
            ]
            raise PermissionDeniedError(
                f"操作 {action} 被禁止访问资源 {resources}",
                rules=relevant_rules,
            )

        if PermissionEffect.ASK in effects:
            # auto 模式下，ASK 自动放行（仍记录成功以重置连续拒绝）
            if self.auto_mode:
                active_state = self._get_active_denial_state(local_denial_tracking)
                new_state = record_success(active_state)
                self._update_denial_state(new_state, local_denial_tracking)
                return {"id": request_id, "effect": "allow"}

            # manual 模式：创建权限请求等待用户回复
            request = PermissionRequest(
                id=request_id,
                session_id=session_id,
                action=action,
                resources=resources,
                save=save,
                metadata=metadata,
                agent=agent_id,
            )
            pending = PendingPermission(
                request=request,
                agent=agent_id,
            )
            self._pending[request_id] = pending

            # 通知前端
            if self._on_permission_asked:
                try:
                    await self._on_permission_asked(request.model_dump())
                except (TypeError, ValueError, RuntimeError, AttributeError, asyncio.TimeoutError) as e:
                    logger.warning(f"权限请求通知回调失败: {e}")

            logger.info(
                f"权限请求已创建: {request_id} action={action} resources={resources} agent={agent_id}"
            )
            return {"id": request_id, "effect": "ask"}

        # allow：记录一次成功以重置连续拒绝
        active_state = self._get_active_denial_state(local_denial_tracking)
        new_state = record_success(active_state)
        self._update_denial_state(new_state, local_denial_tracking)
        return {"id": request_id, "effect": "allow"}

    async def assert_permission(
        self,
        session_id: str,
        action: str,
        resources: List[str],
        save: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        agent_id: Optional[str] = None,
        local_denial_tracking: Optional[DenialTrackingState] = None,
    ) -> None:
        """
        断言权限（阻塞版本）。

        与 ask 的区别：
        - allow → 直接返回
        - deny → 抛出 PermissionDeniedError
        - ask → 阻塞等待用户回复

        local_denial_tracking 用于子 Agent 本地拒绝追踪，优先于全局 self.denial_state。
        """
        result = await self.ask(
            session_id=session_id,
            action=action,
            resources=resources,
            save=save,
            metadata=metadata,
            agent_id=agent_id,
            local_denial_tracking=local_denial_tracking,
        )

        if result["effect"] == "allow":
            return

        # ask 模式：阻塞等待用户回复
        pending = self._pending.get(result["id"])
        if not pending:
            return

        try:
            await asyncio.wait_for(pending.deferred, timeout=300.0)  # 5 分钟超时
        except asyncio.TimeoutError:
            self._pending.pop(result["id"], None)
            raise PermissionRejectedError()
        except PermissionRejectedError:
            self._pending.pop(result["id"], None)
            raise
        except PermissionCorrectedError as e:
            self._pending.pop(result["id"], None)
            raise

    async def reply(self, request_id: str, reply: str, message: Optional[str] = None) -> None:
        """
        处理用户对权限请求的回复。

        - once: 仅本次允许
        - always: 持久化允许规则
        - reject: 拒绝
        """
        pending = self._pending.get(request_id)
        if not pending:
            raise ValueError(f"权限请求 {request_id} 不存在或已过期")

        if reply == "reject":
            # 级联拒绝同 session 的其他 pending 请求
            session_id = pending.request.session_id
            to_reject = [
                pid for pid, p in self._pending.items()
                if p.request.session_id == session_id
            ]
            for pid in to_reject:
                p = self._pending.pop(pid, None)
                if p and not p.deferred.done():
                    if message and pid == request_id:
                        p.deferred.set_exception(PermissionCorrectedError(message))
                    else:
                        p.deferred.set_exception(PermissionRejectedError())

            logger.info(f"权限请求 {request_id} 被拒绝，级联拒绝 {len(to_reject)} 个请求")
            return

        if reply == "always" and pending.request.save:
            # 持久化权限规则
            await self._save_permission(
                action=pending.request.action,
                resources=pending.request.save,
            )

        # 完成当前请求
        if not pending.deferred.done():
            pending.deferred.set_result(None)
        self._pending.pop(request_id, None)

        # 如果是 always，级联批准同 session 中可以被已保存规则覆盖的请求
        if reply == "always" and pending.request.save:
            saved_rules = await self._get_saved_rules()
            session_id = pending.request.session_id
            for pid, p in list(self._pending.items()):
                if p.request.session_id != session_id:
                    continue
                if p.deferred.done():
                    continue
                # 检查是否所有资源都可以被已保存规则覆盖
                all_allowed = all(
                    evaluate_effect(p.request.action, resource, saved_rules) == PermissionEffect.ALLOW
                    for resource in p.request.resources
                )
                if all_allowed:
                    p.deferred.set_result(None)
                    self._pending.pop(pid, None)

        logger.info(f"权限请求 {request_id} 已处理: reply={reply}")

    async def _save_permission(self, action: str, resources: List[str]) -> None:
        """持久化权限规则到数据库"""
        if not self._db_session:
            logger.warning("无法持久化权限：无数据库会话")
            return

        try:
            from db.permission_models import PermissionSaved, PROJECT_GLOBAL

            def _sync_save():
                for resource in resources:
                    # 检查是否已存在
                    existing = self._db_session.query(PermissionSaved).filter(
                        PermissionSaved.action == action,
                        PermissionSaved.resource == resource,
                    ).first()
                    if existing:
                        continue
                    record = PermissionSaved(
                        action=action,
                        resource=resource,
                        project_id=PROJECT_GLOBAL,
                    )
                    self._db_session.add(record)
                self._db_session.commit()

            await asyncio.to_thread(_sync_save)
            # 清除缓存以重新加载
            self._saved_cache = None
            logger.info(f"已持久化权限: action={action} resources={resources}")
        except (SQLAlchemyError, asyncio.TimeoutError, ImportError) as e:
            logger.error(f"持久化权限失败: {e}")
            if self._db_session:
                try:
                    await asyncio.to_thread(self._db_session.rollback)
                except SQLAlchemyError as rollback_exc:
                    logger.bind(
                        event="permission_rollback_failed",
                        module="permission_manager",
                        error=str(rollback_exc),
                    ).error(f"权限回滚失败，数据库状态可能不一致: {rollback_exc}")

    def get_pending_requests(self, session_id: Optional[str] = None) -> List[PermissionRequest]:
        """获取待处理的权限请求"""
        requests = [p.request for p in self._pending.values()]
        if session_id:
            requests = [r for r in requests if r.session_id == session_id]
        return requests

    def get_request(self, request_id: str) -> Optional[PermissionRequest]:
        """获取指定的权限请求"""
        pending = self._pending.get(request_id)
        return pending.request if pending else None

    def cancel_session_requests(self, session_id: str) -> int:
        """取消指定会话的所有待处理权限请求"""
        to_cancel = [
            pid for pid, p in self._pending.items()
            if p.request.session_id == session_id
        ]
        for pid in to_cancel:
            p = self._pending.pop(pid, None)
            if p and not p.deferred.done():
                p.deferred.set_exception(PermissionRejectedError())
        return len(to_cancel)

    async def cleanup(self) -> None:
        """清理所有待处理请求"""
        for pid, p in list(self._pending.items()):
            if not p.deferred.done():
                p.deferred.set_exception(PermissionRejectedError())
        self._pending.clear()
        self._saved_cache = None


# 全局单例
_default_manager: Optional[PermissionManager] = None


def get_permission_manager(db_session=None) -> PermissionManager:
    """获取全局 PermissionManager 实例（非单例，按需创建）"""
    return PermissionManager(db_session)
