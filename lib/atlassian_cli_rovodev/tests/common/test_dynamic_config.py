"""Tests for dynamic_config module."""

from unittest.mock import Mock, patch

import pytest

from rovodev.common.dynamic_config import DynamicConfigData, DynamicConfiguration


def test_dynamic_config_data():
    """Test DynamicConfigData dataclass."""
    config = DynamicConfigData(is_internal=True, model_id=["test-model", "test-model-2"], banned=False)
    assert config.is_internal is True
    assert config.model_id == ["test-model", "test-model-2"]


@pytest.fixture
def mock_requests():
    """Mock requests.post."""
    with patch("requests.post") as mock_post:
        yield mock_post


def test_is_internal_default_value(): # Renamed test
    """Test that is_internal defaults to False as Statsig/domain check is removed."""
    with patch("requests.post") as mock_post: # Mock requests.post even if not used by new logic, to keep test structure
        # Mock successful response (though its content for is_internal is ignored by new logic)
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"value": {"model_id": ["test-model", "test-model-2"], "banned": False}}
        mock_post.return_value = mock_response

        # Test with an @atlassian.com style email
        internal_style_email_config = DynamicConfiguration("test@atlassian.com")
        assert internal_style_email_config.config().is_internal is False # Should now be False

        # Test with an external style email
        external_email_config = DynamicConfiguration("test@example.com")
        assert external_email_config.config().is_internal is False # Remains False


def test_model_id_from_config():
    """Test model ID is correctly retrieved from config response."""
    with patch("requests.post") as mock_post:
        # Mock response with custom model ID
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"value": {"model_id": ["custom-model-v1"], "banned": True}}
        mock_post.return_value = mock_response

        config = DynamicConfiguration("test@example.com")
        assert config.config().model_id == ["custom-model-v1"]
