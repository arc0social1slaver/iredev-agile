"""MonitorModule — artifact watcher + task interpreter for iReDev agents.

TWO usage modes (same class):

    Mode A — Task-driven (framework integration):
        Called once per process(task, ...) invocation from AgentCoordinator.
        interpret(task, pool) converts the Task into a MonitorEvent by reading
        the relevant artifact from the pool.

        event = self.monitor.interpret(task, self.artifact_pool)

    Mode B — Poll-driven (standalone / testing):
        Scans the pool continuously; returns the first detected change.

        event = self.monitor.scan(artifact_pool)

Mapping task → artifact (Mode A):
    task.metadata["phase"] is the primary routing key.
    Each agent declares a phase_artifact_map at __init__ time:
        {
            "interview":             "initial_requirements",
            "user_modeling":         "interview_records",
            "deployment_analysis":   "user_requirements_list",
        }
    Fallback when no map entry: task.description is used as event value,
    task.type as artifact_key.

HITL detection (both modes):
    Task-level:  task.type ends with "_correction" / "_review" / "_revision"
                 OR task.metadata["hitl_feedback"] is present.
    Pool-level:  hitl_keys pool entries that appeared/changed since last scan.
"""

import hashlib
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Event
# ---------------------------------------------------------------------------

@dataclass
class MonitorEvent:
    """A change detected by the monitor.

    Attributes:
        artifact_key:   Pool key (or task.type) that triggered this event.
        artifact_value: Current value from the pool (or task.description).
        is_hitl:        True = human-in-the-loop signal; False = artifact change.
        hitl_approved:  Meaningful only when is_hitl=True.
        hitl_feedback:  Human feedback text (when is_hitl=True).
        task_phase:     task.metadata["phase"] for downstream routing context.
    """
    artifact_key: str
    artifact_value: Any
    is_hitl: bool = False
    hitl_approved: bool = True
    hitl_feedback: str = ""
    task_phase: str = ""


# ---------------------------------------------------------------------------
# MonitorModule
# ---------------------------------------------------------------------------

class MonitorModule:
    """Detects relevant changes and converts them into MonitorEvents.

    Args:
        watched_artifacts:  Ordered pool keys to watch (Mode B).
        hitl_keys:          Pool keys that carry HITL signals (Mode B).
        phase_artifact_map: Maps task.metadata["phase"] → artifact pool key (Mode A).
            Example for InterviewerAgent:
                {
                    "interview":           "initial_requirements",
                    "user_modeling":       "interview_records",
                    "deployment_analysis": "user_requirements_list",
                }
    """

    _HITL_TASK_SUFFIXES = ("_correction", "_review", "_revision")
    _HITL_METADATA_KEY  = "hitl_feedback"
    _REJECTION_MARKER   = "__hitl_rejected__"

    def __init__(
        self,
        watched_artifacts: Optional[List[str]] = None,
        hitl_keys: Optional[List[str]] = None,
        phase_artifact_map: Optional[Dict[str, str]] = None,
    ) -> None:
        self._watched:    List[str]       = watched_artifacts or []
        self._hitl_keys:  List[str]       = hitl_keys or []
        self._phase_map:  Dict[str, str]  = phase_artifact_map or {}
        self._last_seen:  Dict[str, str]  = {}  # key → MD5 hash

    # ------------------------------------------------------------------
    # Mode A — called inside process(task, ...)
    # ------------------------------------------------------------------

    def interpret(self, task: Any, artifact_pool: Any) -> Optional[MonitorEvent]:
        """Convert a framework Task into a MonitorEvent.

        Args:
            task:          Task object from AgentCoordinator.
                           Expected attrs: .type (str), .metadata (dict),
                           .description (str).
            artifact_pool: Shared ArtifactPool; must support .get(key).

        Returns:
            MonitorEvent or None if nothing actionable.
        """
        if task is None:
            return None

        task_type: str  = getattr(task, "type", "") or ""
        task_meta: dict = getattr(task, "metadata", {}) or {}
        task_desc: str  = getattr(task, "description", "") or ""
        phase:     str  = task_meta.get("phase", "")

        # 1. HITL detection -----------------------------------------------
        hitl_feedback  = task_meta.get(self._HITL_METADATA_KEY, "")
        is_hitl_suffix = any(task_type.endswith(s) for s in self._HITL_TASK_SUFFIXES)

        if is_hitl_suffix or hitl_feedback:
            approved = str(hitl_feedback).strip() != self._REJECTION_MARKER
            logger.info(
                "[MonitorModule] HITL task: type='%s' approved=%s", task_type, approved
            )
            return MonitorEvent(
                artifact_key=task_type,
                artifact_value=hitl_feedback or task_desc,
                is_hitl=True,
                hitl_approved=approved,
                hitl_feedback=str(hitl_feedback),
                task_phase=phase,
            )

        # 2. Artifact routing ----------------------------------------------
        artifact_key = self._phase_map.get(phase) or task_type
        value = self._pool_get(artifact_pool, artifact_key)

        if value is None:
            # Bootstrap fallback: use task description
            logger.debug(
                "[MonitorModule] pool key '%s' empty — using task.description.",
                artifact_key,
            )
            value = task_desc
            artifact_key = task_type

        if not value:
            return None

        logger.info(
            "[MonitorModule] artifact event: key='%s' phase='%s'",
            artifact_key, phase,
        )
        return MonitorEvent(
            artifact_key=artifact_key,
            artifact_value=value,
            is_hitl=False,
            task_phase=phase,
        )

    # ------------------------------------------------------------------
    # Mode B — polling scan loop
    # ------------------------------------------------------------------

    def scan(self, artifact_pool: Any) -> Optional[MonitorEvent]:
        """Poll the pool once; return first change since last scan.

        Args:
            artifact_pool: Shared ArtifactPool; must support .get(key).

        Returns:
            MonitorEvent or None.
        """
        for key in self._watched:
            value = self._pool_get(artifact_pool, key)
            if value is not None and self._changed(key, value):
                logger.info("[MonitorModule] artifact changed: key='%s'", key)
                return MonitorEvent(artifact_key=key, artifact_value=value)

        for key in self._hitl_keys:
            value = self._pool_get(artifact_pool, key)
            if value is not None and self._changed(key, value):
                approved = str(value).strip() != self._REJECTION_MARKER
                logger.info(
                    "[MonitorModule] HITL signal: key='%s' approved=%s", key, approved
                )
                return MonitorEvent(
                    artifact_key=key,
                    artifact_value=value,
                    is_hitl=True,
                    hitl_approved=approved,
                    hitl_feedback=str(value),
                )

        return None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def reset(self, key: Optional[str] = None) -> None:
        """Clear last-seen state; call after processing to avoid re-trigger."""
        if key is None:
            self._last_seen.clear()
        else:
            self._last_seen.pop(key, None)

    def add_watched(self, key: str) -> None:
        if key not in self._watched:
            self._watched.append(key)

    def add_hitl_key(self, key: str) -> None:
        if key not in self._hitl_keys:
            self._hitl_keys.append(key)

    @property
    def watched_artifacts(self) -> List[str]:
        return list(self._watched)

    @property
    def hitl_keys(self) -> List[str]:
        return list(self._hitl_keys)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _changed(self, key: str, value: Any) -> bool:
        h = self._hash(value)
        if self._last_seen.get(key) != h:
            self._last_seen[key] = h
            return True
        return False

    @staticmethod
    def _pool_get(pool: Any, key: str) -> Optional[Any]:
        try:
            return pool.get(key)
        except Exception as exc:
            logger.debug("[MonitorModule] pool.get('%s') failed: %s", key, exc)
            return None

    @staticmethod
    def _hash(value: Any) -> str:
        return hashlib.md5(str(value).encode("utf-8")).hexdigest()