"""
模型目录远程同步模块。

从 models.dev 与 openrouter.ai 拉取上游模型目录与定价数据，
合并后写入 config/pricing/pricing_data.json。

设计参考 cherry-studio 的 provider-registry/scripts/upstream.ts：
- parseMdEntry / parseOrEntry 解析两源原始数据为统一中间结构
- mergeMeta 按并集合并 capabilities/modalities，按 max 取上下文窗口，
  pricing 按 per-field 合并（models.dev 优先于 openrouter）
- write_json 保留用户手动修改的定价字段与用户手动新增的模型条目

关键约束：
- 所有 HTTP 调用必须设置超时（asyncio.wait_for + httpx.Timeout）
- 异常按来源隔离：单源失败不影响另一源合并
- 写入前必须保留 user_overrides 字段（input_price/output_price/cache_read_price/cache_write_price）
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import httpx

logger = logging.getLogger(__name__)

# pricing_data.json 所在目录，与 config_loader.py 中 _CONFIG_DIR 保持一致
PRICING_DIR = Path(__file__).resolve().parent.parent / "config" / "pricing"
PRICING_DATA_PATH = PRICING_DIR / "pricing_data.json"

# 用户可在 user_overrides 中标记的字段：这些字段一旦被用户手动修改，同步时不会被覆盖
USER_OVERRIDE_FIELDS: Tuple[str, ...] = (
    "input_price",
    "output_price",
    "cache_read_price",
    "cache_write_price",
)

# 合法模态白名单，过滤上游可能返回的非标准值（参考 cherry-studio MODALITY 集合）
_VALID_MODALITIES = {"text", "image", "audio", "video"}

# 能力标签规范化顺序，保证合并后输出稳定（参考 cherry-studio CAP_ORDER）
_CAP_ORDER = [
    "function-call",
    "reasoning",
    "image-recognition",
    "image-generation",
    "audio-recognition",
    "audio-generation",
    "video-recognition",
    "video-generation",
    "structured-output",
    "file-input",
]


def _drop_none(obj: Dict[str, Any]) -> Dict[str, Any]:
    """移除字典中值为 None 的键，保持输出紧凑。"""
    return {k: v for k, v in obj.items() if v is not None}


def _uniq_ordered(items: List[str]) -> List[str]:
    """按 _CAP_ORDER 顺序去重，未在预定义顺序中的项追加到末尾。"""
    seen: Set[str] = set()
    result: List[str] = []
    for item in _CAP_ORDER:
        if item in items and item not in seen:
            seen.add(item)
            result.append(item)
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _filter_modalities(items: Optional[List[str]]) -> List[str]:
    """过滤模态列表，仅保留合法模态值。"""
    if not items:
        return []
    return [x for x in items if x in _VALID_MODALITIES]


def parse_md_entry(raw: Any) -> Optional[Dict[str, Any]]:
    """
    解析 models.dev 单条模型记录。

    对应 cherry-studio parseMdEntry：从 name/family/attachment/reasoning/tool_call/
    structured_output/modalities/limit/cost 字段提取统一中间结构。

    Args:
        raw: models.dev 单条模型原始 dict

    Returns:
        统一中间结构 dict，解析失败返回 None
    """
    if not isinstance(raw, dict):
        return None

    caps: Set[str] = set()
    if raw.get("tool_call"):
        caps.add("function-call")
    if raw.get("reasoning"):
        caps.add("reasoning")
    if raw.get("structured_output"):
        caps.add("structured-output")
    if raw.get("attachment"):
        caps.add("file-input")

    modalities = raw.get("modalities") or {}
    if not isinstance(modalities, dict):
        modalities = {}
    inp = modalities.get("input") or []
    out = modalities.get("output") or []
    if not isinstance(inp, list):
        inp = []
    if not isinstance(out, list):
        out = []
    if "image" in inp:
        caps.add("image-recognition")
    if "audio" in inp:
        caps.add("audio-recognition")
    if "video" in inp:
        caps.add("video-recognition")
    if "image" in out:
        caps.add("image-generation")
    if "audio" in out:
        caps.add("audio-generation")
    if "video" in out:
        caps.add("video-generation")

    limit = raw.get("limit") or {}
    if not isinstance(limit, dict):
        limit = {}
    cost = raw.get("cost") or {}
    if not isinstance(cost, dict):
        cost = {}

    pricing: Optional[Dict[str, Any]] = None
    if cost.get("input") is not None and cost.get("output") is not None:
        pricing = _drop_none({
            "input": cost.get("input"),
            "output": cost.get("output"),
            "cache_read": cost.get("cache_read"),
            "cache_write": cost.get("cache_write"),
        })

    return _drop_none({
        "name": raw.get("name"),
        "family": raw.get("family"),
        "capabilities": _uniq_ordered(list(caps)) if caps else None,
        "input_modalities": _filter_modalities(inp),
        "output_modalities": _filter_modalities(out),
        "context_window": limit.get("context"),
        "max_output_tokens": limit.get("output"),
        "pricing": pricing,
        "open_weights": raw.get("open_weights") if isinstance(raw.get("open_weights"), bool) else None,
    })


def parse_or_entry(raw: Any) -> Optional[Dict[str, Any]]:
    """
    解析 openrouter 单条模型记录。

    对应 cherry-studio parseOrEntry：
    - context_length → context_window
    - architecture.input_modalities / output_modalities
    - supported_parameters 推导 capabilities（tools/reasoning/structured_outputs）
    - pricing.prompt / pricing.completion 是美元/token 字符串，需 ×1e6 转换为美元/百万 token

    Args:
        raw: openrouter data 数组中单条模型原始 dict

    Returns:
        统一中间结构 dict，解析失败返回 None
    """
    if not isinstance(raw, dict):
        return None

    caps: Set[str] = set()
    sp = raw.get("supported_parameters") or []
    if not isinstance(sp, list):
        sp = []
    if "tools" in sp:
        caps.add("function-call")
    if "reasoning" in sp:
        caps.add("reasoning")
    if "structured_outputs" in sp or "response_format" in sp:
        caps.add("structured-output")

    arch = raw.get("architecture") or {}
    if not isinstance(arch, dict):
        arch = {}
    inp = arch.get("input_modalities") or []
    out = arch.get("output_modalities") or []
    if not isinstance(inp, list):
        inp = []
    if not isinstance(out, list):
        out = []
    if "image" in inp:
        caps.add("image-recognition")
    if "audio" in inp:
        caps.add("audio-recognition")
    if "video" in inp:
        caps.add("video-recognition")
    if "file" in inp:
        caps.add("file-input")
    if "image" in out:
        caps.add("image-generation")
    if "audio" in out:
        caps.add("audio-generation")

    pricing: Optional[Dict[str, Any]] = None
    raw_pricing = raw.get("pricing") or {}
    if isinstance(raw_pricing, dict) and raw_pricing.get("prompt") is not None:
        try:
            # openrouter 返回的是美元/token 字符串，转换为美元/百万 token
            prompt_per_million = float(raw_pricing["prompt"]) * 1e6
            completion_raw = raw_pricing.get("completion") or 0
            completion_per_million = float(completion_raw) * 1e6
            pricing = {
                "input": prompt_per_million,
                "output": completion_per_million,
            }
        except (TypeError, ValueError):
            pricing = None

    return _drop_none({
        "capabilities": _uniq_ordered(list(caps)) if caps else None,
        "input_modalities": _filter_modalities(inp),
        "output_modalities": _filter_modalities(out),
        "context_window": raw.get("context_length"),
        "pricing": pricing,
    })


def merge_meta(a: Optional[Dict[str, Any]], b: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """
    合并两条中间结构记录。

    对应 cherry-studio mergeMeta：
    - capabilities/input_modalities/output_modalities 取并集
    - context_window/max_output_tokens 取最大值
    - pricing 按 per-field 合并（a 优先于 b，b 仅填补 a 缺失的字段）
    - family/name 同样 a 优先

    Args:
        a: 优先源（通常为 models.dev 解析结果）
        b: 兜底源（通常为 openrouter 解析结果）

    Returns:
        合并后的中间结构 dict
    """
    a = a or {}
    b = b or {}
    out: Dict[str, Any] = {**a}

    if b.get("capabilities"):
        merged_caps = list({*(a.get("capabilities") or []), *b["capabilities"]})
        out["capabilities"] = _uniq_ordered(merged_caps)
    for k in ("input_modalities", "output_modalities"):
        if b.get(k):
            out[k] = list({*(a.get(k) or []), *b[k]})
    if b.get("context_window"):
        out["context_window"] = max(a.get("context_window") or 0, b["context_window"])
    if b.get("max_output_tokens"):
        out["max_output_tokens"] = max(a.get("max_output_tokens") or 0, b["max_output_tokens"])

    # pricing per-field 合并：a 优先，b 仅填补 a 缺失字段
    if b.get("pricing"):
        merged_pricing = {**b["pricing"], **(a.get("pricing") or {})}
        out["pricing"] = merged_pricing

    if b.get("open_weights"):
        out["open_weights"] = True
    if b.get("family") and not a.get("family"):
        out["family"] = b["family"]
    if b.get("name") and not a.get("name"):
        out["name"] = b["name"]

    return out


async def fetch_models_dev(url: str, timeout: float = 30.0) -> Dict[str, Dict[str, Any]]:
    """
    从 models.dev 拉取并解析模型目录。

    上游响应结构：{ provider_key: { models: { model_id: entry } } }
    本函数将其扁平化为 {(provider, model_id): parsed_meta} 字典。

    Args:
        url: models.dev API 地址
        timeout: HTTP 超时秒数

    Returns:
        {(provider, model_id): parsed_meta} 字典；拉取失败返回空字典
    """
    result: Dict[str, Dict[str, Any]] = {}
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout)) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            raw = resp.json()
    except Exception as exc:
        logger.warning("models.dev 拉取失败: %s", exc)
        return result

    if not isinstance(raw, dict):
        return result

    for provider_key, provider_data in raw.items():
        if not isinstance(provider_data, dict):
            continue
        models = provider_data.get("models") or {}
        if not isinstance(models, dict):
            continue
        for model_id, entry in models.items():
            parsed = parse_md_entry(entry)
            if not parsed:
                continue
            result[f"{provider_key}/{model_id}"] = parsed

    return result


async def fetch_openrouter(url: str, timeout: float = 30.0) -> Dict[str, Dict[str, Any]]:
    """
    从 openrouter.ai 拉取并解析模型目录。

    上游响应结构：{ data: [{ id: "provider/model", ... }] }
    本函数将其扁平化为 {"provider/model": parsed_meta} 字典。

    Args:
        url: openrouter API 地址
        timeout: HTTP 超时秒数

    Returns:
        {"provider/model": parsed_meta} 字典；拉取失败返回空字典
    """
    result: Dict[str, Dict[str, Any]] = {}
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout)) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            raw = resp.json()
    except Exception as exc:
        logger.warning("openrouter 拉取失败: %s", exc)
        return result

    if not isinstance(raw, dict):
        return result

    data = raw.get("data") or []
    if not isinstance(data, list):
        return result

    for entry in data:
        if not isinstance(entry, dict):
            continue
        model_id = entry.get("id")
        if not isinstance(model_id, str) or "/" not in model_id:
            continue
        parsed = parse_or_entry(entry)
        if not parsed:
            continue
        result[model_id] = parsed

    return result


def merge_sources(md: Dict[str, Dict[str, Any]], or_data: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """
    合并 models.dev 与 openrouter 两源数据。

    合并键为 "provider/model" 字符串。models.dev 优先，openrouter 仅填补缺失字段。
    对应 cherry-studio buildIndex 中的 consider + mergeMeta 流程。

    Args:
        md: models.dev 解析结果
        or_data: openrouter 解析结果

    Returns:
        {"provider/model": merged_meta} 字典
    """
    index: Dict[str, Dict[str, Any]] = {}
    # 先注入 models.dev（优先源），再合并 openrouter（兜底源）
    for key, meta in md.items():
        index[key] = merge_meta(index.get(key), meta)
    for key, meta in or_data.items():
        index[key] = merge_meta(index.get(key), meta)
    return index


def convert_to_openawa(catalog: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    将合并后的中间结构转换为 Open-AwA 扁平 JSON 格式。

    输出每条记录字段：
    provider, model, input_price, output_price, cache_read_price, cache_write_price,
    currency, context_window, max_output_tokens, owned_by, family,
    capabilities, input_modalities, output_modalities

    Args:
        catalog: {"provider/model": merged_meta} 字典

    Returns:
        扁平结构列表，按 provider/model 排序保证输出稳定
    """
    rows: List[Dict[str, Any]] = []
    for key in sorted(catalog.keys()):
        meta = catalog[key]
        if "/" not in key:
            continue
        provider, model = key.split("/", 1)
        pricing = meta.get("pricing") or {}
        row: Dict[str, Any] = {
            "provider": provider,
            "model": model,
            "input_price": pricing.get("input") if pricing else None,
            "output_price": pricing.get("output") if pricing else None,
            "cache_read_price": pricing.get("cache_read") if pricing else None,
            "cache_write_price": pricing.get("cache_write") if pricing else None,
            "currency": "USD",
            "context_window": meta.get("context_window"),
            "max_output_tokens": meta.get("max_output_tokens"),
            "owned_by": provider,  # 默认以 provider 作为 owned_by，后续可由调用方覆盖
            "family": meta.get("family"),
            "capabilities": meta.get("capabilities") or [],
            "input_modalities": meta.get("input_modalities") or [],
            "output_modalities": meta.get("output_modalities") or [],
        }
        rows.append(row)
    return rows


def compute_stats(old: List[Dict[str, Any]], new: List[Dict[str, Any]]) -> Dict[str, int]:
    """
    计算新增/更新/失效/跳过统计。

    - added: 新数据中存在但旧数据中不存在的 (provider, model)
    - updated: 两侧均存在但字段值有差异
    - removed: 旧数据中存在但新数据中不存在的（仅统计，不实际删除）
    - skipped: 两侧均存在且字段值完全一致

    Args:
        old: 旧数据列表
        new: 新数据列表

    Returns:
        {"added": int, "updated": int, "removed": int, "skipped": int}
    """
    old_map = {(r.get("provider"), r.get("model")): r for r in old}
    new_map = {(r.get("provider"), r.get("model")): r for r in new}

    added = 0
    updated = 0
    skipped = 0
    for key, new_row in new_map.items():
        if key not in old_map:
            added += 1
        else:
            old_row = old_map[key]
            if _row_differs(old_row, new_row):
                updated += 1
            else:
                skipped += 1

    removed = sum(1 for key in old_map if key not in new_map)
    return {"added": added, "updated": updated, "removed": removed, "skipped": skipped}


def _row_differs(old: Dict[str, Any], new: Dict[str, Any]) -> bool:
    """比较两行记录的所有同步字段是否有差异（忽略 user_overrides 字段）。"""
    compare_keys = (
        "input_price", "output_price", "cache_read_price", "cache_write_price",
        "currency", "context_window", "max_output_tokens",
        "owned_by", "family", "capabilities",
        "input_modalities", "output_modalities",
    )
    for k in compare_keys:
        old_val = old.get(k)
        new_val = new.get(k)
        if old_val != new_val:
            return True
    return False


def write_json(
    data: List[Dict[str, Any]],
    path: Path = PRICING_DATA_PATH,
    user_overrides: Optional[Set[Tuple[str, str]]] = None,
) -> Dict[str, int]:
    """
    写入 JSON 文件，保留 user_overrides 标记的字段与用户手动新增的模型条目。

    合并策略（对每条 (provider, model) 记录）：
    - 若 (provider, model) 在新数据中存在且旧数据中也存在：
      * 若在 user_overrides 中：保留旧的 USER_OVERRIDE_FIELDS，更新其他字段
      * 否则：用新数据覆盖
    - 若仅在新数据中：新增
    - 若仅在旧数据中：保留（用户手动新增的，不被同步移除）

    Args:
        data: 新数据列表
        path: 写入目标路径
        user_overrides: 用户标记的 (provider, model) 集合，这些记录的定价字段不被覆盖

    Returns:
        {"added": int, "updated": int, "removed": int, "skipped": int}
    """
    user_overrides = user_overrides or set()

    # 读取现有 JSON（若不存在则视为空列表）
    old_data: List[Dict[str, Any]] = []
    if path.exists():
        try:
            with path.open("r", encoding="utf-8") as f:
                loaded = json.load(f)
                if isinstance(loaded, list):
                    old_data = loaded
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("读取 %s 失败，将以空数据开始: %s", path, exc)

    old_map = {(r.get("provider"), r.get("model")): r for r in old_data}
    new_map = {(r.get("provider"), r.get("model")): r for r in data}

    merged: List[Dict[str, Any]] = []
    stats = {"added": 0, "updated": 0, "removed": 0, "skipped": 0}

    # 先处理新数据中所有记录（保留排序）
    for new_row in data:
        key = (new_row.get("provider"), new_row.get("model"))
        if key in old_map:
            old_row = old_map[key]
            if key in user_overrides:
                # 保留用户修改的定价字段，其他字段用新数据更新
                merged_row = {**new_row}
                for field in USER_OVERRIDE_FIELDS:
                    if field in old_row:
                        merged_row[field] = old_row[field]
                merged.append(merged_row)
                stats["updated"] += 1
            else:
                if _row_differs(old_row, new_row):
                    merged.append(new_row)
                    stats["updated"] += 1
                else:
                    # 无差异，保留旧记录（避免无谓的写入）
                    merged.append(old_row)
                    stats["skipped"] += 1
        else:
            merged.append(new_row)
            stats["added"] += 1

    # 再保留仅在旧数据中的记录（用户手动新增，不被同步移除）
    for old_row in old_data:
        key = (old_row.get("provider"), old_row.get("model"))
        if key not in new_map:
            merged.append(old_row)
            stats["removed"] += 1  # 此处 "removed" 表示"未在新数据中找到，但已保留"

    # 确保目录存在
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)

    return stats


async def run_sync(
    sources: Optional[List[str]] = None,
    dry_run: bool = False,
    timeout: float = 30.0,
    user_overrides: Optional[Set[Tuple[str, str]]] = None,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    主入口，执行完整同步流程。

    步骤：
    1. 读取配置（从 settings）
    2. 并行拉取 models.dev + openrouter
    3. 合并两源数据
    4. 转换为 Open-AwA 扁平格式
    5. 若 dry_run 则只打印统计，不写文件
    6. 否则写入 pricing_data.json
    7. 推送通知到收件箱（若提供 user_id）
    8. 返回统计

    Args:
        sources: 数据源列表，可选值 "models.dev" / "openrouter"，None 表示全部
        dry_run: 只打印变更不写文件
        timeout: HTTP 超时秒数
        user_overrides: 用户标记的 (provider, model) 集合
        user_id: 触发同步的用户 ID，用于推送通知

    Returns:
        {"added": int, "updated": int, "removed": int, "skipped": int,
         "synced_at": str, "dry_run": bool}
    """
    from config.settings import settings

    sources = sources or ["models.dev", "openrouter"]
    sources_lower = {s.lower() for s in sources}

    # 并行拉取两源，单源失败不影响另一源（fetch_* 内部已捕获异常并返回空字典）
    md_data: Dict[str, Dict[str, Any]] = {}
    or_data: Dict[str, Dict[str, Any]] = {}

    if "models.dev" in sources_lower and "openrouter" in sources_lower:
        # 两源并行
        md_data, or_data = await asyncio.gather(
            fetch_models_dev(settings.MODELS_DEV_URL, timeout=timeout),
            fetch_openrouter(settings.OPENROUTER_MODELS_URL, timeout=timeout),
        )
    elif "models.dev" in sources_lower:
        md_data = await fetch_models_dev(settings.MODELS_DEV_URL, timeout=timeout)
    elif "openrouter" in sources_lower:
        or_data = await fetch_openrouter(settings.OPENROUTER_MODELS_URL, timeout=timeout)

    # 兜底：fetch_* 异常时返回空字典，此处再防御性校验一次
    if not isinstance(md_data, dict):
        md_data = {}
    if not isinstance(or_data, dict):
        or_data = {}

    merged_catalog = merge_sources(md_data, or_data)
    new_rows = convert_to_openawa(merged_catalog)

    # 读取旧数据用于统计
    old_data: List[Dict[str, Any]] = []
    if PRICING_DATA_PATH.exists():
        try:
            with PRICING_DATA_PATH.open("r", encoding="utf-8") as f:
                loaded = json.load(f)
                if isinstance(loaded, list):
                    old_data = loaded
        except (json.JSONDecodeError, OSError):
            pass

    stats = compute_stats(old_data, new_rows)
    synced_at = datetime_utcnow_iso()

    if dry_run:
        logger.info(
            "模型目录同步 dry-run: 新增 %d, 更新 %d, 移除 %d, 跳过 %d",
            stats["added"], stats["updated"], stats["removed"], stats["skipped"],
        )
    else:
        write_stats = write_json(new_rows, PRICING_DATA_PATH, user_overrides=user_overrides)
        stats = write_stats
        logger.info(
            "模型目录同步完成: 新增 %d, 更新 %d, 保留 %d, 跳过 %d",
            stats["added"], stats["updated"], stats["removed"], stats["skipped"],
        )

    # 推送通知（若提供 user_id）
    if user_id:
        try:
            from api.routes.inbox import add_task_result_notification
            add_task_result_notification(
                task_name="模型目录同步",
                success=True,
                summary=(
                    f"新增 {stats['added']} 条，更新 {stats['updated']} 条，"
                    f"保留 {stats['removed']} 条，跳过 {stats['skipped']} 条"
                ),
                user_id=user_id,
            )
        except Exception as exc:
            logger.warning("推送同步结果通知失败: %s", exc)

    return {
        **stats,
        "synced_at": synced_at,
        "dry_run": dry_run,
    }


def datetime_utcnow_iso() -> str:
    """返回 UTC 当前时间的 ISO 格式字符串，避免重复导入。"""
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


async def run_scheduled_catalog_sync() -> None:
    """
    APScheduler 定时触发的同步入口。

    与 run_sync 的区别：
    - 不传 user_overrides（定时同步不感知用户上下文）
    - 不推送通知（无触发用户）
    - 异常仅记录日志，不向上抛出（避免 APScheduler 把任务标记为失败）
    """
    try:
        await run_sync()
    except Exception as exc:
        logger.error("定时模型目录同步失败: %s", exc, exc_info=True)
