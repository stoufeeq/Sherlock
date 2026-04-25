from urllib.parse import quote

import httpx

from app.config import settings


class GitLabClient:
    """Thin client for the bits of the GitLab API Sherlock needs."""

    def __init__(self) -> None:
        self._http = httpx.Client(
            base_url=f"{settings.gitlab_internal_url}/api/v4",
            headers={"PRIVATE-TOKEN": settings.gitlab_token},
            timeout=30.0,
        )

    def list_group_projects(self, group: str | None = None) -> list[dict]:
        g = group or settings.gitlab_group
        r = self._http.get(f"/groups/{quote(g, safe='')}/projects", params={"per_page": 100})
        r.raise_for_status()
        return r.json()

    def get_project(self, project_id: int) -> dict:
        r = self._http.get(f"/projects/{project_id}")
        r.raise_for_status()
        return r.json()

    def head_commit(self, project_id: int, ref: str = "main") -> str:
        r = self._http.get(
            f"/projects/{project_id}/repository/commits/{quote(ref, safe='')}"
        )
        r.raise_for_status()
        return r.json()["id"]

    def clone_url(self, project_path: str) -> str:
        """
        Authenticated HTTP clone URL usable from inside the compose network.
        project_path is like "banking/account-service".
        """
        # strip scheme://host and rebuild with oauth2:token@ prefix
        base = settings.gitlab_internal_url.replace("http://", "", 1).replace("https://", "", 1)
        return f"http://oauth2:{settings.gitlab_token}@{base}/{project_path}.git"

    def list_mr_notes(self, project_id: int, mr_iid: int) -> list[dict]:
        r = self._http.get(f"/projects/{project_id}/merge_requests/{mr_iid}/notes", params={"per_page": 100})
        r.raise_for_status()
        return r.json()

    def list_open_mrs(self, project_id: int, labels: str | None = None) -> list[dict]:
        params: dict = {"state": "opened", "per_page": 100}
        if labels:
            params["labels"] = labels
        r = self._http.get(f"/projects/{project_id}/merge_requests", params=params)
        r.raise_for_status()
        return r.json()

    def create_merge_request(
        self,
        project_id: int,
        *,
        source_branch: str,
        target_branch: str,
        title: str,
        description: str,
        labels: list[str] | None = None,
        remove_source_branch: bool = True,
    ) -> dict:
        payload: dict = {
            "source_branch": source_branch,
            "target_branch": target_branch,
            "title": title,
            "description": description,
            "remove_source_branch": remove_source_branch,
        }
        if labels:
            payload["labels"] = ",".join(labels)
        r = self._http.post(f"/projects/{project_id}/merge_requests", json=payload)
        r.raise_for_status()
        return r.json()

    def update_mr(self, project_id: int, mr_iid: int, **fields) -> dict:
        r = self._http.put(
            f"/projects/{project_id}/merge_requests/{mr_iid}", json=fields
        )
        r.raise_for_status()
        return r.json()

    def upsert_mr_note(self, project_id: int, mr_iid: int, body: str, marker: str) -> dict:
        """Create a new MR note, or update the existing one that contains `marker`."""
        for note in self.list_mr_notes(project_id, mr_iid):
            if marker in (note.get("body") or "") and not note.get("system"):
                r = self._http.put(
                    f"/projects/{project_id}/merge_requests/{mr_iid}/notes/{note['id']}",
                    json={"body": body},
                )
                r.raise_for_status()
                return r.json()
        r = self._http.post(
            f"/projects/{project_id}/merge_requests/{mr_iid}/notes",
            json={"body": body},
        )
        r.raise_for_status()
        return r.json()

    # ---- Labels + Issues (Loop 4C: sticky impact tags) ---------------------

    def ensure_label(self, project_id: int, name: str, color: str, description: str = "") -> None:
        """Create the label if it doesn't exist; otherwise leave it alone."""
        r = self._http.get(f"/projects/{project_id}/labels", params={"per_page": 100})
        r.raise_for_status()
        for lbl in r.json():
            if lbl.get("name") == name:
                return
        self._http.post(
            f"/projects/{project_id}/labels",
            json={"name": name, "color": color, "description": description},
        ).raise_for_status()

    def list_issues(self, project_id: int, labels: str | None = None, state: str | None = None) -> list[dict]:
        params: dict = {"per_page": 100}
        if labels:
            params["labels"] = labels
        if state:
            params["state"] = state
        r = self._http.get(f"/projects/{project_id}/issues", params=params)
        r.raise_for_status()
        return r.json()

    def find_issue_by_marker(self, project_id: int, marker: str) -> dict | None:
        for issue in self.list_issues(project_id):
            if marker in (issue.get("description") or ""):
                return issue
        return None

    def create_issue(self, project_id: int, title: str, description: str, labels: list[str]) -> dict:
        r = self._http.post(
            f"/projects/{project_id}/issues",
            json={"title": title, "description": description, "labels": ",".join(labels)},
        )
        r.raise_for_status()
        return r.json()

    def update_issue(self, project_id: int, issue_iid: int, *, labels: list[str] | None = None,
                     state_event: str | None = None, description: str | None = None) -> dict:
        payload: dict = {}
        if labels is not None:
            payload["labels"] = ",".join(labels)
        if state_event:
            payload["state_event"] = state_event  # "close" or "reopen"
        if description is not None:
            payload["description"] = description
        r = self._http.put(f"/projects/{project_id}/issues/{issue_iid}", json=payload)
        r.raise_for_status()
        return r.json()

    def add_issue_note(self, project_id: int, issue_iid: int, body: str) -> dict:
        r = self._http.post(
            f"/projects/{project_id}/issues/{issue_iid}/notes", json={"body": body}
        )
        r.raise_for_status()
        return r.json()

    def ensure_webhook(self, project_id: int, url: str, secret: str) -> dict:
        hooks = self._http.get(f"/projects/{project_id}/hooks").json()
        for h in hooks:
            if h.get("url") == url:
                return h
        r = self._http.post(
            f"/projects/{project_id}/hooks",
            json={
                "url": url,
                "token": secret,
                "push_events": True,
                "merge_requests_events": True,
                "enable_ssl_verification": False,
            },
        )
        r.raise_for_status()
        return r.json()

    def list_project_hooks(self, project_id: int) -> list[dict]:
        r = self._http.get(f"/projects/{project_id}/hooks")
        r.raise_for_status()
        return r.json()

    def ensure_allow_local_requests(self) -> None:
        """Required so webhooks pointing at container hostnames (http://sherlock:8000)
        aren't rejected by GitLab as 'local network' addresses."""
        r = self._http.put(
            "/application/settings",
            data={"allow_local_requests_from_web_hooks_and_services": True},
        )
        r.raise_for_status()
