"""
灵魂状态管理模块，负责跟踪和控制灵魂注入的生命周期。

参考 Agent Diva 的 SoulState 设计，提供：
- 灵魂注入开关控制
- 注入状态持久化
- 生命周期追踪
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from loguru import logger


@dataclass
class SoulState:
    """
    灵魂状态数据类。
    
    记录灵魂注入的生命周期状态，包括：
    - 首次注入时间
    - 注入完成时间
    - 是否启用注入
    - 最近一次注入时间
    - 累计注入次数
    """
    bootstrap_seeded_at: Optional[datetime] = None
    bootstrap_completed_at: Optional[datetime] = None
    injection_enabled: bool = True
    last_injection_at: Optional[datetime] = None
    injection_count: int = 0


class SoulStateManager:
    """
    灵魂状态管理器。
    
    负责管理特定工作区的灵魂注入状态，提供：
    - 状态加载和持久化
    - 注入开关控制
    - 生命周期标记
    """
    
    def __init__(self, workspace_id: str, state_dir: Optional[Path] = None):
        """
        初始化灵魂状态管理器。
        
        Args:
            workspace_id: 工作区 ID
            state_dir: 状态文件存储目录，默认为 ./data/soul_states
        """
        self.workspace_id = workspace_id
        self.state_dir = state_dir or Path("./data/soul_states")
        self.state_file = self.state_dir / f"{workspace_id}_soul_state.json"
        self._state: Optional[SoulState] = None
        
        logger.debug(f"SoulStateManager initialized for workspace: {workspace_id}")
    
    def load_state(self) -> SoulState:
        """
        加载灵魂状态。
        
        如果内存中已有状态，直接返回；否则从文件加载或创建默认状态。
        
        Returns:
            SoulState: 当前灵魂状态
        """
        if self._state is not None:
            return self._state
        
        if self.state_file.exists():
            try:
                with open(self.state_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self._state = SoulState(
                        bootstrap_seeded_at=self._parse_datetime(data.get('bootstrap_seeded_at')),
                        bootstrap_completed_at=self._parse_datetime(data.get('bootstrap_completed_at')),
                        injection_enabled=data.get('injection_enabled', True),
                        last_injection_at=self._parse_datetime(data.get('last_injection_at')),
                        injection_count=data.get('injection_count', 0)
                    )
                logger.debug(f"Loaded soul state from {self.state_file}")
            except (json.JSONDecodeError, OSError, ValueError) as e:
                logger.warning(f"Failed to load soul state from {self.state_file}: {e}")
                self._state = SoulState()
        else:
            self._state = SoulState()
            logger.debug(f"Created default soul state for workspace: {self.workspace_id}")
        
        return self._state
    
    def save_state(self) -> None:
        """
        保存灵魂状态到文件。
        
        自动创建目录（如果不存在）。
        """
        if self._state is None:
            return
        
        try:
            self.state_dir.mkdir(parents=True, exist_ok=True)
            
            data = {
                'bootstrap_seeded_at': self._format_datetime(self._state.bootstrap_seeded_at),
                'bootstrap_completed_at': self._format_datetime(self._state.bootstrap_completed_at),
                'injection_enabled': self._state.injection_enabled,
                'last_injection_at': self._format_datetime(self._state.last_injection_at),
                'injection_count': self._state.injection_count
            }
            
            with open(self.state_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            logger.debug(f"Saved soul state to {self.state_file}")
        except OSError as e:
            logger.error(f"Failed to save soul state to {self.state_file}: {e}")
            raise
    
    def is_injection_enabled(self) -> bool:
        """
        检查是否启用灵魂注入。
        
        Returns:
            bool: True 表示启用，False 表示禁用
        """
        state = self.load_state()
        return state.injection_enabled
    
    def set_injection_enabled(self, enabled: bool) -> None:
        """
        设置灵魂注入开关。
        
        Args:
            enabled: True 启用，False 禁用
        """
        state = self.load_state()
        state.injection_enabled = enabled
        self.save_state()
        logger.info(f"Soul injection {'enabled' if enabled else 'disabled'} for workspace: {self.workspace_id}")
    
    def mark_bootstrap_seeded(self) -> None:
        """
        标记首次注入已播种。
        
        仅在首次调用时记录时间戳。
        """
        state = self.load_state()
        if state.bootstrap_seeded_at is None:
            state.bootstrap_seeded_at = datetime.utcnow()
            self.save_state()
            logger.debug(f"Marked bootstrap seeded for workspace: {self.workspace_id}")
    
    def mark_injection_completed(self) -> None:
        """
        标记注入完成。
        
        记录完成时间、更新最近注入时间和累计次数。
        """
        state = self.load_state()
        now = datetime.utcnow()
        
        if state.bootstrap_seeded_at is None:
            state.bootstrap_seeded_at = now
        
        if state.bootstrap_completed_at is None:
            state.bootstrap_completed_at = now
        
        state.last_injection_at = now
        state.injection_count += 1
        self.save_state()
        logger.debug(f"Marked injection completed (count: {state.injection_count}) for workspace: {self.workspace_id}")
    
    def is_bootstrap_completed(self) -> bool:
        """
        检查是否已完成首次注入。
        
        Returns:
            bool: True 表示已完成，False 表示未完成
        """
        state = self.load_state()
        return state.bootstrap_completed_at is not None
    
    def reset_state(self) -> None:
        """
        重置灵魂状态。
        
        用于测试或重新初始化场景。
        """
        self._state = SoulState()
        self.save_state()
        logger.info(f"Reset soul state for workspace: {self.workspace_id}")
    
    def get_state_summary(self) -> dict:
        """
        获取状态摘要（用于 API 响应）。
        
        Returns:
            dict: 包含状态信息的字典
        """
        state = self.load_state()
        return {
            'workspace_id': self.workspace_id,
            'injection_enabled': state.injection_enabled,
            'bootstrap_seeded_at': self._format_datetime(state.bootstrap_seeded_at),
            'bootstrap_completed_at': self._format_datetime(state.bootstrap_completed_at),
            'last_injection_at': self._format_datetime(state.last_injection_at),
            'injection_count': state.injection_count
        }
    
    @staticmethod
    def _parse_datetime(value: Optional[str]) -> Optional[datetime]:
        """
        解析 ISO 格式时间字符串。
        
        Args:
            value: ISO 格式时间字符串或 None
            
        Returns:
            datetime 对象或 None
        """
        if not value:
            return None
        try:
            return datetime.fromisoformat(value)
        except (ValueError, TypeError):
            return None
    
    @staticmethod
    def _format_datetime(value: Optional[datetime]) -> Optional[str]:
        """
        格式化 datetime 为 ISO 字符串。
        
        Args:
            value: datetime 对象或 None
            
        Returns:
            ISO 格式字符串或 None
        """
        if not value:
            return None
        return value.isoformat()
