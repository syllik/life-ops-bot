from dataclasses import replace

import pytest

from life_ops_bot.core import Capture, Issue, LifeOps, make_issue_body, make_title


class FakeIssues:
    def __init__(self) -> None:
        self.existing: Issue | None = None
        self.created: list[dict[str, object]] = []
        self.closed: list[int] = []
        self.later: list[int] = []

    async def find_by_source_key(self, source_key: str) -> Issue | None:
        self.last_source_key = source_key
        return self.existing

    async def create_issue(self, *, title: str, body: str, labels: tuple[str, ...]) -> Issue:
        self.created.append({"title": title, "body": body, "labels": labels})
        return Issue(41, "https://github.test/issues/41", title, labels)

    async def close_issue(self, issue_number: int) -> Issue:
        self.closed.append(issue_number)
        return Issue(
            issue_number, f"https://github.test/issues/{issue_number}", "x", state="closed"
        )

    async def set_later(self, issue_number: int) -> Issue:
        self.later.append(issue_number)
        return Issue(
            issue_number, f"https://github.test/issues/{issue_number}", "x", ("state:later",)
        )


@pytest.mark.asyncio
async def test_capture_creates_inbox_issue_and_preserves_input() -> None:
    store = FakeIssues()
    life_ops = LifeOps(store)
    original = "  keep  exact whitespace\nhttps://example.com/?a=1&b=2  "
    capture = Capture(original, chat_id=12, message_id=34, forwarded_from="user @alice (id=7)")

    issue = await life_ops.capture(capture)

    assert issue.number == 41
    assert store.last_source_key == "telegram:12:34"
    assert store.created[0]["labels"] == ("state:inbox",)
    body = store.created[0]["body"]
    assert isinstance(body, str)
    assert original in body
    assert "forwarded_from: user @alice (id=7)" in body
    assert "source_key: telegram:12:34" in body


@pytest.mark.asyncio
async def test_capture_returns_existing_issue_without_duplicate_create() -> None:
    store = FakeIssues()
    store.existing = Issue(9, "https://github.test/issues/9", "existing")
    life_ops = LifeOps(store)

    issue = await life_ops.capture(Capture("same", 1, 2))

    assert issue == store.existing
    assert store.created == []


@pytest.mark.asyncio
async def test_done_and_later_delegate_state_changes() -> None:
    store = FakeIssues()
    life_ops = LifeOps(store)

    done = await life_ops.done(7)
    later = await life_ops.ater(8)

    assert done.state == "closed"
    assert later.labels == ("state:later",)
    assert store.closed == [7]
    assert store.later == [8]


def test_make_title_is_deterministic_and_bounded() -> None:
    assert make_title("  a\nb\t c  ") == "a b c"
    assert make_title("   ") == "Telegram capture"
    title = make_title("x" * 100)
    assert len(title) == 80
    assert title.endswith"…")


def test_make_issue_body_omits_forward_line_for_normal_message() -> None:
    capture = Capture("hello", 1, 2, forwarded_from="source")
    with_forward = make_issue_body(capture)
    without_forward = make_issue_body(replace(capture, forwarded_from=None))
    assert "forwarded_from:" in with_forward
    assert "forwarded_from:" not in without_forward
