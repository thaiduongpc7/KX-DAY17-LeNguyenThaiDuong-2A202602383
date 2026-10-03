from __future__ import annotations

from pathlib import Path

from agent_advanced import AdvancedAgent
from agent_baseline import BaselineAgent
from config import LabConfig
from memory_store import CompactMemoryManager, UserProfileStore
from model_provider import ProviderConfig


def make_config(tmp_path: Path) -> LabConfig:
    """Student TODO: build an isolated config for tests."""

    model = ProviderConfig(provider="openai", model_name="gpt-4o-mini", temperature=0.0)
    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    return LabConfig(
        base_dir=tmp_path,
        data_dir=tmp_path / "data",
        state_dir=state_dir,
        compact_threshold_tokens=80,
        compact_keep_messages=2,
        model=model,
        judge_model=model,
    )


def test_user_markdown_read_write_edit(tmp_path: Path) -> None:
    """Student TODO: verify `User.md` can be created, updated, and edited."""

    store = UserProfileStore(tmp_path / "profiles")

    store.write_text("user-1", "# User Profile\n\n## Facts\n- name: Lan")

    assert "name: Lan" in store.read_text("user-1")
    assert store.file_size("user-1") > 0
    assert store.edit_text("user-1", "- name: Lan", "- name: Mai") is True
    assert "name: Mai" in store.read_text("user-1")
    assert "name: Lan" not in store.read_text("user-1")


def test_compact_trigger(tmp_path: Path) -> None:
    """Student TODO: verify long threads trigger compaction."""

    config = make_config(tmp_path)
    memory = CompactMemoryManager(
        threshold_tokens=config.compact_threshold_tokens,
        keep_messages=config.compact_keep_messages,
    )

    for index in range(8):
        memory.append("thread-1", "user", f"Long context {index}: " + ("detail " * 80))

    context = memory.context("thread-1")
    assert memory.compaction_count("thread-1") > 0
    assert context["summary"]
    assert len(context["messages"]) <= config.compact_keep_messages


def test_cross_session_recall(tmp_path: Path) -> None:
    """Student TODO: verify advanced remembers across sessions and baseline does not."""

    config = make_config(tmp_path)

    advanced = AdvancedAgent(config, force_offline=True)
    advanced.reply("user-1", "thread-a", "Minh ten la Lan.")
    advanced_answer = advanced.reply("user-1", "thread-b", "Minh ten gi?")["answer"]

    assert "Lan" in advanced_answer
    assert advanced.memory_file_size("user-1") > 0

    baseline = BaselineAgent(config, force_offline=True)
    baseline.reply("user-1", "thread-a", "Minh ten la Lan.")
    baseline_answer = baseline.reply("user-1", "thread-b", "Minh ten gi?")["answer"]

    assert "Lan" not in baseline_answer
    assert "khong biet" in baseline_answer.lower()


def test_compact_reduces_prompt_load_on_long_thread(tmp_path: Path) -> None:
    """Student TODO: compare prompt load of baseline vs advanced on a long thread."""

    config = make_config(tmp_path)
    baseline = BaselineAgent(config, force_offline=True)
    advanced = AdvancedAgent(config, force_offline=True)

    for index in range(14):
        message = (
            f"Long turn {index}. "
            + "This message adds repeated context for the stress benchmark. " * 20
        )
        baseline.reply("user-1", "long-thread", message)
        advanced.reply("user-1", "long-thread", message)

    assert advanced.compaction_count("long-thread") > 0
    assert advanced.prompt_token_usage("long-thread") < baseline.prompt_token_usage("long-thread")
