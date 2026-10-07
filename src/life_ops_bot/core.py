from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

INBOX_LABEL = "state:inbox"
LATER_LABEL = "state:later"
STATE_PREFIX = "state:"
TITLE_LIMIT = 80

_PARENT_RE = re.compile(r"(?mi)^\s*Parent:\s*#(\d+)\s*$")
_CHECKLIST_CHILD_RE = re.compile(r"(?mi)^\s*-\s*\[[ x]\]\s*#(\d+)\b")
_ORIGINAL_INPUT_HEADING_RE = re.compile(r"(?m)^## Original Telegram input\s*$")
_BOT_METADATA_MARKER = "<!-- life-ops"
_METADATA_CHAT_ID_RE = re.compile(r"(?m)^telegram_chat_id:\s*(-?\d+)\s*$")
_METADATA_MESSAGE_ID_RE = re.compile(r"(?m)^telegram_message_id:\s*(\d+)\s*$")


@dataclass(frozen=True, slots=True)
class Capture:
    text: str
    chat_id: int
    message_id: int
    forwarded_from: str | None = None
    link_targets: tuple[str, ...] = ()

    @property
    def source_key(self) -> str:
        return f"telegram:{self.chat_id}:{self.message_id}"


@dataclass(frozen=True, slots=True)
class Issue:
    number: int
    url: str
    title: str
    labels: tuple[str, ...] = ()
    state: str = "open"
    body: str = ""


class IssueStore(Protocol):
    async def find_by_source_key(self, source_key: str) -> Issue | None: ...

    async def create_issue(self, *, title: str, body: str, labels: tuple[str, ...]) -> Issue: ...

    async def get_issue(self, issue_number: int) -> Issue: ...

    async def list_issues(self, *, state: str = "all") -> tuple[Issue, ...]: ...

    async def close_issue(self, issue_number: int) -> Issue: ...

    async def set_later(self, issue_number: int) -> Issue: ...


class LifeOps:
    def __init__(self, issues: IssueStore) -> None:
        self._issues = issues

    async def capture(self, capture: Capture) -> Issue:
        existing = await self._issues.find_by_source_key(capture.source_key)
        if existing is not None:
            return existing

        return await self._issues.create_issue(
            title=make_title(capture.text),
            body=make_issue_body(capture),
            labels=(INBOX_LABEL,),
        )

    async def get_issue(self, issue_number: int) -> Issue:
        return await self._issues.get_issue(issue_number)

    async def list_issues(self, *, state: str = "all") -> tuple[Issue, ...]:
        return await self._issues.list_issues(state=state)

    async def done(self, issue_number: int) -> Issue:
        return await self._issues.close_issue(issue_number)

    async def later(self, issue_number: int) -> Issue:
        return await self._issues.set_later(issue_number)


def goal_children(issues: tuple[Issue, ...]) -> dict[int, tuple[Issue, ...]]:
    by_number = {issue.number: issue for issue in issues}
    children: dict[int, dict[int, Issue]] = {}

    for issue in issues:
        hierarchy_text = _hierarchy_text(issue.body)
        for match in _PARENT_RE.finditer(hierarchy_text):
            parent_number = int(match.group(1))
            if parent_number in by_number and parent_number != issue.number:
                children.setdefault(parent_number, {})[issue.number] = issue

    for parent in issues:
        hierarchy_text = _hierarchy_text(parent.body)
        for match in _CHECKLIST_CHILD_RE.finditer(hierarchy_text):
            child_number = int(match.group(1))
            child = by_number.get(child_number)
            if child is not None and child.number != parent.number:
                children.setdefault(parent.number, {})[child.number] = child

    return {
        parent_number: tuple(sorted(items.values(), key=lambda item: item.number))
        for parent_number, items in children.items()
    }


def _hierarchy_text(body: str) -> str:
    marker_index = body.rfind(_BOT_METADATA_MARKER)
    original_heading = _ORIGINAL_INPUT_HEADING_RE.search(body)
    if marker_index < 0 or original_heading is None:
        return body

    metadata = body[marker_index:]
    chat_match = _METADATA_CHAT_ID_RE.search(metadata)
    message_match = _METADATA_MESSAGE_ID_RE.search(metadata)
    if chat_match is None or message_match is None:
        return ""

    chat_id = re.escape(chat_match.group(1))
    message_id = re.escape(message_match.group(1))
    source_re = re.compile(
        rf"(?m)^## Telegram source\s*$\n\s*\n"
        rf"- chat_id: `{chat_id}`\s*$\n"
        rf"- message_id: `{message_id}`\s*$"
    )
    source_matches = list(source_re.finditer(body[:marker_index]))
    if not source_matches:
        return ""

    source_start = source_matches[-1].start()
    if source_start <= original_heading.start():
        return ""

    return body[: original_heading.start()] + body[source_start:]


def make_title(text: str) -> str:
    normalized = " ".join(text.split())
    if not normalized:
        return "Telegram capture"
    if len(normalized) <= TITLE_LIMIT:
        return normalized
    return normalized[: TITLE_LIMIT - 1].rstrip() + "…"


def make_issue_body(capture: Capture) -> str:
    source_lines = [
        "## Telegram source",
        "",
        f"- chat_id: `{capture.chat_id}`",
        f"- message_id: `{capture.message_id}`",
    ]
    if capture.forwarded_from is not None:
        source_lines.append(f"- forwarded_from: {capture.forwarded_from}")
    for target in capture.link_targets:
        source_lines.append(f"- text_link_target: {target}")

    return "\n".join(
        [
            "## Original Telegram input",
            "",
            capture.text,
            "",
            *source_lines,
            "",
            "<!-- life-ops",
            "schema: 1",
            "source: telegram",
            f"source_key: {capture.source_key}",
            f"telegram_chat_id: {capture.chat_id}",
            f"telegram_message_id: {capture.message_id}",
            "-->",
        ]
    )
