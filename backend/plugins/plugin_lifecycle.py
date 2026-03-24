from __future__ import annotations

import asyncio
import inspect
import threading
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, Optional

from loguru import logger


class PluginState(str, Enum):
    REGISTERED = "registered"
    LOADED = "loaded"
    ENABLED = "enabled"
    DISABLED = "disabled"
    UNLOADED = "unloaded"
    ERROR = "error"
    UPDATING = "updating"


@dataclass
class TransitionResult:
    success: bool
    plugin_name: str
    from_state: str
    to_state: str
    rolled_back: bool = False
    error: Optional[str] = None


class PluginStateMachine:
    VALID_TRANSITIONS = {
        PluginState.REGISTERED: {PluginState.LOADED, PluginState.ERROR},
        PluginState.LOADED: {PluginState.ENABLED, PluginState.UNLOADED, PluginState.ERROR},
        PluginState.ENABLED: {PluginState.DISABLED, PluginState.UPDATING, PluginState.ERROR},
        PluginState.DISABLED: {PluginState.ENABLED, PluginState.UNLOADED, PluginState.ERROR},
        PluginState.UPDATING: {PluginState.LOADED, PluginState.ERROR},
        PluginState.ERROR: {PluginState.UNLOADED, PluginState.LOADED},
        PluginState.UNLOADED: {PluginState.LOADED},
    }

    def __init__(self):
        self._states: Dict[str, PluginState] = {}
        self._lock = threading.Lock()

    def get_state(self, plugin_name: str) -> PluginState:
        with self._lock:
            return self._states.get(plugin_name, PluginState.REGISTERED)

    def set_state(self, plugin_name: str, new_state: PluginState) -> None:
        with self._lock:
            self._states[plugin_name] = new_state

    def can_transition(self, plugin_name: str, to_state: PluginState) -> bool:
        current = self.get_state(plugin_name)
        return to_state in self.VALID_TRANSITIONS.get(current, set())


class TransitionExecutor:
    def __init__(self, state_machine: PluginStateMachine):
        self.state_machine = state_machine
        self._idempotency_cache: Dict[str, TransitionResult] = {}

    def execute(
        self,
        plugin_name: str,
        plugin_instance: Any,
        to_state: PluginState,
        action: Optional[Callable[[], Any]] = None,
        rollback_action: Optional[Callable[[PluginState], Any]] = None,
        idempotency_key: Optional[str] = None,
    ) -> TransitionResult:
        from_state = self.state_machine.get_state(plugin_name)
        resolved_plugin_instance = self._resolve_plugin_instance(plugin_instance)

        if from_state == to_state:
            result = TransitionResult(
                success=True,
                plugin_name=plugin_name,
                from_state=from_state.value,
                to_state=to_state.value,
            )
            if idempotency_key:
                self._idempotency_cache[idempotency_key] = result
            return result

        cache_key = idempotency_key or f"{plugin_name}:{from_state.value}->{to_state.value}"
        if cache_key in self._idempotency_cache:
            cached = self._idempotency_cache[cache_key]
            if cached.success and cached.from_state == from_state.value and cached.to_state == to_state.value:
                logger.debug(f"Idempotent transition hit for {cache_key}")
                return cached

        if not self.state_machine.can_transition(plugin_name, to_state):
            result = TransitionResult(
                success=False,
                plugin_name=plugin_name,
                from_state=from_state.value,
                to_state=to_state.value,
                error=f"Invalid transition {from_state.value} -> {to_state.value}",
            )
            self._idempotency_cache[cache_key] = result
            return result

        try:
            if action is not None:
                self._call(action)

            self.state_machine.set_state(plugin_name, to_state)
            self._call_state_hook(resolved_plugin_instance, to_state)
            result = TransitionResult(
                success=True,
                plugin_name=plugin_name,
                from_state=from_state.value,
                to_state=to_state.value,
            )
            self._idempotency_cache[cache_key] = result
            return result
        except Exception as exc:
            logger.error(f"Plugin transition failed for {plugin_name}: {exc}")
            rolled_back = False
            try:
                if rollback_action is not None:
                    self._call(lambda: rollback_action(from_state))
                    rolled_back = True
                elif resolved_plugin_instance is not None and hasattr(resolved_plugin_instance, "rollback"):
                    self._call(
                        lambda err=exc: resolved_plugin_instance.rollback(from_state.value, {"error": str(err)})
                    )
                    rolled_back = True
            except Exception as rollback_error:
                logger.error(f"Rollback failed for {plugin_name}: {rollback_error}")

            self.state_machine.set_state(plugin_name, from_state)
            self._call_error_hook(resolved_plugin_instance, exc, from_state, to_state)

            result = TransitionResult(
                success=False,
                plugin_name=plugin_name,
                from_state=from_state.value,
                to_state=to_state.value,
                rolled_back=rolled_back,
                error=str(exc),
            )
            self._idempotency_cache[cache_key] = result
            return result

    def _resolve_plugin_instance(self, plugin_instance: Any) -> Any:
        if callable(plugin_instance):
            try:
                return plugin_instance()
            except Exception as resolve_error:
                logger.error(f"Failed to resolve plugin instance: {resolve_error}")
                return None
        return plugin_instance

    def _call_state_hook(self, plugin_instance: Any, state: PluginState) -> None:
        if plugin_instance is None:
            return

        hook_name_map = {
            PluginState.REGISTERED: "on_registered",
            PluginState.LOADED: "on_loaded",
            PluginState.ENABLED: "on_enabled",
            PluginState.DISABLED: "on_disabled",
            PluginState.UNLOADED: "on_unloaded",
            PluginState.UPDATING: "on_updating",
            PluginState.ERROR: "on_error_state",
        }

        hook_name = hook_name_map.get(state)
        if hook_name and hasattr(plugin_instance, hook_name):
            self._call(getattr(plugin_instance, hook_name))

    def _call_error_hook(self, plugin_instance: Any, error: Exception, from_state: PluginState, to_state: PluginState) -> None:
        if plugin_instance is None or not hasattr(plugin_instance, "on_error"):
            return
        try:
            self._call(lambda: plugin_instance.on_error(error, from_state.value, to_state.value))
        except Exception as hook_error:
            logger.error(f"Failed to execute on_error hook: {hook_error}")

    def _call(self, callable_obj: Callable[[], Any]) -> Any:
        result = callable_obj()
        if inspect.isawaitable(result):
            return self._run_coroutine(result)
        return result

    def _run_coroutine(self, awaitable: Any) -> Any:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(awaitable)

        result_holder: Dict[str, Any] = {}
        error_holder: Dict[str, BaseException] = {}

        def _runner() -> None:
            new_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(new_loop)
            try:
                result_holder["value"] = new_loop.run_until_complete(awaitable)
            except BaseException as thread_error:
                error_holder["error"] = thread_error
            finally:
                new_loop.close()

        thread = threading.Thread(target=_runner)
        thread.start()
        thread.join()

        if "error" in error_holder:
            raise error_holder["error"]

        if not loop.is_closed() and not loop.is_running():
            return loop.run_until_complete(awaitable)

        return result_holder.get("value")
