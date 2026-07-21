"""
问题反馈只写器。

设计约束（用户明确要求，禁止违反）：
1. 本模块只能"创建文件 + 写入内容"，不得执行任何其他文件操作
2. 禁止 import 任何读取/删除/列举目录内容的 API
3. 仅暴露 write_issue 函数，不暴露任何读取接口
4. 文件名使用 timestamp + uuid 防碰撞
"""

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

# 问题反馈落盘目录：锚定到项目根 var/data/issue_reports（__file__ = lib/backend/issue_writer/writer.py，parents[3] = 项目根）
_ISSUE_DIR = Path(__file__).resolve().parents[3] / "var" / "data" / "issue_reports"


def write_issue(payload: Dict[str, Any]) -> str:
    """
    将一条问题反馈以 JSON 文件形式写入 var/data/issue_reports/ 目录。

    仅执行：
    1. _ISSUE_DIR.mkdir(parents=True, exist_ok=True)
    2. file_path.write_text(json_str, encoding="utf-8")

    不返回文件内容、不列举目录、不读取已有文件。
    返回 file_id（文件名不含扩展名），供调用方记录但无法反向读取。
    """
    file_id = f"{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    file_path = _ISSUE_DIR / f"{file_id}.json"

    # 仅创建目录（已存在则跳过）
    _ISSUE_DIR.mkdir(parents=True, exist_ok=True)

    # 仅创建并写入文件
    file_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return file_id
