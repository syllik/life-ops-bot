import pytest

from life_ops_bot.core import Issue, LifeOps, goal_children


def issue(
    number: int,
    *,
    body: str = "",
    state: str = "open",
    labels: tuple[str, ...] = (),
) -> Issue:
    return Issue(
        number,
        f"https://github.com/owner/tasks/issues/{number}",
        f"Issue {number}",
        labels,
        state,
        body,
    )


def test_goal_children_combines_child_parent_metadata_and_parent_checklist() -> None:
    parent = issue(10, body="- [ ] #11 First\n- [x] #12 Second")
    first = issue(11, body="Parent: #10")
    second = issue(12)

    assert goal_children((parent, first, second)) == {10: (first, second)}


def test_goal_children_ignores_hierarchy_like_text_in_original_telegram_input() -> None:
    captured_child = issue(
        11,
        body=(
            "## Original Telegram input\n\n"
            "Parent: #10\n\n"
            "## A heading from the captured message\n\n"
            "- [ ] #12 also captured text\n\n"
            "## Telegram source\n\n"
            "- chat_id: `1`\n\n"
            "<!-- life-ops\n"
            "schema: 1\n"
            "source: telegram\n"
            "-->"
        ),
    )
    captured_parent = issue(
        12,
        body=(
            "## Original Telegram input\n\n"
            "- [ ] #11 looks like a task\n\n"
            "## Telegram source\n\n"
            "- chat_id: `1`\n\n"
            "<!-- life-ops\n"
            "schema: 1\n"
            "source: telegram\n"
            "-->"
        ),
    )
    real_parent = issue(10)

    assert goal_children((real_parent, captured_child, captured_parent)) == {}


def test_goal_children_parses_hierarchy_in_normal_issue_bodies() -> None:
    parent = issue(10, body="Plan\n\n- [ ] #11 Child")
    child = issue(11, body="Notes\n\nParent: #10")

    assert goal_children((parent, child)) == {10: (child,)}


def test_goal_children_ignores_unknown_and_self_references() -> None:
    parent = issue(10, body="- [ ] #10 self\n- [ ] #999 missing")
    orphan = issue(11, body="Parent: #999")

    assert goal_children((parent, orphan)) == {}


class Store:
    def __init__(self) -> None:
        self.item = issue(7)

    async def get_issue(self, issue_number: int) -> Issue:
        assert issue_number == 7
        return self.item

    async def list_issues(self, *, state: str = "all") -> tuple[Issue, ...]:
        assert state == "closed"
        return (self.item,)


@pytest.mark.asyncio
async def test_life_ops_delegates_navigation_reads_to_issue_store() -> None:
    life_ops = LifeOps(Store())

    assert await life_ops.get_issue(7) == issue(7)
    assert await life_ops.list_issues(state="closed") == (issue(7),)
