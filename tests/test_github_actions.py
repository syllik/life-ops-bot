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
        "html_url": f"https://github.com/syllik/life-ops/issues/{number}",
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
        github = GitHubIssues(token="secret", repository="syllik/life-ops", client=client)
        first = await github.close_issue(7)
        second = await github.close_issue(7)
    assert first.state == second.state == "closed"
    assert requests == 2


@pytest.mark.asyncio
async def test_set_later_replaces_only_conflicting_state_labels() -> None:
    calls: list[tuple[str, dict[str, object] | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content) if request.content else None
        calls.append((request.method, payload))
        if request.method == "GET":
            return httpx.Response(
                200,
                json=issue_json(
                    8,
                    labels=[{"name": "area:software"}, "type:task", {"name": "state:now"}, 123],
                ),
            )
        return httpx.Response(
            200,
            json=issue_json(
                8,
                labels=[
                    {"name": "area:software"},
                    {"name": "type:task"},
                    {"name": "state:later"},
                ],
            ),
        )

    async with make_client(handler) as client:
        github = GitHubIssues(token="secret", repository="syllik/life-ops", client=client)
        issue = await github.set_later(8)

    assert calls == [
        ("GET", None),
        ("PATCH", {"labels": ["area:software", "type:task", "state:later"]}),
    ]
    assert issue.labels == ("area:software", "type:task", "state:later")


@pytest.mark.asyncio
async def test_set_later_is_noop_when_already_later() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        return httpx.Response(200, json=issue_json(8, labels=[{"name": "state:later"}]))

    async with make_client(handler) as client:
        github = GitHubIssues(token="secret", repository="syllik/life-ops", client=client)
        issue = await github.set_later(8)
    assert issue.labels == ("state:later",)


@pytest.mark.asyncio
async def test_close_rejects_false_success_response() -> None:
    async with make_client(
        lambda _: httpx.Response(200, json=issue_json(7, state="open"))
    ) as client:
        github = GitHubIssues(token="secret", repository="syllik/life-ops", client=client)
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
            ),
        )

    async with make_client(handler) as client:
        github = GitHubIssues(token="secret", repository="syllik/life-ops", client=client)
        with pytest.raises(GitHubError, match="Later state"):
            await github.set_later(8)
