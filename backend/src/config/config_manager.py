"""
config_manager.py — single config hub for iReDev.

Responsibilities
----------------
1. Load the .env file into the process environment exactly once at import time.
2. Read agent_config.yaml and expand ${ENV_VAR} placeholders.
3. Provide sensible defaults for knowledge_base (including embedding) so the
   system works out-of-the-box when the YAML block is absent or incomplete.
4. Expose three public functions for other modules:

   get_raw(config_path, force_reload)  -> Dict[str, Any]
       Expanded YAML as a plain dict. Used by LLMFactory and BaseAgent.

   get_config(force_reload)            -> iReDevConfig
       Typed wrapper with defaults applied. Used by KnowledgeModule.

   get_config_manager(config_path)     -> ConfigManager
       Access / create the process-level singleton.

5. Export KnowledgeType enum used by KnowledgeModule.
"""

import os
import re
import logging
import yaml
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Optional

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
# KnowledgeType — exported for knowledge_module.py
# ---------------------------------------------------------------------------

class KnowledgeType(Enum):
    """Types of knowledge files recognised by KnowledgeModule."""
    DOMAIN_KNOWLEDGE = "domain_knowledge"
    METHODOLOGY      = "methodology"
    STANDARDS        = "standards"
    TEMPLATES        = "templates"
    STRATEGIES       = "strategies"


# ---------------------------------------------------------------------------
# Typed config — only the slice KnowledgeModule actually reads
# ---------------------------------------------------------------------------

@dataclass
class iReDevConfig:
    """Typed view over the raw YAML with defaults applied."""
    knowledge_base: Dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Default knowledge_base block
    # ------------------------------------------------------------------

    @staticmethod
    def default_knowledge_base() -> Dict[str, Any]:
        """Return a complete knowledge_base config with sensible defaults.

        Embedding defaults to the OpenAI-compatible Ollama endpoint so the
        system works with a local model out of the box.  Override any key in
        the YAML knowledge_base block to customise.

        Env vars consulted (loaded from .env by the time this runs):
          OLLAMA_BASE_URL   — Ollama API base  (default: http://localhost:11434/v1)
          OPENAI_API_KEY    — used when type=openai pointing at OpenAI cloud
          OPENAI_BASE_URL   — alternative OpenAI-compatible base URL
        """
        return {
            # Knowledge file paths (resolved relative to project root)
            "base_path":              "knowledge",
            "domain_knowledge_path":  "knowledge/domains",
            "methodology_path":       "knowledge/methodologies",
            "standards_path":         "knowledge/standards",
            "templates_path":         "knowledge/templates",
            "strategies_path":        "knowledge/strategies",
            # Chunking
            "chunk_size":    800,
            "chunk_overlap": 100,
            # Vector store
            "collection_name": "iredev_knowledge",
            # Embedding — Ollama local by default; override in YAML for cloud
            "embedding": {
                "type":     "openai",            # openai-compatible protocol
                "model":    "nomic-embed-text",  # default local model
                "api_key":  "EMPTY",             # Ollama ignores the key
                "base_url": os.environ.get(
                    "OLLAMA_BASE_URL", "http://localhost:11434/v1"
                ),
            },
        }


# ---------------------------------------------------------------------------
# ConfigurationError
# ---------------------------------------------------------------------------

class ConfigurationError(Exception):
    """Raised for configuration-related errors."""


# ---------------------------------------------------------------------------
# ConfigManager
# ---------------------------------------------------------------------------

class ConfigManager:
    """Reads agent_config.yaml, expands env-var placeholders, caches results."""

    def __init__(self, config_path: Optional[str] = None) -> None:
        self.config_path: str = config_path or self._find_config_file()
        self._raw_cache:  Optional[Dict[str, Any]] = None
        self._config:     Optional[iReDevConfig]   = None

    # ------------------------------------------------------------------ #
    #  Path discovery                                                      #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _find_config_file() -> str:
        candidates = [
            "config/iredev_config.yaml",
            "config/agent_config.yaml",
            "iredev_config.yaml",
            os.path.expanduser("~/.iredev/config.yaml"),
        ]
        for path in candidates:
            if os.path.exists(path):
                return path
        return "config/iredev_config.yaml"

    # ------------------------------------------------------------------ #
    #  Raw YAML — with env-var expansion                                   #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _read_and_expand(path: str) -> Dict[str, Any]:
        """Read *path*, substitute ${VAR}/$VAR placeholders, parse YAML.

        Unset variables are left as the literal string ``${VAR}`` so missing
        keys surface as obvious sentinel values rather than silent None lookups.

        Args:
            path: Path to the YAML config file.

        Returns:
            Parsed dict with all environment-variable placeholders expanded.

        Raises:
            FileNotFoundError: If *path* does not exist.
        """
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"Config not found: {path}")
        raw_text      = p.read_text(encoding="utf-8")
        expanded_text = os.path.expandvars(raw_text)
        return yaml.safe_load(expanded_text) or {}

    def get_raw(self, force_reload: bool = False) -> Dict[str, Any]:
        """Return the YAML config as a plain dict with env vars expanded.

        The result is cached. Other modules (LLMFactory, BaseAgent) call this
        to access ``llm``, ``agent_llms``, ``rate_limits``, ``agents``, etc.

        Args:
            force_reload: Discard cached result and re-read from disk.

        Returns:
            Expanded YAML dict (empty dict when the file does not exist).
        """
        if self._raw_cache is None or force_reload:
            try:
                self._raw_cache = self._read_and_expand(self.config_path)
            except FileNotFoundError:
                logger.warning(
                    "[config_manager] Config not found at '%s'. Using empty dict.",
                    self.config_path,
                )
                self._raw_cache = {}
        return self._raw_cache

    # ------------------------------------------------------------------ #
    #  Typed config — defaults merged with YAML values                     #
    # ------------------------------------------------------------------ #

    def load_config(self, force_reload: bool = False) -> iReDevConfig:
        """Return a typed iReDevConfig with defaults applied.

        Merge strategy: defaults first, then YAML values override them.
        Nested dicts (e.g. ``embedding``) are merged key-by-key so a partial
        YAML block only overrides the keys it specifies.

        Args:
            force_reload: Re-read the file even if already cached.

        Returns:
            iReDevConfig with knowledge_base fully populated.
        """
        if self._config is not None and not force_reload:
            return self._config

        raw = self.get_raw(force_reload=force_reload)

        # Start from defaults, then let YAML override key-by-key
        kb = iReDevConfig.default_knowledge_base()
        yaml_kb = raw.get("knowledge_base", {})

        # Merge embedding sub-dict separately so a partial override works
        if "embedding" in yaml_kb:
            kb["embedding"] = {**kb["embedding"], **yaml_kb.pop("embedding")}

        kb.update(yaml_kb)

        self._config = iReDevConfig(knowledge_base=kb)
        return self._config

    @staticmethod
    def _clean_unexpanded_vars(data: Any) -> Any:
        if isinstance(data, dict):
            return {k: ConfigManager._clean_unexpanded_vars(v) for k, v in data.items()}
        elif isinstance(data, list):
            return [ConfigManager._clean_unexpanded_vars(v) for v in data]
        elif isinstance(data, str) and re.match(r"^\$\{.*\}$", data.strip()):
            return None
        return data

    @staticmethod
    def _read_and_expand(path: str) -> Dict[str, Any]:
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"Config not found: {path}")

        raw_text = p.read_text(encoding="utf-8")
        expanded_text = os.path.expandvars(raw_text)

        raw_dict = yaml.safe_load(expanded_text) or {}

        return ConfigManager._clean_unexpanded_vars(raw_dict)


# ---------------------------------------------------------------------------
# Process-level singleton + public API
# ---------------------------------------------------------------------------

_config_manager: Optional[ConfigManager] = None


def get_config_manager(config_path: Optional[str] = None) -> ConfigManager:
    """Return the global ConfigManager, creating it on first call.

    Passing *config_path* always creates a fresh instance (useful during
    initialisation or testing).

    Args:
        config_path: Optional explicit path to the YAML config file.

    Returns:
        The global ConfigManager instance.
    """
    global _config_manager
    if _config_manager is None or config_path is not None:
        _config_manager = ConfigManager(config_path)
    return _config_manager


def get_raw(
    config_path: Optional[str] = None,
    force_reload: bool = False,
) -> Dict[str, Any]:
    """Return the YAML config as a plain dict with all ${ENV_VAR} expanded.

    Primary entry point for modules that need raw config values (LLMFactory,
    BaseAgent, …). Env vars are loaded from .env before the first expansion
    because load_dotenv() is called at module import time above.

    Args:
        config_path: Optional path to the YAML file.
        force_reload: Re-read the file even if already cached.

    Returns:
        Expanded YAML dict (empty dict if the file does not exist).
    """
    return get_config_manager(config_path).get_raw(force_reload=force_reload)


def get_config(force_reload: bool = False) -> iReDevConfig:
    """Return the typed iReDevConfig with defaults applied.

    Args:
        force_reload: Force re-read from disk.

    Returns:
        iReDevConfig instance.
    """
    return get_config_manager().load_config(force_reload)
