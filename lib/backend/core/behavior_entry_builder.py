import json
from typing import Any, Dict, List, Optional


def build_behavior_entries(
    *,
    user_id: str,
    node_type: str,
    status: str,
    error_message: Optional[str],
    llm_output: Any,
    llm_tokens_used: Optional[int],
    execution_duration_ms: Optional[int],
    metadata: Any,
) -> List[Dict[str, Any]]:
    entries: List[Dict[str, Any]] = []
    action_type = ""
    details_str = ""

    if node_type == "llm_call":
        action_type = "llm_call"
        response_content = None
        if isinstance(llm_output, dict):
            response_content = llm_output.get("response") or llm_output.get("error")
        details_str = json.dumps(
            {
                "duration_ms": execution_duration_ms,
                "status": status,
                "provider": metadata.get("provider") if isinstance(metadata, dict) else None,
                "model": metadata.get("model") if isinstance(metadata, dict) else None,
                "tokens_used": llm_tokens_used,
                "response_result": response_content,
            },
            ensure_ascii=False,
        )
    elif node_type == "tool_execution":
        action_type = "tool_usage"
        tool_name = "unknown"
        if isinstance(metadata, dict):
            if metadata.get("execution_type") == "skill":
                tool_name = metadata.get("skill_name", "unknown")
            elif metadata.get("execution_type") == "plugin":
                tool_name = metadata.get("plugin_name", "unknown")
        details_str = f"{tool_name}:" + json.dumps({"status": status}, ensure_ascii=False)
    elif node_type == "intent_recognition":
        action_type = "intent"
        details_str = metadata.get("intent", "unknown") if isinstance(metadata, dict) else str(metadata)

    if action_type:
        entries.append({"user_id": user_id, "action_type": action_type, "details": details_str})
    if status == "error":
        entries.append({"user_id": user_id, "action_type": "error", "details": error_message or "Unknown error"})
    return entries
