"""Integration tests for the proxy API rate limits and entitlement checks."""

import base64
import os
from unittest.mock import patch

import pytest

import nemo
from nemo.agent import get_model
from nemo.cli import _run_agent
from rovodev.common.agent import create_agent_factory
from rovodev.common.config import save_config
from rovodev.common.config_model import AIAgentConfig # Changed RovoDevConfig
from rovodev.common.exceptions import EntitlementCheckFailed, RateLimitExceededError, AIAgentError # Changed RovoDevError
from rovodev.modules.adaptive_fallback_model import AdaptiveFallbackModel
from rovodev.modules.usage import get_usage

pytestmark = pytest.mark.skipif(
    not os.getenv("RUN_SLOW") or not os.getenv("USER_API_TOKEN"), reason="Proxy API integration tests"
)

USER_EMAIL = os.getenv("USER_EMAIL")
USER_API_TOKEN = os.getenv("USER_API_TOKEN")
MODEL_IDS = ["anthropic:claude-3-5-sonnet-v2@20241022", "bedrock:anthropic.claude-3-5-sonnet-20241022-v2:0"]
BASE_HEADERS = {
    "Authorization": "Basic " + base64.b64encode(f"{USER_EMAIL}:{USER_API_TOKEN}".encode("utf-8")).decode("utf-8"),
}


def get_agent_objects(tmp_path):
    """Fixture to return an agent factory and agent instance."""
    nemo.AUTH_METHOD = "api_token"
    config = AIAgentConfig() # Changed RovoDevConfig
    config_path = str(tmp_path / "config.yml")
    save_config(config, config_path)
    agent_factory = create_agent_factory(config, config_path, interactive=True)
    agent = agent_factory.create()
    models = []
    for model_id in MODEL_IDS:
        models.append(get_model(model_id, use_known_fallbacks=False))
    agent.model = AdaptiveFallbackModel(models[0], *models[1:])

    return agent_factory, agent


@patch(
    "rovodev.modules.usage.get_ai_gateway_headers",
    return_value=BASE_HEADERS | {"X-Atlassian--Override--hflfkjhfiqcxnsvsooovaqxu": "false"},
)
def test_entitlement_check_failure(mock_ai_gateway_headers):
    """Test that the entitlement check fails when the user is not entitled."""
    nemo.AUTH_METHOD = "api_token"
    with pytest.raises(EntitlementCheckFailed):
        get_usage()


@pytest.mark.asyncio
@patch(
    "nemo.providers.anthropic.get_ai_gateway_headers",
    return_value=BASE_HEADERS | {"X-Atlassian--Override--hflfkjhfiqcxnsvsooovaqxu": "false"},
)
async def test_llm_request_entitlement_check_failure(mock_ai_gateway_headers, tmp_path):
    """Test that the entitlement check fails when the user is not entitled."""
    agent_factory, agent = get_agent_objects(tmp_path)

    with pytest.raises(AIAgentError): # Changed RovoDevError
        await _run_agent(agent_factory=agent_factory, problem_statement="List your tools", agent_instance=agent)


@pytest.mark.asyncio
@patch(
    "nemo.providers.anthropic.get_ai_gateway_headers",
    return_value=BASE_HEADERS
    | {
        "X-Atlassian--Override--qgvoewxbpqwtsmyelvrhikvb": "1000",
        "X-Atlassian--Override--mlokjlalaixxnfxojzgqfxae": "1",
    },
)
async def test_daily_rate_limit_exception(mock_ai_gateway_headers, tmp_path):
    """Test that the correct exception is raised when daily limits are exceeded."""
    agent_factory, agent = get_agent_objects(tmp_path)

    with pytest.raises(RateLimitExceededError, match="Your daily usage limit of 1 tokens resets in "):
        await _run_agent(agent_factory=agent_factory, problem_statement="List your tools", agent_instance=agent)


@pytest.mark.asyncio
@patch(
    "nemo.providers.anthropic.get_ai_gateway_headers",
    return_value=BASE_HEADERS
    | {
        "X-Atlassian--Override--hajudlilxobnyjwfcstkczso": "5",
        "X-Atlassian--Override--hflfkjhfiqcxnsvsooovaqxu": "true",
    },
)
async def test_minute_rate_limit_exception(mock_ai_gateway_headers, tmp_path):
    """Test that the correct exception is raised when minute limits are exceeded."""
    agent_factory, agent = get_agent_objects(tmp_path)

    # Use only the first model to prevent fallback
    model = AdaptiveFallbackModel(
        get_model(MODEL_IDS[0], use_known_fallbacks=False),
        fallback_threshold=1,
        success_preference_factor=0,
    )
    agent.model = model

    with pytest.raises(RateLimitExceededError):
        await _run_agent(
            agent_factory=agent_factory,
            problem_statement="Give me a haiku on AI-powered software development.",
            agent_instance=agent,
        )
        await _run_agent(
            agent_factory=agent_factory,
            problem_statement="List your tools with one dot point per tool and no explanations.",
            agent_instance=agent,
        )
