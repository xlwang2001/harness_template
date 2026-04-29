"""Linear-compatible tracker client contracts and normalization."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from typing import Any

from .models import BlockerRef, Issue
from .workflow import RuntimeConfig


class TrackerError(RuntimeError):
    pass


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
