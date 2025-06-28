from unittest.mock import MagicMock, patch

import pytest
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart
from pydantic_ai.models.function import AgentInfo, FunctionModel


def model_function(_: list[ModelMessage], __: AgentInfo) -> ModelResponse:
    return ModelResponse(parts=[TextPart(content="test")])


MOCK_MODEL = FunctionModel(model_function)


@pytest.fixture
def mock_get_model():
    with patch("nemo.agent.get_model") as mock:
        mock.return_value = MOCK_MODEL
        yield mock


@pytest.fixture(autouse=True)
def mock_analytics_client():
    """Mock Atlassian Analytics client to prevent any real API calls."""
    # with patch("rovodev.modules.analytics.atlassian_client.Client") as mock_client: # Commented out as analytics module is removed
    #     mock_instance = MagicMock()
    #     mock_instance.track.return_value = (True, "")  # Simulate successful tracking
    #     mock_client.return_value = mock_instance
    #     yield mock_client
    yield None # Return None as the fixture is now a no-op
