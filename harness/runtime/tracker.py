"""Linear-compatible tracker client contracts and normalization."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from .models import BlockerRef, Issue
from .workflow import RuntimeConfig


class TrackerError(RuntimeError):
    pass


@dataclass(frozen=True)
class TrackerWriteResult:
    id: str | None = None
    url: str | None = None
    success: bool = True
    raw: dict[str, Any] | None = None


class IssueTrackerClient(ABC):
    @abstractmethod
    def fetch_candidate_issues(self) -> list[Issue]:
        raise NotImplementedError

    @abstractmethod
    def fetch_issues_by_states(self, state_names: list[str]) -> list[Issue]:
        raise NotImplementedError

    @abstractmethod
    def fetch_issue_states_by_ids(self, issue_ids: list[str]) -> list[Issue]:
        raise NotImplementedError

    def add_comment(self, issue_id: str, body: str) -> TrackerWriteResult:
        raise TrackerError("tracker_write_not_supported")

    def transition_issue(self, issue_id: str, state_name: str) -> TrackerWriteResult:
        raise TrackerError("tracker_write_not_supported")

    def record_pull_request(self, issue_id: str, url: str, *, title: str | None = None) -> TrackerWriteResult:
        raise TrackerError("tracker_write_not_supported")


class LinearClient(IssueTrackerClient):
    def __init__(self, config: RuntimeConfig):
        if not config.tracker_api_key:
            raise TrackerError("missing_tracker_api_key")
        if not config.tracker_project_slug:
            raise TrackerError("missing_tracker_project_slug")
        self.config = config

    def fetch_candidate_issues(self) -> list[Issue]:
        query = """
        query CandidateIssues($projectSlug: String!, $states: [String!], $after: String) {
          issues(first: 50, after: $after, filter: { project: { slugId: { eq: $projectSlug } }, state: { name: { in: $states } } }) {
            nodes {
              id identifier title description priority branchName url createdAt updatedAt
              state { name }
              labels { nodes { name } }
              inverseRelations { nodes { type issue { id identifier state { name } } } }
            }
            pageInfo { hasNextPage endCursor }
          }
        }
        """
        return self._fetch_paginated(query, {"projectSlug": self.config.tracker_project_slug, "states": list(self.config.active_states)})

    def fetch_issues_by_states(self, state_names: list[str]) -> list[Issue]:
        if not state_names:
            return []
        query = """
        query IssuesByStates($projectSlug: String!, $states: [String!], $after: String) {
          issues(first: 50, after: $after, filter: { project: { slugId: { eq: $projectSlug } }, state: { name: { in: $states } } }) {
            nodes { id identifier title description priority branchName url createdAt updatedAt state { name } labels { nodes { name } } inverseRelations { nodes { type issue { id identifier state { name } } } } }
            pageInfo { hasNextPage endCursor }
          }
        }
        """
        return self._fetch_paginated(query, {"projectSlug": self.config.tracker_project_slug, "states": state_names})

    def fetch_issue_states_by_ids(self, issue_ids: list[str]) -> list[Issue]:
        if not issue_ids:
            return []
        query = """
        query IssueStates($ids: [ID!]) {
          issues(first: 100, filter: { id: { in: $ids } }) {
            nodes { id identifier title state { name } }
          }
        }
        """
        payload = self._graphql(query, {"ids": issue_ids})
        nodes = payload.get("data", {}).get("issues", {}).get("nodes", [])
        return [normalize_linear_issue(node) for node in nodes]

    def add_comment(self, issue_id: str, body: str) -> TrackerWriteResult:
        issue_id = _required_text(issue_id, "issue_id")
        body = _required_text(body, "body")
        query = """
        mutation AddIssueComment($issueId: String!, $body: String!) {
          commentCreate(input: { issueId: $issueId, body: $body }) {
            success
            comment { id url }
          }
        }
        """
        payload = self._graphql(query, {"issueId": issue_id, "body": body})
        result = payload.get("data", {}).get("commentCreate")
        if not isinstance(result, dict):
            raise TrackerError("linear_unknown_payload")
        comment = result.get("comment") if isinstance(result.get("comment"), dict) else {}
        return TrackerWriteResult(
            id=comment.get("id"),
            url=comment.get("url"),
            success=bool(result.get("success", True)),
            raw=result,
        )

    def transition_issue(self, issue_id: str, state_name: str) -> TrackerWriteResult:
        issue_id = _required_text(issue_id, "issue_id")
        state_name = _required_text(state_name, "state_name")
        state = self._find_state_by_name(state_name)
        query = """
        mutation TransitionIssue($issueId: String!, $stateId: String!) {
          issueUpdate(id: $issueId, input: { stateId: $stateId }) {
            success
            issue { id identifier url state { name } }
          }
        }
        """
        payload = self._graphql(query, {"issueId": issue_id, "stateId": state["id"]})
        result = payload.get("data", {}).get("issueUpdate")
        if not isinstance(result, dict):
            raise TrackerError("linear_unknown_payload")
        issue = result.get("issue") if isinstance(result.get("issue"), dict) else {}
        return TrackerWriteResult(
            id=issue.get("id"),
            url=issue.get("url"),
            success=bool(result.get("success", True)),
            raw=result,
        )

    def record_pull_request(self, issue_id: str, url: str, *, title: str | None = None) -> TrackerWriteResult:
        issue_id = _required_text(issue_id, "issue_id")
        url = _required_text(url, "url")
        title = _required_text(title or "Pull request", "title")
        query = """
        mutation RecordPullRequest($issueId: String!, $title: String!, $url: String!) {
          attachmentCreate(input: { issueId: $issueId, title: $title, url: $url }) {
            success
            attachment { id title url }
          }
        }
        """
        payload = self._graphql(query, {"issueId": issue_id, "title": title, "url": url})
        result = payload.get("data", {}).get("attachmentCreate")
        if not isinstance(result, dict):
            raise TrackerError("linear_unknown_payload")
        attachment = result.get("attachment") if isinstance(result.get("attachment"), dict) else {}
        return TrackerWriteResult(
            id=attachment.get("id"),
            url=attachment.get("url"),
            success=bool(result.get("success", True)),
            raw=result,
        )

    def _find_state_by_name(self, state_name: str) -> dict[str, Any]:
        query = """
        query WorkflowStateByName($stateName: String!) {
          workflowStates(first: 25, filter: { name: { eq: $stateName } }) {
            nodes { id name }
          }
        }
        """
        payload = self._graphql(query, {"stateName": state_name})
        workflow_states = payload.get("data", {}).get("workflowStates")
        if not isinstance(workflow_states, dict):
            raise TrackerError("linear_unknown_payload")
        states = workflow_states.get("nodes")
        if not isinstance(states, list):
            raise TrackerError("linear_unknown_payload")
        matching = [state for state in states if isinstance(state, dict) and str(state.get("name", "")).lower() == state_name.lower()]
        if not matching:
            raise TrackerError("linear_state_not_found")
        return matching[0]

    def _fetch_paginated(self, query: str, variables: dict[str, Any]) -> list[Issue]:
        issues: list[Issue] = []
        after = None
        while True:
            page_vars = dict(variables)
            page_vars["after"] = after
            payload = self._graphql(query, page_vars)
            data = payload.get("data", {}).get("issues")
            if not isinstance(data, dict):
                raise TrackerError("linear_unknown_payload")
            issues.extend(normalize_linear_issue(node) for node in data.get("nodes", []))
            page_info = data.get("pageInfo") or {}
            if not page_info.get("hasNextPage"):
                return issues
            after = page_info.get("endCursor")
            if not after:
                raise TrackerError("linear_missing_end_cursor")

    def _graphql(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        request = urllib.request.Request(
            self.config.tracker_endpoint,
            data=json.dumps({"query": query, "variables": variables}).encode("utf-8"),
            headers={
                "Authorization": self.config.tracker_api_key or "",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                if response.status != 200:
                    raise TrackerError("linear_api_status")
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise TrackerError("linear_api_status") from exc
        except urllib.error.URLError as exc:
            raise TrackerError("linear_api_request") from exc
        except json.JSONDecodeError as exc:
            raise TrackerError("linear_unknown_payload") from exc
        if payload.get("errors"):
            raise TrackerError("linear_graphql_errors")
        return payload


def _required_text(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise TrackerError(f"{field}_required")
    return text


def normalize_linear_issue(node: dict[str, Any]) -> Issue:
    state = (node.get("state") or {}).get("name") if isinstance(node.get("state"), dict) else node.get("state")
    labels = [
        item.get("name")
        for item in ((node.get("labels") or {}).get("nodes") or [])
        if isinstance(item, dict) and item.get("name")
    ]
    blockers: list[BlockerRef] = []
    for relation in ((node.get("inverseRelations") or {}).get("nodes") or []):
        if not isinstance(relation, dict) or relation.get("type") != "blocks":
            continue
        issue = relation.get("issue") or {}
        blockers.append(
            BlockerRef(
                id=issue.get("id"),
                identifier=issue.get("identifier"),
                state=(issue.get("state") or {}).get("name") if isinstance(issue.get("state"), dict) else issue.get("state"),
            )
        )
    return Issue.from_mapping(
        {
            "id": node.get("id"),
            "identifier": node.get("identifier"),
            "title": node.get("title") or "",
            "description": node.get("description"),
            "priority": node.get("priority"),
            "state": state or "",
            "branch_name": node.get("branchName") or node.get("branch_name"),
            "url": node.get("url"),
            "labels": labels,
            "blocked_by": blockers,
            "created_at": node.get("createdAt") or node.get("created_at"),
            "updated_at": node.get("updatedAt") or node.get("updated_at"),
        }
    )
