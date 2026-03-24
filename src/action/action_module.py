"""ActionModule — predefined action registry for iReDev agents.

Each agent registers named callables that map directly to the predefined
actions in the iReDev paper (Section 4.2). The ActionModule dispatches to
them from inside process(task, in_q, out_q).

Action callable signature (async):
    async def action_fn(
        context:     str,           # ThinkModule context string
        event_value: Any,           # artifact content from MonitorEvent
        task:        Any,           # original Task object from framework
        in_queue:    asyncio.Queue, # human-in-loop input queue
        out_queue:   asyncio.Queue, # human-in-loop output queue
        **kwargs,
    ) -> str

Predefined actions per agent (iReDev paper §4.2):

    InterviewerAgent:
        dialogue_enduser          write_interview_records
        write_url                 dialogue_deployer
        write_oel

    EndUserAgent / DeployerAgent:
        respond                   raise_question
        confirm_or_refine

    AnalystAgent:
        write_system_requirements select_model
        build_model

    ArchivistAgent:
        write_srs

    ReviewerAgent:
        evaluate                  confirm_closure
"""

import asyncio
import logging
from typing import Any, Callable, Coroutine, Dict, List, Optional, Union

logger = logging.getLogger(__name__)

# Type alias for an async action callable
AsyncActionFn = Callable[..., Coroutine[Any, Any, str]]


class ActionModule:
    """Registry and dispatcher for an agent's predefined actions.

    Supports both sync and async callables transparently: sync callables
    are wrapped in asyncio.to_thread() so process() always stays async.

    Usage:
        self.action.register("dialogue_enduser", self._action_dialogue_enduser)
        result = await self.action.dispatch(
            "dialogue_enduser",
            context=ctx,
            event_value=value,
            task=task,
            in_queue=in_q,
            out_queue=out_q,
        )
    """

    def __init__(self) -> None:
        self._registry: Dict[str, Callable] = {}

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, name: str, fn: Callable) -> None:
        """Register a named action callable (sync or async).

        Args:
            name: Unique action identifier.
            fn:   Callable; async preferred; sync is wrapped automatically.
        """
        if name in self._registry:
            logger.warning("[ActionModule] Overwriting action '%s'.", name)
        self._registry[name] = fn
        logger.debug("[ActionModule] registered '%s' (async=%s).", name, asyncio.iscoroutinefunction(fn))

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    async def dispatch(
        self,
        name: str,
        context: str = "",
        event_value: Any = None,
        task: Any = None,
        in_queue: Optional[asyncio.Queue] = None,
        out_queue: Optional[asyncio.Queue] = None,
        **kwargs: Any,
    ) -> str:
        """Execute a registered action by name (always async).

        Args:
            name:        Action identifier.
            context:     Knowledge + memory context from ThinkModule.
            event_value: Artifact content from MonitorEvent.
            task:        Original Task object from AgentCoordinator.
            in_queue:    Human-in-loop input queue (framework-provided).
            out_queue:   Human-in-loop output queue (framework-provided).
            **kwargs:    Extra kwargs forwarded to the callable.

        Returns:
            Action output string.

        Raises:
            KeyError: If action name is not registered.
        """
        if name not in self._registry:
            raise KeyError(
                f"Action '{name}' not registered. Available: {self.available}"
            )

        fn = self._registry[name]
        call_kwargs = dict(
            context=context,
            event_value=event_value,
            task=task,
            in_queue=in_queue,
            out_queue=out_queue,
            **kwargs,
        )

        logger.info("[ActionModule] dispatching '%s'.", name)

        if asyncio.iscoroutinefunction(fn):
            return await fn(**call_kwargs)
        else:
            # Wrap sync callable so it doesn't block the event loop
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, lambda: fn(**call_kwargs))

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def available(self) -> List[str]:
        return list(self._registry.keys())

    def __contains__(self, name: str) -> bool:
        return name in self._registry


# ---------------------------------------------------------------------------
# ActionRouter — maps MonitorEvent.artifact_key → action name
# ---------------------------------------------------------------------------

class ActionRouter:
    """Maps artifact keys (or task phases) to action names.

    A static routing table avoids extra LLM calls for deterministic dispatch.
    Subclass or call add() to extend routing at runtime.

    Example for InterviewerAgent:
        ActionRouter({
            "interview":             "dialogue_enduser",
            "user_modeling":         "write_interview_records",
            "deployment_analysis":   "dialogue_deployer",
        })
    The router checks task_phase first, then artifact_key as fallback.
    """

    def __init__(self, routing_table: Optional[Dict[str, str]] = None) -> None:
        self._table: Dict[str, str] = routing_table or {}

    def route(
        self,
        artifact_key: str,
        is_hitl: bool,
        task_phase: str = "",
    ) -> Optional[str]:
        """Return the action name for a MonitorEvent, or None if unmapped.

        Args:
            artifact_key: MonitorEvent.artifact_key.
            is_hitl:      True → return "__hitl__" sentinel.
            task_phase:   MonitorEvent.task_phase (checked before artifact_key).

        Returns:
            Action name string, "__hitl__" for HITL events, or None.
        """
        if is_hitl:
            return "__hitl__"
        # Phase takes priority over artifact_key (phase is more specific)
        return self._table.get(task_phase) or self._table.get(artifact_key)

    def add(self, key: str, action_name: str) -> None:
        self._table[key] = action_name