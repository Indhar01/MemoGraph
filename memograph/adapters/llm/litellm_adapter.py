"""
LiteLLM Unified Adapter for MemoGraph

This adapter provides a unified interface to 100+ LLM providers through LiteLLM,
including OpenAI, Anthropic, Google, Ollama, Azure, and many more.

Usage:
    from memograph.adapters.llm.litellm_adapter import LiteLLMClient, LiteLLMConfig

    # OpenAI
    client = LiteLLMClient(LiteLLMConfig(model="gpt-4"))

    # Anthropic Claude
    client = LiteLLMClient(LiteLLMConfig(model="claude-3-5-sonnet-20240620"))

    # Ollama (local)
    client = LiteLLMClient(LiteLLMConfig(model="ollama/llama3.1:8b"))

    # Google Gemini
    client = LiteLLMClient(LiteLLMConfig(model="gemini/gemini-pro"))
"""

import os
from dataclasses import dataclass, field
from typing import Any


@dataclass
class LiteLLMConfig:
    """
    Configuration for LiteLLM client.

    Attributes:
        model: Model identifier. Examples:
            - OpenAI: "gpt-4", "gpt-3.5-turbo"
            - Anthropic: "claude-3-5-sonnet-20240620", "claude-3-opus-20240229"
            - Ollama: "ollama/llama3.1:8b", "ollama/mistral"
            - Google: "gemini/gemini-pro"
            - Azure: "azure/gpt-4"
        max_tokens: Maximum tokens to generate
        temperature: Sampling temperature (0.0 to 2.0)
        api_key: API key (optional, reads from environment if not provided)
        api_base: Base URL for API (optional, provider-specific)
        timeout: Request timeout in seconds
        drop_params: Drop unsupported parameters instead of erroring
    """

    model: str = field(default_factory=lambda: os.environ.get("LITELLM_MODEL", "gpt-3.5-turbo"))
    max_tokens: int = 1024
    temperature: float = 0.1
    api_key: str | None = None
    api_base: str | None = None
    timeout: int = 180
    drop_params: bool = True


class LiteLLMClient:
    """
    Unified LLM client supporting 100+ providers via LiteLLM.

    This client provides a consistent interface across all major LLM providers,
    automatically handling provider-specific details and API differences.

    Features:
        - Unified API for all providers
        - Automatic retries with exponential backoff
        - Cost tracking
        - Streaming support
        - Async/await support
        - Automatic fallbacks

    Example:
        >>> client = LiteLLMClient(LiteLLMConfig(model="gpt-4"))
        >>> response = client.generate("What is machine learning?")
        >>> print(response)
    """

    def __init__(self, config: LiteLLMConfig | None = None):
        """
        Initialize LiteLLM client.

        Args:
            config: Configuration object. If None, uses default config.

        Raises:
            RuntimeError: If litellm is not installed
        """
        try:
            import litellm

            self._litellm = litellm
        except ImportError as exc:
            raise RuntimeError(
                "LiteLLM is not installed. Install it with: pip install litellm"
            ) from exc

        self.config = config or LiteLLMConfig()

        # Configure LiteLLM settings
        self._litellm.drop_params = self.config.drop_params
        self._litellm.set_verbose = False  # Set to True for debugging

        # Suppress unnecessary warnings
        import warnings

        warnings.filterwarnings("ignore", category=UserWarning, module="litellm")

    def generate(self, prompt: str, config: LiteLLMConfig | None = None) -> str:
        """
        Generate text from a prompt using the configured LLM provider.

        Args:
            prompt: The input prompt text
            config: Optional config override. If None, uses instance config.

        Returns:
            Generated text response

        Raises:
            RuntimeError: If generation fails

        Example:
            >>> client = LiteLLMClient(LiteLLMConfig(model="claude-3-5-sonnet-20240620"))
            >>> response = client.generate("Explain quantum computing")
            >>> print(response)
        """
        cfg = config or self.config

        try:
            # Prepare completion parameters
            params: dict[str, Any] = {
                "model": cfg.model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": cfg.max_tokens,
                "temperature": cfg.temperature,
                "timeout": cfg.timeout,
            }

            # Add optional parameters
            if cfg.api_key:
                params["api_key"] = cfg.api_key
            if cfg.api_base:
                params["api_base"] = cfg.api_base

            # Call LiteLLM
            response = self._litellm.completion(**params)

            # Extract text from response
            content = response.choices[0].message.content
            if content is None:
                raise RuntimeError(f"No content in response from model '{cfg.model}'")
            return str(content).strip()

        except Exception as e:
            # Provide helpful error message
            error_msg = f"LLM generation failed with model '{cfg.model}': {str(e)}"

            # Add provider-specific hints
            if "ollama" in cfg.model.lower():
                error_msg += "\nHint: Make sure Ollama is running (ollama serve)"
            elif "api_key" in str(e).lower():
                error_msg += "\nHint: Set appropriate API key environment variable"

            raise RuntimeError(error_msg) from e

    async def generate_async(self, prompt: str, config: LiteLLMConfig | None = None) -> str:
        """
        Async version of generate() for better performance in async contexts.

        Args:
            prompt: The input prompt text
            config: Optional config override

        Returns:
            Generated text response

        Raises:
            RuntimeError: If generation fails

        Example:
            >>> client = LiteLLMClient(LiteLLMConfig(model="gpt-4"))
            >>> response = await client.generate_async("Explain AI")
        """
        cfg = config or self.config

        try:
            params: dict[str, Any] = {
                "model": cfg.model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": cfg.max_tokens,
                "temperature": cfg.temperature,
                "timeout": cfg.timeout,
            }

            if cfg.api_key:
                params["api_key"] = cfg.api_key
            if cfg.api_base:
                params["api_base"] = cfg.api_base

            response = await self._litellm.acompletion(**params)
            content = response.choices[0].message.content
            if content is None:
                raise RuntimeError(f"No content in response from model '{cfg.model}'")
            return str(content).strip()

        except Exception as e:
            error_msg = f"Async LLM generation failed with model '{cfg.model}': {str(e)}"
            raise RuntimeError(error_msg) from e

    def generate_with_fallback(
        self, prompt: str, fallback_models: list[str], config: LiteLLMConfig | None = None
    ) -> str:
        """
        Generate with automatic fallback to alternative models on failure.

        Args:
            prompt: The input prompt text
            fallback_models: List of fallback model names to try
            config: Optional config override

        Returns:
            Generated text response

        Raises:
            RuntimeError: If all models fail

        Example:
            >>> client = LiteLLMClient(LiteLLMConfig(model="gpt-4"))
            >>> response = client.generate_with_fallback(
            ...     "Hello",
            ...     fallback_models=["gpt-3.5-turbo", "claude-3-sonnet-20240229"]
            ... )
        """
        cfg = config or self.config
        models_to_try = [cfg.model] + fallback_models
        last_error = None

        for model in models_to_try:
            try:
                temp_config = LiteLLMConfig(
                    model=model,
                    max_tokens=cfg.max_tokens,
                    temperature=cfg.temperature,
                    api_key=cfg.api_key,
                    api_base=cfg.api_base,
                    timeout=cfg.timeout,
                )
                return self.generate(prompt, temp_config)
            except Exception as e:
                last_error = e
                continue

        raise RuntimeError(f"All models failed. Last error: {last_error}") from last_error

    def stream_generate(self, prompt: str, config: LiteLLMConfig | None = None):
        """
        Generate text with streaming response (yields chunks as they arrive).

        Args:
            prompt: The input prompt text
            config: Optional config override

        Yields:
            Text chunks as they are generated

        Example:
            >>> client = LiteLLMClient(LiteLLMConfig(model="gpt-4"))
            >>> for chunk in client.stream_generate("Write a story"):
            ...     print(chunk, end="", flush=True)
        """
        cfg = config or self.config

        try:
            params: dict[str, Any] = {
                "model": cfg.model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": cfg.max_tokens,
                "temperature": cfg.temperature,
                "stream": True,
                "timeout": cfg.timeout,
            }

            if cfg.api_key:
                params["api_key"] = cfg.api_key
            if cfg.api_base:
                params["api_base"] = cfg.api_base

            response = self._litellm.completion(**params)

            for chunk in response:
                if chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content

        except Exception as e:
            raise RuntimeError(
                f"Streaming generation failed with model '{cfg.model}': {str(e)}"
            ) from e

    def get_cost(self, response: Any) -> float:
        """
        Get the cost of a completion response.

        Args:
            response: Response object from litellm.completion()

        Returns:
            Cost in USD

        Example:
            >>> response = client._litellm.completion(model="gpt-4", messages=[...])
            >>> cost = client.get_cost(response)
            >>> print(f"Cost: ${cost:.4f}")
        """
        try:
            return self._litellm.completion_cost(response)
        except Exception:
            return 0.0

    @staticmethod
    def get_supported_models() -> list[str]:
        """
        Get a list of popular supported model identifiers.

        Returns:
            List of model identifiers
        """
        return [
            # OpenAI
            "gpt-4-turbo-preview",
            "gpt-4",
            "gpt-3.5-turbo",
            # Anthropic
            "claude-3-5-sonnet-20240620",
            "claude-3-opus-20240229",
            "claude-3-sonnet-20240229",
            # Google
            "gemini/gemini-pro",
            "gemini/gemini-1.5-pro",
            # Ollama (local)
            "ollama/llama3.1:8b",
            "ollama/mistral",
            "ollama/codellama",
            # Azure
            "azure/gpt-4",
            "azure/gpt-35-turbo",
            # Cohere
            "command-r-plus",
            "command-r",
            # And 100+ more...
        ]


# Convenience function for quick usage
def create_client(model: str, **kwargs) -> LiteLLMClient:
    """
    Convenience function to create a LiteLLM client with minimal configuration.

    Args:
        model: Model identifier (e.g., "gpt-4", "claude-3-5-sonnet-20240620")
        **kwargs: Additional config parameters

    Returns:
        Configured LiteLLMClient instance

    Example:
        >>> client = create_client("gpt-4", temperature=0.7)
        >>> response = client.generate("Hello")
    """
    config = LiteLLMConfig(model=model, **kwargs)
    return LiteLLMClient(config)
