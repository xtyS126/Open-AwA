"""
内置技能包 — 提供 10 个开箱即用的技能模块。
每个技能模块是一个独立的功能单元，遵循 SkillExecutor 协议。
启动时自动从本目录发现并注册。
"""
from pathlib import Path
from typing import Optional

# 内置技能注册表（名称 -> 模块路径）
_BUILTIN_SKILLS: dict[str, str] = {}


def discover_builtin_skills() -> dict[str, str]:
    """
    扫描 builtin 目录，自动发现并返回所有内置技能的 (名称, 模块路径) 映射。
    """
    global _BUILTIN_SKILLS
    if _BUILTIN_SKILLS:
        return _BUILTIN_SKILLS

    builtin_dir = Path(__file__).resolve().parent
    for py_file in builtin_dir.glob("*.py"):
        name = py_file.stem
        if name.startswith("_") or name == "__init__":
            continue
        module_path = f"backend.skills.builtin.{name}"
        _BUILTIN_SKILLS[name] = module_path

    return _BUILTIN_SKILLS


def get_builtin_skill_module(name: str) -> Optional[str]:
    """
    获取指定内置技能的模块路径。
    """
    skills = discover_builtin_skills()
    return skills.get(name)
