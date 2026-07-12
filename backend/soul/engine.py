"""
Soul Engine 主入口。
协调画像分析器、管道和存储，提供统一的画像管理接口。

持久化层接入说明：
- 内存缓存 _profiles 仅作为请求级短期缓存，避免每次请求都查库
- 通过 db: Optional[Session] 参数注入持久化能力
- db 为 None 时降级为纯内存模式（仅打印 warning，不阻塞调用方）
- db 提供时：get_profile 未命中查库 → process_event 后写回库 → clear_profile 删库
"""
import copy
from typing import Dict, Optional

from loguru import logger
from sqlalchemy.orm import Session

from db.models import UserProfileOverride
from soul.event import BehaviorEvent
from soul.overrides import ProfileOverrides
from soul.persistence import delete_profile, load_profile, save_profile
from soul.pipeline import ProfileUpdatePipeline
from soul.profile import OnionProfile


class SoulEngine:
    """
    Soul Engine 主类。
    协调画像分析器、管道和存储，提供统一的画像管理接口。
    """

    def __init__(self):
        self.pipeline = ProfileUpdatePipeline()
        # 内存中的画像缓存（短期，避免每次请求都查库）
        self._profiles: Dict[str, OnionProfile] = {}
        logger.info("SoulEngine 初始化完成")

    async def process_event(
        self,
        user_id: str,
        event: BehaviorEvent,
        db: Optional[Session] = None,
    ) -> OnionProfile:
        """
        处理单个行为事件，更新用户画像。

        Args:
            user_id: 用户ID
            event: 行为事件
            db: 可选的数据库会话，传入时会持久化画像到 user_profiles 表

        Returns:
            OnionProfile: 更新后的画像
        """
        event.user_id = user_id
        current_profile = self._load_profile_internal(user_id, db)

        updated_profile = await self.pipeline.process([event], current_profile)
        updated_profile.user_id = user_id

        # 更新内存缓存并持久化（若 db 提供）
        self._profiles[user_id] = updated_profile
        self._save_profile_internal(user_id, updated_profile, db)

        return updated_profile

    async def process_events(
        self,
        user_id: str,
        events: list,
        db: Optional[Session] = None,
    ) -> OnionProfile:
        """
        处理多个行为事件，批量更新用户画像。

        Args:
            user_id: 用户ID
            events: 行为事件列表
            db: 可选的数据库会话，传入时会持久化画像到 user_profiles 表

        Returns:
            OnionProfile: 更新后的画像
        """
        for event in events:
            event.user_id = user_id

        current_profile = self._load_profile_internal(user_id, db)

        updated_profile = await self.pipeline.process(events, current_profile)
        updated_profile.user_id = user_id

        # 更新内存缓存并持久化（若 db 提供）
        self._profiles[user_id] = updated_profile
        self._save_profile_internal(user_id, updated_profile, db)

        return updated_profile

    def get_profile(
        self,
        user_id: str,
        db: Optional[Session] = None,
    ) -> Optional[OnionProfile]:
        """
        获取用户画像（已合并用户手动编辑的覆盖层）。

        读取流程：内存缓存 / 数据库加载原始 AI 画像 → 应用 UserProfileOverride 覆盖层。
        覆盖层合并失败时降级返回原始 AI 画像，不阻塞读取。

        Args:
            user_id: 用户ID
            db: 可选的数据库会话，传入时内存未命中会回查数据库并应用覆盖层

        Returns:
            Optional[OnionProfile]: 合并覆盖层后的画像，不存在时返回 None
        """
        profile = self._load_profile_internal(user_id, db)
        return self._apply_overrides(user_id, profile, db)

    def get_or_create_profile(
        self,
        user_id: str,
        db: Optional[Session] = None,
    ) -> OnionProfile:
        """
        获取或创建用户画像（已合并用户手动编辑的覆盖层）。

        不存在时创建空画像并持久化，随后统一应用 UserProfileOverride 覆盖层。
        覆盖层合并失败时降级返回原始 AI 画像，不阻塞读取。

        Args:
            user_id: 用户ID
            db: 可选的数据库会话，传入时创建的空画像会持久化到 user_profiles 表

        Returns:
            OnionProfile: 合并覆盖层后的画像
        """
        profile = self._load_profile_internal(user_id, db)
        if profile is None:
            # 创建空画像并持久化
            profile = OnionProfile(user_id=user_id)
            self._profiles[user_id] = profile
            self._save_profile_internal(user_id, profile, db)

        # 应用覆盖层；profile 非 None 时 _apply_overrides 必返回非 None，
        # 此处的 None 兜底仅为满足类型检查
        merged = self._apply_overrides(user_id, profile, db)
        return merged if merged is not None else profile

    def get_profile_summary(
        self,
        user_id: str,
        db: Optional[Session] = None,
    ) -> str:
        """
        获取用户画像摘要。

        Args:
            user_id: 用户ID
            db: 可选的数据库会话

        Returns:
            str: 画像摘要文本
        """
        profile = self.get_profile(user_id, db)
        if profile is None:
            return "画像尚未建立"
        return profile.get_summary()

    def get_profile_for_prompt(
        self,
        user_id: str,
        db: Optional[Session] = None,
    ) -> str:
        """
        获取用于注入 system prompt 的画像摘要。
        格式化为适合 LLM 理解的文本。

        Args:
            user_id: 用户ID
            db: 可选的数据库会话

        Returns:
            str: 画像摘要（适合注入 prompt）
        """
        profile = self.get_profile(user_id, db)
        if profile is None:
            return ""

        parts = []
        parts.append("[用户画像]")
        if profile.surface.description:
            parts.append(f"- 行为偏好: {profile.surface.description}")
        if profile.interest.description:
            parts.append(f"- 兴趣偏好: {profile.interest.description}")
        if profile.role.description:
            parts.append(f"- 角色认同: {profile.role.description}")
        if profile.core.description:
            parts.append(f"- 人格特征: {profile.core.description}")
        if len(parts) <= 1:
            return ""

        return "\n".join(parts)

    def clear_profile(
        self,
        user_id: str,
        db: Optional[Session] = None,
    ) -> None:
        """
        清除用户画像。

        Args:
            user_id: 用户ID
            db: 可选的数据库会话，传入时会同步删除数据库记录
        """
        # 先移除内存缓存
        if user_id in self._profiles:
            del self._profiles[user_id]

        # 再删除数据库记录（若 db 提供）
        if db is not None:
            try:
                delete_profile(db, user_id)
            except Exception as exc:
                # 持久化失败不阻塞内存清空，但需记录日志便于排查
                logger.bind(user_id=user_id).opt(exception=True).warning(
                    f"删除数据库画像记录失败: {exc}"
                )

        logger.info(f"已清除用户画像: {user_id}")

    # ---- 内部辅助方法 ----

    def _load_profile_internal(
        self,
        user_id: str,
        db: Optional[Session],
    ) -> Optional[OnionProfile]:
        """
        加载画像的内部统一入口：先查内存缓存，未命中且 db 提供时回查数据库。

        数据库命中后写入内存缓存，避免后续请求重复查库。
        """
        cached = self._profiles.get(user_id)
        if cached is not None:
            return cached

        if db is None:
            return None

        try:
            db_profile = load_profile(db, user_id)
        except Exception as exc:
            # 数据库异常降级为未命中，不影响主流程
            logger.bind(user_id=user_id).opt(exception=True).warning(
                f"加载数据库画像失败，降级为内存模式: {exc}"
            )
            return None

        if db_profile is not None:
            # 数据库命中后写入内存缓存
            self._profiles[user_id] = db_profile
        return db_profile

    def _save_profile_internal(
        self,
        user_id: str,
        profile: OnionProfile,
        db: Optional[Session],
    ) -> None:
        """
        持久化画像的内部统一入口：db 为 None 时打印 warning 并跳过持久化。
        """
        if db is None:
            logger.bind(user_id=user_id).debug(
                "未传入 db 会话，画像仅保留在内存缓存，重启后将丢失"
            )
            return

        try:
            save_profile(db, user_id, profile)
        except Exception as exc:
            # 持久化失败不阻塞内存更新，但需记录日志便于排查
            logger.bind(user_id=user_id).opt(exception=True).warning(
                f"持久化画像到数据库失败: {exc}"
            )

    def _apply_overrides(
        self,
        user_id: str,
        profile: Optional[OnionProfile],
        db: Optional[Session],
    ) -> Optional[OnionProfile]:
        """
        应用用户手动编辑的画像覆盖层。

        覆盖层优先级高于 AI 推断，实现"用户编辑 ⊕ AI 画像"的合并逻辑。
        合并失败时降级返回原画像，不阻塞读取流程。

        Args:
            user_id: 用户ID
            profile: AI 推断的原始画像（None 时直接返回 None）
            db: 数据库会话，None 时跳过覆盖层查询

        Returns:
            Optional[OnionProfile]: 合并后的画像；无覆盖层或合并失败时返回原画像
        """
        # 无画像或无 db 会话时直接返回，不应用覆盖层
        if profile is None or db is None:
            return profile

        try:
            db_override = db.query(UserProfileOverride).filter(
                UserProfileOverride.user_id == user_id
            ).first()
        except Exception as exc:
            # 查询异常降级为原画像，不阻塞读取
            logger.bind(user_id=user_id).opt(exception=True).warning(
                f"查询画像覆盖层失败，降级返回原画像: {exc}"
            )
            return profile

        # 无覆盖层记录或空覆盖层时直接返回原画像
        if db_override is None:
            return profile
        overrides_data = db_override.overrides or {}
        if not overrides_data:
            return profile

        # 深拷贝原画像，避免 merge() 共享 LayerData 引用导致
        # 内存缓存 _profiles 中的 AI 原始画像被污染
        profile_copy = copy.deepcopy(profile)

        try:
            overrides = ProfileOverrides(
                user_id=db_override.user_id,
                overrides=dict(overrides_data),
                created_at=db_override.created_at,
                updated_at=db_override.updated_at,
            )
            merged_profile = overrides.merge(profile_copy)
            logger.bind(user_id=user_id).debug("画像覆盖层已合并")
            return merged_profile
        except Exception as exc:
            # 合并失败降级返回原画像，不阻塞读取
            logger.bind(user_id=user_id).opt(exception=True).warning(
                f"合并画像覆盖层失败，降级返回原画像: {exc}"
            )
            return profile
