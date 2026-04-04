"""
Configuration management system for iReDev framework.

File responsibilities
---------------------
iredev_config.yaml  (base layer, committed to VCS)
    Framework-level settings that rarely change between deployments:
    agent definitions, knowledge-base topology, human-in-the-loop gates,
    artifact storage, and docstring options.

agent_config.yaml  (override layer, gitignored / user-managed)
    Deployment/environment choices that vary per user or per machine:
    LLM provider & model, API tier rate limits, flow-control tuning,
    and optional Perplexity web-search credentials.

Load order (later layer wins)
------------------------------
  1. iredev_config.yaml  — framework defaults / fallback
  2. agent_config.yaml   — user overrides (priority)

Both files are deep-merged so agent_config only needs to specify the keys
it overrides.  A missing or broken file is treated as {} and the system
always returns something usable.
"""

import os
import re
import logging
import yaml
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Load .env once at import time — must happen before any os.path.expandvars
# ---------------------------------------------------------------------------

try:
    from dotenv import load_dotenv
    load_dotenv(override=False)   # real env vars always win over .env values
    logger.debug("[config_manager] .env loaded.")
except ImportError:
    logger.debug("[config_manager] python-dotenv not installed; skipping .env load.")


# ---------------------------------------------------------------------------
# ConfigurationError
# ---------------------------------------------------------------------------

class ConfigurationError(Exception):
    """Raised for configuration-related errors."""


# ---------------------------------------------------------------------------
# ConfigManager
# ---------------------------------------------------------------------------

class ConfigManager:
    """Loads config by merging two YAML files.

    Layer 1 — ``iredev_config.yaml`` (base, committed to VCS)
        Framework behaviour: agent definitions, knowledge-base topology,
        human-in-the-loop review gates, artifact storage, docstring options.
        Edit this when the framework itself changes.

    Layer 2 — ``agent_config.yaml`` (override, user-managed / gitignored)
        Deployment choices: LLM provider & model, API tier rate limits,
        flow-control tuning, Perplexity credentials.
        Edit this when you switch providers or tune for your API tier.

    Deep-merge rules
    ----------------
    - Dict values are merged key-by-key (layer 2 wins on conflicts).
    - Non-dict values (strings, lists, numbers) are replaced wholesale
      by the layer-2 value.
    - A missing or unparseable file is treated as ``{}``; the system
      always returns something usable.

    Env-var placeholders (``${VAR}``) in both files are expanded before
    parsing.  Unresolved placeholders are replaced with ``None``.
    """

    _AGENT_CANDIDATES: List[str] = [
        "config/agent_config.yaml",
        "agent_config.yaml",
    ]
    _IREDEV_CANDIDATES: List[str] = [
        "config/iredev_config.yaml",
        "iredev_config.yaml",
        os.path.expanduser("~/.iredev/config.yaml"),
    ]

    def __init__(
        self,
        agent_config_path:  Optional[str] = None,
        iredev_config_path: Optional[str] = None,
        # Legacy single-path arg — treated as agent_config_path
        config_path:        Optional[str] = None,
    ) -> None:
        self._agent_path: Optional[str] = (
            agent_config_path or config_path
            or self._find_file(self._AGENT_CANDIDATES)
        )
        self._iredev_path: Optional[str] = (
            iredev_config_path or self._find_file(self._IREDEV_CANDIDATES)
        )
        self._cache: Optional[Dict[str, Any]] = None

    # ------------------------------------------------------------------ #
    #  Path discovery                                                      #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _find_file(candidates: List[str]) -> Optional[str]:
        """Return the first existing path from *candidates*, or ``None``."""
        for path in candidates:
            if os.path.exists(path):
                return path
        return None

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
    config_path:        Optional[str] = None,
    agent_config_path:  Optional[str] = None,
    iredev_config_path: Optional[str] = None,
) -> ConfigManager:
    """Return the global ConfigManager, creating it on first call.

    Passing any path argument always creates a fresh instance (useful during
    initialisation or testing).

    Args:
        config_path:        Legacy single-path arg; treated as agent_config_path.
        agent_config_path:  Explicit path to agent_config.yaml (deployment layer).
        iredev_config_path: Explicit path to iredev_config.yaml (framework layer).

    Returns:
        The global ConfigManager instance.
    """
    global _config_manager
    if _config_manager is None or any(
        p is not None for p in (config_path, agent_config_path, iredev_config_path)
    ):
        _config_manager = ConfigManager(
            config_path=config_path,
            agent_config_path=agent_config_path,
            iredev_config_path=iredev_config_path,
        )
    return _config_manager


def get_config(
    config_path:        Optional[str] = None,
    agent_config_path:  Optional[str] = None,
    iredev_config_path: Optional[str] = None,
    force_reload:       bool = False,
) -> Dict[str, Any]:
    """Return the merged YAML config as a plain dict with all ${ENV_VAR} expanded.

    Merges ``iredev_config.yaml`` (framework layer) with ``agent_config.yaml``
    (deployment override layer).  Either file failing to load is treated as an
    empty dict so the system always returns something usable.

    Args:
        config_path:        Legacy single-path arg; treated as agent_config_path.
        agent_config_path:  Explicit path to agent_config.yaml.
        iredev_config_path: Explicit path to iredev_config.yaml.
        force_reload:       Re-read both files even if already cached.

    Returns:
        Deep-merged YAML dict (empty dict if both files are unavailable).
    """
    return get_config_manager(
        config_path=config_path,
        agent_config_path=agent_config_path,
        iredev_config_path=iredev_config_path,
    ).get_raw(force_reload=force_reload)