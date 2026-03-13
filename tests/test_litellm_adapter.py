"""
Tests for LiteLLM unified adapter

These tests verify the LiteLLM adapter works correctly with multiple providers.
Note: Some tests require API keys or running services (like Ollama).
"""

# Check if litellm can be imported properly
import importlib.util
from unittest.mock import Mock, patch

import pytest

from memograph.adapters.llm.litellm_adapter import LiteLLMClient, LiteLLMConfig, create_client

LITELLM_AVAILABLE = importlib.util.find_spec("litellm") is not None

# Skip marker for tests that require litellm
requires_litellm = pytest.mark.skipif(
    not LITELLM_AVAILABLE, reason="LiteLLM not properly installed or has dependency issues"
)


class TestLiteLLMConfig:
    """Test LiteLLMConfig dataclass"""

    def test_default_config(self):
        """Test default configuration values"""
        config = LiteLLMConfig()
        assert config.model == "gpt-3.5-turbo"  # Default
        assert config.max_tokens == 1024
        assert config.temperature == 0.1
        assert config.api_key is None
        assert config.api_base is None
        assert config.timeout == 180
        assert config.drop_params is True

    def test_custom_config(self):
        """Test custom configuration"""
        config = LiteLLMConfig(
            model="claude-3-5-sonnet-20240620",
            max_tokens=2048,
            temperature=0.7,
            api_key="test-key",
            api_base="https://api.test.com",
            timeout=300,
        )
        assert config.model == "claude-3-5-sonnet-20240620"
        assert config.max_tokens == 2048
        assert config.temperature == 0.7
        assert config.api_key == "test-key"
        assert config.api_base == "https://api.test.com"
        assert config.timeout == 300

    def test_config_from_env(self, monkeypatch):
        """Test reading model from environment variable"""
        monkeypatch.setenv("LITELLM_MODEL", "gpt-4")
        config = LiteLLMConfig()
        assert config.model == "gpt-4"


class TestLiteLLMClient:
    """Test LiteLLMClient class"""

    @requires_litellm
    def test_client_initialization(self):
        """Test client can be initialized"""
        config = LiteLLMConfig(model="gpt-3.5-turbo")
        client = LiteLLMClient(config)
        assert client.config.model == "gpt-3.5-turbo"

    @requires_litellm
    def test_client_default_config(self):
        """Test client with default config"""
        client = LiteLLMClient()
        assert client.config.model == "gpt-3.5-turbo"

    def test_litellm_import_error(self):
        """Test error when litellm not installed"""
        with patch("builtins.__import__", side_effect=ImportError("No module named 'litellm'")):
            with pytest.raises(RuntimeError) as exc_info:
                LiteLLMClient()
            assert "LiteLLM is not installed" in str(exc_info.value)

    @requires_litellm
    @patch("litellm.completion")
    def test_generate_basic(self, mock_completion):
        """Test basic generate method"""
        # Mock litellm response
        mock_response = Mock()
        mock_response.choices = [Mock()]
        mock_response.choices[0].message.content = "Test response"
        mock_completion.return_value = mock_response

        # Test
        config = LiteLLMConfig(model="gpt-3.5-turbo")
        client = LiteLLMClient(config)
        response = client.generate("Test prompt")

        # Verify
        assert response == "Test response"
        mock_completion.assert_called_once()
        call_args = mock_completion.call_args[1]
        assert call_args["model"] == "gpt-3.5-turbo"
        assert call_args["messages"] == [{"role": "user", "content": "Test prompt"}]

    @requires_litellm
    @patch("litellm.completion")
    def test_generate_with_custom_config(self, mock_completion):
        """Test generate with custom config override"""
        mock_response = Mock()
        mock_response.choices = [Mock()]
        mock_response.choices[0].message.content = "Custom response"
        mock_completion.return_value = mock_response

        client = LiteLLMClient(LiteLLMConfig(model="gpt-3.5-turbo"))
        custom_config = LiteLLMConfig(model="gpt-4", temperature=0.9)

        response = client.generate("Test", config=custom_config)

        assert response == "Custom response"
        call_args = mock_completion.call_args[1]
        assert call_args["model"] == "gpt-4"
        assert call_args["temperature"] == 0.9

    @requires_litellm
    @patch("litellm.completion")
    def test_generate_with_api_key(self, mock_completion):
        """Test generate passes API key"""
        mock_response = Mock()
        mock_response.choices = [Mock()]
        mock_response.choices[0].message.content = "Response"
        mock_completion.return_value = mock_response

        config = LiteLLMConfig(model="gpt-4", api_key="test-key-123")
        client = LiteLLMClient(config)
        client.generate("Test")

        call_args = mock_completion.call_args[1]
        assert call_args["api_key"] == "test-key-123"

    @requires_litellm
    @patch("litellm.completion")
    def test_generate_error_handling(self, mock_completion):
        """Test error handling in generate"""
        mock_completion.side_effect = Exception("API Error")

        client = LiteLLMClient(LiteLLMConfig(model="gpt-4"))

        with pytest.raises(RuntimeError) as exc_info:
            client.generate("Test")

        assert "LLM generation failed" in str(exc_info.value)
        assert "gpt-4" in str(exc_info.value)

    @requires_litellm
    @patch("litellm.completion")
    def test_generate_ollama_hint(self, mock_completion):
        """Test helpful error message for Ollama"""
        mock_completion.side_effect = Exception("Connection refused")

        client = LiteLLMClient(LiteLLMConfig(model="ollama/llama3.1:8b"))

        with pytest.raises(RuntimeError) as exc_info:
            client.generate("Test")

        error_msg = str(exc_info.value)
        assert "ollama" in error_msg.lower()
        assert "ollama serve" in error_msg.lower()

    @requires_litellm
    @patch("litellm.acompletion")
    async def test_generate_async(self, mock_acompletion):
        """Test async generate method"""
        mock_response = Mock()
        mock_response.choices = [Mock()]
        mock_response.choices[0].message.content = "Async response"
        mock_acompletion.return_value = mock_response

        client = LiteLLMClient(LiteLLMConfig(model="gpt-4"))
        response = await client.generate_async("Test async")

        assert response == "Async response"
        mock_acompletion.assert_called_once()

    @requires_litellm
    @patch("litellm.completion")
    def test_generate_with_fallback(self, mock_completion):
        """Test generate with fallback models"""
        # First call fails, second succeeds
        mock_response = Mock()
        mock_response.choices = [Mock()]
        mock_response.choices[0].message.content = "Fallback response"

        mock_completion.side_effect = [Exception("Primary failed"), mock_response]

        client = LiteLLMClient(LiteLLMConfig(model="gpt-4"))
        response = client.generate_with_fallback("Test", fallback_models=["gpt-3.5-turbo"])

        assert response == "Fallback response"
        assert mock_completion.call_count == 2

    @requires_litellm
    @patch("litellm.completion")
    def test_generate_with_fallback_all_fail(self, mock_completion):
        """Test fallback when all models fail"""
        mock_completion.side_effect = Exception("All failed")

        client = LiteLLMClient(LiteLLMConfig(model="gpt-4"))

        with pytest.raises(RuntimeError) as exc_info:
            client.generate_with_fallback(
                "Test", fallback_models=["gpt-3.5-turbo", "claude-3-sonnet"]
            )

        assert "All models failed" in str(exc_info.value)

    @requires_litellm
    @patch("litellm.completion")
    def test_stream_generate(self, mock_completion):
        """Test streaming generate"""
        # Mock streaming response
        mock_chunk1 = Mock()
        mock_chunk1.choices = [Mock()]
        mock_chunk1.choices[0].delta.content = "Hello "

        mock_chunk2 = Mock()
        mock_chunk2.choices = [Mock()]
        mock_chunk2.choices[0].delta.content = "World"

        mock_completion.return_value = [mock_chunk1, mock_chunk2]

        client = LiteLLMClient(LiteLLMConfig(model="gpt-4"))
        chunks = list(client.stream_generate("Test"))

        assert chunks == ["Hello ", "World"]

    def test_get_supported_models(self):
        """Test getting list of supported models"""
        models = LiteLLMClient.get_supported_models()

        assert isinstance(models, list)
        assert len(models) > 0
        assert "gpt-4" in models
        assert "claude-3-5-sonnet-20240620" in models
        assert "ollama/llama3.1:8b" in models


class TestConvenienceFunction:
    """Test convenience functions"""

    @requires_litellm
    def test_create_client(self):
        """Test create_client convenience function"""
        client = create_client("gpt-4", temperature=0.5, max_tokens=100)

        assert isinstance(client, LiteLLMClient)
        assert client.config.model == "gpt-4"
        assert client.config.temperature == 0.5
        assert client.config.max_tokens == 100


class TestProtocolCompliance:
    """Test that LiteLLMClient follows the LLMAdapter protocol"""

    @requires_litellm
    def test_has_generate_method(self):
        """Test client has generate method"""
        client = LiteLLMClient()
        assert hasattr(client, "generate")
        assert callable(client.generate)

    @requires_litellm
    @patch("litellm.completion")
    def test_generate_signature(self, mock_completion):
        """Test generate method signature matches protocol"""
        mock_response = Mock()
        mock_response.choices = [Mock()]
        mock_response.choices[0].message.content = "Test"
        mock_completion.return_value = mock_response

        client = LiteLLMClient()
        config = LiteLLMConfig()

        # Should accept (prompt: str, config: Any) and return str
        result = client.generate("test prompt", config)
        assert isinstance(result, str)


@pytest.mark.integration
class TestIntegrationWithMemograph:
    """Integration tests with MemoGraph components"""

    @requires_litellm
    @patch("litellm.completion")
    def test_with_smart_auto_organizer(self, mock_completion):
        """Test LiteLLM with SmartAutoOrganizer"""
        from memograph.core.enums import MemoryType
        from memograph.core.extractor import SmartAutoOrganizer
        from memograph.core.node import MemoryNode

        # Mock LLM response
        mock_response = Mock()
        mock_response.choices = [Mock()]
        mock_response.choices[0].message.content = """
        {
            "topics": [{"name": "Test", "description": "Test topic", "confidence": 0.9}],
            "subtopics": [],
            "people": [],
            "organizations": [],
            "action_items": [],
            "decisions": [],
            "questions": [],
            "sentiment": null,
            "timeline": [],
            "references": [],
            "ideas": [],
            "risks": [],
            "recurring_themes": []
        }
        """
        mock_completion.return_value = mock_response

        # Create organizer with LiteLLM
        config = LiteLLMConfig(model="gpt-3.5-turbo")
        client = LiteLLMClient(config)
        organizer = SmartAutoOrganizer(client, config)

        # Create test memory
        memory = MemoryNode(
            id="test-123",
            title="Test Memory",
            content="This is a test memory about testing.",
            memory_type=MemoryType.SEMANTIC,
        )

        # Extract entities
        result = organizer.extract(memory)

        # Verify
        assert result.memory_id == "test-123"
        assert len(result.topics) > 0
        assert result.topics[0].name == "Test"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
