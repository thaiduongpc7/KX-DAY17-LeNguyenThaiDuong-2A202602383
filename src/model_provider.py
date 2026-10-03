from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ProviderConfig:
    """Student TODO: define the provider configuration shared by the agents.

    Required providers for this lab:
    - openai
    - custom (OpenAI-compatible base URL)
    - gemini
    - anthropic
    - ollama
    - openrouter
    """

    provider: str
    model_name: str
    temperature: float
    api_key: str | None = None
    base_url: str | None = None


SUPPORTED_PROVIDERS = {"openai", "custom", "gemini", "anthropic", "ollama", "openrouter"}


def normalize_provider(value: str) -> str:
    """Student TODO: map aliases like `anthorpic` -> `anthropic`."""

    normalized = (value or "").strip().lower().replace("_", "-")
    aliases = {
        "open-ai": "openai",
        "chatgpt": "openai",
        "openai-compatible": "custom",
        "compatible": "custom",
        "google": "gemini",
        "google-genai": "gemini",
        "google-generative-ai": "gemini",
        "anthorpic": "anthropic",
        "claude": "anthropic",
        "local": "ollama",
        "open-router": "openrouter",
    }
    provider = aliases.get(normalized, normalized)
    if provider not in SUPPORTED_PROVIDERS:
        supported = ", ".join(sorted(SUPPORTED_PROVIDERS))
        raise ValueError(f"Unsupported LLM provider '{value}'. Supported providers: {supported}.")
    return provider


def build_chat_model(config: ProviderConfig):
    """Student TODO: instantiate the real chat model for the selected provider.

    Pseudocode:
    - `openai` -> `ChatOpenAI`
    - `custom` -> `ChatOpenAI` with `base_url`
    - `gemini` -> `ChatGoogleGenerativeAI`
    - `anthropic` -> `ChatAnthropic`
    - `ollama` -> `ChatOllama`
    - `openrouter` -> `ChatOpenRouter`
    """

    provider = normalize_provider(config.provider)
    common = {
        "model": config.model_name,
        "temperature": config.temperature,
    }

    try:
        if provider == "openai":
            from langchain_openai import ChatOpenAI

            kwargs = {**common}
            if config.api_key:
                kwargs["api_key"] = config.api_key
            return ChatOpenAI(**kwargs)

        if provider == "custom":
            from langchain_openai import ChatOpenAI

            kwargs = {**common}
            if config.api_key:
                kwargs["api_key"] = config.api_key
            if config.base_url:
                kwargs["base_url"] = config.base_url
            return ChatOpenAI(**kwargs)

        if provider == "gemini":
            from langchain_google_genai import ChatGoogleGenerativeAI

            kwargs = {**common}
            if config.api_key:
                kwargs["api_key"] = config.api_key
            return ChatGoogleGenerativeAI(**kwargs)

        if provider == "anthropic":
            from langchain_anthropic import ChatAnthropic

            kwargs = {**common}
            if config.api_key:
                kwargs["api_key"] = config.api_key
            return ChatAnthropic(**kwargs)

        if provider == "ollama":
            from langchain_ollama import ChatOllama

            kwargs = {**common}
            if config.base_url:
                kwargs["base_url"] = config.base_url
            return ChatOllama(**kwargs)

        if provider == "openrouter":
            from langchain_openrouter import ChatOpenRouter

            kwargs = {**common}
            if config.api_key:
                kwargs["api_key"] = config.api_key
            return ChatOpenRouter(**kwargs)
    except ImportError as exc:
        raise ImportError(
            f"Provider '{provider}' requires an optional LangChain package that is not installed."
        ) from exc

    raise ValueError(f"Unsupported LLM provider '{config.provider}'.")
