import httpx
import pytest

from life_ops_bot.github import GitHubError, GitHubIssues


def issue_json(
    number: int,
    *,
    body: str = "",
    state: str = "open",
    pull_request: bool = False,
) -> dict[str, object]:
    result: dict[str, object] = {
        "number": number,
        "html_url": f"https://github.com/owner/tasks/issues/{number}",
        "title": f"Issue {number}",
        "labels": [{"name": "state:inbox"}],
        "state": state,
        "body": body,
    }
    if pull_request:
        result["pull_request"] = {"url": "https://api.github.com/pulls/1"}
    return result


def make_client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url="https://api.github.com",
        transport=httpx.MockTransport(handler),
    )


@pytest.mark.asyncio
async def test_get_issue_preserves_body_for_navigation_relations() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/repos/owner/tasks/issues/7"
        return httpx.Response(200, json=issue_json(7, body="Parent: #2"))

    async with make_client(handler) as client:
        github = GitHubIssues(token="secret", repository="owner/tasks", client=client)
        result = await github.get_issue(7)

    assert result.number == 7
    assert result.body == "Parent: #2"


@pytest.mark.asyncio
async def test_list_issues_paginates_and_filters_pull_requests() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params["page"])
        calls.append(page)
        assert request.url.params["state"] == "all"
        assert request.url.params["sort"] == "updated"
        assert request.url.params["direction"] == "desc"
        if page == 1:
            items = [issue_json(number) for number in range(1, 100)]
            items.append(issue_json(100, pull_request=True))
            return httpx.Response(200, json=items)
        return httpx.Response(200, json=[issue_json(101, body="Parent: #1")])

    async with make_client(handler) as client:
        github = GitHubIssues(token="secret", repository="owner/tasks", client=client)
        result = await github.list_issues()

    assert calls == [1, 2]
    assert len(result) == 100
    assert result[-1].number == 101
    assert result[-1].body == "Parent: #1"


@pytest.mark.asyncio
async def test_list_issues_rejects_unknown_state_without_request() -> None:
    async with make_client(lambda _: pytest.fail("request should not be sent")) as client:
        github = GitHubIssues(token="secret", repository="owner/tasks", client=client)
        with pytest.raises(ValueError, match="state must be"):
            await github.list_issues(state="invalid")


@pytest.mark.asyncio
async def test_get_issue_rejects_pull_request_payload() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=issue_json(7, pull_request=True))

    async with make_client(handler) as client:
        github = GitHubIssues(token="secret", repository="owner/tasks", client=client)
        with pytest.raises(GitHubError, match="not an issue"):
            await github.get_issue(7)


@pytest.mark.asyncio
async def test_get_issue_rejects_non_string_body() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        data = issue_json(7)
        data["body"] = 123
        return httpx.Response(200, json=data)

    async with make_client(handler) as client:
        github = GitHubIssues(token="secret", repository="owner/tasks", client=client)
        with pytest.raises(GitHubError, match="invalid issue body"):
            await github.get_issue(7)
