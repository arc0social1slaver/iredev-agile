import time
import threading
import logging
from typing import Any, Dict, Optional
from collections import deque
from langchain_core.rate_limiters import BaseRateLimiter

logger = logging.getLogger("AdvancedTokenRateLimiter")


class AdvancedTokenRateLimiter(BaseRateLimiter):
    """LangChain-compatible rate limiter with sliding-window token tracking and cost calculation."""

    def __init__(
        self,
        provider: str,
        requests_per_minute: int,
        input_tokens_per_minute: int,
        output_tokens_per_minute: int,
        input_token_price_per_million: float,
        output_token_price_per_million: float,
        buffer_percentage: float = 0.1,
    ):
        self.provider = provider
        self.requests_per_minute = requests_per_minute * (1 - buffer_percentage)
        self.input_tokens_per_minute = input_tokens_per_minute * (1 - buffer_percentage)
        self.output_tokens_per_minute = output_tokens_per_minute * (
            1 - buffer_percentage
        )

        self.input_token_price = input_token_price_per_million / 1_000_000
        self.output_token_price = output_token_price_per_million / 1_000_000

        self.request_timestamps: deque = deque()
        self.input_token_usage: deque = deque()
        self.output_token_usage: deque = deque()

        self.total_requests: int = 0
        self.total_input_tokens: int = 0
        self.total_output_tokens: int = 0
        self.total_cost: float = 0.0

        self._lock = threading.Lock()

    # ------------------------------------------------------------------ #
    #  Factory                                                             #
    # ------------------------------------------------------------------ #

    @classmethod
    def from_config(
        cls, provider: str, config: Dict[str, Any]
    ) -> "AdvancedTokenRateLimiter":
        """Instantiate from a provider config dict (e.g. from agent_config.yaml).

        Args:
            provider: Provider name (e.g. 'openai', 'claude').
            config: Dict with rate limit keys for the provider.

        Returns:
            A configured AdvancedTokenRateLimiter instance.
        """
        return cls(
            provider=provider,
            requests_per_minute=config.get("requests_per_minute", 60),
            input_tokens_per_minute=config.get("input_tokens_per_minute", 100_000),
            output_tokens_per_minute=config.get("output_tokens_per_minute", 50_000),
            input_token_price_per_million=config.get(
                "input_token_price_per_million", 0.0
            ),
            output_token_price_per_million=config.get(
                "output_token_price_per_million", 0.0
            ),
        )

    # ------------------------------------------------------------------ #
    #  BaseRateLimiter interface                                           #
    # ------------------------------------------------------------------ #

    def acquire(self, *, blocking: bool = True) -> bool:
        """Check or wait for request capacity (called by LangChain before each invocation).

        Args:
            blocking: If False, return immediately without waiting.

        Returns:
            True when the request may proceed.
        """
        if not blocking:
            return self._can_proceed(0, 0)
        self._wait(input_tokens=0, estimated_output_tokens=0)
        return True

    async def aacquire(self, *, blocking: bool = True) -> bool:
        """Async version of acquire.

        Args:
            blocking: If False, return immediately without waiting.

        Returns:
            True when the request may proceed.
        """
        return self.acquire(blocking=blocking)

    # ------------------------------------------------------------------ #
    #  Public helpers                                                      #
    # ------------------------------------------------------------------ #

    def wait_if_needed(
        self, input_tokens: int, estimated_output_tokens: Optional[int] = None
    ) -> None:
        """
        Check if we're about to exceed rate limits and wait if necessary.
        This improved version uses a while loop instead of recursion to
        avoid potential infinite waiting scenarios.
        Args:
            input_tokens: Number of input tokens for the upcoming request
            estimated_output_tokens: Estimated number of output tokens
        """
        if estimated_output_tokens is None:
            estimated_output_tokens = input_tokens // 2

        self._wait(input_tokens, estimated_output_tokens)

    def record_request(self, input_tokens: int, output_tokens: int) -> None:
        """Record actual token usage after a completed request.

        Args:
            input_tokens: Actual input tokens consumed.
            output_tokens: Actual output tokens generated.
        """
        with self._lock:
            now = time.time()
            self.request_timestamps.append(now)
            self.input_token_usage.append((now, input_tokens))
            self.output_token_usage.append((now, output_tokens))

            self.total_requests += 1
            self.total_input_tokens += input_tokens
            self.total_output_tokens += output_tokens

            cost = (input_tokens * self.input_token_price) + (
                output_tokens * self.output_token_price
            )
            self.total_cost += cost

            logger.info(
                f"[{self.provider}] req={self.total_requests} "
                f"in={input_tokens} out={output_tokens} "
                f"cost=${cost:.6f} total=${self.total_cost:.4f}"
            )

    # ------------------------------------------------------------------ #
    #  Internal                                                          #
    # ------------------------------------------------------------------ #

    def _clean_old_entries(self, now: float) -> None:
        cutoff = now - 60.0
        while self.request_timestamps and self.request_timestamps[0] < cutoff:
            self.request_timestamps.popleft()
        while self.input_token_usage and self.input_token_usage[0][0] < cutoff:
            self.input_token_usage.popleft()
        while self.output_token_usage and self.output_token_usage[0][0] < cutoff:
            self.output_token_usage.popleft()

    def _window_sum(self, queue: deque) -> int:
        return sum(count for _, count in queue)

    def _can_proceed(self, in_tk: int, out_tk: int) -> bool:
        now = time.time()
        self._clean_old_entries(now)
        return (
            len(self.request_timestamps) + 1 <= self.requests_per_minute
            and self._window_sum(self.input_token_usage) + in_tk
            <= self.input_tokens_per_minute
            and self._window_sum(self.output_token_usage) + out_tk
            <= self.output_tokens_per_minute
        )

    def _wait(self, input_tokens: int, estimated_output_tokens: int) -> None:
        with self._lock:
            if (
                input_tokens > self.input_tokens_per_minute
                or estimated_output_tokens > self.output_tokens_per_minute
            ):
                logger.warning(
                    f"[{self.provider}] Request uses more tokens ({input_tokens} in / {estimated_output_tokens} out) "
                    f"than the configured per-minute capacity. This request may never succeed."
                )

            while True:
                now = time.time()
                self._clean_old_entries(now)

                current_requests = len(self.request_timestamps)
                current_input_tokens = self._window_sum(self.input_token_usage)
                current_output_tokens = self._window_sum(self.output_token_usage)

                if (
                    (current_requests + 1) <= self.requests_per_minute
                    and (current_input_tokens + input_tokens)
                    <= self.input_tokens_per_minute
                    and (current_output_tokens + estimated_output_tokens)
                    <= self.output_tokens_per_minute
                ):
                    break

                wait_time = 0.0
                if self.request_timestamps:
                    wait_time = max(
                        wait_time, 60.0 - (now - self.request_timestamps[0])
                    )
                if self.input_token_usage:
                    wait_time = max(
                        wait_time, 60.0 - (now - self.input_token_usage[0][0])
                    )
                if self.output_token_usage:
                    wait_time = max(
                        wait_time, 60.0 - (now - self.output_token_usage[0][0])
                    )

                if wait_time <= 0:
                    logger.warning(
                        f"[{self.provider}] Waiting cannot reduce usage enough to allow this request; "
                        "request exceeds per-minute capacity or usage remains too high."
                    )
                    break

                logger.info(
                    f"[{self.provider}] Rate limit approaching. Waiting {wait_time:.2f} seconds..."
                )
                time.sleep(wait_time)
