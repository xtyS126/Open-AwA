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
from typing import Any, Dict, List, Optional, Set, Tuple

from loguru import logger
from sqlalchemy.exc import SQLAlchemyError
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
    # surface(行为表象) ← behavior + context + emotional_state + custom
    # interest(兴趣偏好) ← preference
    # role(角色认同) ← identity + expertise
    # values(价值驱动) ← goal + communication_style
    # core(核心人格) ← 暂不映射(emotional_state 衰减快不适合核心层)
    _CATEGORY_TO_LAYER: Dict[str, str] = {
        "behavior": "surface",
        "context": "surface",
        "emotional_state": "surface",
        "custom": "surface",
        "preference": "interest",
        "identity": "role",
        "expertise": "role",
        "goal": "values",
        "communication_style": "values",
    }

    def _persist_onion_profile(
        self,
        db: Session,
        user_id: str,
        changed_facts: Optional[List[Dict[str, Any]]] = None,
        commit: bool = True,
    ) -> None:
        """
        从 ProfileFact 表构建 OnionProfile 并持久化到 user_profiles 表。

        桥接 ProfileExtractor(写 ProfileFact)与 SoulEngine(读 user_profiles):
        提取完成后,按 category 映射到 OnionProfile 五层,聚合 description/
        structured_data/confidence 后调用 save_profile 写入数据库。

        支持两种模式:
        1. 增量模式(changed_facts 非 None): 仅重建受影响层,保留未受影响层原有数据
           - 根据 changed_facts 的 category 计算受影响的层(_CATEGORY_TO_LAYER)
           - 仅重新查询这些受影响层的所有活跃事实(而非全部事实)
           - 重建这些层的 LayerData
           - 未受影响层从现有 OnionProfile 读取(load_profile)保留原数据
        2. 全量重建(changed_facts 为 None): 查询所有活跃事实,重建五层(fallback)

        事务收敛:
        - commit=True(默认,向后兼容): save_profile 内部 commit,失败抛异常由调用方处理
        - commit=False: save_profile 仅 flush 不 commit,与 ProfileFact 写入收敛到同一事务
          桥接失败时抛出异常,由调用方(maybe_extract 或 CRUD 接口)统一 rollback

        异常处理:
        - 本方法不吞异常,SQLAlchemy 错误会向上抛出
        - 调用方需在事务边界 try/except 并执行 rollback

        Args:
            db: 数据库 session
            user_id: 用户 ID
            changed_facts: 变更事实列表,每个 dict 包含 category/fact_key/fact_value/action 字段,
                          action ∈ {"add", "update", "delete"};None 时走全量重建 fallback
            commit: 是否在内部提交事务;透传给 save_profile

        Raises:
            SQLAlchemyError: 数据库操作失败时抛出,由调用方处理
        """
        from soul.persistence import load_profile, save_profile
        from soul.profile import LayerData, OnionProfile

        # 五层名称固定顺序
        all_layers: Tuple[str, ...] = (
            "surface", "interest", "role", "values", "core",
        )

        # 为每层构建 LayerData 的辅助函数(全量与增量共用)
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

        if changed_facts is None:
            # ===== 全量重建 fallback =====
            # 读取该用户所有活跃事实
            facts: List[ProfileFact] = db.query(ProfileFact).filter(
                ProfileFact.user_id == user_id,
                ProfileFact.is_active.is_(True),
            ).all()

            if not facts:
                logger.bind(user_id=user_id).debug("无活跃事实,跳过 OnionProfile 持久化")
                return

            # 按五层分组
            layers: Dict[str, List[ProfileFact]] = {name: [] for name in all_layers}
            for fact in facts:
                layer_name = self._CATEGORY_TO_LAYER.get(fact.category, "")
                if layer_name:
                    layers[layer_name].append(fact)

            profile = OnionProfile(
                user_id=user_id,
                surface=_build_layer(layers["surface"]),
                interest=_build_layer(layers["interest"]),
                role=_build_layer(layers["role"]),
                values=_build_layer(layers["values"]),
                core=_build_layer(layers["core"]),
            )

            save_profile(db, user_id, profile, commit=commit)
            logger.bind(
                user_id=user_id,
                fact_count=len(facts),
                layers_filled=sum(1 for v in layers.values() if v),
                mode="full",
            ).info("OnionProfile 已从 ProfileFact 桥接并持久化(全量重建)")
            return

        # ===== 增量模式 =====
        # 1. 根据 changed_facts 的 category 计算受影响的层
        affected_layers: Set[str] = set()
        for cf in changed_facts:
            category = cf.get("category", "")
            layer_name = self._CATEGORY_TO_LAYER.get(category, "")
            if layer_name:
                affected_layers.add(layer_name)

        if not affected_layers:
            logger.bind(
                user_id=user_id,
                changed_count=len(changed_facts),
            ).debug("变更事实未命中任何层,跳过 OnionProfile 增量持久化")
            return

        # 2. 仅重新查询受影响层的所有活跃事实
        # 反查受影响层对应的 category 列表(用于 IN 查询)
        affected_categories: List[str] = [
            cat for cat, layer in self._CATEGORY_TO_LAYER.items()
            if layer in affected_layers
        ]

        affected_facts: List[ProfileFact] = []
        if affected_categories:
            affected_facts = db.query(ProfileFact).filter(
                ProfileFact.user_id == user_id,
                ProfileFact.is_active.is_(True),
                ProfileFact.category.in_(affected_categories),
            ).all()

        # 按层分组受影响事实
        affected_layer_facts: Dict[str, List[ProfileFact]] = {
            name: [] for name in affected_layers
        }
        for fact in affected_facts:
            layer_name = self._CATEGORY_TO_LAYER.get(fact.category, "")
            if layer_name in affected_layer_facts:
                affected_layer_facts[layer_name].append(fact)

        # 3. 读取现有 OnionProfile,保留未受影响层的原有 LayerData
        existing_profile: Optional[OnionProfile] = load_profile(db, user_id)

        # 4. 构建各层 LayerData:受影响层用新数据重建,未受影响层保留原数据
        layer_kwargs: Dict[str, LayerData] = {}
        for name in all_layers:
            if name in affected_layers:
                layer_kwargs[name] = _build_layer(affected_layer_facts[name])
            elif existing_profile is not None:
                # 保留未受影响层的原有 LayerData
                layer_kwargs[name] = getattr(existing_profile, name)
            else:
                # 现有画像不存在时,未受影响层初始化为空 LayerData
                layer_kwargs[name] = LayerData()

        profile = OnionProfile(user_id=user_id, **layer_kwargs)

        save_profile(db, user_id, profile, commit=commit)
        logger.bind(
            user_id=user_id,
            changed_count=len(changed_facts),
            affected_layers=sorted(affected_layers),
            affected_fact_count=len(affected_facts),
            mode="incremental",
        ).info("OnionProfile 已从 ProfileFact 桥接并持久化(增量模式)")

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
            # 事务收敛：extract 与 _persist_onion_profile 均 commit=False，
            # 在同一事务内完成 ProfileFact 写入与 OnionProfile 桥接，
            # 最后统一 db.commit()；任一步骤失败则 db.rollback() 保证一致性
            try:
                from plugins.user_profile_builtin.profile_extractor import ProfileExtractor
                extractor = ProfileExtractor(db, user_id)
                # commit=False: extract 内部 _apply_merge_result 与 _log_extraction
                # 仅 flush 不 commit，等待本方法统一提交
                result = await extractor.extract(trigger_type="auto", commit=False)

                # 探针生成：在 _reset_counter 之前调用，
                # 确保 periodic_review 能基于触发时的 turns 值（如 20 的倍数）判断
                # 探针生成失败不影响提取结果，也不影响主事务
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
                # 增量模式:从 extract 结果提取 decisions(add/update/delete),
                # 仅重建受影响层,保留未受影响层原有数据,避免全量重建开销
                # commit=False: 与 extract 收敛到同一事务，由本方法统一 commit/rollback
                decisions: List[Dict[str, Any]] = (
                    result.get("decisions", []) if isinstance(result, dict) else []
                )
                changed_facts: List[Dict[str, Any]] = [
                    {
                        "category": d.get("category", ""),
                        "fact_key": d.get("fact_key", ""),
                        "fact_value": d.get("fact_value", ""),
                        "action": d.get("action", ""),
                    }
                    for d in decisions
                    if isinstance(d, dict) and d.get("action") in ("add", "update", "delete")
                ]
                # _persist_onion_profile 不再吞异常，桥接失败抛出由本 except 捕获
                self._persist_onion_profile(
                    db, user_id, changed_facts=changed_facts, commit=False
                )

                # 统一提交：ProfileFact 写入 + ProfileExtractionLog + OnionProfile 桥接
                # 在同一事务内原子提交，消除原有的数据不一致时间窗口
                db.commit()

                # 提取完成后重置计数器（独立事务，不影响上面已提交的主事务）
                self._reset_counter(db, state)

                logger.bind(
                    user_id=user_id,
                    result_status=result.get("status"),
                    facts_added=result.get("facts_added", 0),
                ).info("画像提取完成")

                return result
            except SQLAlchemyError as exc:
                # 数据库相关异常：回滚事务，保证 ProfileFact 与 OnionProfile 一致性
                logger.bind(user_id=user_id).opt(exception=True).error(
                    f"画像提取事务失败(数据库错误),已回滚: {exc}"
                )
                db.rollback()
                return {
                    "status": "failed",
                    "message": str(exc),
                }
            except Exception as exc:
                # 兜底捕获：ProfileExtractor 内部已有异常处理，此处防止意外错误冒泡
                # 不静默吞异常，记录完整堆栈日志便于诊断
                # 同样回滚事务，避免未提交的变更残留
                logger.bind(user_id=user_id).opt(exception=True).error(
                    f"画像提取失败,已回滚: {exc}"
                )
                db.rollback()
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
