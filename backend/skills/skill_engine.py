"""
技能系统模块，负责技能注册、加载、校验、执行或适配外部能力。
当 Agent 需要调用外部能力时，通常会经过这一层完成查找、验证与执行。
"""

from typing import Dict, List, Optional, Any
from loguru import logger
import time
import uuid
from datetime import datetime, timezone
from dataclasses import dataclass, field

from .skill_registry import SkillRegistry
from .skill_validator import SkillValidator, ValidationResult
from .skill_loader import SkillLoader
from .skill_executor import SkillExecutor, ExecutionResult
from .weixin_skill_adapter import WeixinSkillAdapter


@dataclass
class PerformanceMetrics:
    """
    封装与PerformanceMetrics相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    skill_name: str
    start_time: float
    end_time: Optional[float] = None
    duration: Optional[float] = None
    step_count: int = 0
    step_durations: List[float] = field(default_factory=list)
    memory_usage: Optional[int] = None
    peak_memory: Optional[int] = None

    def finalize(self):
        """
        处理finalize相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        self.end_time = time.time()
        self.duration = self.end_time - self.start_time

    def to_dict(self) -> Dict[str, Any]:
        """
        处理to、dict相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        return {
            'skill_name': self.skill_name,
            'start_time': self.start_time,
            'end_time': self.end_time,
            'duration': self.duration,
            'step_count': self.step_count,
            'step_durations': self.step_durations,
            'memory_usage': self.memory_usage,
            'peak_memory': self.peak_memory
        }


@dataclass
class ExecutionLog:
    """
    封装与ExecutionLog相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    log_id: str
    skill_name: str
    timestamp: str
    event_type: str
    message: str
    details: Optional[Dict[str, Any]] = None
    level: str = 'INFO'

    def to_dict(self) -> Dict[str, Any]:
        """
        处理to、dict相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        return {
            'log_id': self.log_id,
            'skill_name': self.skill_name,
            'timestamp': self.timestamp,
            'event_type': self.event_type,
            'message': self.message,
            'details': self.details,
            'level': self.level
        }


class SkillEngine:
    """
    封装与SkillEngine相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    def __init__(self, db_session):
        """
        处理init相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        self.db_session = db_session
        self.registry = SkillRegistry(db_session)
        self.validator = SkillValidator()
        self.loader = SkillLoader(db_session)
        self.executor = SkillExecutor()
        self.weixin_adapter = WeixinSkillAdapter()

        self._execution_logs: List[ExecutionLog] = []
        self._performance_metrics: List[PerformanceMetrics] = []
        self._max_logs = 1000
        self._max_metrics = 500

        logger.info("SkillEngine initialized")

    async def _execute_built_in_skill(
        self,
        skill_name: str,
        skill_config: Dict[str, Any],
        inputs: Dict[str, Any],
        context: Dict[str, Any],
        execution_id: str,
        metrics: PerformanceMetrics,
    ) -> Dict[str, Any]:
        """
        执行内置工具型技能。
        该分支复用统一的内置工具注册器，避免走通用步骤执行器。
        """
        tool_name = skill_config.get('builtin_tool')
        action = inputs.get('action') or context.get('action') or skill_config.get('default_action')
        params = inputs.get('params') if isinstance(inputs.get('params'), dict) else None
        if params is None:
            params = {
                key: value
                for key, value in inputs.items()
                if key not in {'action', 'params', 'intent', 'entities', 'context'}
            }

        if not tool_name:
            return {
                'success': False,
                'skill_name': skill_name,
                'execution_id': execution_id,
                'error': '内置技能缺少 builtin_tool 配置',
                'outputs': {},
                'steps': [],
                'metrics': metrics.to_dict(),
            }

        if not action:
            return {
                'success': False,
                'skill_name': skill_name,
                'execution_id': execution_id,
                'error': '执行内置技能时缺少 action 参数',
                'outputs': {},
                'steps': [],
                'metrics': metrics.to_dict(),
            }

        from tools.registry import built_in_tool_registry

        result = await built_in_tool_registry.execute_tool(
            tool_name,
            action=action,
            params=params,
            config=skill_config,
        )
        metrics.finalize()
        metrics.step_count = 1

        if result.get('success'):
            self.registry.increment_usage(skill_name)
            return {
                'success': True,
                'skill_name': skill_name,
                'execution_id': execution_id,
                'outputs': result,
                'steps': [
                    {
                        'action': action,
                        'tool': tool_name,
                        'success': True,
                        'error': None,
                        'result': result,
                    }
                ],
                'metrics': metrics.to_dict(),
                'execution_time': metrics.duration,
            }

        return {
            'success': False,
            'skill_name': skill_name,
            'execution_id': execution_id,
            'error': result.get('error', '内置工具执行失败'),
            'outputs': result,
            'steps': [
                {
                    'action': action,
                    'tool': tool_name,
                    'success': False,
                    'error': result.get('error'),
                    'result': result,
                }
            ],
            'metrics': metrics.to_dict(),
            'execution_time': metrics.duration,
        }

    def _generate_log_id(self) -> str:
        """
        处理generate、log、id相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        return str(uuid.uuid4())

    def _get_timestamp(self) -> str:
        """
        处理get、timestamp相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        return datetime.now(timezone.utc).isoformat()

    def _add_execution_log(
        self,
        skill_name: str,
        event_type: str,
        message: str,
        level: str = 'INFO',
        details: Optional[Dict[str, Any]] = None
    ) -> ExecutionLog:
        """
        处理add、execution、log相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        log = ExecutionLog(
            log_id=self._generate_log_id(),
            skill_name=skill_name,
            timestamp=self._get_timestamp(),
            event_type=event_type,
            message=message,
            details=details,
            level=level
        )

        self._execution_logs.append(log)

        if len(self._execution_logs) > self._max_logs:
            self._execution_logs = self._execution_logs[-self._max_logs:]

        log_level_map = {
            'DEBUG': logger.debug,
            'INFO': logger.info,
            'WARNING': logger.warning,
            'ERROR': logger.error
        }
        log_func = log_level_map.get(level, logger.info)
        log_func(f"[{skill_name}] [{event_type}] {message}")

        return log

    def _start_performance_tracking(self, skill_name: str) -> PerformanceMetrics:
        """
        处理start、performance、tracking相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        metrics = PerformanceMetrics(
            skill_name=skill_name,
            start_time=time.time()
        )
        self._performance_metrics.append(metrics)

        if len(self._performance_metrics) > self._max_metrics:
            self._performance_metrics = self._performance_metrics[-self._max_metrics:]

        return metrics

    def _get_current_memory_usage(self) -> Optional[int]:
        """
        处理get、current、memory、usage相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        try:
            import psutil
            process = psutil.Process()
            return process.memory_info().rss
        except ImportError:
            return None

    async def execute_skill(self, skill_name: str, inputs: Dict, context: Dict) -> Dict[str, Any]:
        """
        处理execute、skill相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        execution_id = self._generate_log_id()
        metrics = self._start_performance_tracking(skill_name)

        self._add_execution_log(
            skill_name=skill_name,
            event_type='EXECUTION_START',
            message=f'Starting skill execution: {skill_name}',
            details={'execution_id': execution_id, 'inputs': inputs, 'context_keys': list(context.keys())}
        )

        try:
            skill_record = self.registry.get(skill_name)
            if not skill_record:
                self._add_execution_log(
                    skill_name=skill_name,
                    event_type='SKILL_NOT_FOUND',
                    message=f'Skill not found in registry: {skill_name}',
                    level='ERROR',
                    details={'execution_id': execution_id}
                )
                return {
                    'success': False,
                    'skill_name': skill_name,
                    'execution_id': execution_id,
                    'error': f"Skill '{skill_name}' not found in registry",
                    'outputs': {},
                    'steps': [],
                    'metrics': metrics.to_dict()
                }

            if not skill_record.enabled:
                self._add_execution_log(
                    skill_name=skill_name,
                    event_type='SKILL_DISABLED',
                    message=f'Skill is disabled: {skill_name}',
                    level='WARNING',
                    details={'execution_id': execution_id}
                )
                return {
                    'success': False,
                    'skill_name': skill_name,
                    'execution_id': execution_id,
                    'error': f"Skill '{skill_name}' is disabled",
                    'outputs': {},
                    'steps': [],
                    'metrics': metrics.to_dict()
                }

            skill_config = self.loader.load_from_db(skill_name)
            if not skill_config:
                self._add_execution_log(
                    skill_name=skill_name,
                    event_type='LOAD_FAILED',
                    message=f'Failed to load skill config: {skill_name}',
                    level='ERROR',
                    details={'execution_id': execution_id}
                )
                return {
                    'success': False,
                    'skill_name': skill_name,
                    'execution_id': execution_id,
                    'error': f"Failed to load config for skill '{skill_name}'",
                    'outputs': {},
                    'steps': [],
                    'metrics': metrics.to_dict()
                }

            self._add_execution_log(
                skill_name=skill_name,
                event_type='CONFIG_LOADED',
                message=f'Skill config loaded: {skill_name}',
                details={'execution_id': execution_id, 'version': skill_config.get('version')}
            )

            validation_result = await self.validate_skill(skill_config)
            if not validation_result.get('valid', False):
                errors = validation_result.get('errors', [])
                self._add_execution_log(
                    skill_name=skill_name,
                    event_type='VALIDATION_FAILED',
                    message=f'Skill validation failed: {skill_name}',
                    level='ERROR',
                    details={'execution_id': execution_id, 'errors': errors}
                )
                return {
                    'success': False,
                    'skill_name': skill_name,
                    'execution_id': execution_id,
                    'error': f"Validation failed: {', '.join(errors)}",
                    'outputs': {},
                    'steps': [],
                    'metrics': metrics.to_dict(),
                    'validation': validation_result
                }

            self._add_execution_log(
                skill_name=skill_name,
                event_type='VALIDATION_PASSED',
                message=f'Skill validation passed: {skill_name}',
                details={'execution_id': execution_id}
            )

            if skill_config.get('builtin_tool'):
                self._add_execution_log(
                    skill_name=skill_name,
                    event_type='BUILTIN_TOOL_ROUTED',
                    message=f'Routing skill to built-in tool: {skill_name}',
                    details={
                        'execution_id': execution_id,
                        'builtin_tool': skill_config.get('builtin_tool')
                    }
                )
                return await self._execute_built_in_skill(
                    skill_name=skill_name,
                    skill_config=skill_config,
                    inputs=inputs,
                    context=context,
                    execution_id=execution_id,
                    metrics=metrics,
                )

            merged_inputs = {**inputs, **context}

            if self.weixin_adapter.is_weixin_skill(skill_config):
                self._add_execution_log(
                    skill_name=skill_name,
                    event_type='ADAPTER_ROUTED',
                    message=f'Routing skill to weixin adapter: {skill_name}',
                    details={'execution_id': execution_id}
                )
                adapter_result = await self.weixin_adapter.execute(
                    skill_name=skill_name,
                    skill_config=skill_config,
                    inputs=merged_inputs,
                    context=context
                )
                metrics.finalize()
                metrics.step_count = 1

                adapter_error = adapter_result.get('error')
                adapter_outputs = adapter_result.get('outputs', {})
                adapter_action = adapter_result.get('action', 'unknown')

                if adapter_result.get('success'):
                    self._add_execution_log(
                        skill_name=skill_name,
                        event_type='ADAPTER_EXECUTION_SUCCESS',
                        message=f'Weixin adapter executed successfully: {skill_name}',
                        details={
                            'execution_id': execution_id,
                            'adapter': 'weixin',
                            'action': adapter_action
                        }
                    )
                    self.registry.increment_usage(skill_name)
                    return {
                        'success': True,
                        'skill_name': skill_name,
                        'execution_id': execution_id,
                        'outputs': adapter_outputs,
                        'steps': [
                            {
                                'action': adapter_action,
                                'tool': 'weixin_adapter',
                                'success': True,
                                'error': None,
                                'result': adapter_outputs
                            }
                        ],
                        'metrics': metrics.to_dict(),
                        'execution_time': metrics.duration
                    }

                self._add_execution_log(
                    skill_name=skill_name,
                    event_type='ADAPTER_EXECUTION_FAILED',
                    message=f'Weixin adapter execution failed: {skill_name}',
                    level='ERROR',
                    details={
                        'execution_id': execution_id,
                        'adapter': 'weixin',
                        'action': adapter_action,
                        'error': adapter_error
                    }
                )
                return {
                    'success': False,
                    'skill_name': skill_name,
                    'execution_id': execution_id,
                    'error': adapter_error.get('message') if isinstance(adapter_error, dict) else 'weixin adapter execution failed',
                    'outputs': adapter_outputs,
                    'steps': [
                        {
                            'action': adapter_action,
                            'tool': 'weixin_adapter',
                            'success': False,
                            'error': adapter_error,
                            'result': adapter_outputs
                        }
                    ],
                    'metrics': metrics.to_dict(),
                    'execution_time': metrics.duration
                }

            env_init_success = await self.executor.initialize_environment(skill_config, context)
            if not env_init_success:
                self._add_execution_log(
                    skill_name=skill_name,
                    event_type='ENV_INIT_FAILED',
                    message=f'Failed to initialize environment for: {skill_name}',
                    level='ERROR',
                    details={'execution_id': execution_id}
                )
                return {
                    'success': False,
                    'skill_name': skill_name,
                    'execution_id': execution_id,
                    'error': 'Failed to initialize execution environment',
                    'outputs': {},
                    'steps': [],
                    'metrics': metrics.to_dict()
                }

            self._add_execution_log(
                skill_name=skill_name,
                event_type='ENV_INITIALIZED',
                message=f'Execution environment initialized for: {skill_name}',
                details={'execution_id': execution_id}
            )

            execution_result: ExecutionResult = await self.executor.execute_skill(
                skill_name=skill_name,
                inputs=merged_inputs,
                context=context
            )

            metrics.step_count = len(execution_result.steps)
            metrics.finalize()

            if execution_result.success:
                self._add_execution_log(
                    skill_name=skill_name,
                    event_type='EXECUTION_SUCCESS',
                    message=f'Skill execution completed successfully: {skill_name}',
                    details={
                        'execution_id': execution_id,
                        'duration': execution_result.execution_time,
                        'step_count': len(execution_result.steps)
                    }
                )

                self.registry.increment_usage(skill_name)

                return {
                    'success': True,
                    'skill_name': skill_name,
                    'execution_id': execution_id,
                    'outputs': execution_result.outputs,
                    'steps': [
                        {
                            'action': step.action,
                            'tool': step.tool,
                            'success': step.success,
                            'error': step.error,
                            'result': step.result
                        }
                        for step in execution_result.steps
                    ],
                    'metrics': metrics.to_dict(),
                    'execution_time': execution_result.execution_time
                }
            else:
                self._add_execution_log(
                    skill_name=skill_name,
                    event_type='EXECUTION_FAILED',
                    message=f'Skill execution failed: {skill_name}',
                    level='ERROR',
                    details={
                        'execution_id': execution_id,
                        'error': execution_result.error,
                        'duration': execution_result.execution_time
                    }
                )

                return {
                    'success': False,
                    'skill_name': skill_name,
                    'execution_id': execution_id,
                    'error': execution_result.error,
                    'outputs': execution_result.outputs,
                    'steps': [
                        {
                            'action': step.action,
                            'tool': step.tool,
                            'success': step.success,
                            'error': step.error,
                            'result': step.result
                        }
                        for step in execution_result.steps
                    ],
                    'metrics': metrics.to_dict(),
                    'execution_time': execution_result.execution_time
                }

        except Exception as e:
            metrics.finalize()
            error_message = str(e)

            self._add_execution_log(
                skill_name=skill_name,
                event_type='EXECUTION_ERROR',
                message=f'Unexpected error during skill execution: {error_message}',
                level='ERROR',
                details={'execution_id': execution_id, 'exception': type(e).__name__}
            )

            return {
                'success': False,
                'skill_name': skill_name,
                'execution_id': execution_id,
                'error': error_message,
                'outputs': {},
                'steps': [],
                'metrics': metrics.to_dict()
            }

        finally:
            await self.executor.cleanup()

    async def validate_skill(self, config: Dict) -> Dict[str, Any]:
        """
        校验skill相关输入、规则或结构是否合法。
        返回结果通常用于阻止非法输入继续流入后续链路。
        """
        logger.info(f"Validating skill config: {config.get('name', 'unknown')}")

        result: ValidationResult = self.validator.validate_skill_config(config)

        return {
            'valid': result.valid,
            'errors': result.errors,
            'warnings': result.warnings,
            'skill_name': config.get('name', 'unknown'),
            'version': config.get('version'),
            'validation_timestamp': self._get_timestamp()
        }

    async def parse_config(self, yaml_content: str) -> Dict:
        """
        解析config相关输入内容，并转换为内部可用结构。
        它常用于屏蔽外部协议差异并统一上层业务使用的数据格式。
        """
        logger.debug("Parsing YAML configuration")

        if not self.validator.validate_yaml_format(yaml_content):
            raise ValueError("Invalid YAML format")

        config = self.loader.parse_config(yaml_content)

        self._add_execution_log(
            skill_name=config.get('name', 'unknown'),
            event_type='CONFIG_PARSED',
            message='YAML configuration parsed successfully',
            details={'keys': list(config.keys())}
        )

        return config

    def get_execution_logs(
        self,
        skill_name: Optional[str] = None,
        event_type: Optional[str] = None,
        level: Optional[str] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        获取execution、logs相关数据或当前状态。
        调用方通常依赖该结果继续进行后续判断、渲染或业务编排。
        """
        filtered_logs = self._execution_logs

        if skill_name:
            filtered_logs = [log for log in filtered_logs if log.skill_name == skill_name]

        if event_type:
            filtered_logs = [log for log in filtered_logs if log.event_type == event_type]

        if level:
            filtered_logs = [log for log in filtered_logs if log.level == level]

        filtered_logs = filtered_logs[-limit:]

        return [log.to_dict() for log in filtered_logs]

    def get_performance_metrics(
        self,
        skill_name: Optional[str] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        获取performance、metrics相关数据或当前状态。
        调用方通常依赖该结果继续进行后续判断、渲染或业务编排。
        """
        filtered_metrics = self._performance_metrics

        if skill_name:
            filtered_metrics = [m for m in filtered_metrics if m.skill_name == skill_name]

        filtered_metrics = filtered_metrics[-limit:]

        return [m.to_dict() for m in filtered_metrics]

    def get_skill_statistics(self, skill_name: str) -> Dict[str, Any]:
        """
        获取skill、statistics相关数据或当前状态。
        调用方通常依赖该结果继续进行后续判断、渲染或业务编排。
        """
        skill_record = self.registry.get(skill_name)

        if not skill_record:
            return {
                'error': f"Skill '{skill_name}' not found",
                'skill_name': skill_name
            }

        skill_metrics = [m for m in self._performance_metrics if m.skill_name == skill_name]
        skill_logs = [log for log in self._execution_logs if log.skill_name == skill_name]

        total_executions = len(skill_metrics)
        successful_executions = sum(1 for m in skill_metrics if m.end_time is not None)

        execution_times = [m.duration for m in skill_metrics if m.duration is not None]
        avg_execution_time = sum(execution_times) / len(execution_times) if execution_times else 0
        max_execution_time = max(execution_times) if execution_times else 0
        min_execution_time = min(execution_times) if execution_times else 0

        return {
            'skill_name': skill_name,
            'version': skill_record.version,
            'enabled': skill_record.enabled,
            'usage_count': skill_record.usage_count,
            'total_executions': total_executions,
            'successful_executions': successful_executions,
            'success_rate': successful_executions / total_executions if total_executions > 0 else 0,
            'avg_execution_time': avg_execution_time,
            'max_execution_time': max_execution_time,
            'min_execution_time': min_execution_time,
            'total_log_entries': len(skill_logs)
        }

    def clear_logs(self) -> int:
        """
        处理clear、logs相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        count = len(self._execution_logs)
        self._execution_logs.clear()
        logger.info(f"Cleared {count} execution logs")
        return count

    def clear_metrics(self) -> int:
        """
        处理clear、metrics相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        count = len(self._performance_metrics)
        self._performance_metrics.clear()
        logger.info(f"Cleared {count} performance metrics")
        return count
