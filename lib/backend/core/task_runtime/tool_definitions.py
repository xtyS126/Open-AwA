"""
任务运行时工具的 OpenAI function-calling schema 定义模块。

从 core/agent.py 的 _build_native_tools 方法迁移而来，集中维护 18 个任务运行时工具
（task_spawn_agent / task_send_message / task_stop_agent / task_list_agents /
task_list_agent_types / task_create_task / task_list_tasks / task_update_task /
task_claim_task / task_get_task / task_create_team / task_delete_team /
task_list_teams / task_get_team / task_add_teammate / task_remove_teammate /
task_get_mailbox / task_todo_write）的工具 schema 字面量，便于独立演进与复用。

设计原则：
- 不依赖 core.agent 模块，避免循环 import；
- model_hint 参数化注入，由调用方（_build_native_tools）传入；
- 仅返回工具 dict 列表，去重逻辑仍由调用方负责，保持职责单一。
"""

from __future__ import annotations

from typing import Any, Dict, List


def build_task_runtime_tool_definitions(model_hint: str = "") -> List[Dict[str, Any]]:
    """构建任务运行时工具的 OpenAI function-calling schema 列表。

    参数:
        model_hint: 已配置模型的精简提示文本，注入到 task_spawn_agent 的 description
                    与 model 字段说明中，与原 _build_native_tools 行为一致。
                    默认空字符串，表示不附加模型提示。

    返回:
        18 个任务运行时工具的 dict 列表，顺序固定；
        调用方负责基于返回列表做 seen_names 去重与异常降级处理。
    """
    # 在函数内部导入 list_agent_types，避免模块加载时与 core.agent 形成循环依赖；
    # 同时与原 _build_native_tools 行为一致：task_runtime 不可用时整块降级跳过。
    from core.task_runtime.definitions import list_agent_types

    agent_types = list_agent_types()

    task_tools: List[Dict[str, Any]] = [
        {
            "type": "function",
            "function": {
                "name": "task_spawn_agent",
                "description": (
                    f"派生子代理执行任务。可用代理类型: {', '.join(agent_types)}。"
                    f"子代理拥有独立上下文窗口，完成后只回传摘要。{model_hint}"
                    "如需指定跨供应商模型，优先同时传 provider 和 model；"
                    "也支持在 model 中使用 provider:model。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "agent_type": {
                            "type": "string",
                            "description": f"代理类型: {', '.join(agent_types)}",
                        },
                        "prompt": {
                            "type": "string",
                            "description": "子代理要执行的任务描述",
                        },
                        "description": {
                            "type": "string",
                            "description": "任务短描述，用于状态展示",
                        },
                        "provider": {
                            "type": "string",
                            "description": "可选的供应商覆盖。仅传 provider 时，系统会使用该供应商的默认或已选模型。",
                        },
                        "model": {
                            "type": "string",
                            "description": (
                                "可选的模型覆盖。建议填写该 provider 下已配置的模型名；"
                                "也支持 provider:model 单字段格式。"
                                f"{model_hint}"
                            ),
                        },
                        "background": {
                            "type": "boolean",
                            "description": "是否后台执行，默认 false（前台）",
                        },
                    },
                    "required": ["prompt", "description"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "task_send_message",
                "description": "向指定代理发送消息，可用于恢复已停止/失败的代理继续执行",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "to": {
                            "type": "string",
                            "description": "目标代理的 agent_id",
                        },
                        "message": {
                            "type": "string",
                            "description": "要发送的消息或继续执行的指令",
                        },
                    },
                    "required": ["to", "message"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "task_stop_agent",
                "description": "停止运行中的后台代理",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "agent_id": {
                            "type": "string",
                            "description": "要停止的代理 agent_id",
                        },
                    },
                    "required": ["agent_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "task_list_agents",
                "description": "列出当前活跃或历史代理会话",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "state": {
                            "type": "string",
                            "description": "按状态过滤: running/completed/failed/stopped",
                        },
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "task_list_agent_types",
                "description": "列出所有可用的代理类型及其描述",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "task_create_task",
                "description": "在共享任务清单中创建新的任务项",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "list_id": {
                            "type": "string",
                            "description": "任务清单标识",
                        },
                        "subject": {
                            "type": "string",
                            "description": "任务主题",
                        },
                        "description": {
                            "type": "string",
                            "description": "任务详细描述",
                        },
                        "dependencies": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "依赖的任务 ID 列表",
                        },
                    },
                    "required": ["subject"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "task_list_tasks",
                "description": "列出共享任务清单中的任务项",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "list_id": {
                            "type": "string",
                            "description": "任务清单标识",
                        },
                        "status": {
                            "type": "string",
                            "description": "按状态过滤: pending/running/completed/failed",
                        },
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "task_update_task",
                "description": "更新任务项的状态、描述或归属",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "task_id": {
                            "type": "string",
                            "description": "任务 ID",
                        },
                        "status": {
                            "type": "string",
                            "description": "新状态: pending/running/completed/failed/cancelled",
                        },
                        "subject": {
                            "type": "string",
                            "description": "新的任务主题",
                        },
                        "result_summary": {
                            "type": "string",
                            "description": "任务结果摘要",
                        },
                    },
                    "required": ["task_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "task_claim_task",
                "description": "领取一个待执行的任务项，将其状态设为 running 并绑定到当前代理",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "task_id": {
                            "type": "string",
                            "description": "要领取的任务 ID",
                        },
                    },
                    "required": ["task_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "task_get_task",
                "description": "获取单个任务项的完整详情，包括依赖、状态与结果摘要",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "task_id": {
                            "type": "string",
                            "description": "任务 ID",
                        },
                    },
                    "required": ["task_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "task_create_team",
                "description": "创建代理团队，lead 作为团队负责人。队友可共享任务清单并互发消息。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "团队名称",
                        },
                        "lead_agent_id": {
                            "type": "string",
                            "description": "团队负责人的 agent_id",
                        },
                        "teammate_agent_ids": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "agent_id": {"type": "string"},
                                    "name": {"type": "string"},
                                },
                            },
                            "description": "队友列表，每个队友包含 agent_id 和 name",
                        },
                        "task_list_id": {
                            "type": "string",
                            "description": "共享任务清单 ID",
                        },
                    },
                    "required": ["lead_agent_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "task_delete_team",
                "description": "删除代理团队，清理所有成员与相关消息",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "team_id": {
                            "type": "string",
                            "description": "要删除的团队 ID",
                        },
                    },
                    "required": ["team_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "task_list_teams",
                "description": "列出所有代理团队及其成员",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "state": {
                            "type": "string",
                            "description": "按状态过滤: active/cleaning/stopped/failed",
                        },
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "task_get_team",
                "description": "获取单个团队的详细信息，包括成员列表与共享任务",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "team_id": {
                            "type": "string",
                            "description": "团队 ID",
                        },
                    },
                    "required": ["team_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "task_add_teammate",
                "description": "向已有团队添加新成员",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "team_id": {
                            "type": "string",
                            "description": "团队 ID",
                        },
                        "agent_id": {
                            "type": "string",
                            "description": "要添加的代理 ID",
                        },
                        "name": {
                            "type": "string",
                            "description": "成员名称",
                        },
                    },
                    "required": ["team_id", "agent_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "task_remove_teammate",
                "description": "从团队移除成员（不能移除 lead）",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "team_id": {
                            "type": "string",
                            "description": "团队 ID",
                        },
                        "agent_id": {
                            "type": "string",
                            "description": "要移除的代理 ID",
                        },
                    },
                    "required": ["team_id", "agent_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "task_get_mailbox",
                "description": "获取代理的邮箱消息，查看队友发来的消息",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "agent_id": {
                            "type": "string",
                            "description": "代理 ID",
                        },
                        "unread_only": {
                            "type": "boolean",
                            "description": "是否仅获取未读消息，默认 false",
                        },
                    },
                    "required": ["agent_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "task_todo_write",
                "description": "同步 todo 快照到共享任务清单，非交互模式的简化入口。传入完整 todo 列表即可自动增/改/删任务项",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "list_id": {
                            "type": "string",
                            "description": "任务清单 ID，可选",
                        },
                        "todos": {
                            "type": "array",
                            "description": "todo 项列表，每项包含 subject（主题）和 status（状态）",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "subject": {
                                        "type": "string",
                                        "description": "任务主题",
                                    },
                                    "status": {
                                        "type": "string",
                                        "description": "任务状态",
                                        "enum": ["pending", "completed", "running", "cancelled"],
                                    },
                                    "description": {
                                        "type": "string",
                                        "description": "任务描述",
                                    },
                                },
                                "required": ["subject", "status"],
                            },
                        },
                    },
                    "required": ["todos"],
                },
            },
        },
    ]

    return task_tools
