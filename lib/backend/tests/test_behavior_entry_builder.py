from core.behavior_entry_builder import build_behavior_entries


def test_builds_llm_and_error_entries() -> None:
    entries = build_behavior_entries(
        user_id="1", node_type="llm_call", status="error", error_message="failed",
        llm_output={"error": "timeout"}, llm_tokens_used=5, execution_duration_ms=12,
        metadata={"provider": "test", "model": "model"},
    )

    assert entries[0]["action_type"] == "llm_call"
    assert entries[1] == {"user_id": "1", "action_type": "error", "details": "failed"}


def test_builds_plugin_tool_entry() -> None:
    entries = build_behavior_entries(
        user_id="1", node_type="tool_execution", status="success", error_message=None,
        llm_output=None, llm_tokens_used=None, execution_duration_ms=None,
        metadata={"execution_type": "plugin", "plugin_name": "demo"},
    )

    assert entries == [{"user_id": "1", "action_type": "tool_usage", "details": 'demo:{"status": "success"}'}]
