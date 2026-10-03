from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from model_provider import ProviderConfig, normalize_provider


@dataclass
class LabConfig:
    """Student TODO: define the shared configuration for the lab.

    Hints:
    - Keep paths for the repo root, dataset directory, and state directory.
    - Add compact-memory settings such as threshold and number of messages to keep.
    - Add provider settings for `openai`, `custom`, `gemini`, `anthropic`, `ollama`, and `openrouter`.
    """

    base_dir: Path
    data_dir: Path
    state_dir: Path
    compact_threshold_tokens: int
    compact_keep_messages: int
    model: ProviderConfig
    judge_model: ProviderConfig


def load_config(base_dir: Path | None = None) -> LabConfig:
    """Student TODO: load environment variables and return a LabConfig.

    Pseudocode:
    1. Resolve the repo root or default to the current file parent.
    2. Optionally load values from `.env`.
    3. Create `state/` if it does not exist.
    4. Return a populated LabConfig instance.
    """

    root = (base_dir or Path(__file__).resolve().parent.parent).resolve()

    try:
        from dotenv import load_dotenv

        load_dotenv(root / ".env")
    except ImportError:
        pass

    data_dir = root / "data"
    state_dir = root / "state"
    state_dir.mkdir(parents=True, exist_ok=True)

    compact_threshold_tokens = _env_int("COMPACT_THRESHOLD_TOKENS", 1600)
    compact_keep_messages = _env_int("COMPACT_KEEP_MESSAGES", 6)

    model = _provider_from_env(prefix="LLM", default_provider="openai", default_model="gpt-4o-mini")
    judge_model = _provider_from_env(
        prefix="JUDGE",
        default_provider=model.provider,
        default_model=os.getenv("LLM_MODEL", model.model_name),
    )

    return LabConfig(
        base_dir=root,
        data_dir=data_dir,
        state_dir=state_dir,
        compact_threshold_tokens=compact_threshold_tokens,
        compact_keep_messages=compact_keep_messages,
        model=model,
        judge_model=judge_model,
    )


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got {raw!r}.") from exc
    if value <= 0:
        raise ValueError(f"{name} must be positive, got {value}.")
    return value


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number, got {raw!r}.") from exc


def _provider_from_env(prefix: str, default_provider: str, default_model: str) -> ProviderConfig:
    provider = normalize_provider(os.getenv(f"{prefix}_PROVIDER", default_provider))
    model_name = os.getenv(f"{prefix}_MODEL", default_model)
    temperature = _env_float(f"{prefix}_TEMPERATURE", 0.0)

    return ProviderConfig(
        provider=provider,
        model_name=model_name,
        temperature=temperature,
        api_key=_api_key_for(provider, prefix),
        base_url=_base_url_for(provider, prefix),
    )


def _api_key_for(provider: str, prefix: str) -> str | None:
    specific = os.getenv(f"{prefix}_API_KEY")
    if specific:
        return specific

    if provider == "openai":
        return os.getenv("OPENAI_API_KEY")
    if provider == "custom":
        return os.getenv("CUSTOM_API_KEY") or os.getenv("OPENAI_API_KEY")
    if provider == "gemini":
        return os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if provider == "anthropic":
        return os.getenv("ANTHROPIC_API_KEY")
    if provider == "openrouter":
        return os.getenv("OPENROUTER_API_KEY")
    return None


def _base_url_for(provider: str, prefix: str) -> str | None:
    specific = os.getenv(f"{prefix}_BASE_URL")
    if specific:
        return specific

    if provider == "custom":
        return os.getenv("CUSTOM_BASE_URL")
    if provider == "ollama":
        return os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    if provider == "openrouter":
        return os.getenv("OPENROUTER_BASE_URL")
    return None
