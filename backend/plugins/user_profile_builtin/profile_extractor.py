"""
用户画像提取引擎，基于 LLM 从对话内容和行为日志中提取结构化用户特征。

参考:
- PersonaX: 离线提取 + 在线注入的解耦架构
- Mem0: LLM 驱动的 ADD/UPDATE/DELETE/UNCHANGED 决策流水线
- ChatGPT Memory: 30-50 个结构化事实的直接上下文注入
"""

import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger
from sqlalchemy.orm import Session

from db.models import ProfileFact, ProfileExtractionLog, BehaviorLog, ShortTermMemory, Conversation
from .profile_dimensions import PROFILE_CATEGORIES
from .profile_confidence import (
    ConfidenceModel,
    generate_fact_id,
    generate_extraction_log_id,
)


class ProfileExtractor:
    """
    LLM 驱动的用户画像提取器。

    核心流程:
    1. 收集数据源（对话历史 + 行为日志 + 现有画像）
    2. 构建 Prompt（结构化 Schema + Few-shot 示例）
    3. 调用 LLM 提取事实
    4. 与现有画像比对合并
    5. 写入数据库 + 记录审计日志
    """

    # 每次提取的最大对话轮次
    MAX_TURNS_PER_EXTRACTION = 50
    # 最大行为日志条数
    MAX_BEHAVIOR_LOGS = 200
    # 已有画像上下文的最大 token 估算
    MAX_EXISTING_CONTEXT_CHARS = 3000

    def __init__(self, db: Session, user_id: str):
        self.db = db
        self.user_id = user_id
        self._prompt_templates: Dict[str, str] = {}

    async def extract(
        self,
        session_ids: Optional[List[str]] = None,
        trigger_type: str = "auto",
        model_name: str = "gpt-4o-mini",
        commit: bool = True,
    ) -> Dict[str, Any]:
        """
        执行画像提取（异步）。

        Args:
            session_ids: 要分析的会话 ID 列表，None 表示自动选择最近的会话
            trigger_type: 触发类型（auto/manual/scheduled）
            model_name: 使用的 LLM 模型
            commit: 是否在内部提交事务；True 时各写库步骤自行 commit（默认，向后兼容），
                    False 时 _apply_merge_result 与 _log_extraction 均 flush 不 commit，
                    由调用方（如 maybe_extract）统一 commit/rollback，实现与
                    OnionProfile 桥接的事务一致性收敛

        Returns:
            提取结果摘要
        """
        start_time = time.time()
        extraction_log_id = generate_extraction_log_id()

        logger.bind(
            user_id=self.user_id,
            trigger_type=trigger_type,
            extraction_log_id=extraction_log_id,
        ).info("开始用户画像提取")

        try:
            # Step 1: 收集数据源
            conversation_content, turns_count = self._collect_conversations(session_ids)
            behavior_summary, behavior_count = self._collect_behaviors()
            existing_facts = self._get_existing_facts()

            if turns_count == 0 and behavior_count == 0:
                return self._build_result(
                    extraction_log_id, "skipped",
                    "无对话内容和行为日志，跳过提取",
                    0, 0, 0, 0, 0,
                    start_time=start_time,
                )

            # Step 2: 构建 Prompt 并调用 LLM
            prompt = self._build_extraction_prompt(
                conversation_content, behavior_summary, existing_facts
            )
            raw_response = await self._call_llm(prompt, model_name)

            # Step 3: 解析 LLM 输出
            new_facts_data = self._parse_llm_response(raw_response)
            if not new_facts_data:
                return self._build_result(
                    extraction_log_id, "partial",
                    "LLM 未提取到新的画像事实",
                    turns_count, behavior_count, 0, 0, 0,
                    start_time=start_time,
                )

            # Step 4: 合并决策
            merge_result = self._merge_with_existing(existing_facts, new_facts_data)

            # Step 5: 写入数据库
            # _apply_merge_result 返回 (stats, applied_decisions),
            # applied_decisions 包含 add/update/delete 决策(不含 unchanged),
            # 供上层 maybe_extract 桥接到 OnionProfile 增量持久化
            # commit=False 时仅 flush,与后续 _log_extraction 及上层桥接收敛到同一事务
            stats, applied_decisions = self._apply_merge_result(
                merge_result, extraction_log_id, commit=commit
            )

            # Step 6: 记录提取日志
            # 同样透传 commit，保证事务边界由调用方控制
            self._log_extraction(
                extraction_log_id, trigger_type, session_ids,
                turns_count, behavior_count, model_name, stats, start_time,
                commit=commit,
            )

            logger.bind(
                user_id=self.user_id,
                extraction_log_id=extraction_log_id,
                **stats,
            ).info(f"用户画像提取完成: +{stats['added']}/~{stats['updated']}/"
                   f"-{stats['deleted']}/={stats['unchanged']}")

            result = self._build_result(
                extraction_log_id, "success",
                f"提取完成: 新增 {stats['added']}, 更新 {stats['updated']}, "
                f"删除 {stats['deleted']}, 不变 {stats['unchanged']}",
                turns_count, behavior_count, model_name=model_name,
                start_time=start_time, **stats,
            )
            # 暴露 decisions 供上层桥接到 OnionProfile 增量持久化
            result["decisions"] = applied_decisions
            return result

        except Exception as exc:
            logger.bind(
                user_id=self.user_id,
                extraction_log_id=extraction_log_id,
            ).opt(exception=True).error(f"画像提取失败: {exc}")

            # commit=False 模式下，清理未提交的部分变更，避免污染调用方事务
            # commit=True 模式下保持原行为（_log_extraction_error 内部 commit）
            if not commit:
                self.db.rollback()

            self._log_extraction_error(extraction_log_id, trigger_type, str(exc), start_time)
            return self._build_result(
                extraction_log_id, "failed",
                f"提取失败: {exc}",
                0, 0, 0, 0, 0,
                start_time=start_time,
            )

    def _collect_conversations(
        self, session_ids: Optional[List[str]]
    ) -> Tuple[str, int]:
        """
        收集对话历史内容。

        ShortTermMemory 表无 user_id 字段，需通过 Conversation 表（有 user_id）关联用户：
        先查 Conversation 中属于当前用户的 session_id 列表，再用这些 session_id
        过滤 ShortTermMemory。ShortTermMemory 用 timestamp 字段排序（无 created_at）。

        注意：不使用 ConversationRecord 表，因为该表由 conversation_recorder 异步写入，
        在数据清空后或异步写入失败时可能为空，而 Conversation 表在 chat 流程中同步写入更可靠。

        Args:
            session_ids: 指定会话 ID 列表

        Returns:
            (格式化的对话文本, 对话轮次数)
        """
        user_session_ids_query = self.db.query(Conversation.session_id).filter(
            Conversation.user_id == self.user_id,
        ).distinct()
        if session_ids:
            user_session_ids_query = user_session_ids_query.filter(
                Conversation.session_id.in_(session_ids)
            )
        user_session_ids = [row[0] for row in user_session_ids_query.all()]

        if not user_session_ids:
            return "", 0

        query = self.db.query(ShortTermMemory).filter(
            ShortTermMemory.session_id.in_(user_session_ids),
        )

        # 按时间倒序取最近的对话（ShortTermMemory 用 timestamp 字段）
        memories = query.order_by(
            ShortTermMemory.timestamp.desc()
        ).limit(self.MAX_TURNS_PER_EXTRACTION * 2).all()

        if not memories:
            return "", 0

        # 格式化对话
        lines = []
        for m in reversed(memories):
            role_label = "用户" if m.role == "user" else "助手"
            content = m.content or ""
            if len(content) > 2000:
                content = content[:2000] + "..."
            lines.append(f"[{role_label}]: {content}")

        return "\n".join(lines), len([m for m in memories if m.role == "user"])

    def _collect_behaviors(self) -> Tuple[str, int]:
        """
        收集近期行为日志摘要。

        Returns:
            (行为摘要文本, 行为记录数)
        """
        behaviors = self.db.query(BehaviorLog).filter(
            BehaviorLog.user_id == self.user_id
        ).order_by(
            BehaviorLog.timestamp.desc()
        ).limit(self.MAX_BEHAVIOR_LOGS).all()

        if not behaviors:
            return "", 0

        # 统计行为类型分布
        action_counts: Dict[str, int] = {}
        for b in behaviors:
            action = b.action_type or "unknown"
            action_counts[action] = action_counts.get(action, 0) + 1

        summary_parts = [f"近期行为统计（共 {len(behaviors)} 条记录）："]
        for action, count in sorted(action_counts.items(), key=lambda x: -x[1]):
            summary_parts.append(f"  - {action}: {count} 次")

        # 加入最近10条具体行为
        summary_parts.append("\n最近行为：")
        for b in behaviors[:10]:
            ts = b.timestamp.strftime("%m-%d %H:%M") if b.timestamp else "?"
            summary_parts.append(f"  [{ts}] {b.action_type}")

        return "\n".join(summary_parts), len(behaviors)

    def _get_existing_facts(self) -> List[Dict[str, Any]]:
        """获取用户现有的活跃画像事实"""
        facts = self.db.query(ProfileFact).filter(
            ProfileFact.user_id == self.user_id,
            ProfileFact.is_active == True,
        ).order_by(ProfileFact.confidence.desc()).all()

        return [
            {
                "category": f.category,
                "fact_key": f.fact_key,
                "fact_value": f.fact_value,
                "confidence": f.confidence,
                "source_type": f.source_type,
            }
            for f in facts
        ]

    def _build_extraction_prompt(
        self,
        conversation_content: str,
        behavior_summary: str,
        existing_facts: List[Dict[str, Any]],
    ) -> str:
        """构建画像提取的 Prompt"""
        template = self._load_prompt_template("extract_profile.txt")

        # 构建已有画像上下文
        if existing_facts:
            by_category: Dict[str, List[str]] = {}
            for f in existing_facts:
                cat = f["category"]
                if cat not in by_category:
                    by_category[cat] = []
                by_category[cat].append(
                    f"  [{f['fact_key']}] = \"{f['fact_value']}\" "
                    f"(置信度: {f['confidence']:.0%}, 来源: {f['source_type']})"
                )

            context_parts = []
            for cat, items in by_category.items():
                cat_label = PROFILE_CATEGORIES.get(cat, {}).get("label", cat)
                context_parts.append(f"### {cat_label} ({cat})")
                context_parts.extend(items[:15])  # 每类最多15条

            existing_context = "\n".join(context_parts)
            if len(existing_context) > self.MAX_EXISTING_CONTEXT_CHARS:
                existing_context = existing_context[:self.MAX_EXISTING_CONTEXT_CHARS] + "\n... (已截断)"
        else:
            existing_context = "暂无已有画像数据"

        # 注意：模板中包含 JSON 示例（如 {"extracted_facts": ...}），
        # 不能用 str.format()（会把 JSON 的 {...} 当作变量名解析抛 KeyError），
        # 改用 str.replace 逐个替换占位符。
        return (
            template
            .replace("{existing_profile_context}", existing_context)
            .replace("{conversation_content}", conversation_content or "无对话内容")
            .replace("{recent_behaviors}", behavior_summary or "无行为数据")
        )

    def _load_prompt_template(self, filename: str) -> str:
        """加载 Prompt 模板文件"""
        if filename in self._prompt_templates:
            return self._prompt_templates[filename]

        import os
        template_dir = os.path.join(os.path.dirname(__file__), "prompts")
        template_path = os.path.join(template_dir, filename)

        try:
            with open(template_path, "r", encoding="utf-8") as f:
                content = f.read()
            self._prompt_templates[filename] = content
            return content
        except FileNotFoundError:
            logger.warning(f"Prompt 模板文件未找到: {template_path}，使用内联默认模板")
            return self._get_fallback_template(filename)

    def _get_fallback_template(self, filename: str) -> str:
        """获取内联回退 Prompt 模板"""
        if "extract" in filename:
            return (
                "从以下对话中提取用户画像事实。\n"
                "返回 JSON: {\"extracted_facts\": [{"
                "\"category\": \"...\", \"fact_key\": \"...\", \"fact_value\": \"...\", "
                "\"confidence\": 0.5, \"evidence\": \"...\", \"action\": \"add\"}]}\n\n"
                "已有画像:\n{existing_profile_context}\n\n"
                "对话:\n{conversation_content}\n\n"
                "行为:\n{recent_behaviors}"
            )
        return ""

    async def _call_llm(self, prompt: str, model_name: str) -> str:
        """
        调用 LLM 进行画像提取（异步）。

        使用项目已有的 litellm_adapter 进行调用。
        provider 和 api_key 解析顺序：
        1. 默认 ModelConfiguration（若 api_key 有效）
        2. 遍历所有 active provider 的 ModelConfiguration，找到第一个有凭据的
        3. DeepSeek 优先（v4-flash > v4-pro），与 E2E 测试一致
        """
        try:
            from core.litellm_adapter import litellm_chat_completion
            from billing.pricing_manager import PricingManager
            from config.security import decrypt_secret_value
            from db.models import ModelConfiguration, ProviderCredential

            pricing_manager = PricingManager(self.db)

            # 候选配置列表：默认配置 + 所有 active 配置（去重）
            default_config = pricing_manager.get_default_configuration()
            all_configs = self.db.query(ModelConfiguration).filter(
                ModelConfiguration.is_active == True,
            ).all()

            # 按 provider 分组，DeepSeek 优先
            def _config_priority(c):
                # 优先级：deepseek-v4-flash > deepseek-v4-pro > deepseek 其他 > 其他
                p = (c.provider or "").lower()
                m = (c.model or "").lower()
                if p == "deepseek" and "v4-flash" in m:
                    return 0
                if p == "deepseek" and "v4-pro" in m:
                    return 1
                if p == "deepseek":
                    return 2
                return 3

            candidates = sorted(all_configs, key=_config_priority)
            if default_config and default_config not in candidates:
                candidates.insert(0, default_config)

            provider = ""
            model = model_name or ""
            api_key = ""
            api_endpoint = None

            for config in candidates:
                p = (config.provider or "").strip()
                m = (config.model or "").strip()
                if not p or not m:
                    continue

                # 优先从 ModelConfiguration.api_key 解密
                raw_key = getattr(config, "api_key", "") or ""
                if raw_key:
                    if raw_key.startswith("enc:"):
                        continue
                    api_key = decrypt_secret_value(raw_key) or ""
                else:
                    # 回退到 ProviderCredential 表
                    cred = pricing_manager.get_provider_credential(p)
                    if cred and cred.api_key:
                        if cred.api_key.startswith("enc:"):
                            continue
                        api_key = decrypt_secret_value(cred.api_key) or ""
                        if not api_endpoint and getattr(cred, "base_url", None):
                            api_endpoint = cred.base_url

                if api_key:
                    provider = p
                    model = m
                    api_endpoint = api_endpoint or config.api_endpoint
                    logger.info(f"画像提取选用 provider={provider}, model={model}")
                    break

            if not api_key or not provider:
                logger.warning("无法从任何 active provider 解析有效 API Key")
                return json.dumps({
                    "extracted_facts": [],
                    "summary": "API Key 未配置或已失效"
                })

            messages = [
                {
                    "role": "system",
                    "content": "你是一个专业的用户画像分析器。你的输出必须是严格的 JSON 格式。"
                },
                {"role": "user", "content": prompt},
            ]

            response = await litellm_chat_completion(
                provider=provider,
                model=model,
                messages=messages,
                api_key=api_key,
                api_base=api_endpoint,
                temperature=0.3,
                max_tokens=4000,
            )

            # litellm_adapter 返回的字典可能包含 ok 字段
            # 成功: {"ok": True, "response": "...", "reasoning_content": "..."}
            # 失败: {"ok": False, "error": {...}}
            if not response:
                logger.warning("LLM 返回空响应对象")
                return ""

            if response.get("ok") is False:
                error_info = response.get("error", {})
                logger.warning(f"LLM 调用返回错误: {error_info.get('error_type', 'unknown')}: {error_info.get('message', '')}")
                return json.dumps({
                    "extracted_facts": [],
                    "summary": f"LLM 调用失败: {error_info.get('message', 'unknown')}"
                })

            # 优先取 response 字段（litellm_adapter 的标准返回格式）
            content = response.get("response") or ""
            reasoning = response.get("reasoning_content") or ""

            # 兼容原始 choices 格式
            if not content and response.get("choices"):
                choices = response["choices"]
                if choices and isinstance(choices[0], dict):
                    msg = choices[0].get("message", {})
                    content = msg.get("content") or ""
                    reasoning = msg.get("reasoning_content") or ""

            # 某些 reasoner 模型（如 deepseek-v4-flash）可能把内容放在 reasoning_content
            if not content and reasoning:
                logger.info("LLM content 为空，使用 reasoning_content 作为响应")
                content = reasoning

            if not content:
                logger.warning(f"LLM 响应 content 和 reasoning_content 均为空，完整响应 keys: {list(response.keys())}")

            return content

        except ImportError:
            logger.warning("litellm_adapter 不可用，返回空结果")
            return json.dumps({
                "extracted_facts": [],
                "summary": "LLM 服务不可用"
            })
        except Exception as exc:
            logger.opt(exception=True).error(f"LLM 调用失败: {exc}")
            raise

    def _parse_llm_response(self, raw_response: str) -> List[Dict[str, Any]]:
        """解析 LLM 返回的 JSON 响应"""
        if not raw_response:
            return []

        try:
            # 尝试直接解析
            data = json.loads(raw_response)
            return data.get("extracted_facts", [])
        except json.JSONDecodeError:
            pass

        # 尝试提取 JSON 块
        try:
            # 查找 ```json ... ``` 代码块
            import re
            json_match = re.search(r'```(?:json)?\s*([\s\S]*?)```', raw_response)
            if json_match:
                data = json.loads(json_match.group(1))
                return data.get("extracted_facts", [])
        except (json.JSONDecodeError, AttributeError):
            pass

        # 尝试查找第一个完整的 JSON 对象
        try:
            import re
            # 使用非贪婪匹配查找第一个完整的 JSON 对象
            brace_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', raw_response)
            if brace_match:
                data = json.loads(brace_match.group(0))
                return data.get("extracted_facts", [])
            # 回退：尝试匹配更宽泛的 JSON
            brace_match = re.search(r'\{[\s\S]*?"extracted_facts"[\s\S]*?\}', raw_response)
            if brace_match:
                data = json.loads(brace_match.group(0))
                return data.get("extracted_facts", [])
        except (json.JSONDecodeError, AttributeError):
            pass

        logger.warning(f"无法解析 LLM 响应为 JSON: {raw_response[:200]}...")
        return []

    def _merge_with_existing(
        self,
        existing_facts: List[Dict[str, Any]],
        new_facts_data: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        将新提取的事实与已有事实合并。

        使用规则引擎而非 LLM 进行合并决策，降低延迟和成本。
        只在规则无法判断时才使用 LLM。
        """
        existing_map: Dict[str, Dict[str, Any]] = {}
        for f in existing_facts:
            key = f"{f['category']}:{f['fact_key']}"
            existing_map[key] = f

        decisions = []
        for new_fact in new_facts_data:
            cat = new_fact.get("category", "custom")
            key = new_fact.get("fact_key", "").strip()
            val = new_fact.get("fact_value", "").strip()
            confidence = float(new_fact.get("confidence", 0.5))
            action = new_fact.get("action", "add")

            if not key or not val:
                continue
            if cat not in PROFILE_CATEGORIES:
                cat = "custom"

            # 规范化
            key = key.lower().replace(" ", "_")
            compound_key = f"{cat}:{key}"

            if compound_key in existing_map:
                existing = existing_map[compound_key]

                if action == "delete":
                    decisions.append({
                        "category": cat, "fact_key": key, "fact_value": val,
                        "confidence": confidence, "action": "delete",
                        "reason": "LLM标记删除",
                    })
                elif existing["fact_value"].strip() == val:
                    # 值相同，不变
                    decisions.append({
                        "category": cat, "fact_key": key, "fact_value": val,
                        "confidence": max(confidence, existing["confidence"]),
                        "action": "unchanged",
                        "reason": "值与已有记录一致",
                    })
                else:
                    # 值不同，更新
                    # 加权合并置信度
                    if confidence >= 0.8 and existing["confidence"] < 0.5:
                        w_new, w_old = 0.7, 0.3
                    elif confidence < 0.5 and existing["confidence"] >= 0.7:
                        w_new, w_old = 0.2, 0.8
                    else:
                        w_new, w_old = 0.4, 0.6

                    merged_confidence = confidence * w_new + existing["confidence"] * w_old
                    decisions.append({
                        "category": cat, "fact_key": key, "fact_value": val,
                        "confidence": round(merged_confidence, 2),
                        "action": "update",
                        "reason": f"值变更: \"{existing['fact_value']}\" -> \"{val}\"",
                    })
            else:
                # 新事实
                if action != "delete":
                    decisions.append({
                        "category": cat, "fact_key": key, "fact_value": val,
                        "confidence": confidence, "action": "add",
                        "reason": "新发现的事实",
                    })

        return decisions

    def _apply_merge_result(
        self,
        decisions: List[Dict[str, Any]],
        extraction_log_id: str,
        commit: bool = True,
    ) -> Tuple[Dict[str, int], List[Dict[str, Any]]]:
        """应用合并决策到数据库

        Args:
            decisions: 合并决策列表(来自 _merge_with_existing)
            extraction_log_id: 提取日志 ID(用于 fact_metadata 关联)
            commit: 是否在内部提交事务；True 时执行 db.commit()（默认，向后兼容），
                    False 时仅 flush 让变更在当前事务可见，由调用方统一提交/回滚

        Returns:
            (stats, applied_decisions):
              - stats: 统计信息 {added, updated, deleted, unchanged}
              - applied_decisions: 实际应用的决策列表(包含 add/update/delete/unchanged),
                供上层桥接到 OnionProfile 增量持久化
        """
        stats = {"added": 0, "updated": 0, "deleted": 0, "unchanged": 0}
        now = datetime.now(timezone.utc)
        applied_decisions: List[Dict[str, Any]] = []

        for d in decisions:
            compound_key = f"{d['category']}:{d['fact_key']}"
            existing = self.db.query(ProfileFact).filter(
                ProfileFact.user_id == self.user_id,
                ProfileFact.category == d["category"],
                ProfileFact.fact_key == d["fact_key"],
            ).first()

            if d["action"] == "add":
                if existing:
                    # 冲突：数据库已存在同 key 记录（可能由并发提取导致），转换为 update
                    logger.bind(
                        user_id=self.user_id,
                        compound_key=compound_key,
                        old_value=existing.fact_value,
                        new_value=d["fact_value"],
                    ).warning("画像事实 add 动作因已存在记录而转换为 update")
                    existing.fact_value = d["fact_value"]
                    existing.confidence = d["confidence"]
                    existing.last_updated_at = now
                    existing.source_type = "inferred"
                    stats["updated"] += 1
                    # 实际动作转换为 update,记录转换后的动作便于上层增量重建
                    applied_decisions.append({**d, "action": "update"})
                else:
                    new_fact = ProfileFact(
                        id=generate_fact_id(),
                        user_id=self.user_id,
                        category=d["category"],
                        fact_key=d["fact_key"],
                        fact_value=d["fact_value"],
                        confidence=d["confidence"],
                        source_type="inferred",
                        first_observed_at=now,
                        last_updated_at=now,
                        fact_metadata={"extraction_log_id": extraction_log_id},
                    )
                    self.db.add(new_fact)
                    stats["added"] += 1
                    applied_decisions.append(d)

            elif d["action"] == "update":
                if existing:
                    existing.fact_value = d["fact_value"]
                    existing.confidence = d["confidence"]
                    existing.last_updated_at = now
                    stats["updated"] += 1
                    applied_decisions.append(d)

            elif d["action"] == "delete":
                if existing:
                    existing.is_active = False
                    existing.last_updated_at = now
                    stats["deleted"] += 1
                    applied_decisions.append(d)

            elif d["action"] == "unchanged":
                if existing:
                    existing.access_count += 1
                    existing.last_accessed_at = now
                stats["unchanged"] += 1
                # unchanged 不属于变更,不追加到 applied_decisions
                # (上层 changed_facts 只需 add/update/delete)

        # flush 让变更在当前事务可见，便于后续步骤读取到最新状态
        self.db.flush()

        if commit:
            self.db.commit()
        return stats, applied_decisions

    def _log_extraction(
        self,
        extraction_log_id: str,
        trigger_type: str,
        session_ids: Optional[List[str]],
        turns_count: int,
        behavior_count: int,
        model_name: str,
        stats: Dict[str, int],
        start_time: float,
        commit: bool = True,
    ):
        """记录提取日志

        Args:
            commit: 是否在内部提交事务；True 时执行 db.commit()（默认，向后兼容），
                    False 时仅 add 不 commit，由调用方统一提交/回滚
        """
        duration_ms = int((time.time() - start_time) * 1000)
        log_entry = ProfileExtractionLog(
            id=extraction_log_id,
            user_id=self.user_id,
            trigger_type=trigger_type,
            source_session_ids=session_ids,
            conversation_turns_analyzed=turns_count,
            behavior_logs_analyzed=behavior_count,
            facts_added=stats.get("added", 0),
            facts_updated=stats.get("updated", 0),
            facts_deleted=stats.get("deleted", 0),
            facts_unchanged=stats.get("unchanged", 0),
            llm_model_used=model_name,
            extraction_duration_ms=duration_ms,
            status="success",
        )
        self.db.add(log_entry)
        self.db.flush()

        if commit:
            self.db.commit()

    def _log_extraction_error(
        self,
        extraction_log_id: str,
        trigger_type: str,
        error_message: str,
        start_time: float,
    ):
        """记录提取错误日志"""
        try:
            duration_ms = int((time.time() - start_time) * 1000)
            log_entry = ProfileExtractionLog(
                id=extraction_log_id,
                user_id=self.user_id,
                trigger_type=trigger_type,
                status="failed",
                error_message=error_message[:1000],
                extraction_duration_ms=duration_ms,
            )
            self.db.add(log_entry)
            self.db.commit()
        except Exception as exc:
            logger.opt(exception=True).error(f"记录提取错误日志失败: {exc}")

    def _build_result(
        self,
        extraction_log_id: str,
        status: str,
        message: str,
        turns_count: int,
        behavior_count: int,
        added: int,
        updated: int,
        deleted: int,
        unchanged: int = 0,
        start_time: float = 0,
        model_name: str = "",
    ) -> Dict[str, Any]:
        """构建返回结果"""
        duration_ms = int((time.time() - start_time) * 1000) if start_time else 0
        return {
            "extraction_id": extraction_log_id,
            "status": status,
            "message": message,
            "conversation_turns_analyzed": turns_count,
            "behavior_logs_analyzed": behavior_count,
            "facts_added": added,
            "facts_updated": updated,
            "facts_deleted": deleted,
            "facts_unchanged": unchanged,
            "model": model_name,
            "duration_ms": duration_ms,
        }
