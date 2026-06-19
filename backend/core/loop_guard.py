"""
循环守卫模块。

防止子代理陷入死循环或重复失败，提供：
- 迭代次数限制
- 执行时间限制
- 重复失败检测
- 停止原因追踪

参考 Agent Diva 的 LoopGuard 设计。
"""

import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Optional


class LoopStopReason(str, Enum):
    """循环停止原因。"""
    
    MAX_ITERATIONS = "max_iterations"  # 达到最大迭代次数
    TIMEOUT = "timeout"  # 执行超时
    REPEATED_FAILURE = "repeated_failure"  # 重复失败
    SUCCESS = "success"  # 成功完成
    CANCELLED = "cancelled"  # 被取消


@dataclass
class LoopGuardConfig:
    """循环守卫配置。"""
    
    max_iterations: int = 15  # 最大迭代次数
    timeout_seconds: float = 120.0  # 超时时间（秒）
    repeated_failure_threshold: int = 3  # 重复失败阈值
    
    def __post_init__(self):
        """校验参数合法性。"""
        if self.max_iterations < 1:
            raise ValueError("max_iterations 必须 >= 1")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds 必须 > 0")
        if self.repeated_failure_threshold < 1:
            raise ValueError("repeated_failure_threshold 必须 >= 1")


class LoopGuard:
    """
    循环守卫。
    
    监控子代理执行，防止死循环和资源浪费。
    """
    
    def __init__(self, config: Optional[LoopGuardConfig] = None):
        """
        初始化循环守卫。
        
        Args:
            config: 守卫配置，None 表示使用默认配置
        """
        self.config = config or LoopGuardConfig()
        self._start_time: Optional[float] = None
        self._iteration_count: int = 0
        self._stop_reason: Optional[LoopStopReason] = None
        self._last_tool_fingerprint: Optional[str] = None
        self._consecutive_failures: int = 0
        self._stopped: bool = False
    
    def start(self) -> None:
        """开始监控。"""
        self._start_time = time.time()
        self._iteration_count = 0
        self._stop_reason = None
        self._last_tool_fingerprint = None
        self._consecutive_failures = 0
        self._stopped = False
    
    def check_iteration(self) -> bool:
        """
        检查是否可以继续下一次迭代。
        
        Returns:
            True 表示可以继续，False 表示应该停止
        """
        if self._stopped:
            return False
        
        # 检查是否已超时
        if self._is_timeout():
            self._stop_reason = LoopStopReason.TIMEOUT
            self._stopped = True
            return False
        
        # 检查是否达到最大迭代次数
        if self._iteration_count >= self.config.max_iterations:
            self._stop_reason = LoopStopReason.MAX_ITERATIONS
            self._stopped = True
            return False
        
        return True
    
    def record_iteration(self) -> None:
        """记录一次迭代完成。"""
        self._iteration_count += 1
    
    def record_tool_result(
        self,
        tool_name: str,
        tool_args: Dict[str, Any],
        success: bool,
        error_message: Optional[str] = None
    ) -> Optional[LoopStopReason]:
        """
        记录工具调用结果。
        
        Args:
            tool_name: 工具名称
            tool_args: 工具参数
            success: 是否成功
            error_message: 错误消息（失败时）
            
        Returns:
            如果应该停止，返回停止原因；否则返回 None
        """
        if self._stopped:
            return self._stop_reason
        
        # 生成工具调用指纹
        fingerprint = self._generate_fingerprint(tool_name, tool_args)
        
        if success:
            # 成功调用，重置失败计数
            self._consecutive_failures = 0
            self._last_tool_fingerprint = fingerprint
            return None
        
        # 失败调用
        if fingerprint == self._last_tool_fingerprint:
            # 相同工具相同参数的重复失败
            self._consecutive_failures += 1
            
            if self._consecutive_failures >= self.config.repeated_failure_threshold:
                self._stop_reason = LoopStopReason.REPEATED_FAILURE
                self._stopped = True
                return self._stop_reason
        else:
            # 不同的失败，重置计数
            self._consecutive_failures = 1
            self._last_tool_fingerprint = fingerprint
        
        return None
    
    def mark_success(self) -> None:
        """标记成功完成。"""
        if not self._stopped:
            self._stop_reason = LoopStopReason.SUCCESS
            self._stopped = True
    
    def mark_cancelled(self) -> None:
        """标记被取消。"""
        if not self._stopped:
            self._stop_reason = LoopStopReason.CANCELLED
            self._stopped = True
    
    def get_status(self) -> Dict[str, Any]:
        """
        获取当前状态。
        
        Returns:
            包含状态信息的字典
        """
        elapsed = 0.0
        if self._start_time is not None:
            elapsed = time.time() - self._start_time
        
        return {
            "iteration_count": self._iteration_count,
            "max_iterations": self.config.max_iterations,
            "elapsed_seconds": elapsed,
            "timeout_seconds": self.config.timeout_seconds,
            "consecutive_failures": self._consecutive_failures,
            "stopped": self._stopped,
            "stop_reason": self._stop_reason.value if self._stop_reason else None,
        }
    
    def get_stop_message(self) -> Optional[str]:
        """
        获取停止消息。
        
        Returns:
            停止原因的用户友好消息，如果未停止则返回 None
        """
        if not self._stopped or not self._stop_reason:
            return None
        
        messages = {
            LoopStopReason.MAX_ITERATIONS: (
                f"已达到最大迭代次数限制 ({self.config.max_iterations})。"
                f"建议简化任务或调整策略。"
            ),
            LoopStopReason.TIMEOUT: (
                f"执行超时 ({self.config.timeout_seconds}秒)。"
                f"建议拆分为更小的任务或检查是否存在阻塞操作。"
            ),
            LoopStopReason.REPEATED_FAILURE: (
                f"检测到重复失败 (连续 {self._consecutive_failures} 次相同错误)。"
                f"建议检查工具参数或更换执行策略。"
            ),
            LoopStopReason.SUCCESS: "任务成功完成。",
            LoopStopReason.CANCELLED: "任务被取消。",
        }
        
        return messages.get(self._stop_reason, "未知停止原因。")
    
    def _is_timeout(self) -> bool:
        """检查是否已超时。"""
        if self._start_time is None:
            return False
        elapsed = time.time() - self._start_time
        return elapsed > self.config.timeout_seconds
    
    def _generate_fingerprint(self, tool_name: str, tool_args: Dict[str, Any]) -> str:
        """
        生成工具调用指纹。
        
        用于检测重复的失败调用。
        
        Args:
            tool_name: 工具名称
            tool_args: 工具参数
            
        Returns:
            工具调用指纹字符串
        """
        # 对参数进行规范化处理（排序键名，确保相同参数生成相同指纹）
        normalized_args = self._normalize_args(tool_args)
        return f"{tool_name}:{normalized_args}"
    
    def _normalize_args(self, args: Any) -> str:
        """
        规范化参数为字符串。
        
        Args:
            args: 任意参数
            
        Returns:
            规范化后的字符串
        """
        if isinstance(args, dict):
            # 字典：按键排序
            sorted_items = sorted(args.items())
            normalized_items = [
                f"{k}:{self._normalize_args(v)}" 
                for k, v in sorted_items
            ]
            return "{" + ",".join(normalized_items) + "}"
        elif isinstance(args, (list, tuple)):
            # 列表/元组：递归处理
            normalized_items = [self._normalize_args(item) for item in args]
            return "[" + ",".join(normalized_items) + "]"
        else:
            # 基本类型：直接转字符串
            return str(args)
    
    @property
    def iteration_count(self) -> int:
        """获取当前迭代次数。"""
        return self._iteration_count
    
    @property
    def elapsed_seconds(self) -> float:
        """获取已执行时间（秒）。"""
        if self._start_time is None:
            return 0.0
        return time.time() - self._start_time
    
    @property
    def is_stopped(self) -> bool:
        """检查是否已停止。"""
        return self._stopped
    
    @property
    def stop_reason(self) -> Optional[LoopStopReason]:
        """获取停止原因。"""
        return self._stop_reason


def create_loop_guard(
    max_iterations: int = 15,
    timeout_seconds: float = 120.0,
    repeated_failure_threshold: int = 3
) -> LoopGuard:
    """
    创建循环守卫的便捷函数。
    
    Args:
        max_iterations: 最大迭代次数
        timeout_seconds: 超时时间（秒）
        repeated_failure_threshold: 重复失败阈值
        
    Returns:
        配置好的 LoopGuard 实例
    """
    config = LoopGuardConfig(
        max_iterations=max_iterations,
        timeout_seconds=timeout_seconds,
        repeated_failure_threshold=repeated_failure_threshold
    )
    return LoopGuard(config)
