from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import httpx

from .core import INBOX_LABEL, LATER_LABEL, STATE_PREFIX, Issue

REQUIRED_LABELS = (INBOX_LABEL, LATER_LABEL)
BOOTSTRAP_LABEL_COLOR = "ededed"
BOOTSTRAP_LABEL_DESCRIPTION = "Managed by life-ops-bot."


class GitHubError(RuntimeError):
    """A sanitized GitHub adapter error safe to handle without private response bodies."""


class GitHubIssues:
    def __init__(
        self,
        *,
        token: str,
        repository: str,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._repository = repository
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url="https://api.github.com",
            timeout=15.0,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "life-ops-bot",
            },
        )

    async def __aenter__(self) -> GitHubIssues:
        return self

    async def __aexit__(self, *_: object) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def ensure_repository_contract(self) -> None:
        try:
            repository_response = await self._request("GET", f"/repos/{self._repository}")
            repository = _json_object(repository_response)
        except GitHubError as exc:
            raise GitHubError(
                "GitHub repository access check failed; verify the configured owner/repo "
                "and token access"
            ) from exc

        if repository.get("has_issues") is not True:
            raise GitHubError("GitHub Issues are disabled or unavailable for the repository")

        created_label = False
        existing_labels: list[tuple[str, str]] = []
        labels_path = f"/repos/{self._repository}/labels"
        for label in REQUIRED_LABELS:
            label_path = f"{labels_path}/{label}"
            try:
                response = await self._request("GET", label_path, allow_not_found=True)
            except GitHubError as exc:
                raise GitHubError(
                    "GitHub required-label check failed; verify repository Issues read access"
                ) from exc

            if response.status_code == 404:
                try:
                    created_response = await self._request(
                        "POST",
                        labels_path,
                        json={
                            "name": label,
                            "color": BOOTSTRAP_LABEL_COLOR,
                            "description": BOOTSTRAP_LABEL_DESCRIPTION,
                        },
                    )
                    _label_from_json(created_response, label)
                except GitHubError as exc:
                    raise GitHubError(
                        "GitHub required-label bootstrap failed; verify Issues: Read and write "
                        "permission"
                    ) from exc
                created_label = True
            else:
                existing_labels.append(_label_from_json(response, label))

        if not created_label:
            label, color = existing_labels[0]
            try:
                updated_response = await self._request(
                    "PATCH", f"{labels_path}/{label}", json={"color": color}
                )
            except GitHubError as exc:
                raise GitHubError(
                    "GitHub repository contract write check failed; verify Issues: Read and "
                    "write permission"
                ) from exc
            _label_from_json(updated_response, label)

    async def find_by_source_key(self, source_key: str) -> Issue | None:
        response = await self._request(
            "GET",
            f"/repos/{self._repository}/issues",
            params={
                "state": "all",
                "sort": "created",
                "direction": "desc",
                "per_page": 100,
            },
        )
        marker = f"source_key: {source_key}"
        for item in _json_list(response):
            if "pull_request" in item:
                continue
            body = item.get("body") or ""
            if marker in body.splitlines():
                return _issue_from_json(item)
        return None

    async def create_issue(self, *, title: str, body: str, labels: tuple[str, ...]) -> Issue:
        response = await self._request(
            "POST",
            f"/repos/{self._repository}/issues",
            json={"title": title, "body": body, "labels": list(labels)},
        )
        issue = _issue_from_json(_json_object(response))
        if not set(labels).issubset(issue.labels):
            raise GitHubError("GitHub did not apply required labels")
        return issue

    async def close_issue(self, issue_number: int) -> Issue:
        response = await self._request(
            "PATCH",
            f"/repos/{self._repository}/issues/{issue_number}",
            json={"state": "closed", "state_reason": "completed"},
        )
        issue = _issue_from_json(_json_object(response))
        if issue.state != "closed":
            raise GitHubError("GitHub did not close the issue")
        return issue

    async def set_later(self, issue_number: int) -> Issue:
        current_response = await self._request(
            "GET", f"/repos/{self._repository}/issues/{issue_number}"
        )
        current = _json_object(current_response)
        labels = _label_names(current.get("labels", []))
        next_labels = (
            *(label for label in labels if not label.startswith(STATE_PREFIX)),
            LATER_LABEL,
        )
        if tuple(labels) == next_labels and current.get("state") == "open":
            return _issue_from_json(current)

        response = await self._request(
            "PATCH",
            f"/repos/{self._repository}/issues/{issue_number}",
            json={"labels": list(next_labels), "state": "open"},
        )
        issue = _issue_from_json(_json_object(response))
        state_labels = tuple(label for label in issue.labels if label.startswith(STATE_PREFIX))
        if state_labels != (LATER_LABEL,) or issue.state != "open":
            raise GitHubError("GitHub did not apply the Later state")
        return issue

    async def _request(
        self,
        method: str,
        path: str,
        *,
        allow_not_found: bool = False,
        **kwargs: Any,
    ) -> httpx.Response:
        try:
            response = await self._client.request(method, path, **kwargs)
            if allow_not_found and response.status_code == 404:
                return response
            response.raise_for_status()
            return response
        except httpx.HTTPError as exc:
            raise GitHubError("GitHub request failed") from exc


def _response_json(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError as exc:
        raise GitHubError("GitHub returned an unexpected response") from exc


def _json_object(response: httpx.Response) -> dict[str, Any]:
    data = _response_json(response)
    if not isinstance(data, dict):
        raise GitHubError("GitHub returned an unexpected response")
    return data


def _json_list(response: httpx.Response) -> list[dict[str, Any]]:
    data = _response_json(response)
    if not isinstance(data, list) or any(not isinstance(item, dict) for item in data):
        raise GitHubError("GitHub returned an unexpected response")
    return data


def _label_names(labels: Iterable[Any]) -> list[str]:
    result: list[str] = []
    for label in labels:
        if isinstance(label, str):
            result.append(label)
        elif isinstance(label, dict) and isinstance(label.get("name"), str):
            result.append(label["name"])
    return result


def _label_from_json(response: httpx.Response, expected_name: str) -> tuple[str, str]:
    data = _json_object(response)
    name = data.get("name")
    color = data.get("color")
    if name != expected_name or not isinstance(color, str):
        raise GitHubError("GitHub returned an unexpected required label")
    return name, color


def _issue_from_json(data: dict[str, Any]) -> Issue:
    try:
        number = int(data["number"])
        url = str(data["html_url"])
        title = str(data["title"])
    except (KeyError, TypeError, ValueError) as exc:
        raise GitHubError("GitHub returned an incomplete issue") from exc

    return Issue(
        number=number,
        url=url,
        title=title,
        labels=tuple(_label_names(data.get("labels", []))),
        state=str(data.get("state", "open")),
    )
