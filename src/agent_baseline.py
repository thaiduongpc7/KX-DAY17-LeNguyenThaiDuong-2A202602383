from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from config import LabConfig, load_config
from memory_store import estimate_tokens
from model_provider import build_chat_model


@dataclass
class SessionState:
    messages: list[dict[str, str]] = field(default_factory=list)
    token_usage: int = 0
    prompt_tokens_processed: int = 0


class BaselineAgent:
    """Student TODO: implement Agent A.

    Requirements:
    - Within-session memory only
    - No persistent `User.md`
    - Should forget long-term facts across new threads
    """

    def __init__(self, config: LabConfig | None = None, force_offline: bool = False) -> None:
        self.config = config or load_config()
        self.force_offline = force_offline
        self.sessions: dict[str, SessionState] = {}

        self.langchain_agent = None if force_offline else self._maybe_build_langchain_agent()

    def reply(self, user_id: str, thread_id: str, message: str) -> dict[str, Any]:
        """Student TODO: return the agent response and token accounting.

        Pseudocode:
        - If a live agent exists, call the live path.
        - Otherwise use a deterministic offline path.
        """

        if self.langchain_agent is None:
            return self._reply_offline(thread_id, message)

        session = self.sessions.setdefault(thread_id, SessionState())
        session.messages.append({"role": "user", "content": message})
        prompt_tokens = _messages_token_count(session.messages)

        result = self.langchain_agent.invoke(
            [(item["role"], item["content"]) for item in session.messages]
        )
        answer = _message_content(result)
        agent_tokens = estimate_tokens(answer)

        session.prompt_tokens_processed += prompt_tokens
        session.token_usage += agent_tokens
        session.messages.append({"role": "assistant", "content": answer})

        return {
            "answer": answer,
            "agent_tokens": agent_tokens,
            "prompt_tokens": prompt_tokens,
            "total_agent_tokens": session.token_usage,
            "total_prompt_tokens": session.prompt_tokens_processed,
        }

    def token_usage(self, thread_id: str) -> int:
        # TODO: return cumulative agent token count for one thread.
        return self.sessions.get(thread_id, SessionState()).token_usage

    def prompt_token_usage(self, thread_id: str) -> int:
        # TODO: estimate how much prompt context this baseline kept processing.
        return self.sessions.get(thread_id, SessionState()).prompt_tokens_processed

    def compaction_count(self, thread_id: str) -> int:
        # Baseline has no compact memory.
        return 0

    def _reply_offline(self, thread_id: str, message: str) -> dict[str, Any]:
        """Student TODO: implement a simple offline behavior.

        Suggested behavior:
        - Store the new user message in the session
        - Generate a short deterministic reply
        - Update token counts
        - Never remember facts across different thread ids
        """

        session = self.sessions.setdefault(thread_id, SessionState())
        session.messages.append({"role": "user", "content": message})

        prompt_tokens = _messages_token_count(session.messages)
        answer = _offline_response(session.messages, message)
        agent_tokens = estimate_tokens(answer)

        session.prompt_tokens_processed += prompt_tokens
        session.token_usage += agent_tokens
        session.messages.append({"role": "assistant", "content": answer})

        return {
            "answer": answer,
            "agent_tokens": agent_tokens,
            "prompt_tokens": prompt_tokens,
            "total_agent_tokens": session.token_usage,
            "total_prompt_tokens": session.prompt_tokens_processed,
        }

    def _maybe_build_langchain_agent(self):
        """Student TODO: optionally wire `create_agent` + `InMemorySaver` here.

        Use `build_chat_model(self.config.model)` so the baseline can run with any supported provider.
        """

        try:
            return build_chat_model(self.config.model)
        except Exception:
            return None


def _messages_token_count(messages: list[dict[str, str]]) -> int:
    return sum(
        estimate_tokens(f"{item.get('role', '')}: {item.get('content', '')}")
        for item in messages
    )


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


def _offline_response(messages: list[dict[str, str]], message: str) -> str:
    folded = _fold_text(message)
    facts = _thread_facts(messages)

    if _asks_about_name(folded):
        return _fact_answer(facts, "name", "ten")
    if _asks_about_profession(folded):
        return _fact_answer(facts, "profession", "nghe nghiep")
    if _asks_about_location(folded):
        return _fact_answer(facts, "location", "noi o")
    if _asks_about_style(folded):
        return _fact_answer(facts, "response_style", "style tra loi")

    if any(value for value in _facts_from_message(message).values()):
        return "Minh da ghi nhan thong tin do trong thread nay."
    return "Minh chi co ngu canh trong thread hien tai, nen se tra loi dua tren cac tin nhan o day."


def _fact_answer(facts: dict[str, str], key: str, label: str) -> str:
    value = facts.get(key)
    if not value:
        return f"Minh khong biet {label} cua ban trong thread nay."
    return f"Trong thread nay, ban da noi {label} cua ban la {value}."


def _thread_facts(messages: list[dict[str, str]]) -> dict[str, str]:
    facts: dict[str, str] = {}
    for item in messages:
        if item.get("role") == "user":
            facts.update(_facts_from_message(item.get("content", "")))
    return facts


def _facts_from_message(message: str) -> dict[str, str]:
    original = (message or "").strip()
    if not original:
        return {}

    folded = _fold_text(original)
    facts: dict[str, str] = {}

    _set_if_found(
        facts,
        "name",
        original,
        folded,
        [
            r"\bminh ten la\s+(.+?)(?:[.,;!?]|\s+va\s+|\s+hien\s+|$)",
            r"\bten minh la\s+(.+?)(?:[.,;!?]|\s+va\s+|\s+hien\s+|$)",
        ],
    )
    _set_if_found(
        facts,
        "profession",
        original,
        folded,
        [
            r"\bminh (?:dang |hien tai )?(?:lam|la)\s+(.+?)(?:[.,;!?]|\s+cho\s+|\s+va\s+|$)",
            r"\bnghe nghiep(?: hien tai)?(?: cua minh)? la\s+(.+?)(?:[.,;!?]|\s+va\s+|$)",
        ],
    )
    _set_if_found(
        facts,
        "location",
        original,
        folded,
        [
            r"\bminh (?:dang |hien )?o\s+(.+?)(?:[.,;!?]|\s+va\s+|\s+de\s+|$)",
            r"\bnoi o(?: hien tai)?(?: cua minh)? la\s+(.+?)(?:[.,;!?]|\s+va\s+|$)",
        ],
    )
    _set_if_found(
        facts,
        "response_style",
        original,
        folded,
        [
            r"\bmuon ban tra loi\s+(.+?)(?:[.!?]|$)",
            r"\bhay tra loi\s+(.+?)(?:[.!?]|$)",
            r"\bstyle tra loi(?: cua minh)? la\s+(.+?)(?:[.!?]|$)",
        ],
    )

    return facts


def _set_if_found(
    facts: dict[str, str],
    key: str,
    original: str,
    folded: str,
    patterns: list[str],
) -> None:
    for pattern in patterns:
        match = re.search(pattern, folded)
        if match:
            value = " ".join(original[match.start(1) : match.end(1)].strip(" :-,.;!?").split())
            if value:
                facts[key] = value
            return


def _asks_about_name(folded: str) -> bool:
    return any(phrase in folded for phrase in ("minh ten gi", "ten minh la gi", "nho ten minh"))


def _asks_about_profession(folded: str) -> bool:
    return any(phrase in folded for phrase in ("minh lam gi", "nghe nghiep", "cong viec cua minh"))


def _asks_about_location(folded: str) -> bool:
    return any(phrase in folded for phrase in ("minh o dau", "noi o cua minh", "minh dang o dau"))


def _asks_about_style(folded: str) -> bool:
    return any(phrase in folded for phrase in ("style tra loi", "tra loi minh thich", "minh thich ban tra loi"))


def _fold_text(text: str) -> str:
    chars: list[str] = []
    for char in text:
        if char in {"đ", "Đ"}:
            chars.append("d")
            continue
        decomposed = unicodedata.normalize("NFD", char)
        base = decomposed[0] if decomposed else char
        chars.append(base.lower())
    return "".join(chars)
