from __future__ import annotations

import json
from dataclasses import dataclass
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from agent_advanced import AdvancedAgent
from agent_baseline import BaselineAgent
from config import load_config


@dataclass
class BenchmarkRow:
    agent_name: str
    agent_tokens_only: int
    prompt_tokens_processed: int
    recall_score: float
    response_quality: float
    memory_growth_bytes: int
    compactions: int


def load_conversations(path: Path) -> list[dict[str, Any]]:
    """Student TODO: read JSON conversations from disk."""

    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"{path} must contain a JSON list of conversations.")

    required_conversation_keys = {"id", "user_id", "turns", "recall_questions"}
    required_question_keys = {"question", "expected_contains"}
    for index, conversation in enumerate(data):
        if not isinstance(conversation, dict):
            raise ValueError(f"Conversation #{index} in {path} must be an object.")
        missing = required_conversation_keys - set(conversation)
        if missing:
            raise ValueError(f"Conversation #{index} in {path} is missing: {sorted(missing)}.")
        if not isinstance(conversation["turns"], list):
            raise ValueError(f"Conversation {conversation['id']} has non-list turns.")
        if not isinstance(conversation["recall_questions"], list):
            raise ValueError(f"Conversation {conversation['id']} has non-list recall_questions.")
        for question_index, question in enumerate(conversation["recall_questions"]):
            if not isinstance(question, dict):
                raise ValueError(
                    f"Recall question #{question_index} in {conversation['id']} must be an object."
                )
            missing = required_question_keys - set(question)
            if missing:
                raise ValueError(
                    f"Recall question #{question_index} in {conversation['id']} "
                    f"is missing: {sorted(missing)}."
                )
    return data


def recall_points(answer: str, expected: list[str]) -> float:
    """Student TODO: return 0 / 0.5 / 1 depending on how many expected facts appear."""

    expected_values = [value for value in expected if value]
    if not expected_values:
        return 1.0

    folded_answer = (answer or "").casefold()
    matches = sum(1 for value in expected_values if value.casefold() in folded_answer)
    if matches == 0:
        return 0.0
    if matches == len(expected_values):
        return 1.0
    return 0.5


def heuristic_quality(answer: str, expected: list[str]) -> float:
    """Student TODO: add a lightweight quality score for offline mode."""

    normalized = " ".join((answer or "").split())
    if not normalized:
        return 0.0

    recall = recall_points(normalized, expected)
    brevity = 1.0 if len(normalized) <= 600 else 0.7
    structure = 1.0 if any(marker in normalized for marker in (":", "-", ".")) else 0.8
    return round((0.75 * recall) + (0.15 * brevity) + (0.10 * structure), 3)


def run_agent_benchmark(agent_name: str, agent, conversations: list[dict[str, Any]], config) -> BenchmarkRow:
    """Student TODO: evaluate one agent over many conversations.

    Pseudocode:
    1. Feed all turns to the agent.
    2. Track `agent tokens only`.
    3. Track `prompt tokens processed`.
    4. Ask recall questions in a fresh thread.
    5. Compute average recall and quality.
    6. Record memory file growth and compaction count.
    """

    user_ids = sorted({str(conversation["user_id"]) for conversation in conversations})
    memory_before = _memory_size(agent, user_ids)

    agent_tokens_only = 0
    prompt_tokens_processed = 0
    recall_scores: list[float] = []
    quality_scores: list[float] = []
    compactions = 0

    for conversation in conversations:
        conversation_id = str(conversation["id"])
        user_id = str(conversation["user_id"])
        conversation_thread_id = f"{conversation_id}::conversation"

        for turn in conversation["turns"]:
            result = agent.reply(user_id, conversation_thread_id, str(turn))
            agent_tokens_only += int(result.get("agent_tokens", 0))
            prompt_tokens_processed += int(result.get("prompt_tokens", 0))

        compactions += _compaction_count(agent, conversation_thread_id)

        recall_thread_id = f"{conversation_id}::recall"
        for question in conversation["recall_questions"]:
            result = agent.reply(user_id, recall_thread_id, str(question["question"]))
            answer = str(result.get("answer", ""))
            expected = [str(value) for value in question["expected_contains"]]

            agent_tokens_only += int(result.get("agent_tokens", 0))
            prompt_tokens_processed += int(result.get("prompt_tokens", 0))
            recall_scores.append(recall_points(answer, expected))
            quality_scores.append(heuristic_quality(answer, expected))

        compactions += _compaction_count(agent, recall_thread_id)

    memory_after = _memory_size(agent, user_ids)
    return BenchmarkRow(
        agent_name=agent_name,
        agent_tokens_only=agent_tokens_only,
        prompt_tokens_processed=prompt_tokens_processed,
        recall_score=_average(recall_scores),
        response_quality=_average(quality_scores),
        memory_growth_bytes=max(0, memory_after - memory_before),
        compactions=compactions,
    )


def format_rows(rows: list[BenchmarkRow]) -> str:
    """Student TODO: print a markdown table or tabulated output."""

    headers = [
        "Agent",
        "Agent tokens only",
        "Prompt tokens processed",
        "Cross-session recall",
        "Response quality",
        "Memory growth (bytes)",
        "Compactions",
    ]
    table_rows = [
        [
            row.agent_name,
            str(row.agent_tokens_only),
            str(row.prompt_tokens_processed),
            f"{row.recall_score:.2f}",
            f"{row.response_quality:.2f}",
            str(row.memory_growth_bytes),
            str(row.compactions),
        ]
        for row in rows
    ]
    widths = [
        max(len(header), *(len(row[column]) for row in table_rows))
        for column, header in enumerate(headers)
    ]

    def render(values: list[str]) -> str:
        return "| " + " | ".join(
            value.ljust(widths[index]) for index, value in enumerate(values)
        ) + " |"

    separator = "| " + " | ".join("-" * width for width in widths) + " |"
    return "\n".join([render(headers), separator, *(render(row) for row in table_rows)])


def main() -> None:
    """Student TODO: run both benchmark suites.

    Required benchmark sections:
    - Standard benchmark from `data/conversations.json`
    - Long-context stress benchmark from `data/advanced_long_context.json`

    Compare:
    - Baseline
    - Advanced

    Keep the same output columns as the solved lab:
    - Agent tokens only
    - Prompt tokens processed
    - Cross-session recall
    - Response quality
    - Memory growth (bytes)
    - Compactions
    """

    config = load_config(Path(__file__).resolve().parent.parent)

    standard_conversations = load_conversations(config.data_dir / "conversations.json")
    stress_conversations = load_conversations(config.data_dir / "advanced_long_context.json")

    with TemporaryDirectory(prefix="memory_benchmark_") as tmp_dir:
        tmp_root = Path(tmp_dir)
        standard_rows = _run_suite("standard", standard_conversations, config, tmp_root)
        stress_rows = _run_suite("long_context_stress", stress_conversations, config, tmp_root)

    print("## Standard Benchmark")
    print(format_rows(standard_rows))
    print()
    print("## Long-Context Stress Benchmark")
    print(format_rows(stress_rows))


def _run_suite(name: str, conversations: list[dict[str, Any]], config, tmp_root: Path) -> list[BenchmarkRow]:
    rows: list[BenchmarkRow] = []
    for agent_name, agent_cls in (("Baseline", BaselineAgent), ("Advanced", AdvancedAgent)):
        state_dir = tmp_root / name / agent_name.lower()
        state_dir.mkdir(parents=True, exist_ok=True)
        run_config = replace(config, state_dir=state_dir)
        agent = agent_cls(run_config, force_offline=True)
        rows.append(run_agent_benchmark(agent_name, agent, conversations, run_config))
    return rows


def _average(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def _memory_size(agent: Any, user_ids: list[str]) -> int:
    memory_file_size = getattr(agent, "memory_file_size", None)
    if memory_file_size is None:
        return 0
    return sum(int(memory_file_size(user_id)) for user_id in user_ids)


def _compaction_count(agent: Any, thread_id: str) -> int:
    compaction_count = getattr(agent, "compaction_count", None)
    if compaction_count is None:
        return 0
    return int(compaction_count(thread_id))


if __name__ == "__main__":
    main()
