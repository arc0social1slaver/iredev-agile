import os
import yaml
from pathlib import Path
from typing import Any, Dict, Optional

from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic
from langchain_google_genai import ChatGoogleGenerativeAI

from .rate_limiter import AdvancedTokenRateLimiter
from .callback_handler import TokenTrackingCallback


class LLMFactory:
    """Creates LangChain chat-model instances from agent_config.yaml."""

    @staticmethod
    def load_config(config_path: Optional[str] = None) -> Dict[str, Any]:
        """Load YAML config and expand ${ENV_VAR} placeholders.

        Resolution order for config_path:
          1. Explicit argument.
          2. <project_root>/config/agent_config.yaml (default).

        ${VAR} placeholders in the YAML are replaced with the corresponding
        environment variable values via ``os.path.expandvars``.  Unset
        variables are left as-is (the string ``${VAR}``), so missing keys
        will surface as obvious values rather than silent None lookups.

        Args:
            config_path: Path to the YAML config file. Uses default if None.

        Returns:
            Parsed config as a dictionary with env-var placeholders expanded.

        Raises:
            FileNotFoundError: If the config file does not exist.
        """
        if config_path is None:
            config_path = str(
                Path(__file__).parent.parent.parent.parent
                / "config"
                / "agent_config.yaml"
            )
        path = Path(config_path)
        if not path.exists():
            raise FileNotFoundError(f"Config not found: {config_path}")

        raw_text = path.read_text(encoding="utf-8")
        # Expand ${VAR} and $VAR placeholders using current environment
        expanded_text = os.path.expandvars(raw_text)
        return yaml.safe_load(expanded_text)

    @staticmethod
    def create_llm(config: Dict[str, Any]) -> BaseChatModel:
        """Build a LangChain BaseChatModel from a provider config block.

        Rate limit resolution order:
          1. Inline 'rate_limits' block inside the LLM config.
          2. Global rate_limits[<provider>] section in the same YAML.

        API key resolution order (per key field):
          1. Value in config (already expanded from ${ENV_VAR} by load_config).
          2. Provider-specific environment variable fallback (so LangChain's
             own env-var auto-detection still works when the field is absent).

        Args:
            config: LLM config dict (the 'llm' block from agent_config.yaml).

        Returns:
            A configured LangChain BaseChatModel instance.

        Raises:
            ValueError: If 'model' is missing or the provider is unsupported.
        """
        provider = config.get("type", "").lower()
        model = config.get("model")
        if not model:
            raise ValueError("'model' must be specified in the LLM config block.")

        # Resolve rate limits: inline first, then global fallback
        rate_limits = config.get("rate_limits") or {}
        if not rate_limits:
            try:
                global_cfg = LLMFactory.load_config()
                rate_limits = global_cfg.get("rate_limits", {}).get(provider, {})
            except FileNotFoundError:
                pass

        limiter = AdvancedTokenRateLimiter.from_config(
            provider=provider, config=rate_limits
        )
        callback = TokenTrackingCallback(limiter)

        # Helper: return the config value if non-empty, else fall back to an
        # env var so that keys omitted from YAML still resolve correctly.
        def _key(config_value: Optional[str], env_var: str) -> Optional[str]:
            v = config_value or ""
            # Treat unexpanded placeholders as missing
            if v and not v.startswith("${"):
                return v
            return os.environ.get(env_var) or None

        common = {
            "model": model,
            "temperature": config.get("temperature", 0.7),
            "rate_limiter": limiter,
            "callbacks": [callback],
        }

        if provider == "openai":
            return ChatOpenAI(
                api_key=_key(config.get("api_key"), "OPENAI_API_KEY"),
                base_url=config.get("base_url") or os.environ.get("OPENAI_BASE_URL"),
                **common,
            )

        if provider in ("claude", "anthropic"):
            return ChatAnthropic(
                api_key=_key(config.get("api_key"), "ANTHROPIC_API_KEY"),
                **common,
            )

        if provider == "gemini":
            return ChatGoogleGenerativeAI(
                model=model,
                google_api_key=_key(config.get("api_key"), "GEMINI_API_KEY"),
                max_output_tokens=config.get("max_output_tokens"),
                temperature=config.get("temperature", 0.1),
                rate_limiter=limiter,
                callbacks=[callback],
            )

        if provider == "huggingface":
            # Local servers (Ollama) use the OpenAI-compatible wrapper.
            return ChatOpenAI(
                model=model,
                api_key=_key(config.get("api_key"), "HUGGINGFACE_API_KEY"),
                base_url=config.get("api_base") or os.environ.get("OLLAMA_BASE_URL"),
                temperature=config.get("temperature", 0.1),
                rate_limiter=limiter,
                callbacks=[callback],
            )

        raise ValueError(f"Unsupported provider: '{provider}'")
