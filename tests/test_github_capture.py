import json

import httpx
import pytest

from life_ops_bot.github import GitHubIssues


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
async def test_find_by_source_key_scans_recent_issues_and_skips_prs() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/repos/owner/tasks/issues"
        assert request.url.params["state"] == "all"
        return httpx.Response(
            200,
            json=[
                {**issue_json(99, body="source_key: telegram:1:2"), "pull_request": {}},
                issue_json(13, body="<!-- life-ops\nsource_key: telegram:1:23\n-->"),
                issue_json(12, body="<!-- life-ops\nsource_key: telegram:1:2\n-->"),
            ],
        )

    async with make_client(handler) as client:
        github = GitHubIssues(token="secret", repository="owner/tasks", client=client)
        issue = await github.find_by_source_key("telegram:1:2")
    assert issue is not None
    assert issue.number == 12


@pytest.mark.asyncio
async def test_find_by_source_key_returns_none_when_missing() -> None:
    async with make_client(
        lambda _: httpx.Response(200, json=[issue_json(1, body="other")])
    ) as client:
        github = GitHubIssues(token="secret", repository="owner/tasks", client=client)
        assert await github.find_by_source_key("telegram:1:2") is None


@pytest.mark.asyncio
async def test_create_issue_maps_title_body_and_inbox_label() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        payload = json.loads(request.content)
        assert payload == {"title": "Hello", "body": "raw body", "labels": ["state:inbox"]}
        return httpx.Response(201, json=issue_json(50, labels=[{"name": "state:inbox"}]))

    async with make_client(handler) as client:
        github = GitHubIssues(token="secret", repository="owner/tasks", client=client)
        issue = await github.create_issue(title="Hello", body="raw body", labels=("state:inbox",))
    assert issue.number == 50
    assert issue.labels == ("state:inbox",)
