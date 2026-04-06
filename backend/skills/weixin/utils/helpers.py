"""
工具函数模块
提供通用辅助函数
"""

from __future__ import annotations

import base64
import os
from typing import Any, Dict, Optional


def sanitize_account_id(account_id: str) -> str:
    """
    规范化账号ID，使其适用于文件系统
    
    参数:
        account_id: 原始账号ID
        
    返回:
        规范化后的账号ID，替换了不安全字符
    """
    safe = str(account_id or "default").strip() or "default"
    return safe.replace("/", "-").replace("\\", "-").replace(":", "-").replace("@", "-")


def pick_value(primary: Dict[str, Any], fallback: Dict[str, Any], *keys: str) -> Any:
    """
    从多个字典中按优先级获取值
    
    参数:
        primary: 主字典，优先从中获取
        fallback: 备用字典
        keys: 要查找的键名列表
        
    返回:
        找到的值，如果都未找到则返回None
    """
    for key in keys:
        if key in primary and primary[key] is not None:
            return primary[key]
    for key in keys:
        if key in fallback and fallback[key] is not None:
            return fallback[key]
    return None


def build_random_wechat_uin() -> str:
    """
    生成随机的微信UIN标识
    
    返回:
        Base64编码的随机标识字符串
    """
    raw = str(int.from_bytes(os.urandom(4), byteorder="big", signed=False))
    return base64.b64encode(raw.encode("utf-8")).decode("utf-8")


def normalize_binding_status(binding_status: Optional[str], user_id: str = "") -> str:
    """
    规范化绑定状态
    
    参数:
        binding_status: 原始绑定状态
        user_id: 用户ID，用于推断状态
        
    返回:
        规范化后的绑定状态（unbound/pending/bound）
    """
    normalized = str(binding_status or "").strip().lower()
    if normalized in {"bound", "confirmed", "linked", "success", "succeeded"}:
        return "bound"
    if normalized in {"pending", "confirming", "waiting"}:
        return "pending"
    if user_id:
        return "bound"
    return "unbound"


def read_json_file(file_path: str) -> Dict[str, Any]:
    """
    读取JSON文件
    
    参数:
        file_path: 文件路径
        
    返回:
        解析后的字典，如果文件不存在或解析失败则返回空字典
    """
    import json
    from loguru import logger
    
    try:
        with open(file_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            return data
    except FileNotFoundError:
        return {}
    except Exception as exc:
        logger.warning(f"Failed to read weixin state file {file_path}: {exc}")
    return {}


def write_json_file(file_path: str, data: Dict[str, Any]) -> None:
    """
    写入JSON文件
    
    参数:
        file_path: 文件路径
        data: 要写入的字典数据
    """
    import json
    
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    with open(file_path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False)
