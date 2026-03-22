import json
import re
from typing import Dict, List, Optional, Any
from datetime import datetime
from loguru import logger


class ExperienceExtractor:
    def __init__(self, llm_client=None):
        self.llm_client = llm_client
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
            if experience:
                experience['source_task'] = self._infer_task_type(user_goal)
                experience['metadata'] = json.dumps({
                    'session_id': session_id,
                    'extracted_at': datetime.utcnow().isoformat()
                })
            return experience
        except Exception as e:
            logger.error(f"Failed to parse extraction response: {e}")
            return None

    def _build_extraction_prompt(
        self,
        user_goal: str,
        execution_steps: List