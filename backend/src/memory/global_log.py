import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


class GlobalConversationLog:
    """Records every agent message in a single append-only log.

    Purpose: human inspection and debugging only.
    Not used for agent reasoning — call export() to write to file.

    Format per entry:
        {
            "ts":      ISO-8601 timestamp,
            "agent":   agent name,
            "role":    "user" | "assistant" | "system",
            "content": message text,
            "meta":    optional dict (e.g. pr_id, sprint_id)
        }
    """

    def __init__(self) -> None:
        self._log: List[Dict[str, Any]] = []

    def record(
        self,
        agent: str,
        role: str,
        content: str,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Append one message to the log.

        Args:
            agent: Agent display name.
            role: 'user', 'assistant', or 'system'.
            content: Full message text.
            meta: Optional key-value metadata (e.g. {'pr_id': '42'}).
        """
        self._log.append(
            {
                "ts": datetime.now(timezone.utc).isoformat(),
                "agent": agent,
                "role": role,
                "content": content,
                "meta": meta or {},
            }
        )

    def export(self, path: str, fmt: str = "json") -> None:
        """Write the full log to a file.

        Args:
            path: Output file path.
            fmt: 'json' (structured) or 'text' (human-readable).
        """
        output = Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)

        if fmt == "json":
            output.write_text(json.dumps(self._log, indent=2, ensure_ascii=False))
        else:
            lines = []
            for e in self._log:
                meta_str = f"  [{e['meta']}]" if e["meta"] else ""
                lines.append(
                    f"[{e['ts']}] {e['agent']} / {e['role']}{meta_str}\n"
                    f"  {e['content']}\n"
                )
            output.write_text("\n".join(lines))

    def as_list(self) -> List[Dict[str, Any]]:
        """Return a shallow copy of the log list.

        Returns:
            List of log entry dicts.
        """
        return list(self._log)

    def clear(self) -> None:
        """Wipe the in-memory log."""
        self._log.clear()