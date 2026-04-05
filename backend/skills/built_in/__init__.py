"""
技能系统模块，负责技能注册、加载、校验、执行或适配外部能力。
当 Agent 需要调用外部能力时，通常会经过这一层完成查找、验证与执行。
"""

from .experience_extractor import ExperienceExtractor
from .file_manager import FileManagerSkill

__all__ = ['ExperienceExtractor', 'FileManagerSkill']
