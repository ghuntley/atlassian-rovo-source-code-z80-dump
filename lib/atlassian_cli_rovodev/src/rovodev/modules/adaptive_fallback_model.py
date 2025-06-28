import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from enum import Enum
from typing import Callable

from anthropic import APIConnectionError, APIStatusError, APITimeoutError
from loguru import logger
from pydantic_ai import ModelHTTPError
from pydantic_ai.messages import ModelMessage, ModelResponse
from pydantic_ai.models import Model, ModelRequestParameters, ModelSettings, StreamedResponse
from pydantic_ai.models.fallback import FallbackModel

from nemo.pruners import MidConversationPruner, WorkspaceViewPruner
from rovodev.common.exceptions import RateLimitExceededError, RequestTooLargeError, AIAgentError, UnauthorizedError # Changed RovoDevError


class FallbackOrRetry(Enum):
    """Enum to represent fallback, retry, and prune conditions."""

    FALLBACK = "fallback"
    RETRY = "retry"
    RAISE = "raise"
    PRUNE = "prune"


async def default_fallback_on(exc: Exception) -> FallbackOrRetry:
    """Fallback condition checker to determine if an exception should trigger a fallback.

    Args:
        exc: The exception to check.

    Returns:
        Enum value indicating whether to fallback, retry, prune the messages, or raise an error.
    """
    # Fallback on all 500 errors
    if isinstance(exc, ModelHTTPError) and exc.status_code >= 500:
        logger.bind(role="error", title="Server error").error("\nModel request failed, we'll try again in a moment.\n")
        await asyncio.sleep(10)
        return FallbackOrRetry.FALLBACK
    # Also fallback on per-minute 429s, but not on daily 429s
    if isinstance(exc, ModelHTTPError) and exc.status_code == 429:
        if "DAILY_LIMIT_EXCEEDED" in str(exc.body):
            # Do not retry on daily limits
            return FallbackOrRetry.RAISE
        elif "MINUTE_LIMIT_EXCEEDED" in str(exc.body):
            # Retry on per-minute limits
            retry_in = exc.body.get("retryAfterSeconds", 10)
            logger.bind(role="warning", title="You've reached your minute token limit").warning(
                f"\nWe'll try again in {retry_in} seconds.\n"
            )
            await asyncio.sleep(retry_in + 1)
            return FallbackOrRetry.RETRY
        else:
            # Retry for all other 429 errors
            logger.bind(role="warning", title="Rate limit exceeded").warning(f"\nWe'll try again in 10 seconds.\n")
            await asyncio.sleep(10)
            return FallbackOrRetry.FALLBACK
    if isinstance(exc, ModelHTTPError) and (
        # Standard 413 error for request too large
        exc.status_code == 413
        # This happens when the request input tokens exceed the model's context limit
        or (exc.status_code == 400 and "'statusCode': 413" in str(exc.body))
        # This happens when the request input tokens + max output tokens exceed the model's context limit
        or (exc.status_code == 400 and "exceed context limit" in str(exc.body))
    ):
        logger.bind(role="warning", title="Context limit reached").warning(f"\nRetrying using pruned message history\n")
        return FallbackOrRetry.PRUNE
    # Fallback on Anthropic APIStatusError, APITimeoutError, and APIConnectionError
    if isinstance(exc, (APIStatusError, APITimeoutError, APIConnectionError)):
        await asyncio.sleep(5)
        return FallbackOrRetry.FALLBACK
    return FallbackOrRetry.RAISE


class AdaptiveFallbackModel(FallbackModel):
    """Adaptive fallback model for Nemo."""

    def __init__(
        self,
        default_model: Model,
        *fallback_models: Model,
        fallback_on: Callable[[Exception], bool] | tuple[type[Exception], ...] = default_fallback_on,
        fallback_threshold: int = 3,
        success_preference_factor: int = 1,
        fallback_cycles: int = 1,
    ):
        """Initialize the adaptive fallback model.

        This fallback algorithm work in the following way:
        1. Intialize a "fallback signal" variable to 0.
        2. The default model is tried first and if it fails, the "fallback signal" is incremented by 1.
        3. If the fallback signal reaches the fallback_threshold, it resets to 0 and the next model is tried.
        4. When any model request succeeds, it is preferenced for future requests by:
            a. Moving it to the front of the models list
            b. Setting the fallback signal to: -1 * fallback_threshold * success_preference_factor
        5. If all models fail, we perform the above steps at most fallback_cycles times.
        6. If all models fail after fallback_cycles, a ModelFallbackException is raised.

        Args:
            default_model: The default model to use.
            fallback_models: The fallback models to use.
            fallback_on: A async callable or tuple of exceptions that should trigger a fallback.
            fallback_threshold: Maximum number of retries for each model before falling back.
            success_preference_factor: Factor by which to boost the success rate of the default model.
            fallback_cycles: Number of cycles to try all models before giving up.
        """
        super().__init__(default_model, *fallback_models, fallback_on=fallback_on)
        self.fallback_threshold = fallback_threshold
        self.success_preference_factor = success_preference_factor
        self.fallback_cycles = fallback_cycles
        self.fallback_signal = 0

    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        """Try each model in sequence until one succeeds.

        In case of failure, raise a ModelFallbackException with all exceptions.
        """
        exceptions: list[Exception] = []

        # List of pruners to apply if fallback is triggered. Once we've tried them all, the exception will propagate
        pruners = [MidConversationPruner(), WorkspaceViewPruner(max_workspace_views=0)]

        for _ in range(self.fallback_cycles):
            for model in self.models:
                # Reset fallback signal when switching models
                if self.fallback_signal >= self.fallback_threshold:
                    self.fallback_signal = 0

                while self.fallback_signal < self.fallback_threshold:
                    customized_model_request_parameters = model.customize_request_parameters(model_request_parameters)
                    try:
                        response = await model.request(messages, model_settings, customized_model_request_parameters)
                        self._handle_success(model)
                        self._set_span_attributes(model)
                        return response
                    except Exception as exc:
                        fallback_behavior = await self._fallback_on(exc)
                        exceptions.append(exc)
                        if fallback_behavior == FallbackOrRetry.FALLBACK:
                            self.fallback_signal += 1
                            continue
                        elif fallback_behavior == FallbackOrRetry.RETRY:
                            continue
                        elif fallback_behavior == FallbackOrRetry.PRUNE and pruners:
                            # Prune the messages and retry with the same model
                            # Note that these pruners will not modify the original messages list, but return a new one
                            try:
                                messages = pruners[0](messages)
                                pruners.pop(0)  # Remove the pruner after use
                                continue
                            except Exception:
                                # If pruning fails, raise the original exception
                                pass
                        raise self._process_exception(exc) from exc

        if exceptions:
            raise self._process_exception(exceptions[-1])
        else:
            raise AIAgentError("Failed to generate an LLM response.") # Changed RovoDevError

    @asynccontextmanager
    async def request_stream(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> AsyncIterator[StreamedResponse]:
        """Try each model in sequence until one succeeds using the adaptive fallback algorithm."""
        exceptions: list[Exception] = []

        # List of pruners to apply if fallback is triggered. Once we've tried them all, the exception will propagate
        pruners = [MidConversationPruner(), WorkspaceViewPruner(max_workspace_views=0)]

        for _ in range(self.fallback_cycles):
            for model in self.models:
                # Reset fallback signal when switching models
                if self.fallback_signal >= self.fallback_threshold:
                    self.fallback_signal = 0

                while self.fallback_signal < self.fallback_threshold:
                    customized_model_request_parameters = model.customize_request_parameters(model_request_parameters)
                    async with AsyncExitStack() as stack:
                        try:
                            response = await stack.enter_async_context(
                                model.request_stream(messages, model_settings, customized_model_request_parameters)
                            )
                            self._handle_success(model)
                            self._set_span_attributes(model)
                            yield response
                            return
                        except Exception as exc:
                            fallback_behavior = await self._fallback_on(exc)
                            exceptions.append(exc)
                            if fallback_behavior == FallbackOrRetry.FALLBACK:
                                self.fallback_signal += 1
                                continue
                            elif fallback_behavior == FallbackOrRetry.RETRY:
                                continue
                            elif fallback_behavior == FallbackOrRetry.PRUNE and pruners:
                                # Prune the messages and retry with the same model
                                # Note that these pruners will not modify the original messages list, but return a new one
                                try:
                                    messages = pruners[0](messages)
                                    pruners.pop(0)  # Remove the pruner after use
                                    continue
                                except Exception:
                                    # If pruning fails, raise the original exception
                                    pass
                            raise self._process_exception(exc) from exc

        if exceptions:
            raise self._process_exception(exceptions[-1])
        else:
            raise AIAgentError("Failed to generate an LLM response.") # Changed RovoDevError

    def _handle_success(self, successful_model: Model) -> None:
        """Handle a successful request by moving the model to the front and updating fallback signal."""
        # Move successful model to front of list
        successful_model_index = self.models.index(successful_model)
        self.models = self.models[successful_model_index:] + self.models[:successful_model_index]
        # Set fallback signal to prefer this model
        self.fallback_signal = -1 * self.fallback_threshold * self.success_preference_factor

    def _process_exception(self, exception: Exception) -> AIAgentError: # Changed RovoDevError
        """Process an exception and return an instance of AIAgentError.""" # Changed RovoDevError
        if isinstance(exception, ModelHTTPError):
            if (
                # Standard 413 error for request too large
                exception.status_code == 413
                # This happens when the request input tokens exceed the model's context limit
                or (exception.status_code == 400 and "'statusCode': 413" in str(exception.body))
                # This happens when the request input tokens + max output tokens exceed the model's context limit
                or (exception.status_code == 400 and "exceed context limit" in str(exception.body))
            ):
                return RequestTooLargeError()
            elif exception.status_code == 429:
                payload = exception.body if isinstance(exception.body, dict) else json.loads(exception.body)
                return RateLimitExceededError(payload)
            elif exception.status_code == 401:
                return UnauthorizedError()
            elif exception.status_code == 500:
                return AIAgentError( # Changed RovoDevError
                    title="Internal Server Error",
                    message="An unexpected error occurred while processing your request. Please try again later.",
                )
            elif exception.status_code in [503, 529]:
                return AIAgentError( # Changed RovoDevError
                    title="Service Unavailable",
                    message="The service is currently unavailable. Please try again later.",
                )
        return AIAgentError("Failed to generate an LLM response.") # Changed RovoDevError
