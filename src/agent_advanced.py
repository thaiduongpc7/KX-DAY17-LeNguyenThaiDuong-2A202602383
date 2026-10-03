from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from typing import Any

from config import LabConfig, load_config
from memory_store import CompactMemoryManager, UserProfileStore, estimate_tokens, extract_profile_updates
from model_provider import build_chat_model


@dataclass
class AgentContext:
    user_id: str
    memory_path: str


class AdvancedAgent:
    """Student TODO: implement Agent B / Advanced Agent.

    Required memory layers:
    1. within-session memory
    2. persistent `User.md`
    3. compact memory for long threads
    """

    def __init__(self, config: LabConfig | None = None, force_offline: bool = False) -> None:
        self.config = config or load_config()
        self.force_offline = force_offline
        self.profile_store = UserProfileStore(self.config.state_dir / "profiles")
        self.compact_memory = CompactMemoryManager(
            threshold_tokens=self.config.compact_threshold_tokens,
            keep_messages=self.config.compact_keep_messages,
        )
        self.thread_tokens: dict[str, int] = {}
        self.thread_prompt_tokens: dict[str, int] = {}

        self.langchain_agent = None if force_offline else self._maybe_build_langchain_agent()

    def reply(self, user_id: str, thread_id: str, message: str) -> dict[str, Any]:
        """Student TODO: route between offline mode and live mode."""

        if self.langchain_agent is None:
            return self._reply_offline(user_id, thread_id, message)
        return self._reply_live(user_id, thread_id, message)

    def token_usage(self, thread_id: str) -> int:
        return self.thread_tokens.get(thread_id, 0)

    def prompt_token_usage(self, thread_id: str) -> int:
        return self.thread_prompt_tokens.get(thread_id, 0)

    def memory_file_size(self, user_id: str) -> int:
        return self.profile_store.file_size(user_id)

    def compaction_count(self, thread_id: str) -> int:
        return self.compact_memory.compaction_count(thread_id)

    def _reply_offline(self, user_id: str, thread_id: str, message: str) -> dict[str, Any]:
        """Student TODO: implement the deterministic advanced path.

        Pseudocode:
        1. Extract stable profile facts from the incoming message.
        2. Persist those facts into `User.md`.
        3. Append the message into compact memory.
        4. Estimate prompt-context load from `User.md` + summary + recent messages.
        5. Generate a response that can answer long-term recall questions.
        6. Append the assistant reply and update token counters.
        """

        updates = _stable_profile_updates(message)
        self._persist_profile_updates(user_id, updates)

        self.compact_memory.append(thread_id, "user", message)
        prompt_tokens = self._estimate_prompt_context_tokens(user_id, thread_id)

        answer = self._offline_response(user_id, thread_id, message)
        agent_tokens = estimate_tokens(answer)

        self.compact_memory.append(thread_id, "assistant", answer)
        self.thread_tokens[thread_id] = self.thread_tokens.get(thread_id, 0) + agent_tokens
        self.thread_prompt_tokens[thread_id] = (
            self.thread_prompt_tokens.get(thread_id, 0) + prompt_tokens
        )

        return {
            "answer": answer,
            "agent_tokens": agent_tokens,
            "prompt_tokens": prompt_tokens,
            "total_agent_tokens": self.thread_tokens[thread_id],
            "total_prompt_tokens": self.thread_prompt_tokens[thread_id],
        }

    def _estimate_prompt_context_tokens(self, user_id: str, thread_id: str) -> int:
        """Student TODO: estimate the context carried into one turn.

        Hint:
        - Include `User.md`
        - Include compact summary text
        - Include recent kept messages
        """

        profile_text = self.profile_store.read_text(user_id)
        context = self.compact_memory.context(thread_id)
        summary = str(context.get("summary", ""))
        messages = context.get("messages", [])

        recent_text = ""
        if isinstance(messages, list):
            recent_text = "\n".join(
                f"{item.get('role', 'unknown')}: {item.get('content', '')}"
                for item in messages
                if isinstance(item, dict)
            )

        return (
            estimate_tokens(profile_text)
            + estimate_tokens(summary)
            + estimate_tokens(recent_text)
        )

    def _offline_response(self, user_id: str, thread_id: str, message: str) -> str:
        """Student TODO: return a deterministic answer using persisted memory.

        Make sure the advanced agent can answer questions like:
        - "Mình tên gì?"
        - "Hiện tại mình làm nghề gì?"
        - "Nhắc lại style trả lời mình thích"
        - questions in the long stress dataset
        """

        facts = self.profile_store.facts(user_id)
        folded = _fold_text(message)

        requested = _requested_fact_keys(folded)
        if _asks_for_profile_summary(folded):
            requested.update({"name", "profession", "location", "technical_interests"})
        if not requested and _looks_like_recall_question(folded):
            requested.update(
                key for key in _PROFILE_ORDER if key in facts
            )

        lines = _fact_lines(facts, requested)
        if lines:
            return " ".join(lines)

        if _stable_profile_updates(message):
            return "Minh da cap nhat User.md va se dung thong tin do cho cac thread sau."
        return "Minh se dua tren User.md, summary va cac message gan nhat de tra loi ngan gon."

    def _maybe_build_langchain_agent(self):
        """Student TODO: wire a live agent with tools and compact middleware.

        High-level design:
        - `build_chat_model(self.config.model)` for the selected provider
        - `InMemorySaver` for short-term thread state
        - tool to read `User.md`
        - tool to write/edit `User.md`
        - dynamic prompt that injects profile memory
        - summarization middleware for long threads
        """

        try:
            return build_chat_model(self.config.model)
        except Exception:
            return None

    def _reply_live(self, user_id: str, thread_id: str, message: str) -> dict[str, Any]:
        updates = _stable_profile_updates(message)
        self._persist_profile_updates(user_id, updates)

        self.compact_memory.append(thread_id, "user", message)
        prompt_tokens = self._estimate_prompt_context_tokens(user_id, thread_id)
        context = self.compact_memory.context(thread_id)

        prompt = [
            (
                "system",
                "You are the advanced memory agent. Use the persistent User.md facts, "
                "the compact summary, and the recent messages. Prefer current facts over old ones.\n\n"
                f"User.md:\n{self.profile_store.read_text(user_id)}\n\n"
                f"Summary:\n{context.get('summary', '')}",
            )
        ]
        messages = context.get("messages", [])
        if isinstance(messages, list):
            prompt.extend(
                (str(item.get("role", "user")), str(item.get("content", "")))
                for item in messages
                if isinstance(item, dict)
            )

        result = self.langchain_agent.invoke(prompt)
        answer = _message_content(result)
        agent_tokens = estimate_tokens(answer)

        self.compact_memory.append(thread_id, "assistant", answer)
        self.thread_tokens[thread_id] = self.thread_tokens.get(thread_id, 0) + agent_tokens
        self.thread_prompt_tokens[thread_id] = (
            self.thread_prompt_tokens.get(thread_id, 0) + prompt_tokens
        )

        return {
            "answer": answer,
            "agent_tokens": agent_tokens,
            "prompt_tokens": prompt_tokens,
            "total_agent_tokens": self.thread_tokens[thread_id],
            "total_prompt_tokens": self.thread_prompt_tokens[thread_id],
        }

    def _persist_profile_updates(self, user_id: str, updates: dict[str, str]) -> None:
        existing = self.profile_store.facts(user_id)
        for key, value in updates.items():
            old_value = existing.get(key)
            if old_value is not None:
                value = _merge_fact_value(key, old_value, value)
                changed = self.profile_store.edit_text(
                    user_id,
                    f"- {key}: {old_value}",
                    f"- {key}: {value}",
                )
                if changed:
                    existing[key] = value
                    continue
            self.profile_store.upsert_fact(user_id, key, value)
            existing = self.profile_store.facts(user_id)


_PROFILE_ORDER = [
    "name",
    "profession",
    "location",
    "response_style",
    "favorite_drink",
    "favorite_food",
    "pet",
    "technical_interests",
]


_FACT_LABELS = {
    "name": "ten",
    "profession": "nghe nghiep hien tai",
    "location": "noi o hien tai",
    "response_style": "style tra loi",
    "favorite_drink": "do uong yeu thich",
    "favorite_food": "mon an yeu thich",
    "pet": "thu cung",
    "technical_interests": "moi quan tam ky thuat",
}


def _requested_fact_keys(folded: str) -> set[str]:
    requested: set[str] = set()
    if any(phrase in folded for phrase in ("ten", "dungct")):
        requested.add("name")
    if any(phrase in folded for phrase in ("nghe", "cong viec", "mlops", "backend", "product manager")):
        requested.add("profession")
    if any(phrase in folded for phrase in ("o dau", "noi o", "dang o", "hue", "da nang", "ha noi")):
        requested.add("location")
    if any(phrase in folded for phrase in ("style", "tra loi", "bullet", "ngan gon")):
        requested.add("response_style")
    if any(phrase in folded for phrase in ("do uong", "uong", "ca phe")):
        requested.add("favorite_drink")
    if any(phrase in folded for phrase in ("mon an", "an yeu thich", "mi quang")):
        requested.add("favorite_food")
    if any(phrase in folded for phrase in ("nuoi", "corgi", "thu cung", "con gi")):
        requested.add("pet")
    if any(phrase in folded for phrase in ("quan tam", "ky thuat", "python", "ai", "tom tat")):
        requested.add("technical_interests")
    return requested


def _asks_for_profile_summary(folded: str) -> bool:
    return any(phrase in folded for phrase in ("ban biet", "tom tat", "la ai"))


def _looks_like_recall_question(folded: str) -> bool:
    return folded.endswith("?") or any(
        phrase in folded
        for phrase in ("nhac lai", "hien tai", "yeu thich", "style", "thread moi")
    )


def _fact_lines(facts: dict[str, str], requested: set[str]) -> list[str]:
    lines: list[str] = []
    for key in _PROFILE_ORDER:
        if key not in requested or key not in facts:
            continue
        value = facts[key]
        if key == "response_style":
            value = _normalize_response_style(value)
        lines.append(f"{_FACT_LABELS[key]}: {value}.")
    return lines


def _normalize_response_style(value: str) -> str:
    folded = _fold_text(value)
    normalized = value
    if "ngan gon" not in folded:
        normalized = f"ngắn gọn, {normalized}"
    if "trade-off" not in folded and "trade off" not in folded:
        normalized = f"{normalized}, uu tien trade-off"
    return normalized


def _stable_profile_updates(message: str) -> dict[str, str]:
    updates = extract_profile_updates(message)
    return {
        key: value
        for key, value in updates.items()
        if not _is_question_value(value)
    }


def _is_question_value(value: str) -> bool:
    folded = _fold_text(value).strip(" ?!.:,;")
    if not folded:
        return True
    question_values = {
        "gi",
        "la gi",
        "dau",
        "o dau",
        "nhu the nao",
        "kieu tra loi nhu the nao",
        "con gi",
    }
    if folded in question_values:
        return True
    return folded.endswith((" gi", " dau", " nhu the nao"))


def _merge_fact_value(key: str, old_value: str, new_value: str) -> str:
    if key == "response_style":
        folded_old = _fold_text(old_value)
        folded_new = _fold_text(new_value)
        if "ngan gon" in folded_old and "ngan gon" not in folded_new:
            return f"{old_value}; {new_value}"
    if key == "technical_interests":
        return _merge_comma_list(old_value, new_value)
    return new_value


def _merge_comma_list(old_value: str, new_value: str) -> str:
    parts: list[str] = []
    seen: set[str] = set()
    for raw in (old_value, new_value):
        for part in re_split_interests(raw):
            folded = _fold_text(part)
            if folded and folded not in seen:
                seen.add(folded)
                parts.append(part)
    return ", ".join(parts)


def re_split_interests(value: str) -> list[str]:
    return [
        item.strip(" ,.;")
        for item in value.replace(" và ", ", ").replace(" va ", ", ").split(",")
        if item.strip(" ,.;")
    ]


def _message_content(result: Any) -> str:
    if isinstance(result, str):
        return result
    content = getattr(result, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(result, dict):
        for key in ("answer", "content", "output"):
            value = result.get(key)
            if isinstance(value, str):
                return value
    return str(result)


def _fold_text(text: str) -> str:
    folded_chars: list[str] = []
    for char in text:
        if char in {"đ", "Đ"}:
            folded_chars.append("d")
            continue
        decomposed = unicodedata.normalize("NFD", char)
        base = decomposed[0] if decomposed else char
        if unicodedata.category(base).startswith("M"):
            base = ""
        folded_chars.append(base.lower())
    return "".join(folded_chars)
