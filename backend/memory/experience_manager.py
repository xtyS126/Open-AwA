"""
记忆管理模块，负责短期记忆、长期记忆或经验数据的存储、检索与维护。
它是上下文连续性和经验复用能力的重要支撑层。
"""

import json
from typing import List, Dict, Optional, Any
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, desc, func
from db.models import ExperienceMemory
from loguru import logger


class ExperienceManager:
    """
    封装与ExperienceManager相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    
    def __init__(self, db: Session):
        """
        处理init相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        self.db = db
        logger.info("ExperienceManager initialized")
    
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
        处理add、experience相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
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
        
        logger.info(f"Added new experience: {title} (type: {experience_type})")
        return experience
    
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
        获取experiences相关数据或当前状态。
        调用方通常依赖该结果继续进行后续判断、渲染或业务编排。
        """
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
        
        experiences = query.offset(offset).limit(limit).all()
        
        return experiences
    
    async def get_experience_by_id(self, experience_id: int) -> Optional[ExperienceMemory]:
        """
        获取experience、by、id相关数据或当前状态。
        调用方通常依赖该结果继续进行后续判断、渲染或业务编排。
        """
        return self.db.query(ExperienceMemory).filter(
            ExperienceMemory.id == experience_id
        ).first()
    
    async def search_experiences(
        self,
        query_text: str,
        experience_type: Optional[str] = None,
        min_confidence: float = 0.0,
        limit: int = 10
    ) -> List[ExperienceMemory]:
        """
        处理search、experiences相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
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
        处理semantic、search、experiences相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        keywords = self._extract_keywords(query)
        
        if not keywords:
            return []
        
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
        
        for exp in experiences:
            exp.usage_count += 1
            exp.last_access = datetime.now(timezone.utc)
        
        self.db.commit()
        
        return experiences
    
    def _extract_keywords(self, text: str) -> List[str]:
        """
        处理extract、keywords相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        stop_words = {'的', '了', '是', '在', '和', '与', '或', '我', '你', '他', '她', '它', '这', '那', '有', '没有', '要', '不', '能', '会', '可以', '如何', '怎么', '什么', '哪个', '哪些'}
        
        words = text.replace(',', ' ').replace('。', ' ').replace('！', ' ').replace('？', ' ').split()
        keywords = [w for w in words if w not in stop_words and len(w) >= 2]
        
        return keywords[:10]
    
    async def rule_based_search(
        self,
        conditions: Dict[str, Any],
        limit: int = 5
    ) -> List[ExperienceMemory]:
        """
        处理rule、based、search相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        query = self.db.query(ExperienceMemory)
        
        if 'task_type' in conditions:
            query = query.filter(
                ExperienceMemory.source_task == conditions['task_type']
            )
        
        if 'experience_types' in conditions:
            query = query.filter(
                ExperienceMemory.experience_type.in_(conditions['experience_types'])
            )
        
        if 'min_success_rate' in conditions:
            min_rate = conditions['min_success_rate']
            query = query.filter(
                ExperienceMemory.success_count / ExperienceMemory.usage_count >= min_rate
            )
        
        experiences = query.filter(
            ExperienceMemory.confidence >= 0.3
        ).order_by(
            desc(ExperienceMemory.confidence)
        ).limit(limit).all()
        
        for exp in experiences:
            exp.usage_count += 1
            exp.last_access = datetime.now(timezone.utc)
        
        self.db.commit()
        
        return experiences
    
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
