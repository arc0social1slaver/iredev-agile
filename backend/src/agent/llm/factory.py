from typing import Any, Dict, Optional

from langchain_core.language_models import BaseChatModel
from langchain_core.embeddings import Embeddings

from .rate_limiter import AdvancedTokenRateLimiter
from .callback_handler import TokenTrackingCallback
from ...config.config_manager import get_raw


class LLMFactory:
    """Creates LangChain chat-model and embeddings instances from config.

    Config loading is fully delegated to ConfigManager (via ``get_raw``).
    All ${ENV_VAR} placeholders in the YAML have already been expanded by
    the time any method here is called.
    """

    # ------------------------------------------------------------------ #
    #  LLM factory                                                         #
    # ------------------------------------------------------------------ #

    @staticmethod
    def create_llm(config: Dict[str, Any]) -> BaseChatModel:
        """Build a LangChain BaseChatModel from a provider config block."""
        from langchain_openai import ChatOpenAI
        from langchain_anthropic import ChatAnthropic
        from langchain_google_genai import ChatGoogleGenerativeAI

        provider = config.get("type", "").lower()
        model = config.get("model")

        if not model:
            raise ValueError("'model' must be specified in the LLM config block.")

        # Resolve rate limits: inline first, then global fallback
        rate_limits: Dict[str, Any] = config.get("rate_limits") or {}
        if not rate_limits:
            try:
                rate_limits = get_raw().get("rate_limits", {}).get(provider, {})
            except Exception:
                pass

        limiter = AdvancedTokenRateLimiter.from_config(
            provider=provider, config=rate_limits
        )
        callback = TokenTrackingCallback(limiter)

        common = {
            "model": model,
            "temperature": config.get("temperature", 0.7),
            "rate_limiter": limiter,
            "callbacks": [callback],
        }

        if provider == "openai":
            return ChatOpenAI(
                api_key=config.get("api_key"),
                base_url=config.get("base_url"),
                **common,
            )

        if provider in ("claude", "anthropic"):
            return ChatAnthropic(
                api_key=config.get("api_key"),
                **common,
            )

        if provider == "gemini":
            return ChatGoogleGenerativeAI(
                model=model,
                google_api_key=config.get("api_key"),
                max_output_tokens=config.get("max_output_tokens"),
                temperature=config.get("temperature", 0.1),
                rate_limiter=limiter,
                callbacks=[callback],
            )

        if provider == "huggingface":
            # Local servers (Ollama) use the OpenAI-compatible wrapper.
            return ChatOpenAI(
                model=model,
                api_key=config.get("api_key"),
                base_url=config.get("api_base") or config.get("base_url"),
                temperature=config.get("temperature", 0.1),
                rate_limiter=limiter,
                callbacks=[callback],
            )

        raise ValueError(f"Unsupported LLM provider: '{provider}'")

    # ------------------------------------------------------------------ #
    #  Embeddings factory                                                  #
    # ------------------------------------------------------------------ #

    @staticmethod
    def create_embeddings(config: Dict[str, Any]) -> Embeddings:
        """Build a LangChain Embeddings instance from an embedding config block."""
        provider = config.get("type", "openai").lower()
        model = config.get("model")

        if not model:
            raise ValueError(
                "knowledge_base.embedding.model must be specified. "
                "Check your config YAML or the default_knowledge_base() in config_manager.py."
            )

        if provider in ("google", "gemini"):
            from langchain_google_genai import GoogleGenerativeAIEmbeddings

            return GoogleGenerativeAIEmbeddings(
                model=model,
                api_key=config.get("api_key"),
            )

        if provider == "openai":
            from langchain_openai import OpenAIEmbeddings

            kwargs: Dict[str, Any] = {
                "model": model,
                "api_key": config.get("api_key"),
                # Ollama and most local servers only accept plain text strings,
                # so disable LangChain's tokenization pre-processing step.
                "check_embedding_ctx_length": False,
            }

            base_url = config.get("base_url")
            if base_url:
                kwargs["base_url"] = base_url

            return OpenAIEmbeddings(**kwargs)

        if provider == "huggingface":
            from langchain_huggingface import HuggingFaceEmbeddings

            return HuggingFaceEmbeddings(model_name=model)

        raise ValueError(f"Unsupported embedding provider: '{provider}'")
