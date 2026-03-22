from typing import Dict, List, Optional, Any, NamedTuple
from loguru import logger
import time
from dataclasses import dataclass, field


class StepResult(NamedTuple):
    action: str
    tool: str
    result: Any
    success: bool
    error: Optional[str] = None


class ExecutionResult(NamedTuple):
    skill_name: str
    steps: List[StepResult]
    success: bool
    outputs: Dict[str, Any]
    error: Optional[str] = None
    execution_time: float = 0.0


class SkillExecutor:
    def __init__(self):
        self.environment_initialized = False
        self.execution_context: Dict[str, Any] = {}
        logger.info("SkillExecutor initialized")

    async def initialize_environment(self, skill_config: Dict, context: Dict) -> bool:
        try:
            logger.info(f"Initializing environment for skill config: {skill_config.get('name', 'unknown')}")

            required_fields = ['name', 'steps']
            for field in required_fields:
                if field not in skill_config:
                    logger.error(f"Missing required field in skill config: {field}")
                    return False

            self.execution_context = {
                'skill_config': skill_config,
                'shared_context': context.copy() if context else {},
                'variables': {},
                'artifacts': {}
            }

            environment_type = skill_config.get('environment', 'default')
            logger.info(f"Setting up {environment_type} environment")

            self.environment_initialized = True
            logger.info("Environment initialization completed successfully")
            return True

        except Exception as e:
            logger.error(f"Failed to initialize environment: {e}")
            return False

    async def execute_step(self, step: Dict, context: Dict) -> StepResult:
        try:
            action = step.get('action', 'unknown')
            tool = step.get('tool', 'default')
            params = step.get('params', {})

            logger.info(f"Executing step: {action} with tool: {tool}")

            if not self.environment_initialized:
                raise RuntimeError("Environment not initialized")

            merged_context = {**self.execution_context, **context}
            params_with_context = {**params, 'context': merged_context}

            result = await self._execute_tool(tool, action, params_with_context)

            logger.info(f"Step {action} completed successfully")
            return StepResult(
                action=action,
                tool=tool,
                result=result,
                success=True,
                error=None
            )

        except Exception as e:
            logger.error(f"Step execution failed: {e}")
            return StepResult(
                action=step.get('action', 'unknown'),
                tool=step.get('tool', 'default'),
                result=None,
                success=False,
                error=str(e)
            )

    async def _execute_tool(self, tool: str, action: str, params: Dict) -> Any:
        if tool == 'code_executor':
            return await self._execute_code_action(action, params)
        elif tool == 'file_operation':
            return await self._execute_file_action(action, params)
        elif tool == 'shell':
            return await self._execute_shell_action(action, params)
        elif tool == 'api_call':
            return await self._execute_api_action(action, params)
        elif tool == 'llm':
            return await self._execute_llm_action(action, params)
        else:
            return await self._execute_default_action(action, params)

    async def _execute_code_action(self, action: str, params: Dict) -> Any:
        code = params.get('code', '')
        language = params.get('language', 'python')

        logger.info(f"Executing {language} code: {action}")

        if language == 'python':
            try:
                local_vars = {}
                exec(code, {}, local_vars)
                return local_vars.get('result', {'status': 'executed'})
            except Exception as e:
                raise RuntimeError(f"Code execution error: {e}")

        return {'status': 'executed', 'action': action}

    async def _execute_file_action(self, action: str, params: Dict) -> Any:
        file_path = params.get('path', '')
        content = params.get('content', '')
        mode = params.get('mode', 'r')

        logger.info(f"File operation: {action} on {file_path}")

        if action == 'read':
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    return {'content': f.read()}
            except Exception as e:
                raise RuntimeError(f"Failed to read file: {e}")

        elif action == 'write':
            try:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(content)
                return {'status': 'written', 'path': file_path}
            except Exception as e:
                raise RuntimeError(f"Failed to write file: {e}")

        return {'status': 'completed', 'action': action}

    async def _execute_shell_action(self, action: str, params: Dict) -> Any:
        import subprocess

        command = params.get('command', '')
        logger.info(f"Executing shell command: {command}")

        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=params.get('timeout', 30)
            )

            return {
                'stdout': result.stdout,
                'stderr': result.stderr,
                'returncode': result.returncode
            }
        except Exception as e:
            raise RuntimeError(f"Shell execution error: {e}")

    async def _execute_api_action(self, action: str, params: Dict) -> Any:
        import httpx

        url = params.get('url', '')
        method = params.get('method', 'GET')
        headers = params.get('headers', {})
        data = params.get('data', {})

        logger.info(f"Making API call: {method} {url}")

        try:
            async with httpx.AsyncClient() as client:
                if method.upper() == 'GET':
                    response = await client.get(url, headers=headers)
                    return {
                        'status': response.status_code,
                        'data': response.json() if response.headers.get('content-type') == 'application/json' else response.text
                    }
                elif method.upper() == 'POST':
                    response = await client.post(url, json=data, headers=headers)
                    return {
                        'status': response.status_code,
                        'data': response.json() if response.headers.get('content-type') == 'application/json' else response.text
                    }

        except Exception as e:
            raise RuntimeError(f"API call error: {e}")

    async def _execute_llm_action(self, action: str, params: Dict) -> Any:
        prompt = params.get('prompt', '')
        model = params.get('model', 'default')

        logger.info(f"Executing LLM action: {action} with model {model}")

        llm_client = self.execution_context.get('llm_client')
        if llm_client:
            try:
                response = await llm_client.generate(prompt)
                return {'response': response, 'model': model}
            except Exception as e:
                raise RuntimeError(f"LLM execution error: {e}")

        return {'response': f"LLM placeholder response for: {action}", 'model': model}

    async def _execute_default_action(self, action: str, params: Dict) -> Any:
        logger.info(f"Executing default action: {action}")
        return {
            'action': action,
            'status': 'completed',
            'params': params
        }

    async def execute_skill(self, skill_name: str, inputs: Dict, context: Dict) -> ExecutionResult:
        start_time = time.time()
        steps_results: List[StepResult] = []
        outputs: Dict[str, Any] = {}
        error_message: Optional[str] = None

        try:
            logger.info(f"Starting skill execution: {skill_name}")

            skill_config = self.execution_context.get('skill_config', {})

            if not skill_config or skill_config.get('name') != skill_name:
                error_message = f"Skill '{skill_name}' not found or not initialized"
                logger.error(error_message)
                return ExecutionResult(
                    skill_name=skill_name,
                    steps=[],
                    success=False,
                    outputs={},
                    error=error_message,
                    execution_time=time.time() - start_time
                )

            if not self.environment_initialized:
                success = await self.initialize_environment(skill_config, context)
                if not success:
                    error_message = "Failed to initialize environment"
                    return ExecutionResult(
                        skill_name=skill_name,
                        steps=[],
                        success=False,
                        outputs={},
                        error=error_message,
                        execution_time=time.time() - start_time
                    )

            skill_steps = skill_config.get('steps', [])

            for idx, step in enumerate(skill_steps):
                logger.info(f"Executing step {idx + 1}/{len(skill_steps)}: {step.get('action', 'unknown')}")

                result = await self.execute_step(step, context)
                steps_results.append(result)

                if result.success:
                    outputs[f"step_{idx}_result"] = result.result
                    self.execution_context['variables'][f"step_{idx}"] = result.result
                else:
                    if skill_config.get('continue_on_error', False):
                        logger.warning(f"Step failed but continuing: {result.error}")
                        continue
                    else:
                        error_message = result.error
                        break

            execution_time = time.time() - start_time
            overall_success = all(step.success for step in steps_results) and not error_message

            final_outputs = {
                'skill_outputs': outputs,
                'context_variables': self.execution_context.get('variables', {}),
                'artifacts': self.execution_context.get('artifacts', {})
            }

            logger.info(f"Skill {skill_name} completed with success={overall_success} in {execution_time:.2f}s")

            return ExecutionResult(
                skill_name=skill_name,
                steps=steps_results,
                success=overall_success,
                outputs=final_outputs,
                error=error_message,
                execution_time=execution_time
            )

        except Exception as e:
            error_message = str(e)
            logger.error(f"Skill execution error: {error_message}")

            return ExecutionResult(
                skill_name=skill_name,
                steps=steps_results,
                success=False,
                outputs=outputs,
                error=error_message,
                execution_time=time.time() - start_time
            )

    async def cleanup(self):
        try:
            logger.info("Starting cleanup process")

            if hasattr(self, 'execution_context'):
                for key, value in self.execution_context.items():
                    if hasattr(value, 'close'):
                        try:
                            await value.close()
                        except:
                            pass

            self.execution_context.clear()
            self.environment_initialized = False

            logger.info("Cleanup completed successfully")

        except Exception as e:
            logger.error(f"Cleanup error: {e}")
