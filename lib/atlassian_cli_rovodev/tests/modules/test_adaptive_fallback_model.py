from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic_ai import ModelHTTPError
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, UserPromptPart
from pydantic_ai.models import Model, ModelRequestParameters

from rovodev.common.exceptions import RequestTooLargeError, AIAgentError # Changed RovoDevError
from rovodev.modules.adaptive_fallback_model import AdaptiveFallbackModel, FallbackOrRetry, default_fallback_on


@pytest.fixture
def mock_model():
    model = MagicMock(spec=Model)
    model.request = AsyncMock()
    model.customize_request_parameters = lambda x: x
    with pytest.MonkeyPatch().context() as m:
        m.setattr("asyncio.sleep", AsyncMock())
        yield model


@pytest.fixture
def mock_response():
    return ModelResponse(parts=[TextPart(content="test response")])


@pytest.mark.asyncio
async def test_successful_request(mock_model, mock_response):
    """Test that a successful request works with the default model."""
    mock_model.request.return_value = mock_response
    model = AdaptiveFallbackModel(mock_model)

    response = await model.request(
        messages=[ModelRequest(parts=[UserPromptPart(content="test")])],  # type: ignore
        model_settings=None,
        model_request_parameters=ModelRequestParameters(),
    )

    assert response == mock_response
    assert model.fallback_signal < 0  # Success preference applied


@pytest.mark.asyncio
async def test_fallback_behavior(mock_model):
    """Test that fallback works when the default model fails."""
    failing_model = MagicMock(spec=Model)
    failing_model.request = AsyncMock(side_effect=ModelHTTPError(status_code=500, model_name="failing-model"))
    failing_model.customize_request_parameters = lambda x: x

    mock_model.request.return_value = ModelResponse(parts=[TextPart(content="fallback response")])

    model = AdaptiveFallbackModel(failing_model, mock_model, fallback_threshold=1)

    response = await model.request(
        messages=[ModelRequest(parts=[UserPromptPart(content="test")])],
        model_settings=None,
        model_request_parameters=ModelRequestParameters(),
    )

    assert response.parts[0].content == "fallback response"  # type: ignore
    assert model.models[0] == mock_model  # Successful model moved to front


@pytest.mark.asyncio
async def test_fallback_threshold(mock_model):
    """Test that fallback threshold controls when to switch models."""
    failing_model = MagicMock(spec=Model)
    failing_model.request = AsyncMock(side_effect=ModelHTTPError(status_code=500, model_name="failing-model"))
    failing_model.customize_request_parameters = lambda x: x

    mock_model.request.return_value = ModelResponse(parts=[TextPart(content="fallback response")])

    model = AdaptiveFallbackModel(failing_model, mock_model, fallback_threshold=2)

    # First request should try failing_model twice before falling back to mock_model
    response = await model.request(
        messages=[ModelRequest(parts=[UserPromptPart(content="test")])],
        model_settings=None,
        model_request_parameters=ModelRequestParameters(),
    )

    # Verify the failing model was tried twice before fallback
    assert failing_model.request.call_count == 2
    assert mock_model.request.call_count == 1
    assert response.parts[0].content == "fallback response"  # type: ignore
    assert model.models[0] == mock_model  # Successful model should be moved to front


@pytest.mark.asyncio
async def test_all_models_fail(mock_model):
    """Test behavior when all models fail."""
    failing_model1 = MagicMock(spec=Model)
    failing_model1.request = AsyncMock(side_effect=ModelHTTPError(status_code=500, model_name="failing-model"))
    failing_model1.customize_request_parameters = lambda x: x

    failing_model2 = MagicMock(spec=Model)
    failing_model2.request = AsyncMock(side_effect=ModelHTTPError(status_code=500, model_name="failing-model"))
    failing_model2.customize_request_parameters = lambda x: x

    model = AdaptiveFallbackModel(
        failing_model1,
        failing_model2,
        fallback_threshold=1,
        fallback_cycles=2,
    )

    with pytest.raises(AIAgentError) as exc_info: # Changed RovoDevError
        await model.request(
            messages=[ModelRequest(parts=[UserPromptPart(content="test")])],
            model_settings=None,
            model_request_parameters=ModelRequestParameters(),
        )

    assert "An unexpected error occurred while processing your request. Please try again later." in str(exc_info.value)


@pytest.mark.asyncio
async def test_success_preference_factor(mock_model, mock_response):
    """Test that success preference factor affects fallback signal."""
    mock_model.request.return_value = mock_response
    model = AdaptiveFallbackModel(
        mock_model,
        success_preference_factor=2,
        fallback_threshold=1,
    )

    await model.request(
        messages=[ModelRequest(parts=[UserPromptPart(content="test")])],
        model_settings=None,
        model_request_parameters=ModelRequestParameters(),
    )

    assert model.fallback_signal == -2  # -1 * threshold * preference_factor


@pytest.mark.asyncio
async def test_rate_limit_error_message(mock_model):
    """Test that rate limit errors produce the correct message."""
    failing_model = MagicMock(spec=Model)
    failing_model.request = AsyncMock(side_effect=ModelHTTPError(status_code=429, model_name="failing-model", body={}))
    failing_model.customize_request_parameters = lambda x: x

    model = AdaptiveFallbackModel(failing_model)

    with pytest.raises(AIAgentError) as exc_info: # Changed RovoDevError
        await model.request(
            messages=[ModelRequest(parts=[UserPromptPart(content="test")])],
            model_settings=None,
            model_request_parameters=ModelRequestParameters(),
        )

    assert "You have exceeded" in str(exc_info.value)


@pytest.mark.asyncio
async def test_request_too_large_error_triggers_pruning(mock_model):
    """Test that request too large errors trigger message pruning."""
    failing_model = MagicMock(spec=Model)
    # First call fails with 413, second call (with pruned messages) succeeds
    failing_model.request = AsyncMock(
        side_effect=[
            ModelHTTPError(status_code=400, model_name="failing-model", body={"statusCode": 413}),
            ModelResponse(parts=[TextPart(content="success after pruning")]),
        ]
    )
    failing_model.customize_request_parameters = lambda x: x

    model = AdaptiveFallbackModel(failing_model)

    # Create a longer message history that would benefit from pruning
    messages = [
        ModelRequest(parts=[UserPromptPart(content="First message")]),
        ModelResponse(parts=[TextPart(content="First response")]),
        ModelRequest(parts=[UserPromptPart(content="Second message")]),
        ModelResponse(parts=[TextPart(content="Second response")]),
        ModelRequest(parts=[UserPromptPart(content="Third message")]),
        ModelResponse(parts=[TextPart(content="Third response")]),
        ModelRequest(parts=[UserPromptPart(content="Final message")]),
    ]

    response = await model.request(
        messages=messages,
        model_settings=None,
        model_request_parameters=ModelRequestParameters(),
    )

    # Should succeed after pruning
    assert response.parts[0].content == "success after pruning"  # type: ignore
    # Should have been called twice (once failed, once succeeded with pruned messages)
    assert failing_model.request.call_count == 2


@pytest.mark.asyncio
async def test_standard_413_error_triggers_pruning(mock_model):
    """Test that standard 413 errors trigger message pruning."""
    failing_model = MagicMock(spec=Model)
    failing_model.request = AsyncMock(
        side_effect=[
            ModelHTTPError(status_code=413, model_name="failing-model", body="Request Entity Too Large"),
            ModelResponse(parts=[TextPart(content="success after pruning")]),
        ]
    )
    failing_model.customize_request_parameters = lambda x: x

    model = AdaptiveFallbackModel(failing_model)

    response = await model.request(
        messages=[ModelRequest(parts=[UserPromptPart(content="test")])],
        model_settings=None,
        model_request_parameters=ModelRequestParameters(),
    )

    assert response.parts[0].content == "success after pruning"  # type: ignore
    assert failing_model.request.call_count == 2


@pytest.mark.asyncio
async def test_context_limit_exceeded_triggers_pruning(mock_model):
    """Test that 400 errors with 'exceed context limit' message trigger pruning."""
    failing_model = MagicMock(spec=Model)
    failing_model.request = AsyncMock(
        side_effect=[
            ModelHTTPError(
                status_code=400,
                model_name="failing-model",
                body={"error": "Request input tokens + max output tokens exceed context limit"},
            ),
            ModelResponse(parts=[TextPart(content="success after pruning")]),
        ]
    )
    failing_model.customize_request_parameters = lambda x: x

    model = AdaptiveFallbackModel(failing_model)

    response = await model.request(
        messages=[ModelRequest(parts=[UserPromptPart(content="test")])],
        model_settings=None,
        model_request_parameters=ModelRequestParameters(),
    )

    assert response.parts[0].content == "success after pruning"  # type: ignore
    assert failing_model.request.call_count == 2


@pytest.mark.asyncio
async def test_unauthorized_error_message(mock_model):
    """Test that unauthorized errors produce the correct message."""
    failing_model = MagicMock(spec=Model)
    failing_model.request = AsyncMock(side_effect=ModelHTTPError(status_code=401, model_name="failing-model"))
    failing_model.customize_request_parameters = lambda x: x

    model = AdaptiveFallbackModel(failing_model)

    with pytest.raises(AIAgentError) as exc_info: # Changed RovoDevError
        await model.request(
            messages=[ModelRequest(parts=[UserPromptPart(content="test")])],
            model_settings=None,
            model_request_parameters=ModelRequestParameters(),
        )

    assert "You are not authorized" in str(exc_info.value.title)


@pytest.mark.asyncio
async def test_streaming_request(mock_model):
    """Test streaming request functionality with fallback."""
    # Setup a failing model that will be tried first
    failing_model = MagicMock(spec=Model)
    failing_model.customize_request_parameters = lambda x: x

    # Setup mock for the successful model
    mock_model.customize_request_parameters = lambda x: x

    # Setup the failing model to raise an error
    failing_cm = MagicMock()
    failing_cm.__aenter__ = AsyncMock(side_effect=ModelHTTPError(status_code=500, model_name="failing-model"))
    failing_cm.__aexit__ = AsyncMock(return_value=None)
    failing_model.request_stream = MagicMock(return_value=failing_cm)

    # Setup the successful model to return a stream
    success_cm = MagicMock()
    success_stream = MagicMock()
    success_stream.__aiter__ = MagicMock(return_value=success_stream)
    success_stream.__anext__ = AsyncMock(
        side_effect=[
            ModelResponse(parts=[TextPart(content="chunk1")]),
            ModelResponse(parts=[TextPart(content="chunk2")]),
            StopAsyncIteration,
        ]
    )
    success_cm.__aenter__ = AsyncMock(return_value=success_stream)
    success_cm.__aexit__ = AsyncMock(return_value=None)
    mock_model.request_stream = MagicMock(return_value=success_cm)

    model = AdaptiveFallbackModel(failing_model, mock_model, fallback_threshold=1)

    chunks = []
    async with model.request_stream(
        messages=[ModelRequest(parts=[UserPromptPart(content="test")])],
        model_settings=None,
        model_request_parameters=ModelRequestParameters(),
    ) as stream:
        async for chunk in stream:
            chunks.append(chunk)

    # Verify the failing model was tried once before fallback
    assert failing_model.request_stream.call_count == 1
    assert mock_model.request_stream.call_count == 1

    # Verify we got both chunks from the successful model
    assert len(chunks) == 2
    assert chunks[0].parts[0].content == "chunk1"  # type: ignore
    assert chunks[1].parts[0].content == "chunk2"  # type: ignore

    # Verify the successful model was moved to front
    assert model.models[0] == mock_model


@pytest.mark.asyncio
async def test_default_fallback_on_server_error():
    """Test that server errors return FALLBACK."""
    exc = ModelHTTPError(status_code=500, model_name="test-model")
    result = await default_fallback_on(exc)
    assert result == FallbackOrRetry.FALLBACK


@pytest.mark.asyncio
async def test_default_fallback_on_daily_limit():
    """Test that daily limit errors return RAISE."""
    exc = ModelHTTPError(status_code=429, model_name="test-model", body={"error": "DAILY_LIMIT_EXCEEDED"})
    result = await default_fallback_on(exc)
    assert result == FallbackOrRetry.RAISE


@pytest.mark.asyncio
async def test_default_fallback_on_minute_limit():
    """Test that minute limit errors return RETRY."""
    exc = ModelHTTPError(
        status_code=429, model_name="test-model", body={"error": "MINUTE_LIMIT_EXCEEDED", "retryAfterSeconds": 5}
    )
    result = await default_fallback_on(exc)
    assert result == FallbackOrRetry.RETRY


@pytest.mark.asyncio
async def test_default_fallback_on_context_limit():
    """Test that context limit errors return PRUNE."""
    exc = ModelHTTPError(status_code=413, model_name="test-model")
    result = await default_fallback_on(exc)
    assert result == FallbackOrRetry.PRUNE


@pytest.mark.asyncio
async def test_default_fallback_on_other_errors():
    """Test that other errors return RAISE."""
    exc = ModelHTTPError(status_code=401, model_name="test-model")
    result = await default_fallback_on(exc)
    assert result == FallbackOrRetry.RAISE


@pytest.mark.asyncio
@pytest.mark.parametrize("use_streaming", [False, True])
async def test_large_request_exhausts_both_pruners_then_raises_exception(use_streaming):
    """Test that large requests try both pruners and then raise RequestTooLargeError when both fail."""
    # Mock the pruners to track their usage
    mock_mid_conversation_pruner = MagicMock()
    mock_workspace_view_pruner = MagicMock()

    # Configure pruners to return the same messages (simulating pruning failure)
    original_messages = [ModelRequest(parts=[UserPromptPart(content="test" * 1000)])]
    mock_mid_conversation_pruner.return_value = original_messages
    mock_workspace_view_pruner.return_value = original_messages

    # Create a model that always fails with context limit error
    failing_model = MagicMock(spec=Model)
    failing_model.customize_request_parameters = lambda x: x

    if use_streaming:
        # Setup the failing model to raise a context limit error for streaming
        failing_cm = MagicMock()
        failing_cm.__aenter__ = AsyncMock(
            side_effect=ModelHTTPError(status_code=400, model_name="failing-model", body="exceed context limit")
        )
        failing_cm.__aexit__ = AsyncMock(return_value=None)
        failing_model.request_stream = MagicMock(return_value=failing_cm)
    else:
        # Setup the failing model to raise a context limit error for regular requests
        failing_model.request = AsyncMock(
            side_effect=ModelHTTPError(status_code=400, model_name="failing-model", body="exceed context limit")
        )

    # Patch the pruners in the adaptive fallback model
    with pytest.MonkeyPatch().context() as m:
        m.setattr("rovodev.modules.adaptive_fallback_model.MidConversationPruner", lambda: mock_mid_conversation_pruner)
        m.setattr(
            "rovodev.modules.adaptive_fallback_model.WorkspaceViewPruner", lambda **kwargs: mock_workspace_view_pruner
        )

        model = AdaptiveFallbackModel(failing_model)

        # Should raise RequestTooLargeError after trying both pruners
        with pytest.raises(RequestTooLargeError):
            if use_streaming:
                async with model.request_stream(
                    messages=original_messages,
                    model_settings=None,
                    model_request_parameters=ModelRequestParameters(),
                ) as stream:
                    async for chunk in stream:
                        pass  # This should never be reached
            else:
                await model.request(
                    messages=original_messages,
                    model_settings=None,
                    model_request_parameters=ModelRequestParameters(),
                )

        # Verify both pruners were called exactly once
        assert mock_mid_conversation_pruner.call_count == 1
        assert mock_workspace_view_pruner.call_count == 1

        # Verify the model was called multiple times (original + after each pruner attempt)
        if use_streaming:
            assert failing_model.request_stream.call_count == 3  # Original + 2 pruner attempts
        else:
            assert failing_model.request.call_count == 3  # Original + 2 pruner attempts
