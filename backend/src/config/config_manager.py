"""Configuration management system for iReDev framework."""

import os
import re
import logging
import yaml
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

try:
    from dotenv import load_dotenv
    load_dotenv(override=False)   # real env vars always win over .env values
    logger.debug("[config_manager] .env loaded.")
except ImportError:
    logger.debug("[config_manager] python-dotenv not installed; skipping .env load.")


class ConfigManager:
    """Loads config by merging two YAML files."""

    def __init__(
        self,
        iredev_config_path: Optional[str] = None,
        agent_config_path:  Optional[str] = None,
    ) -> None:
        self._agent_path: str = iredev_config_path or "config/agent_config.yaml"
        self._iredev_path: str = agent_config_path or "config/iredev_config.yaml"
        self._cache: Optional[Dict[str, Any]] = None


    # ------------------------------------------------------------------ #
    #  YAML helpers                                                        #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _clean_unexpanded_vars(data: Any) -> Any:
        """Replace unresolved ``${VAR}`` placeholders with ``None``."""
        if isinstance(data, dict):
            return {k: ConfigManager._clean_unexpanded_vars(v) for k, v in data.items()}
        if isinstance(data, list):
            return [ConfigManager._clean_unexpanded_vars(v) for v in data]
        if isinstance(data, str) and re.match(r"^\$\{.*\}$", data.strip()):
            return None
        return data

    @staticmethod
    def _read_and_expand(path: str) -> Dict[str, Any]:
        """Read *path*, expand ``${VAR}`` placeholders, parse YAML.

        Args:
            path: Path to the YAML file.

        Returns:
            Parsed dict with env-var placeholders expanded and unresolved
            placeholders replaced with ``None``.

        Raises:
            FileNotFoundError: If *path* does not exist.
            yaml.YAMLError: If the file cannot be parsed.
        """
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"Config not found: {path}")
        raw_text      = p.read_text(encoding="utf-8")
        expanded_text = os.path.expandvars(raw_text)
        raw_dict      = yaml.safe_load(expanded_text) or {}
        return ConfigManager._clean_unexpanded_vars(raw_dict)

    @staticmethod
    def _try_load(path: Optional[str], label: str) -> Dict[str, Any]:
        """Attempt to load *path*; return ``{}`` and log a warning on failure."""
        if not path:
            logger.debug("[config_manager] No %s found; skipping.", label)
            return {}
        try:
            data = ConfigManager._read_and_expand(path)
            logger.debug("[config_manager] Loaded %s from '%s'.", label, path)
            return data
        except FileNotFoundError:
            logger.warning(
                "[config_manager] %s not found at '%s'; skipping.", label, path
            )
        except yaml.YAMLError as exc:
            logger.warning(
                "[config_manager] %s at '%s' is invalid YAML (%s); falling back.",
                label, path, exc,
            )
        except Exception as exc:  # pragma: no cover
            logger.warning(
                "[config_manager] Failed to load %s at '%s': %s; falling back.",
                label, path, exc,
            )
        return {}

    # ------------------------------------------------------------------ #
    #  Deep merge                                                          #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
        """Recursively merge *override* into *base* (non-destructive).

        Dict values are merged key-by-key; all other types are replaced
        wholesale by the override value.

        Args:
            base:     Framework config layer (iredev_config.yaml).
            override: User/deployment config layer (agent_config.yaml).

        Returns:
            New merged dict — neither input is mutated.
        """
        result = dict(base)
        for key, override_val in override.items():
            base_val = result.get(key)
            if isinstance(base_val, dict) and isinstance(override_val, dict):
                result[key] = ConfigManager._deep_merge(base_val, override_val)
            else:
                result[key] = override_val
        return result

    # ------------------------------------------------------------------ #
    #  Public API                                                          #
    # ------------------------------------------------------------------ #

    def get_raw(self, force_reload: bool = False) -> Dict[str, Any]:
        """Return the merged config as a plain dict with env vars expanded.

        Load order:
          1. ``iredev_config.yaml`` — framework layer (base).
          2. ``agent_config.yaml``  — deployment layer (priority override).

        Args:
            force_reload: Discard cached result and re-read both files.

        Returns:
            Deep-merged YAML dict (empty dict if both files are unavailable).
        """
        if self._cache is not None and not force_reload:
            return self._cache

        base     = self._try_load(self._iredev_path, "iredev_config (framework base)")
        override = self._try_load(self._agent_path,  "agent_config (deployment override)")

        if not base and not override:
            logger.warning(
                "[config_manager] Neither iredev_config nor agent_config "
                "could be loaded. Using empty config."
            )

        self._cache = self._deep_merge(base, override)
        return self._cache


# ---------------------------------------------------------------------------
# Process-level singleton + public helpers
# ---------------------------------------------------------------------------

_config_manager: Optional[ConfigManager] = None


def get_config_manager(
    agent_config_path:  Optional[str] = None,
    iredev_config_path: Optional[str] = None,
) -> ConfigManager:
    """Return the global ConfigManager, creating it on first call.

    Passing any path argument always creates a fresh instance (useful during
    initialization or testing).

    Args:
        agent_config_path:  Explicit path to agent_config.yaml (deployment layer).
        iredev_config_path: Explicit path to iredev_config.yaml (framework layer).

    Returns:
        The global ConfigManager instance.
    """
    global _config_manager
    if _config_manager is None or any(
        p is not None for p in (agent_config_path, iredev_config_path)
    ):
        _config_manager = ConfigManager(
            agent_config_path=agent_config_path,
            iredev_config_path=iredev_config_path,
        )
    return _config_manager


def get_config(
    agent_config_path:  Optional[str] = None,
    iredev_config_path: Optional[str] = None,
    force_reload:       bool = False,
) -> Dict[str, Any]:
    """Return the final config dict"""
    return get_config_manager(
        agent_config_path=agent_config_path,
        iredev_config_path=iredev_config_path,
    ).get_raw(force_reload=force_reload)