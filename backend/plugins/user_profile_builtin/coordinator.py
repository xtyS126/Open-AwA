"""
画像提取协调器。
负责：
1. 并发锁（asyncio.Lock）防止重复触发画像提取
2. N 轮兜底触发（默认 5 轮，可配置）
3. 复用 feedback._should_persist 决策触发画像提取
4. 读取用户配置（ProfileExtractionState.n_threshold）
"""

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from loguru import logger
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from db.models import ProfileExtractionState, ProfileFact


class ProfileExtractionCoordinator:
    """画像提取协调器（模块级单例）"""

    # 默认 N 轮兜底阈值：每累计 5 轮对话触发一次画像提取
    DEFAULT_N_THRESHOLD = 5

    def __init__(self):
        # 按 user_id 隔离的锁字典（每个用户独立锁，避免互相阻塞）
        self._locks: Dict[str, asyncio.Lock] = {}
        # 保护 _locks 字典本身的写入（防止并发创建同用户的锁）
        self._locks_guard = asyncio.Lock()

    async def _get_lock(self, user_id: str) -> asyncio.Lock:
        """获取指定用户的锁（不存在则创建）"""
        async with self._locks_guard:
            if user_id not in self._locks:
                self._locks[user_id] = asyncio.Lock()
            return self._locks[user_id]

    def _get_or_create_state(self, db: Session, user_id: str) -> ProfileExtractionState:
        """获取或创建用户的提取状态记录"""
        state = db.query(ProfileExtractionState).filter(
            ProfileExtractionState.user_id == user_id
        ).first()
        if state is None:
            state = ProfileExtractionState(
                user_id=user_id,
                turns_since_last_extract=0,
                n_threshold=self.DEFAULT_N_THRESHOLD,
                probe_flags={
                    "low_confidence": True,
                    "new_interest": True,
                    "periodic_review": False,
                },
            )
            db.add(state)
            db.commit()
            db.refresh(state)
        return state

    async def increment_turns(self, user_id: str, db: Session) -> int:
        """
        递增对话轮次计数器。
        返回递增后的 turns_since_last_extract 值。
        """
        state = self._get_or_create_state(db, user_id)
        state.turns_since_last_extract = (state.turns_since_last_extract or 0) + 1
        db.commit()
        db.refresh(state)
        return state.turns_since_last_extract

    def _reset_counter(self, db: Session, state: ProfileExtractionState) -> None:
        """提取完成后重置计数器"""
        state.turns_since_last_extract = 0
        state.last_extracted_at = datetime.now(timezone.utc)
        db.commit()

    # ProfileFact.category → OnionProfile 五层映射
    # surface(行为表象) ← behavior + context
    # interest(兴趣偏好) ← preference
    # role(角色认同) ← identity + expertise
    # values(价值驱动) ← goal + communication_style
    # core(核心人格) ← 暂不映射(emotional_state 衰减快不适合核心层)
    _CATEGORY_TO_LAYER: Dict[str, str] = {
        "behavior": "surface",
        "context": "surface",
        "preference": "interest",
        "identity": "role",
        "expertise": "role",
        "goal": "values",
        "communication_style": "values",
    }

    def _persist_onion_profile(self, db: Session, user_id: str) -> None:
        """
        从 ProfileFact 表构建 OnionProfile 并持久化到 user_profiles 表。

        桥接 ProfileExtractor(写 ProfileFact)与 SoulEngine(读 user_profiles):
        提取完成后,按 category 映射到 OnionProfile 五层,聚合 description/
        structured_data/confidence 后调用 save_profile 写入数据库。

        失败不阻断主流程(探针生成与计数器重置已完成),仅记录警告日志。

        Args:
            db: 数据库 session
            user_id: 用户 ID
        """
        try:
            from soul.persistence import save_profile
            from soul.profile import LayerData, OnionProfile

            # 读取该用户所有活跃事实
            facts: List[ProfileFact] = db.query(ProfileFact).filter(
                ProfileFact.user_id == user_id,
                ProfileFact.is_active.is_(True),
            ).all()

            if not facts:
                logger.bind(user_id=user_id).debug("无活跃事实,跳过 OnionProfile 持久化")
                return

            # 按五层分组
            layers: Dict[str, List[ProfileFact]] = {
                "surface": [], "interest": [], "role": [],
                "values": [], "core": [],
            }
            for fact in facts:
                layer_name = self._CATEGORY_TO_LAYER.get(fact.category, "")
                if layer_name:
                    layers[layer_name].append(fact)

            # 为每层构建 LayerData
            def _build_layer(layer_facts: List[ProfileFact]) -> LayerData:
                if not layer_facts:
                    return LayerData()
                # description: 拼接 fact_value(最多 5 条,用 "; " 分隔)
                values = [f.fact_value for f in layer_facts if f.fact_value][:5]
                description = "; ".join(values)
                # structured_data: {fact_key: fact_value}
                structured = {f.fact_key: f.fact_value for f in layer_facts if f.fact_key}
                # confidence: 平均置信度
                avg_conf = sum(f.confidence or 0.0 for f in layer_facts) / len(layer_facts)
                return LayerData(
                    description=description,
                    structured_data=structured,
                    confidence=round(avg_conf, 2),
                )

            profile = OnionProfile(
                user_id=user_id,
                surface=_build_layer(layers["surface"]),
                interest=_build_layer(layers["interest"]),
                role=_build_layer(layers["role"]),
                values=_build_layer(layers["values"]),
                core=_build_layer(layers["core"]),
            )

            save_profile(db, user_id, profile)
            logger.bind(
                user_id=user_id,
                fact_count=len(facts),
                layers_filled=sum(1 for v in layers.values() if v),
            ).info("OnionProfile 已从 ProfileFact 桥接并持久化")
        except Exception as exc:
            # 桥接失败不阻断主流程,记录完整堆栈便于诊断
            logger.bind(user_id=user_id).opt(exception=True).warning(
                f"OnionProfile 桥接持久化失败: {exc}"
            )

    async def maybe_extract(
        self,
        user_id: str,
        db: Session,
        force: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """
        决策并触发画像提取。

        Args:
            user_id: 用户 ID
            db: 数据库 session
            force: 是否强制触发（如 N 轮兜底）

        Returns:
            提取结果摘要（dict），未触发时返回 None
        """
        lock = await self._get_lock(user_id)

        # 非阻塞检查：若锁已被占用（提取进行中），直接跳过避免重复触发
        if lock.locked():
            logger.bind(user_id=user_id).info("画像提取正在进行中，跳过本次触发")
            return None

        async with lock:
            state = self._get_or_create_state(db, user_id)
            n_threshold = state.n_threshold or self.DEFAULT_N_THRESHOLD
            turns = state.turns_since_last_extract or 0

            # 决策：force 强制触发，或 N 轮兜底触发
            should_trigger = force or (turns >= n_threshold)

            if not should_trigger:
                logger.bind(
                    user_id=user_id,
                    turns=turns,
                    n_threshold=n_threshold,
                ).debug("画像提取未达触发条件，跳过")
                return None

            # 触发 ProfileExtractor（延迟导入避免循环依赖）
            try:
                from plugins.user_profile_builtin.profile_extractor import ProfileExtractor
                extractor = ProfileExtractor(db, user_id)
                result = await extractor.extract(trigger_type="auto")

                # 探针生成：在 _reset_counter 之前调用，
                # 确保 periodic_review 能基于触发时的 turns 值（如 20 的倍数）判断
                # 探针生成失败不影响提取结果
                try:
                    from soul.probe_generator import get_probe_generator
                    probe_gen = get_probe_generator()
                    probes = await probe_gen.generate_probes(user_id, db)
                    if probes:
                        logger.bind(
                            user_id=user_id,
                            probe_count=len(probes),
                        ).info("探针生成完成")
                except Exception as exc:
                    logger.bind(user_id=user_id).opt(exception=True).warning(
                        f"探针生成失败: {exc}"
                    )

                # 桥接 ProfileFact → OnionProfile 并持久化到 user_profiles 表
                # 确保 /api/soul/profile 能返回真实画像(非 null)
                # 失败不阻断主流程(探针已生成,计数器仍可重置)
                self._persist_onion_profile(db, user_id)

                # 提取完成后重置计数器
                self._reset_counter(db, state)

                logger.bind(
                    user_id=user_id,
                    result_status=result.get("status"),
                    facts_added=result.get("facts_added", 0),
                ).info("画像提取完成")

                return result
            except Exception as exc:
                # 兜底捕获：ProfileExtractor 内部已有异常处理，此处防止意外错误冒泡
                # 不静默吞异常，记录完整堆栈日志便于诊断
                logger.bind(user_id=user_id).opt(exception=True).error(
                    f"画像提取失败: {exc}"
                )
                return {
                    "status": "failed",
                    "message": str(exc),
                }

    def get_settings(self, user_id: str, db: Session) -> Dict[str, Any]:
        """获取用户画像设置"""
        state = self._get_or_create_state(db, user_id)
        return {
            "n_threshold": state.n_threshold or self.DEFAULT_N_THRESHOLD,
            "probe_flags": state.probe_flags or {
                "low_confidence": True,
                "new_interest": True,
                "periodic_review": False,
            },
            "turns_since_last_extract": state.turns_since_last_extract or 0,
            "last_extracted_at": state.last_extracted_at.isoformat()
            if state.last_extracted_at else None,
        }

    def update_settings(
        self,
        user_id: str,
        db: Session,
        n_threshold: Optional[int] = None,
        probe_flags: Optional[Dict[str, bool]] = None,
    ) -> Dict[str, Any]:
        """更新用户画像设置"""
        state = self._get_or_create_state(db, user_id)
        if n_threshold is not None:
            # N 值范围 3-20，防止用户设置过小（频繁触发）或过大（长期不触发）
            state.n_threshold = max(3, min(20, int(n_threshold)))
        if probe_flags is not None:
            # 合并 probe_flags（保留未传入的字段）
            # 注意：必须创建新 dict 触发 SQLAlchemy 的脏标记，
            # 原地修改 state.probe_flags 不会被 ORM 检测到变更
            current_flags = dict(state.probe_flags or {})
            current_flags.update(probe_flags)
            state.probe_flags = current_flags
            # 显式标记 JSON 列为脏,确保 UPDATE 语句生成
            # (SQLAlchemy 对 JSON 列重新赋值的脏标记检测在某些版本/配置下不可靠)
            flag_modified(state, "probe_flags")
        db.commit()
        db.refresh(state)
        return self.get_settings(user_id, db)


# 模块级单例
_coordinator: Optional[ProfileExtractionCoordinator] = None


def get_coordinator() -> ProfileExtractionCoordinator:
    """获取协调器单例"""
    global _coordinator
    if _coordinator is None:
        _coordinator = ProfileExtractionCoordinator()
    return _coordinator
