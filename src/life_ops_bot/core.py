from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

INBOX_LABEL = "state:inbox"
LATER_LABEL = "state:later"
STATE_PREFIX = "state:"
TITLE_LIMIT = 80


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


class IssueStore(Protocol):
    async def find_by_source_key(self, source_key: str) -> Issue | None: ...

    async def create_issue(self, *, title: str, body: str, labels: tuple[str, ...]) -> Issue: ...

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

    async def done(self, issue_number: int) -> Issue:
        return await self._issues.close_issue(issue_number)

    async def later(self, issue_number: int) -> Issue:
        return await self._issues.set_later(issue_number)


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
