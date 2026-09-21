import json

import httpx
import pytest

from life_ops_bot.github import GitHubError, GitHubIssues


def repository_json(*, has_issues: bool = True) -> dict[str, object]:
    return {"full_name": "owner/tasks", "has_issues": has_issues}


def label_json(
    name: str,
    color: str,
    description: str = "",
) -> dict[str, str]:
    return {"name": name, "color": color, "description": description}


def make_client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url="https://api.github.com", transport=httpx.MockTransport(handler)
    )


@pytest.mark.asyncio
async def test_contract_checks_existing_labels_and_probes_write_without_restyling() -> None:
    calls: list[tuple[str, str, dict[str, object] | None]] = []
    existing = {
        "state:inbox": label_json("state:inbox", "123abc", "Custom inbox description"),
        "state:later": label_json("state:later", "fedcba", "Custom later description"),
    }

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content) if request.content else None
        calls.append((request.method, request.url.path, payload))
        if request.url.path == "/repos/owner/tasks":
            return httpx.Response(200, json=repository_json())
        label_name = request.url.path.rsplit("/", 1)[-1]
        if request.method == "GET":
            return httpx.Response(200, json=existing[label_name])
        assert request.method == "PATCH"
        return httpx.Response(200, json=existing[label_name])

    async with make_client(handler) as client:
        github = GitHubIssues(token="secret", repository="owner/tasks", client=client)
        await github.ensure_repository_contract()

    assert calls == [
        ("GET", "/repos/owner/tasks", None),
        ("GET", "/repos/owner/tasks/labels/state:inbox", None),
        ("GET", "/repos/owner/tasks/labels/state:later", None),
        ("PATCH", "/repos/owner/tasks/labels/state:inbox", {"color": "123abc"}),
    ]


@pytest.mark.asyncio
async def test_contract_creates_each_missing_required_label() -> None:
    calls: list[tuple[str, str, dict[str, object] | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content) if request.content else None
        calls.append((request.method, request.url.path, payload))
        if request.url.path == "/repos/owner/tasks":
            return httpx.Response(200, json=repository_json())
        if request.method == "GET":
            return httpx.Response(404, json={"message": "Not Found"})
        assert payload is not None
        label_name = str(payload["name"])
        return httpx.Response(
            201,
            json=label_json(label_name, "ededed", "Managed by life-ops-bot."),
        )

    async with make_client(handler) as client:
        github = GitHubIssues(token="secret", repository="owner/tasks", client=client)
        await github.ensure_repository_contract()

    assert calls == [
        ("GET", "/repos/owner/tasks", None),
        ("GET", "/repos/owner/tasks/labels/state:inbox", None),
        (
            "POST",
            "/repos/owner/tasks/labels",
            {"name": "state:inbox", "color": "ededed", "description": "Managed by life-ops-bot."},
        ),
        ("GET", "/repos/owner/tasks/labels/state:later", None),
        (
            "POST",
            "/repos/owner/tasks/labels",
            {"name": "state:later", "color": "ededed", "description": "Managed by life-ops-bot."},
        ),
    ]


@pytest.mark.asyncio
async def test_contract_reports_inaccessible_repository_without_response_details() -> None:
    async with make_client(
        lambda _: httpx.Response(404, text="private repository response detail")
    ) as client:
        github = GitHubIssues(
            token="never-print-this-token", repository="owner/tasks", client=client
        )

        with pytest.raises(GitHubError, match="repository access") as exc_info:
            await github.ensure_repository_contract()

    assert "private repository response detail" not in str(exc_info.value)
    assert "never-print-this-token" not in str(exc_info.value)


@pytest.mark.asyncio
async def test_contract_rejects_repositories_with_issues_disabled() -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=repository_json(has_issues=False))

    async with make_client(handler) as client:
        github = GitHubIssues(token="secret", repository="owner/tasks", client=client)

        with pytest.raises(GitHubError, match="Issues are disabled"):
            await github.ensure_repository_contract()

    assert calls == 1


@pytest.mark.asyncio
async def test_contract_fails_when_existing_labels_cannot_be_updated() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if request.url.path == "/repos/owner/tasks":
            return httpx.Response(200, json=repository_json())
        label_name = request.url.path.rsplit("/", 1)[-1]
        if request.method == "GET":
            color = "123abc" if label_name == "state:inbox" else "fedcba"
            return httpx.Response(200, json=label_json(label_name, color))
        return httpx.Response(403, text="permission failure detail")

    async with make_client(handler) as client:
        github = GitHubIssues(token="secret", repository="owner/tasks", client=client)

        with pytest.raises(GitHubError, match=r"write check.*Issues: Read and write") as exc_info:
            await github.ensure_repository_contract()

    assert calls == 4
    assert "permission failure detail" not in str(exc_info.value)


@pytest.mark.asyncio
async def test_contract_reports_missing_write_permission_when_label_creation_fails() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.method)
        if request.url.path == "/repos/owner/tasks":
            return httpx.Response(200, json=repository_json())
        if request.method == "GET":
            return httpx.Response(404, json={"message": "Not Found"})
        return httpx.Response(403, text="private permission detail")

    async with make_client(handler) as client:
        github = GitHubIssues(token="secret", repository="owner/tasks", client=client)

        with pytest.raises(GitHubError, match=r"bootstrap.*Issues: Read and write") as exc_info:
            await github.ensure_repository_contract()

    assert calls == ["GET", "GET", "POST"]
    assert "private permission detail" not in str(exc_info.value)


@pytest.mark.asyncio
async def test_contract_rejects_a_required_label_response_with_a_different_name() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/repos/owner/tasks":
            return httpx.Response(200, json=repository_json())
        return httpx.Response(200, json=label_json("state:other", "123abc"))

    async with make_client(handler) as client:
        github = GitHubIssues(token="secret", repository="owner/tasks", client=client)

        with pytest.raises(GitHubError, match="required label"):
            await github.ensure_repository_contract()
