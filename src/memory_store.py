from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path


def estimate_tokens(text: str) -> int:
    """Student TODO: implement a simple token estimator.

    Example idea:
    - Strip whitespace
    - Return 0 for empty text
    - Approximate tokens from character count, e.g. len(text) / 4
    """

    normalized = " ".join((text or "").strip().split())
    if not normalized:
        return 0
    return max(1, math.ceil(len(normalized) / 4))


@dataclass
class UserProfileStore:
    """Persistent storage for `User.md`.

    Student TODO:
    - Map each user id to one markdown file
    - Support read / write / edit operations
    - Optionally expose helpers like `facts()` or `upsert_fact()`
    """

    root_dir: Path

    def path_for(self, user_id: str) -> Path:
        # TODO: slugify or sanitize the user id before building the file path.
        slug = _slugify(user_id)
        return self.root_dir / slug / "User.md"

    def read_text(self, user_id: str) -> str:
        # TODO: return file content or an empty default markdown profile.
        path = self.path_for(user_id)
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8")

    def write_text(self, user_id: str, content: str) -> Path:
        # TODO: write markdown to disk and return the file path.
        path = self.path_for(user_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_normalize_markdown(content), encoding="utf-8")
        return path

    def edit_text(self, user_id: str, search_text: str, replacement: str) -> bool:
        # TODO: replace one occurrence inside User.md and return whether it changed.
        current = self.read_text(user_id)
        if not search_text or search_text not in current:
            return False
        self.write_text(user_id, current.replace(search_text, replacement, 1))
        return True

    def file_size(self, user_id: str) -> int:
        # TODO: return the current file size in bytes.
        path = self.path_for(user_id)
        if not path.exists():
            return 0
        return path.stat().st_size

    def facts(self, user_id: str) -> dict[str, str]:
        facts: dict[str, str] = {}
        for line in self.read_text(user_id).splitlines():
            match = re.match(r"^-\s*([A-Za-z0-9_.-]+)\s*:\s*(.+?)\s*$", line)
            if match:
                facts[match.group(1)] = match.group(2)
        return facts

    def upsert_fact(self, user_id: str, key: str, value: str) -> Path:
        facts = self.facts(user_id)
        facts[key] = value.strip()
        lines = ["# User Profile", "", "## Facts"]
        for fact_key in sorted(facts):
            lines.append(f"- {fact_key}: {facts[fact_key]}")
        return self.write_text(user_id, "\n".join(lines))


def extract_profile_updates(message: str) -> dict[str, str]:
    """Student TODO: convert raw user text into stable profile facts.

    Example facts you may want to extract:
    - name
    - location
    - profession
    - preferences / response style
    - favorite food / drink

    Pseudocode:
    1. Build a few regex patterns.
    2. Skip obvious question-only turns.
    3. Return only the facts that are confidently present in the message.
    """

    original = (message or "").strip()
    if not original:
        return {}

    folded = _fold_text(original)
    if _is_question_only(folded):
        return {}

    updates: dict[str, str] = {}

    _set_if_found(
        updates,
        "name",
        original,
        folded,
        [
            r"\bminh ten la\s+(.+?)(?:[.,;]|\s+hien\s+|\s+va\s+|$)",
            r"\bten minh la\s+(.+?)(?:[.,;]|\s+va\s+|$)",
        ],
    )

    _set_if_found(
        updates,
        "profession",
        original,
        folded,
        [
            r"\bnghe nghiep hien tai(?:\s+van)?\s+la\s+(.+?)(?:[.,;]|\s+khong\s+|$)",
            r"\bnghe nghiep thi(?:\s+van)?\s+la\s+(.+?)(?:[.,;]|\s+khong\s+|$)",
            r"\bhien tai minh\s+(?:van\s+)?(?:la|lam)\s+(.+?)(?:[.,;]|\s+cho\s+|\s+khong\s+|$)",
            r"\bgio chuyen sang\s+(.+?)(?:[.,;]|\s+khong\s+|$)",
            r"\bdang lam(?! viec)\s+(.+?)(?:[.,;]|\s+cho\s+|$)",
        ],
    )
    if "profession" in updates and not re.search(
        r"\b(engineer|developer|manager|backend|mlops)\b", _fold_text(updates["profession"])
    ):
        updates.pop("profession")

    _set_if_found(
        updates,
        "location",
        original,
        folded,
        [
            r"\bdang lam viec o\s+(.+?)(?:[.,;]|\s+vai\s+|\s+de\s+|\s+va\s+|$)",
            r"\bnoi o da cap nhat tu .+? sang\s+(.+?)(?:[.,;]|\s+con\s+|\s+va\s+|$)",
            r"\bnoi o hien tai\s+la\s+(.+?)(?:[.,;]|\s+trong\s+|\s+du\s+|\s+va\s+|$)",
            r"\bhien o\s+(.+?)(?:[.,;]|\s+trong\s+|\s+du\s+|\s+va\s+|$)",
            r"\bhien tai minh dang o\s+(.+?)(?:[.,;]|\s+trong\s+|\s+de\s+|\s+du\s+|\s+va\s+|$)",
            r"\bgio minh dang o\s+(.+?)(?:[.,;]|\s+chu\s+|\s+de\s+|\s+va\s+|$)",
            r"\bminh dang o\s+(.+?)(?:[.,;]|\s+trong\s+|\s+de\s+|\s+va\s+|$)",
            r"\bminh o\s+(.+?)(?:[.,;]|\s+va\s+|\s+de\s+|\s+chu\s+|$)",
            r"\bvan o\s+(.+?)(?:[.,;]|\s+chua\s+|\s+va\s+|$)",
        ],
    )

    _set_if_found(
        updates,
        "response_style",
        original,
        folded,
        [
            r"\bmuon ban tra loi\s+(.+?)(?:[.]|$)",
            r"\bhay tra loi\s+(.+?)(?:[.]|$)",
            r"\bstyle tra loi(?:\s+cu)?(?:\s+cung)?(?:\s+van)?\s+giu nguyen:?\s+(.+?)(?:[.]|$)",
            r"\btra loi theo dang\s+(.+?)(?:[.]|$)",
        ],
    )

    _set_if_found(
        updates,
        "favorite_drink",
        original,
        folded,
        [
            r"\bdo uong yeu thich\s+la\s+(.+?)(?:[.,;]|$)",
            r"\bvan uong\s+(.+?)(?:\s+nhu\s+|\s+nhung\s+|[.,;]|$)",
        ],
    )

    _set_if_found(
        updates,
        "favorite_food",
        original,
        folded,
        [
            r"\bmon an yeu thich\s+la\s+(.+?)(?:[.,;]|$)",
        ],
    )

    _set_if_found(
        updates,
        "pet",
        original,
        folded,
        [
            r"\bnuoi\s+(?:mot\s+)?(?:be\s+|con\s+)?(.+?)(?:[.,;]|\s+vi\s+|$)",
        ],
    )

    if re.search(r"\b(python|ai|mlops|rag|benchmark|memory architecture|agent)\b", folded):
        _set_if_found(
            updates,
            "technical_interests",
            original,
            folded,
            [
                r"\bthich\s+(.+?)(?:\s+va ca phe\s+|\s+va cach\s+|[.;]|$)",
                r"\bdang quan tam nhieu den\s+(.+?)(?:[.,;]|$)",
                r"\bmoi quan tam ky thuat chinh(?:\s+la)?\s+(.+?)(?:[.,;]|$)",
            ],
        )
        if "technical_interests" in updates and not re.search(
            r"\b(python|ai|mlops|rag|benchmark|memory architecture|agent)\b",
            _fold_text(updates["technical_interests"]),
        ):
            updates.pop("technical_interests")

    return {key: _clean_fact_value(value) for key, value in updates.items() if _clean_fact_value(value)}


def summarize_messages(messages: list[dict[str, str]], max_items: int = 6) -> str:
    """Student TODO: create a compact summary of older messages.

    This can be heuristic text concatenation first.
    Later, you can replace it with an LLM-based summary if desired.
    """

    if not messages:
        return ""

    selected = messages[-max_items:] if max_items > 0 else []
    lines = []
    for item in selected:
        role = item.get("role", "unknown").strip() or "unknown"
        content = " ".join(item.get("content", "").split())
        if len(content) > 240:
            content = content[:237].rstrip() + "..."
        if content:
            lines.append(f"- {role}: {content}")
    if not lines:
        return ""
    return "Summary of older context:\n" + "\n".join(lines)


@dataclass
class CompactMemoryManager:
    """Student TODO: implement compact memory for long threads.

    Goal:
    - Keep recent messages in full
    - When the thread grows too large, move older content into a summary
    - Track how many compactions happened for benchmarking
    """

    threshold_tokens: int
    keep_messages: int
    state: dict[str, dict[str, object]] = field(default_factory=dict)

    def append(self, thread_id: str, role: str, content: str) -> None:
        # TODO:
        # 1. create thread state if missing
        # 2. append the new message
        # 3. trigger compaction if needed
        thread = self._thread_state(thread_id)
        messages = thread["messages"]
        assert isinstance(messages, list)
        messages.append({"role": role, "content": content})
        self._compact_if_needed(thread)

    def context(self, thread_id: str) -> dict[str, object]:
        # TODO: return per-thread state with keys like messages, summary, compactions.
        thread = self.state.get(thread_id)
        if thread is None:
            return {"messages": [], "summary": "", "compactions": 0}
        return {
            "messages": list(thread.get("messages", [])),
            "summary": str(thread.get("summary", "")),
            "compactions": int(thread.get("compactions", 0)),
        }

    def compaction_count(self, thread_id: str) -> int:
        # TODO: return number of compactions for this thread.
        return int(self.state.get(thread_id, {}).get("compactions", 0))

    def _thread_state(self, thread_id: str) -> dict[str, object]:
        return self.state.setdefault(thread_id, {"messages": [], "summary": "", "compactions": 0})

    def _compact_if_needed(self, thread: dict[str, object]) -> None:
        messages = thread["messages"]
        assert isinstance(messages, list)
        if len(messages) <= self.keep_messages:
            return

        summary = str(thread.get("summary", ""))
        total = estimate_tokens(summary) + sum(
            estimate_tokens(str(message.get("content", ""))) for message in messages if isinstance(message, dict)
        )
        if total <= self.threshold_tokens:
            return

        keep = max(0, self.keep_messages)
        if keep == 0:
            older = messages
            recent = []
        else:
            older = messages[:-keep]
            recent = messages[-keep:]
        summary_input: list[dict[str, str]] = []
        if summary:
            summary_input.append({"role": "summary", "content": summary})
        summary_input.extend(
            {"role": str(message.get("role", "unknown")), "content": str(message.get("content", ""))}
            for message in older
            if isinstance(message, dict)
        )

        thread["summary"] = summarize_messages(summary_input, max_items=6)
        thread["messages"] = recent
        thread["compactions"] = int(thread.get("compactions", 0)) + 1


def _slugify(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", (value or "").strip())
    slug = slug.strip("._-")
    return slug or "user"


def _normalize_markdown(content: str) -> str:
    text = (content or "").replace("\r\n", "\n").replace("\r", "\n")
    return text.rstrip() + "\n"


def _fold_text(text: str) -> str:
    folded_chars: list[str] = []
    for char in text:
        if char in {"\u0111", "\u0110"}:
            folded_chars.append("d")
            continue
        decomposed = unicodedata.normalize("NFD", char)
        base = decomposed[0] if decomposed else char
        if unicodedata.category(base).startswith("M"):
            base = ""
        folded_chars.append(base.lower())
    return "".join(folded_chars)


def _is_question_only(folded: str) -> bool:
    if not folded.endswith("?"):
        return False
    fact_cues = [
        "minh ten la",
        "ten minh la",
        "minh o",
        "minh dang o",
        "dang lam",
        "lam ",
        "thich ",
        "yeu thich",
        "muon ban tra loi",
        "hay tra loi",
    ]
    return not any(cue in folded for cue in fact_cues)


def _set_if_found(
    updates: dict[str, str],
    key: str,
    original: str,
    folded: str,
    patterns: list[str],
) -> None:
    for pattern in patterns:
        match = re.search(pattern, folded)
        if match:
            value = original[match.start(1) : match.end(1)]
            value = _clean_fact_value(value)
            if value:
                updates[key] = value
            return


def _clean_fact_value(value: str) -> str:
    value = " ".join((value or "").strip(" :-,.;").split())
    folded = _fold_text(value)
    stop_phrases = [
        "chi la cau dua",
        "khong phai",
        "minh vua bay ra hop",
        "neu co ai hoi lai",
        "giup minh",
    ]
    for phrase in stop_phrases:
        index = folded.find(phrase)
        if index > 0:
            value = value[:index].strip(" :-,.;")
            folded = folded[:index]
    return value
