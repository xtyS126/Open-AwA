import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger


class ExperienceExtractor:
    def __init__(self, llm_client=None):
        self.llm_client = llm_client
        self.memory_skill_dir = Path(__file__).resolve().parents[2] / "memory_skill"
        self.memory_skill_dir.mkdir(parents=True, exist_ok=True)
        logger.info("ExperienceExtractor initialized")

    async def extract_from_session(
        self,
        user_goal: str,
        execution_steps: List[Dict],
        final_result: str,
        status: str,
        session_id: str
    ) -> Optional[Dict[str, Any]]:
        prompt = self._build_extraction_prompt(
            user_goal, execution_steps, final_result, status
        )

        if self.llm_client:
            llm_response = await self.llm_client.generate(prompt)
        else:
            llm_response = self._rule_based_extraction(
                user_goal, execution_steps, final_result, status
            )

        try:
            experience = self._parse_extraction_response(llm_response)
            if not experience:
                return None

            extracted_at = datetime.now(timezone.utc).isoformat()
            experience['source_task'] = self._infer_task_type(user_goal)
            experience['metadata'] = {
                'session_id': session_id,
                'status': status,
                'extracted_at': extracted_at,
            }
            experience['save_result'] = self._save_experience_markdown(experience)
            return experience
        except Exception as e:
            logger.error(f"Failed to parse extraction response: {e}")
            return None

    def _save_experience_markdown(self, experience: Dict[str, Any]) -> Dict[str, Any]:
        self.memory_skill_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        title_slug = self._slugify(experience.get('title', 'experience'))
        base_name = f"{timestamp}_{title_slug}"

        file_path = self.memory_skill_dir / f"{base_name}.md"
        index = 1
        while file_path.exists():
            file_path = self.memory_skill_dir / f"{base_name}_{index}.md"
            index += 1

        content = self._build_markdown_content(experience)
        file_path.write_text(content, encoding="utf-8")

        stat = file_path.stat()
        updated_at = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()

        return {
            "file_name": file_path.name,
            "file_path": str(file_path),
            "updated_at": updated_at,
            "size": stat.st_size,
        }

    def _build_markdown_content(self, experience: Dict[str, Any]) -> str:
        metadata = experience.get('metadata') or {}
        source_task = experience.get('source_task', 'general')

        metadata_json = json.dumps(metadata, ensure_ascii=False, indent=2)

        return (
            f"# {experience.get('title', '未命名经验')}\n\n"
            f"- 类型: {experience.get('experience_type', 'method')}\n"
            f"- 置信度: {experience.get('confidence', 0.0)}\n"
            f"- 来源任务: {source_task}\n"
            f"- 提取时间: {metadata.get('extracted_at', '')}\n\n"
            f"## 触发条件\n{experience.get('trigger_conditions', '')}\n\n"
            f"## 经验内容\n{experience.get('content', '')}\n\n"
            f"## 元数据\n```json\n{metadata_json}\n```\n"
        )

    def _slugify(self, value: str) -> str:
        normalized = re.sub(r"[^\w\-\u4e00-\u9fff]+", "_", value or "experience")
        normalized = normalized.strip("_")
        if not normalized:
            return "experience"
        return normalized[:80]

    def _build_extraction_prompt(
        self,
        user_goal: str,
        execution_steps: List[Dict],
        final_result: str,
        status: str
    ) -> str:
        prompt_template = """你是一个经验提取专家。请分析以下工作会话，提取可复用的经验：

## 会话上下文
用户目标：{user_goal}
执行过程：{execution_steps}
最终结果：{final_result}
状态：{status}（成功/失败）

## 提取要求
1. 识别成功模式：如果任务成功，总结有效的策略、方法、工具使用技巧
2. 识别失败教训：如果任务失败，分析失败原因和避免方法
3. 识别通用模式：提炼适用于其他类似任务的通用经验
4. 定义触发条件：明确说明在什么情况下应使用此经验

## 输出格式
请以以下JSON格式输出经验：
{{"experience_type": "strategy|method|error_pattern|tool_usage|context_handling", "title": "简短描述性标题（不超过50字）", "content": "详细经验描述（100-500字）", "trigger_conditions": "在什么情况下应检索和应用此经验", "confidence": 0.0-1.0的置信度评分}}

如果没有值得提取的经验，请输出：{{"no_experience": true, "reason": "原因说明"}}"""

        steps_str = "\n".join([
            f"- {step.get('action', 'Unknown')}: {step.get('result', 'No result')}"
            for step in execution_steps
        ])

        return prompt_template.format(
            user_goal=user_goal,
            execution_steps=steps_str or "无",
            final_result=final_result or "无",
            status="成功" if status == "success" else "失败"
        )

    def _parse_extraction_response(self, response: str) -> Optional[Dict[str, Any]]:
        json_match = re.search(r'\{.*\}', response, re.DOTALL)
        if not json_match:
            return None

        try:
            data = json.loads(json_match.group())

            if data.get('no_experience'):
                logger.info(f"No experience to extract: {data.get('reason')}")
                return None

            required_fields = ['experience_type', 'title', 'content', 'trigger_conditions', 'confidence']
            for field in required_fields:
                if field not in data:
                    logger.warning(f"Missing required field: {field}")
                    return None

            if data['experience_type'] not in ['strategy', 'method', 'error_pattern', 'tool_usage', 'context_handling']:
                logger.warning(f"Invalid experience type: {data['experience_type']}")
                return None

            confidence = float(data['confidence'])
            if not 0.0 <= confidence <= 1.0:
                logger.warning(f"Invalid confidence value: {confidence}")
                data['confidence'] = max(0.0, min(1.0, confidence))

            return data

        except json.JSONDecodeError as e:
            logger.error(f"JSON parse error: {e}")
            return None
        except Exception as e:
            logger.error(f"Parse error: {e}")
            return None

    def _rule_based_extraction(
        self,
        user_goal: str,
        execution_steps: List[Dict],
        final_result: str,
        status: str
    ) -> str:
        if status == "success":
            if execution_steps:
                actions = [step.get('action', '') for step in execution_steps]
                return json.dumps({
                    "experience_type": "method",
                    "title": "完成任务的执行步骤",
                    "content": "执行了以下步骤：\n" + "\n".join([f"- {a}" for a in actions if a]),
                    "trigger_conditions": f"当用户需要{self._infer_task_type(user_goal)}时",
                    "confidence": 0.3
                })
        else:
            if execution_steps:
                errors = [step.get('error', '') for step in execution_steps if step.get('error')]
                if errors:
                    return json.dumps({
                        "experience_type": "error_pattern",
                        "title": "任务执行失败模式",
                        "content": "遇到以下错误：\n" + "\n".join([f"- {e}" for e in errors]),
                        "trigger_conditions": "当任务执行失败时",
                        "confidence": 0.2
                    })

        return json.dumps({"no_experience": True, "reason": "未发现明显的可复用经验"})

    def _infer_task_type(self, user_goal: str) -> str:
        user_goal_lower = user_goal.lower()

        task_keywords = {
            'code_generation': ['写代码', '生成代码', 'code', 'programming'],
            'code_review': ['review', '审查', '检查代码'],
            'refactoring': ['重构', 'refactor', '优化代码'],
            'debugging': ['debug', '调试', '修复bug', '错误'],
            'documentation': ['文档', '注释', 'comment', 'readme'],
            'data_analysis': ['分析', '分析数据', '数据处理'],
            'testing': ['测试', 'test', '单元测试'],
            'deployment': ['部署', 'deploy', '发布'],
            'configuration': ['配置', 'config', '设置'],
            'general': []
        }

        for task_type, keywords in task_keywords.items():
            if any(keyword in user_goal_lower for keyword in keywords):
                return task_type

        return 'general'

    def classify_experience_type(self, content: str) -> str:
        content_lower = content.lower()

        if any(word in content_lower for word in ['策略', 'strategy', '计划', '分解', '优先级']):
            return 'strategy'
        elif any(word in content_lower for word in ['步骤', '方法', 'method', '技巧', '使用']):
            return 'method'
        elif any(word in content_lower for word in ['错误', 'error', 'bug', '问题', '失败']):
            return 'error_pattern'
        elif any(word in content_lower for word in ['工具', 'tool', '软件', 'ide']):
            return 'tool_usage'
        elif any(word in content_lower for word in ['上下文', 'context', '理解', '澄清']):
            return 'context_handling'
        else:
            return 'method'

    def evaluate_confidence(
        self,
        experience: Dict[str, Any],
        execution_steps: List[Dict],
        status: str
    ) -> float:
        base_confidence = float(experience.get('confidence', 0.5))

        steps_count = len(execution_steps)
        if steps_count >= 5:
            base_confidence += 0.1
        elif steps_count >= 3:
            base_confidence += 0.05

        if status == "success":
            base_confidence += 0.1
        else:
            base_confidence -= 0.1

        content_length = len(experience.get('content', ''))
        if 100 <= content_length <= 500:
            base_confidence += 0.05
        elif content_length < 50:
            base_confidence -= 0.1

        return max(0.0, min(1.0, base_confidence))
