from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult

from .rate_limiter import AdvancedTokenRateLimiter


class TokenTrackingCallback(BaseCallbackHandler):
    """Updates the rate limiter with actual token usage after each LLM call.

    Handles different key conventions across providers:
      - OpenAI    : llm_output["token_usage"]   -> prompt_tokens / completion_tokens
      - Anthropic : llm_output["usage"]         -> input_tokens  / output_tokens
      - Gemini    : llm_output["usage_metadata"] -> prompt_token_count / candidates_token_count
    """

    def __init__(self, rate_limiter: AdvancedTokenRateLimiter) -> None:
        self.rate_limiter = rate_limiter

    def on_llm_end(self, response: LLMResult, **kwargs) -> None:
        """Extract token usage from the LLM response and record it.

        Args:
            response: The LLMResult returned by LangChain after invocation.
        """
        if not response.llm_output:
            return
        input_tokens, output_tokens = self._extract_tokens(response.llm_output)
        if input_tokens or output_tokens:
            self.rate_limiter.record_request(input_tokens, output_tokens)

    @staticmethod
    def _extract_tokens(llm_output: dict) -> tuple[int, int]:
        """Parse (input_tokens, output_tokens) from any provider's llm_output dict.

        Args:
            llm_output: The llm_output dict from a LangChain LLMResult.

        Returns:
            Tuple of (input_tokens, output_tokens).
        """
        # OpenAI / Anthropic
        usage = llm_output.get("token_usage") or llm_output.get("usage", {})
        if usage:
            input_t = usage.get("prompt_tokens") or usage.get("input_tokens") or 0
            output_t = usage.get("completion_tokens") or usage.get("output_tokens") or 0
            if input_t or output_t:
                return int(input_t), int(output_t)

        # Gemini
        meta = llm_output.get("usage_metadata", {})
        if meta:
            return int(meta.get("prompt_token_count", 0)), int(meta.get("candidates_token_count", 0))

        return 0, 0