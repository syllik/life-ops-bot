import json

import httpx
import pytest

from life_ops_bot.github import GitHubError, GitHubIssues


def issue_json(
    number: int = 12,
    *,
    labels: list[object] | None = None,
    state: str = "open",
    body: str = "",
) -> dict[str, object]:
    return {
        "number": number,
        "html_url": f"https://github.com/owner/tasks/issues/{number}",
        "title": "Issue",
        "labels": labels or [],
        "state": state,
        "body": body,
    }


def make_client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url="https://api.github.com", transport=httpx.MockTransport(handler)
    )


@pytest.mark.asyncio
async def test_close_issue_is_repeatable_state_setting_operation() -> None:
    requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        assert json.loads(request.content) == {"state": "closed", "state_reason": "completed"}
        return httpx.Response(200, json=issue_json(7, state="closed"))

    async with make_client(handler) as client:
        github = GitHubIssues(token="secret", repository="owner/tasks", client=client)
        first = await github.close_issue(7)
        second = await github.close_issue(7)
    assert first.state == second.state == "closed"
    assert requests == 2


@pytest.mark.asyncio
async def test_set_later_replaces_conflicting_state_labels_and_keeps_issue_open() -> None:
    calls: list[tuple[str, dict[str, object] | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content) if request.content else None
        calls.append((request.method, payload))
        if request.method == "GET":
            return httpx.Response(
                200,
                json=issue_json(
                    8,
                    labels=[{"name": "custom-a"}, "custom-b", {"name": "state:now"}, 123],
                ),
            )
        return httpx.Response(
            200,
            json=issue_json(
                8,
                labels=[
                    {"name": "custom-a"},
                    {"name": "custom-b"},
                    {"name": "state:later"},
                ],
                state="open",
            ),
        )

    async with make_client(handler) as client:
        github = GitHubIssues(token="secret", repository="owner/tasks", client=client)
        issue = await github.set_later(8)

    assert calls == [
        ("GET", None),
        (
            "PATCH",
            {
                "labels": ["custom-a", "custom-b", "state:later"],
                "state": "open",
            },
        ),
    ]
    assert issue.labels == ("custom-a", "custom-b", "state:later")
    assert issue.state == "open"


@pytest.mark.asyncio
async def test_set_later_is_noop_when_already_later_and_open() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        return httpx.Response(
            200,
            json=issue_json(8, labels=[{"name": "state:later"}], state="open"),
        )

    async with make_client(handler) as client:
        github = GitHubIssues(token="secret", repository="owner/tasks", client=client)
        issue = await github.set_later(8)
    assert issue.labels == ("state:later",)
    assert issue.state == "open"


@pytest.mark.asyncio
async def test_set_later_reopens_closed_issue() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(
                200,
                json=issue_json(8, labels=[{"name": "state:later"}], state="closed"),
            )
        assert json.loads(request.content) == {"labels": ["state:later"], "state": "open"}
        return httpx.Response(
            200,
            json=issue_json(8, labels=[{"name": "state:later"}], state="open"),
        )

    async with make_client(handler) as client:
        github = GitHubIssues(token="secret", repository="owner/tasks", client=client)
        issue = await github.set_later(8)

    assert issue.state == "open"
    assert calls == 2


@pytest.mark.asyncio
async def test_close_rejects_false_success_response() -> None:
    async with make_client(
        lambda _: httpx.Response(200, json=issue_json(7, state="open"))
    ) as client:
        github = GitHubIssues(token="secret", repository="owner/tasks", client=client)
        with pytest.raises(GitHubError, match="did not close"):
            await github.close_issue(7)


@pytest.mark.asyncio
async def test_later_rejects_conflicting_state_response() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(200, json=issue_json(8, labels=[{"name": "state:now"}]))
        return httpx.Response(
            200,
            json=issue_json(
                8,
                labels=[{"name": "state:later"}, {"name": "state:waiting"}],
                state="open",
            ),
        )

    async with make_client(handler) as client:
        github = GitHubIssues(token="secret", repository="owner/tasks", client=client)
        with pytest.raises(GitHubError, match="Later state"):
            await github.set_later(8)


@pytest.mark.asyncio
async def test_later_rejects_closed_response() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(200, json=issue_json(8, labels=[{"name": "state:now"}]))
        return httpx.Response(
            200,
            json=issue_json(8, labels=[{"name": "state:later"}], state="closed"),
        )

    async with make_client(handler) as client:
        github = GitHubIssues(token="secret", repository="owner/tasks", client=client)
        with pytest.raises(GitHubError, match="Later state"):
            await github.set_later(8)
