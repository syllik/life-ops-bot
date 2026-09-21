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
async def test_http_and_shape_failures_are_sanitized() -> None:
    async with make_client(lambda _: httpx.Response(500, text="private failure body")) as client:
        github = GitHubIssues(token="secret", repository="owner/tasks", client=client)
        with pytest.raises(GitHubError, match="GitHub request failed") as exc_info:
            await github.find_by_source_key("telegram:1:2")
        assert "private failure body" not in str(exc_info.value)

    async with make_client(lambda _: httpx.Response(200, json={"not": "a list"})) as client:
        github = GitHubIssues(token="secret", repository="owner/tasks", client=client)
        with pytest.raises(GitHubError, match="unexpected response"):
            await github.find_by_source_key("telegram:1:2")

    async with make_client(lambda _: httpx.Response(200, json=[])) as client:
        github = GitHubIssues(token="secret", repository="owner/tasks", client=client)
        with pytest.raises(GitHubError, match="unexpected response"):
            await github.create_issue(title="x", body="x", labels=())

    async with make_client(lambda _: httpx.Response(200, json={"number": "bad"})) as client:
        github = GitHubIssues(token="secret", repository="owner/tasks", client=client)
        with pytest.raises(GitHubError, match="incomplete issue"):
            await github.create_issue(title="x", body="x", labels=())


@pytest.mark.asyncio
async def test_owned_client_is_closed_by_context_manager() -> None:
    github = GitHubIssues(token="secret", repository="owner/tasks")
    client = github._client
    async with github as entered:
        assert entered is github
        assert not client.is_closed
    assert client.is_closed

@pytest.mark.asyncio
async def test_external_client_is_not_closed_by_context_manager() -> None:
    async with make_client(lambda _: httpx.Response(200, json=[])) as client:
        github = GitHubIssues(token="secret", repository="owner/tasks", client=client)
        async with github:
            pass
        assert not client.is_closed


@pytest.mark.asyncio
async def test_invalid_json_is_sanitized() -> None:
    async with make_client(
        lambda _: httpx.Response(
            200, content=b"not-json", headers={"content-type": "application/json"}
        )
    ) as client:
        github = GitHubIssues(token="secret", repository="owner/tasks", client=client)
        with pytest.raises(GitHubError, match="unexpected response"):
            await github.find_by_source_key("telegram:1:2")


@pytest.mark.asyncio
async def test_create_rejects_silently_dropped_labels() -> None:
    async with make_client(lambda _: httpx.Response(201, json=issue_json(50))) as client:
        github = GitHubIssues(token="secret", repository="owner/tasks", client=client)
        with pytest.raises(GitHubError, match="required labels"):
            await github.create_issue(title="Hello", body="body", labels=("state:inbox",))


