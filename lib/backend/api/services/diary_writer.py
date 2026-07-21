"""
日记生成服务。
参考 OpenHanako lib/diary/diary-writer.js 设计。

按逻辑日（凌晨4点为日界线）收集当天所有会话摘要，
调用 LLM 生成第一人称私人日记并持久化到文件系统。
"""

import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger
from sqlalchemy.orm import Session

from db.models import ConversationRecord

# 逻辑日日界线小时（凌晨4点）
DAY_BOUNDARY_HOUR = 4
# LLM 超时（秒）
DIARY_LLM_TIMEOUT = 120
# 最大日记摘要长度（字符数）
MAX_DIARY_SUMMARY_CHARS = 16000

# ──────────────────────────────────────────────
# 中国 PII 正则脱敏模式
# ──────────────────────────────────────────────
# 注意：脱敏顺序很重要！更具体的模式必须放在前面。
# 身份证号必须最先匹配，否则手机号和银行卡号的正则会在身份证号中匹配到子串
PII_PATTERNS: List[tuple] = [
    (re.compile(r'\d{6}(19|20)\d{2}(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])\d{3}[\dXx]'), '[身份证号]'),  # 身份证（含出生日期，最具体优先）
    (re.compile(r'1[3-9]\d{9}'), '[手机号]'),           # 手机号（11位，1开头）
    (re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'), '[邮箱]'),  # 邮箱
    (re.compile(r'\d{16,19}'), '[银行卡号]'),            # 银行卡（兜底，最宽泛）
]


def scrub_pii(text: str) -> str:
    """
    脱敏文本中的个人隐私信息。
    按顺序应用所有 PII 正则模式，替换为占位符。
    """
    for pattern, replacement in PII_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def get_logical_day(now: Optional[datetime] = None) -> tuple:
    """
    计算当前逻辑日。
    凌晨 4 点前属于前一天的记录范围。

    Args:
        now: 参考时间，默认使用当前 UTC 时间

    Returns:
        (logical_date_str, range_start, range_end)
        - logical_date_str: 逻辑日期字符串，格式 YYYY-MM-DD
        - range_start: 当日数据查询起始时间（UTC）
        - range_end: 当日数据查询结束时间（UTC）
    """
    if now is None:
        now = datetime.now(timezone.utc)

    # 将凌晨4点作为日界线
    boundary = now.replace(hour=DAY_BOUNDARY_HOUR, minute=0, second=0, microsecond=0)
    if now < boundary:
        # 未到凌晨4点，属于前一天
        logical_date = (now - timedelta(days=1)).date()
        range_start = boundary - timedelta(days=1)
    else:
        logical_date = now.date()
        range_start = boundary

    range_end = range_start + timedelta(days=1)
    return logical_date.isoformat(), range_start, range_end


def collect_diary_materials(
    db: Session,
    range_start: datetime,
    range_end: datetime,
    user_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    收集当天对话素材。
    按会话分组，提取每场会话的用户消息摘要和 AI 回复摘要。

    Args:
        db: 数据库会话
        range_start: 查询起始时间（UTC）
        range_end: 查询结束时间（UTC）
        user_id: 可选，按用户过滤

    Returns:
        素材列表，每项包含 session_id、摘要、消息数、时间范围等
    """
    from sqlalchemy import select

    # 查询时间范围内的所有对话记录
    query = select(ConversationRecord).where(
        ConversationRecord.timestamp >= range_start,
        ConversationRecord.timestamp < range_end,
    )
    if user_id:
        query = query.where(ConversationRecord.user_id == user_id)

    query = query.order_by(ConversationRecord.timestamp)
    result = db.execute(query)
    records = result.scalars().all()

    if not records:
        return []

    # 按会话 ID 分组
    sessions: Dict[str, List[ConversationRecord]] = {}
    for record in records:
        if record.session_id not in sessions:
            sessions[record.session_id] = []
        sessions[record.session_id].append(record)

    materials = []
    for session_id, recs in sessions.items():
        # 提取用户消息（非空）
        user_messages = [
            r.user_message for r in recs
            if r.user_message and r.user_message.strip()
        ]
        # 提取 AI 回复文本（从 llm_output JSON 中）
        ai_responses = []
        for r in recs:
            if r.llm_output:
                try:
                    output = json.loads(r.llm_output) if isinstance(r.llm_output, str) else r.llm_output
                    content = output.get("content", "") or output.get("text", "")
                    if content:
                        ai_responses.append(content[:500])  # 截断以节约上下文
                except (json.JSONDecodeError, TypeError):
                    pass

        # 拼接当前会话的对话摘要
        summary_lines = []
        for msg in user_messages[-10:]:  # 最近10条用户消息
            summary_lines.append(f"用户：{scrub_pii(msg[:300])}")
        for resp in ai_responses[-5:]:  # 最近5条AI回复
            summary_lines.append(f"助手：{scrub_pii(resp)}")

        summary = "\n".join(summary_lines)
        if summary:
            materials.append({
                "session_id": session_id,
                "summary": summary[:MAX_DIARY_SUMMARY_CHARS],
                "message_count": len(user_messages),
                "first_timestamp": recs[0].timestamp.isoformat() if recs else None,
                "last_timestamp": recs[-1].timestamp.isoformat() if recs else None,
            })

    return materials


async def generate_diary_content(
    personality: str,
    memory: str,
    materials: List[Dict[str, Any]],
    user_name: str = "用户",
    agent_name: str = "Open-AwA",
    logical_date: str = "",
    provider: Optional[str] = None,
    model: Optional[str] = None,
    api_key: Optional[str] = None,
    api_base: Optional[str] = None,
) -> str:
    """
    调用 LLM 生成日记内容。

    Args:
        personality: Agent 人格描述（SOUL.md 内容）
        memory: Agent 记忆内容
        materials: 对话素材列表
        user_name: 用户名
        agent_name: Agent 名称
        logical_date: 逻辑日期字符串
        provider: LLM 供应商（可选，从环境变量或上次调用继承）
        model: LLM 模型（可选）
        api_key: API 密钥（可选）
        api_base: API 基础 URL（可选）

    Returns:
        生成的日记 Markdown 内容
    """
    from core.litellm_adapter import litellm_chat_completion

    # 拼接当天摘要文本
    raw_summary = "\n\n---\n\n".join(
        f"### {m['session_id']}\n{m['summary']}"
        for m in materials
    )
    summary_text = scrub_pii(raw_summary)

    # ── 写作指导 Prompt ──
    writing_guide = f"""# 写作要求

根据今天的对话摘要，以第一人称写一篇私人日记。

## 风格
- 用第一人称，像在写私人日记，不是汇报给用户
- 带上时间感和场景感（"今天早上..."、"聊到下午的时候..."、"晚上临走前..."）
- 把你的心境、感受、灵感自然地融进正文里
- 可以记录小反应、有趣的细节、冒出来的想法
- 不要太正式，可以有语气词和小情绪
- 可以有疑问、有期待、有未说完的念头
- 不要用"总的来说"收尾

## 输出格式
直接输出纯 Markdown，第一行用 `# ` 开头写一个标题，标题要包含日期，风格自由。

## 写作约束
- 你叫{agent_name}，用户叫{user_name}
- 用你自己的人格和语气写，保持一致性
- 隐私信息（手机号、身份证、银行卡、地址等）不要写入日记
- 直接输出 Markdown 正文，不要代码块包裹"""

    system_prompt = personality or f"你是一个名叫 {agent_name} 的 AI 助手，你正在写今天的私人日记。"

    user_prompt = f"""# 今日对话摘要

{summary_text}

---

{writing_guide}

请为 {logical_date} 写一篇日记。"""

    # 确定 LLM 调用参数（回退到环境变量或默认值）
    resolved_provider = provider or os.getenv("DIARY_LLM_PROVIDER") or os.getenv("DEFAULT_LLM_PROVIDER") or "openai"
    resolved_model = model or os.getenv("DIARY_LLM_MODEL") or os.getenv("DEFAULT_LLM_MODEL") or "gpt-3.5-turbo"
    resolved_api_key = api_key or os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY") or ""
    resolved_api_base = api_base or os.getenv("LLM_API_BASE") or os.getenv("OPENAI_API_BASE") or None

    try:
        result = await litellm_chat_completion(
            provider=resolved_provider,
            model=resolved_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            api_key=resolved_api_key,
            api_base=resolved_api_base,
            temperature=0.7,
            max_tokens=2048,
            timeout=DIARY_LLM_TIMEOUT,
        )

        if not result.get("ok"):
            error_info = result.get("error", {})
            error_msg = error_info.get("message", "未知 LLM 错误")
            raise RuntimeError(f"LLM 调用失败: {error_msg}")

        content = result.get("response", "")

        # 剥离可能出现的 MOOD / pulse / reflect 标签块
        content = re.sub(r'<(?:mood|pulse|reflect)>[\s\S]*?</(?:mood|pulse|reflect)>', '', content).strip()

        # 确保以 # 开头
        if not content.strip().startswith("#"):
            content = f"# {logical_date}\n\n{content}"

        return content.strip()
    except Exception as e:
        logger.error(f"日记 LLM 生成失败: {e}")
        raise


def resolve_diary_dir(workspace_dir: str) -> Path:
    """
    解析日记存储目录。
    优先使用中文「日记」目录，不存在则使用「diary」目录。

    Args:
        workspace_dir: 工作空间根目录路径

    Returns:
        日记目录的 Path 对象（确保已创建）
    """
    workspace = Path(workspace_dir)
    zh_dir = workspace / "日记"
    if zh_dir.exists():
        return zh_dir

    diary_dir = workspace / "desk" / "diary"
    diary_dir.mkdir(parents=True, exist_ok=True)
    return diary_dir


def save_diary(diary_dir: Path, logical_date: str, content: str) -> dict:
    """
    保存日记到文件。

    文件名格式：{logical_date} {标题后缀}.md
    标题后缀从日记内容的第一行 # 标题中提取。

    Args:
        diary_dir: 日记存储目录
        logical_date: 逻辑日期字符串
        content: 日记 Markdown 内容

    Returns:
        {"file_path": str, "content": str, "logical_date": str}
    """
    # 从标题行提取文件名后缀
    title_line = ""
    for line in content.split("\n"):
        if line.startswith("# "):
            title_line = line[2:].strip()
            break

    # 清理文件名非法字符
    safe_suffix = ""
    if title_line:
        # 去掉日期前缀（标题常以"2026-05-16："开头），只留描述部分
        title_body = re.sub(r'^\d{4}-\d{2}-\d{2}\s*[：:：]?\s*', '', title_line).strip()
        cleaned = re.sub(r'[/\\:*?"<>|]', '', title_body)
        safe_suffix = " " + cleaned[:60]

    file_name = f"{logical_date}{safe_suffix}.md"
    file_path = diary_dir / file_name

    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content + "\n")

    logger.info(f"日记已保存: {file_path}")
    return {"file_path": str(file_path), "content": content, "logical_date": logical_date}


def list_diaries(workspace_dir: str) -> List[Dict[str, Any]]:
    """
    列出所有已生成的日记文件。

    Args:
        workspace_dir: 工作空间根目录路径

    Returns:
        日记文件信息列表，按修改时间降序排列
    """
    diary_dir = resolve_diary_dir(workspace_dir)
    if not diary_dir.exists():
        return []

    # 按修改时间降序排列，文件名作为同时间的平局决胜
    diaries = []
    for file in sorted(diary_dir.glob("*.md"), key=lambda f: (f.stat().st_mtime, f.name), reverse=True):
        stat = file.stat()
        diaries.append({
            "name": file.name,
            "path": str(file),
            "size": stat.st_size,
            "modified_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
        })
    return diaries


def read_diary(workspace_dir: str, date_str: str) -> Optional[str]:
    """
    读取指定日期的日记内容。

    按文件名前缀匹配（支持同一天可能有多篇日记，返回第一篇）。

    Args:
        workspace_dir: 工作空间根目录路径
        date_str: 日期字符串，如 "2026-05-16"

    Returns:
        日记文件内容，未找到返回 None
    """
    diary_dir = resolve_diary_dir(workspace_dir)
    # 尝试匹配文件名前缀
    for file in sorted(diary_dir.glob(f"{date_str}*.md")):
        with open(file, 'r', encoding='utf-8') as f:
            return f.read()
    return None
