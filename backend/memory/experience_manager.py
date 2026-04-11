"""
经验记忆管理模块，负责经验数据的增删改查、语义搜索与检索。
提供基于规则和基于关键词的混合检索策略，支持经验复用与质量评估。
"""

import asyncio
import json
from typing import List, Dict, Optional, Any
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, desc, func
from db.models import ExperienceMemory
from loguru import logger


class ExperienceManager:
    """
    经验记忆管理器，提供经验的增删改查和混合检索功能。
    所有异步方法内部通过 asyncio.to_thread 包装同步数据库操作，
    避免在异步事件循环中阻塞。
    """
    
    def __init__(self, db: Session):
        """
        初始化经验管理器。
        参数:
            db: SQLAlchemy 数据库会话实例
        """
        self.db = db
        logger.info("ExperienceManager initialized")
    
    def _add_experience_sync(
        self,
        experience_type: str,
        title: str,
        content: str,
        trigger_conditions: str,
        confidence: float,
        source_task: str,
        metadata: Optional[Dict],
        user_id: Optional[str]
    ) -> ExperienceMemory:
        """同步方法：向数据库插入一条经验记录。"""
        experience = ExperienceMemory(
            experience_type=experience_type,
            title=title,
            content=content,
            trigger_conditions=trigger_conditions,
            confidence=confidence,
            source_task=source_task,
            experience_metadata=json.dumps(metadata) if metadata else '{}',
            user_id=user_id
        )
        self.db.add(experience)
        self.db.commit()
        self.db.refresh(experience)
        return experience

    async def add_experience(
        self,
        experience_type: str,
        title: str,
        content: str,
        trigger_conditions: str,
        confidence: float = 0.5,
        source_task: str = 'general',
        metadata: Optional[Dict] = None,
        user_id: Optional[str] = None
    ) -> ExperienceMemory:
        """
        添加一条新的经验记录。
        参数:
            experience_type: 经验类型分类
            title: 经验标题
            content: 经验内容详情
            trigger_conditions: 触发条件描述
            confidence: 置信度 (0.0-1.0)
            source_task: 来源任务类型
            metadata: 附加元数据
            user_id: 所属用户ID
        返回: 新创建的 ExperienceMemory 实例
        """
        experience = await asyncio.to_thread(
            self._add_experience_sync,
            experience_type, title, content, trigger_conditions,
            confidence, source_task, metadata, user_id
        )
        logger.info(f"Added new experience: {title} (type: {experience_type})")
        return experience
    
    def _get_experiences_sync(
        self,
        experience_type: Optional[str],
        min_confidence: float,
        source_task: Optional[str],
        limit: int,
        offset: int,
        sort_by: str,
        order: str
    ) -> List[ExperienceMemory]:
        """同步方法：按条件查询经验列表。"""
        query = self.db.query(ExperienceMemory)
        
        if experience_type:
            query = query.filter(ExperienceMemory.experience_type == experience_type)
        if min_confidence > 0:
            query = query.filter(ExperienceMemory.confidence >= min_confidence)
        if source_task:
            query = query.filter(ExperienceMemory.source_task == source_task)
        
        sort_column = getattr(ExperienceMemory, sort_by, ExperienceMemory.confidence)
        if order == 'desc':
            query = query.order_by(desc(sort_column))
        else:
            query = query.order_by(sort_column)
        
        return query.offset(offset).limit(limit).all()

    async def get_experiences(
        self,
        experience_type: Optional[str] = None,
        min_confidence: float = 0.0,
        source_task: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
        sort_by: str = 'confidence',
        order: str = 'desc'
    ) -> List[ExperienceMemory]:
        """
        按条件获取经验记录列表。
        参数:
            experience_type: 按经验类型过滤
            min_confidence: 最低置信度阈值
            source_task: 按来源任务过滤
            limit: 返回数量上限
            offset: 分页偏移量
            sort_by: 排序字段名
            order: 排序方向 ('asc'/'desc')
        返回: 满足条件的经验列表
        """
        return await asyncio.to_thread(
            self._get_experiences_sync,
            experience_type, min_confidence, source_task,
            limit, offset, sort_by, order
        )
    
    def _get_experience_by_id_sync(self, experience_id: int) -> Optional[ExperienceMemory]:
        """同步方法：按ID查询单条经验记录。"""
        return self.db.query(ExperienceMemory).filter(
            ExperienceMemory.id == experience_id
        ).first()

    async def get_experience_by_id(self, experience_id: int) -> Optional[ExperienceMemory]:
        """
        根据ID获取单条经验记录。
        参数:
            experience_id: 经验记录的主键ID
        返回: ExperienceMemory 实例，不存在时返回 None
        """
        return await asyncio.to_thread(
            self._get_experience_by_id_sync, experience_id
        )
    
    def _search_experiences_sync(
        self,
        query_text: str,
        experience_type: Optional[str],
        min_confidence: float,
        limit: int
    ) -> List[ExperienceMemory]:
        """同步方法：按关键字搜索经验记录并更新访问统计。"""
        query = self.db.query(ExperienceMemory).filter(
            or_(
                ExperienceMemory.title.contains(query_text),
                ExperienceMemory.content.contains(query_text),
                ExperienceMemory.trigger_conditions.contains(query_text)
            )
        )
        
        if experience_type:
            query = query.filter(ExperienceMemory.experience_type == experience_type)
        if min_confidence > 0:
            query = query.filter(ExperienceMemory.confidence >= min_confidence)
        
        experiences = query.order_by(
            desc(ExperienceMemory.confidence),
            desc(ExperienceMemory.usage_count)
        ).limit(limit).all()
        
        # 批量更新访问计数和最后访问时间
        for exp in experiences:
            exp.usage_count += 1
            exp.last_access = datetime.now(timezone.utc)
        
        self.db.commit()
        return experiences

    async def search_experiences(
        self,
        query_text: str,
        experience_type: Optional[str] = None,
        min_confidence: float = 0.0,
        limit: int = 10
    ) -> List[ExperienceMemory]:
        """
        按关键字搜索经验记录，同时更新匹配记录的访问统计。
        参数:
            query_text: 搜索关键字
            experience_type: 按经验类型过滤
            min_confidence: 最低置信度阈值
            limit: 返回数量上限
        返回: 匹配的经验记录列表
        """
        return await asyncio.to_thread(
            self._search_experiences_sync,
            query_text, experience_type, min_confidence, limit
        )
    
    def _semantic_search_experiences_sync(
        self,
        keywords: List[str],
        task_context: Optional[Dict],
        limit: int
    ) -> List[ExperienceMemory]:
        """同步方法：基于关键词的语义搜索，并更新访问统计。"""
        conditions = []
        for keyword in keywords:
            conditions.append(ExperienceMemory.content.contains(keyword))
            conditions.append(ExperienceMemory.title.contains(keyword))
            conditions.append(ExperienceMemory.trigger_conditions.contains(keyword))
        
        query_obj = self.db.query(ExperienceMemory).filter(
            and_(
                or_(*conditions),
                ExperienceMemory.confidence >= 0.3
            )
        )
        
        # 优先匹配相同任务类型的经验
        if task_context and 'task_type' in task_context:
            task_experiences = query_obj.filter(
                ExperienceMemory.source_task == task_context['task_type']
            ).limit(limit).all()
            
            if task_experiences:
                return task_experiences
        
        experiences = query_obj.order_by(
            desc(ExperienceMemory.confidence),
            desc(ExperienceMemory.success_count)
        ).limit(limit).all()
        
        # 批量更新访问计数
        for exp in experiences:
            exp.usage_count += 1
            exp.last_access = datetime.now(timezone.utc)
        
        self.db.commit()
        return experiences

    async def semantic_search_experiences(
        self,
        query: str,
        task_context: Optional[Dict] = None,
        limit: int = 5
    ) -> List[ExperienceMemory]:
        """
        基于关键词提取的语义搜索，支持任务上下文优先匹配。
        参数:
            query: 查询文本，会自动提取关键词
            task_context: 任务上下文（可选），含 task_type 时优先匹配
            limit: 返回数量上限
        返回: 语义匹配的经验列表
        """
        keywords = self._extract_keywords(query)
        
        if not keywords:
            return []
        
        return await asyncio.to_thread(
            self._semantic_search_experiences_sync,
            keywords, task_context, limit
        )
    
    def _extract_keywords(self, text: str) -> List[str]:
        """
        处理extract、keywords相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        stop_words = {'的', '了', '是', '在', '和', '与', '或', '我', '你', '他', '她', '它', '这', '那', '有', '没有', '要', '不', '能', '会', '可以', '如何', '怎么', '什么', '哪个', '哪些'}
        
        words = text.replace(',', ' ').replace('。', ' ').replace('！', ' ').replace('？', ' ').split()
        keywords = [w for w in words if w not in stop_words and len(w) >= 2]
        
        return keywords[:10]
    
    def _rule_based_search_sync(
        self,
        conditions: Dict[str, Any],
        limit: int
    ) -> List[ExperienceMemory]:
        """同步方法：基于规则条件搜索经验记录。"""
        query = self.db.query(ExperienceMemory)
        
        if 'task_type' in conditions:
            query = query.filter(
                ExperienceMemory.source_task == conditions['task_type']
            )
        
        if 'experience_types' in conditions:
            exp_types = conditions['experience_types']
            if exp_types:
                query = query.filter(
                    ExperienceMemory.experience_type.in_(exp_types)
                )
        
        # 成功率过滤：先查出符合条件的候选集，在内存中过滤
        # 避免 SQL 直接做除法产生除零错误
        if 'min_success_rate' in conditions:
            min_rate = conditions['min_success_rate']
            candidates = query.filter(
                ExperienceMemory.confidence >= 0.3,
                ExperienceMemory.usage_count > 0
            ).order_by(
                desc(ExperienceMemory.confidence)
            ).all()
            
            experiences = [
                exp for exp in candidates
                if exp.usage_count > 0 and (exp.success_count / exp.usage_count) >= min_rate
            ][:limit]
        else:
            experiences = query.filter(
                ExperienceMemory.confidence >= 0.3
            ).order_by(
                desc(ExperienceMemory.confidence)
            ).limit(limit).all()
        
        # 批量更新访问统计
        for exp in experiences:
            exp.usage_count += 1
            exp.last_access = datetime.now(timezone.utc)
        
        self.db.commit()
        return experiences

    async def rule_based_search(
        self,
        conditions: Dict[str, Any],
        limit: int = 5
    ) -> List[ExperienceMemory]:
        """
        基于规则条件搜索经验记录。
        支持按任务类型、经验类型和最低成功率过滤。
        参数:
            conditions: 查询条件字典，支持 task_type/experience_types/min_success_rate
            limit: 返回数量上限
        返回: 满足规则条件的经验列表
        """
        return await asyncio.to_thread(
            self._rule_based_search_sync, conditions, limit
        )
    
    async def retrieve_relevant_experiences(
        self,
        task_context: Dict[str, Any],
        max_experiences: int = 3
    ) -> List[ExperienceMemory]:
        """
        处理retrieve、relevant、experiences相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        experiences = []
        
        task_type = task_context.get('task_type', 'general')
        exact_matches = await self.search_experiences(
            query_text=task_type,
            min_confidence=0.5,
            limit=max_experiences
        )
        experiences.extend(exact_matches)
        
        description = task_context.get('description', '')
        if description:
            semantic_matches = await self.semantic_search_experiences(
                query=description,
                task_context=task_context,
                limit=max_experiences
            )
            experiences.extend(semantic_matches)
        
        rule_matches = await self.rule_based_search(
            conditions={
                'task_type': task_type,
                'experience_types': task_context.get('experience_types'),
                'min_success_rate': 0.6
            },
            limit=max_experiences
        )
        experiences.extend(rule_matches)
        
        experiences = self._deduplicate_and_rank(experiences)
        
        return experiences[:max_experiences]
    
    def _deduplicate_and_rank(
        self,
        experiences: List[ExperienceMemory]
    ) -> List[ExperienceMemory]:
        """
        处理deduplicate、and、rank相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        seen_ids = set()
        unique_experiences = []
        
        for exp in experiences:
            if exp.id not in seen_ids:
                seen_ids.add(exp.id)
                unique_experiences.append(exp)
        
        def calculate_score(exp: ExperienceMemory) -> float:
            """
            处理calculate、score相关逻辑，并为调用方返回对应结果。
            阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
            """
            confidence_weight = 0.4
            usage_weight = 0.2
            success_weight = 0.3
            recency_weight = 0.1
            
            success_rate = (
                exp.success_count / exp.usage_count 
                if exp.usage_count > 0 else 0.5
            )
            
            days_since_access = (datetime.now(timezone.utc) - exp.last_access).days
            recency_score = max(0, 1 - (days_since_access / 30))
            
            score = (
                exp.confidence * confidence_weight +
                min(exp.usage_count / 10, 1.0) * usage_weight +
                success_rate * success_weight +
                recency_score * recency_weight
            )
            
            return score
        
        return sorted(unique_experiences, key=calculate_score, reverse=True)
    
    async def update_experience_quality(
        self,
        experience_id: int,
        success: bool,
        feedback: Optional[Dict] = None
    ) -> bool:
        """
        更新experience、quality相关数据、配置或状态。
        阅读时需要重点关注覆盖规则、副作用以及更新后的数据一致性。
        """
        experience = await self.get_experience_by_id(experience_id)
        if not experience:
            return False
        
        if success:
            experience.success_count += 1
        
        if experience.usage_count > 0:
            base_rate = experience.success_count / experience.usage_count
            
            weeks_since_creation = (datetime.now(timezone.utc) - experience.created_at).days / 7
            decay_rate = 0.95
            decayed_rate = base_rate * (decay_rate ** weeks_since_creation)
            
            experience.confidence = max(0.0, min(1.0, decayed_rate))
        
        experience.last_access = datetime.now(timezone.utc)
        
        if feedback:
            metadata = json.loads(experience.experience_metadata or '{}')
            metadata['last_feedback'] = feedback
            experience.experience_metadata = json.dumps(metadata)
        
        self.db.commit()
        
        logger.info(f"Updated experience quality: {experience_id}, new confidence: {experience.confidence}")
        return True
    
    async def archive_low_quality_experiences(self) -> int:
        """
        处理archive、low、quality、experiences相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        low_quality = self.db.query(ExperienceMemory).filter(
            and_(
                ExperienceMemory.confidence < 0.2,
                ExperienceMemory.usage_count > 20
            )
        ).all()
        
        archived_count = 0
        for exp in low_quality:
            metadata = json.loads(exp.experience_metadata or '{}')
            metadata['archived'] = True
            metadata['archived_at'] = datetime.now(timezone.utc).isoformat()
            exp.experience_metadata = json.dumps(metadata)
            archived_count += 1
        
        self.db.commit()
        
        logger.info(f"Archived {archived_count} low-quality experiences")
        return archived_count
    
    async def mark_for_review(self, experience_id: int) -> bool:
        """
        处理mark、for、review相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        experience = await self.get_experience_by_id(experience_id)
        if not experience:
            return False
        
        metadata = json.loads(experience.experience_metadata or '{}')
        metadata['needs_review'] = True
        metadata['marked_at'] = datetime.now(timezone.utc).isoformat()
        experience.experience_metadata = json.dumps(metadata)
        
        self.db.commit()
        
        return True
    
    async def get_experience_stats(self) -> Dict[str, Any]:
        """
        获取experience、stats相关数据或当前状态。
        调用方通常依赖该结果继续进行后续判断、渲染或业务编排。
        """
        total = self.db.query(ExperienceMemory).count()
        
        experience_types = ['strategy', 'method', 'error_pattern', 'tool_usage', 'context_handling']
        type_counts = {t: 0 for t in experience_types}
        type_count_results = self.db.query(
            ExperienceMemory.experience_type,
            func.count(ExperienceMemory.id)
        ).filter(
            ExperienceMemory.experience_type.in_(experience_types)
        ).group_by(ExperienceMemory.experience_type).all()
        type_counts.update(dict(type_count_results))
        
        all_experiences = self.db.query(ExperienceMemory).all()
        avg_confidence = sum(e.confidence for e in all_experiences) / total if total > 0 else 0
        
        total_usage = sum(e.usage_count for e in all_experiences)
        total_success = sum(e.success_count for e in all_experiences)
        avg_success_rate = total_success / total_usage if total_usage > 0 else 0
        
        top_experiences = self.db.query(ExperienceMemory).order_by(
            desc(ExperienceMemory.usage_count)
        ).limit(5).all()
        
        return {
            'total_experiences': total,
            'type_distribution': type_counts,
            'avg_confidence': round(avg_confidence, 2),
            'avg_success_rate': round(avg_success_rate, 2),
            'total_usage': total_usage,
            'total_success': total_success,
            'top_experiences': [
                {'id': e.id, 'title': e.title, 'usage_count': e.usage_count}
                for e in top_experiences
            ]
        }
    
    async def delete_experience(self, experience_id: int) -> bool:
        """
        删除experience相关对象或持久化记录。
        实现中通常还会同时处理资源释放、状态回收或关联数据清理。
        """
        experience = await self.get_experience_by_id(experience_id)
        if not experience:
            return False
        
        self.db.delete(experience)
        self.db.commit()
        
        logger.info(f"Deleted experience: {experience_id}")
        return True
