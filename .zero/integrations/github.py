"""
integrations/github.py — Zero GitHub Integration

Wraps the GitHub REST API via httpx (no extra library needed).
Supports two accounts:
  - GITHUB_TOKEN / GITHUB_USERNAME       → new account (Cyph08) — primary
  - GITHUB_OLD_TOKEN / GITHUB_OLD_USERNAME → old account (Deepen-cyph) — migration source

Functions:
  list_repos(account="new")         → list all repos for an account
  get_repo(repo, account="new")     → get repo metadata
  list_files(repo, path, account)   → list files in a repo path
  read_file(repo, path, account)    → read a file from a repo
  create_repo(name, private, desc)  → create repo on new account
  create_issue(repo, title, body)   → create issue on new account
  create_file(repo, path, content, message) → commit a file
  migrate_repo(repo_name)           → clone from old → push to new account
"""

from __future__ import annotations

import base64
import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

logger = logging.getLogger(__name__)

_BASE = "https://api.github.com"
_HEADERS_NEW = {
    "Authorization": f"Bearer {os.getenv('GITHUB_TOKEN', '')}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}
_HEADERS_OLD = {
    "Authorization": f"Bearer {os.getenv('GITHUB_OLD_TOKEN', '')}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}

NEW_USER = os.getenv("GITHUB_USERNAME", "")
OLD_USER = os.getenv("GITHUB_OLD_USERNAME", "")


def _headers(account: str = "new") -> dict[str, str]:
    """Return auth headers for the specified account."""
    return _HEADERS_NEW if account == "new" else _HEADERS_OLD


def _username(account: str = "new") -> str:
    """Return username for the specified account."""
    return NEW_USER if account == "new" else OLD_USER


# ---------------------------------------------------------------------------
# Read operations
# ---------------------------------------------------------------------------

def list_repos(account: str = "new", per_page: int = 50) -> list[dict[str, Any]]:
    """
    List all repos for an account.

    Args:
        account: "new" (Cyph08) or "old" (Deepen-cyph).
        per_page: Max repos to return.

    Returns:
        List of repo dicts with name, description, private, url, language, stars.
    """
    url = f"{_BASE}/user/repos"
    params = {"per_page": per_page, "sort": "updated", "type": "all"}
    try:
        r = httpx.get(url, headers=_headers(account), params=params, timeout=15)
        r.raise_for_status()
        repos = r.json()
        return [
            {
                "name": repo["name"],
                "full_name": repo["full_name"],
                "description": repo.get("description", ""),
                "private": repo["private"],
                "url": repo["html_url"],
                "clone_url": repo["clone_url"],
                "language": repo.get("language", ""),
                "stars": repo.get("stargazers_count", 0),
                "updated_at": repo.get("updated_at", ""),
            }
            for repo in repos
        ]
    except Exception as exc:
        logger.error(f"[github] list_repos({account}) failed: {exc}")
        return []


def get_repo(repo: str, account: str = "new") -> dict[str, Any]:
    """
    Get metadata for a specific repo.

    Args:
        repo: Repo name (without username).
        account: "new" or "old".

    Returns:
        Repo metadata dict.
    """
    owner = _username(account)
    url = f"{_BASE}/repos/{owner}/{repo}"
    try:
        r = httpx.get(url, headers=_headers(account), timeout=15)
        r.raise_for_status()
        data = r.json()
        return {
            "name": data["name"],
            "description": data.get("description", ""),
            "private": data["private"],
            "url": data["html_url"],
            "default_branch": data.get("default_branch", "main"),
            "language": data.get("language", ""),
            "stars": data.get("stargazers_count", 0),
            "topics": data.get("topics", []),
        }
    except Exception as exc:
        logger.error(f"[github] get_repo({repo}) failed: {exc}")
        return {}


def list_files(repo: str, path: str = "", account: str = "new") -> list[dict[str, Any]]:
    """
    List files/folders in a repo path.

    Args:
        repo: Repo name.
        path: Sub-path inside repo (empty = root).
        account: "new" or "old".

    Returns:
        List of file/dir entries.
    """
    owner = _username(account)
    url = f"{_BASE}/repos/{owner}/{repo}/contents/{path}"
    try:
        r = httpx.get(url, headers=_headers(account), timeout=15)
        r.raise_for_status()
        return [
            {"name": f["name"], "type": f["type"], "path": f["path"], "size": f.get("size", 0)}
            for f in r.json()
        ]
    except Exception as exc:
        logger.error(f"[github] list_files({repo}/{path}) failed: {exc}")
        return []


def read_file(repo: str, path: str, account: str = "new") -> str:
    """
    Read a file from a repo.

    Args:
        repo: Repo name.
        path: File path inside the repo.
        account: "new" or "old".

    Returns:
        File content as string, or empty string on failure.
    """
    owner = _username(account)
    url = f"{_BASE}/repos/{owner}/{repo}/contents/{path}"
    try:
        r = httpx.get(url, headers=_headers(account), timeout=15)
        r.raise_for_status()
        data = r.json()
        content_b64 = data.get("content", "")
        return base64.b64decode(content_b64).decode("utf-8", errors="replace")
    except Exception as exc:
        logger.error(f"[github] read_file({repo}/{path}) failed: {exc}")
        return ""


# ---------------------------------------------------------------------------
# Write operations (new account only)
# ---------------------------------------------------------------------------

def create_repo(
    name: str,
    private: bool = True,
    description: str = "",
) -> dict[str, Any]:
    """
    Create a new repo on the new account (Cyph08).

    Args:
        name: Repo name.
        private: Whether to make it private.
        description: Repo description.

    Returns:
        Created repo metadata dict.
    """
    url = f"{_BASE}/user/repos"
    payload = {
        "name": name,
        "private": private,
        "description": description,
        "auto_init": True,
    }
    try:
        r = httpx.post(url, headers=_HEADERS_NEW, json=payload, timeout=15)
        r.raise_for_status()
        data = r.json()
        logger.info(f"[github] Created repo: {data['full_name']}")
        return {
            "name": data["name"],
            "url": data["html_url"],
            "clone_url": data["clone_url"],
            "private": data["private"],
        }
    except Exception as exc:
        logger.error(f"[github] create_repo({name}) failed: {exc}")
        return {}


def create_issue(
    repo: str,
    title: str,
    body: str = "",
    labels: list[str] | None = None,
) -> dict[str, Any]:
    """
    Create an issue on a repo in the new account.

    Args:
        repo: Repo name.
        title: Issue title.
        body: Issue body (markdown).
        labels: List of label names.

    Returns:
        Created issue dict with url and number.
    """
    url = f"{_BASE}/repos/{NEW_USER}/{repo}/issues"
    payload: dict[str, Any] = {"title": title, "body": body}
    if labels:
        payload["labels"] = labels
    try:
        r = httpx.post(url, headers=_HEADERS_NEW, json=payload, timeout=15)
        r.raise_for_status()
        data = r.json()
        logger.info(f"[github] Created issue #{data['number']} in {repo}")
        return {"number": data["number"], "url": data["html_url"], "title": data["title"]}
    except Exception as exc:
        logger.error(f"[github] create_issue({repo}) failed: {exc}")
        return {}


def create_file(
    repo: str,
    path: str,
    content: str,
    message: str = "Add file via Astra",
    branch: str = "main",
) -> dict[str, Any]:
    """
    Create or update a file in a repo on the new account.

    Args:
        repo: Repo name.
        path: File path inside repo.
        content: File content as string.
        message: Commit message.
        branch: Target branch.

    Returns:
        Dict with commit sha and file url.
    """
    url = f"{_BASE}/repos/{NEW_USER}/{repo}/contents/{path}"
    content_b64 = base64.b64encode(content.encode()).decode()

    # Check if file exists (need sha to update)
    sha: str | None = None
    try:
        existing = httpx.get(url, headers=_HEADERS_NEW, timeout=10)
        if existing.status_code == 200:
            sha = existing.json().get("sha")
    except Exception:
        pass

    payload: dict[str, Any] = {
        "message": message,
        "content": content_b64,
        "branch": branch,
    }
    if sha:
        payload["sha"] = sha

    try:
        r = httpx.put(url, headers=_HEADERS_NEW, json=payload, timeout=15)
        r.raise_for_status()
        data = r.json()
        logger.info(f"[github] Created/updated {path} in {repo}")
        return {
            "path": path,
            "sha": data["commit"]["sha"],
            "url": data["content"]["html_url"],
        }
    except Exception as exc:
        logger.error(f"[github] create_file({repo}/{path}) failed: {exc}")
        return {}


# ---------------------------------------------------------------------------
# Migration helper
# ---------------------------------------------------------------------------

def migrate_repo(repo_name: str) -> dict[str, Any]:
    """
    Mirror a repo from the old account to the new account.

    Does a bare clone from old account → pushes all branches + tags to new account.
    The new repo is created first if it doesn't exist.

    Args:
        repo_name: Repo name (same name used on both accounts).

    Returns:
        Dict with status and new repo url.
    """
    old_url = f"https://{os.getenv('GITHUB_OLD_TOKEN')}@github.com/{OLD_USER}/{repo_name}.git"
    new_url = f"https://{os.getenv('GITHUB_TOKEN')}@github.com/{NEW_USER}/{repo_name}.git"

    try:
        # Get old repo metadata
        old_meta = get_repo(repo_name, account="old")
        description = old_meta.get("description", "")
        private = old_meta.get("private", True)

        # Create new repo (ignore if already exists)
        new_repo = create_repo(repo_name, private=private, description=description)

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp) / repo_name

            # Bare clone from old account
            subprocess.run(
                ["git", "clone", "--bare", old_url, str(tmp_path)],
                check=True, capture_output=True, text=True,
            )

            # Mirror push to new account
            subprocess.run(
                ["git", "push", "--mirror", new_url],
                check=True, capture_output=True, text=True,
                cwd=str(tmp_path),
            )

        logger.info(f"[github] Migrated {repo_name}: {OLD_USER} → {NEW_USER}")
        return {
            "status": "success",
            "repo": repo_name,
            "old_account": OLD_USER,
            "new_account": NEW_USER,
            "new_url": new_repo.get("url", f"https://github.com/{NEW_USER}/{repo_name}"),
        }
    except subprocess.CalledProcessError as exc:
        error = exc.stderr if exc.stderr else str(exc)
        logger.error(f"[github] migrate_repo({repo_name}) git error: {error}")
        return {"status": "error", "repo": repo_name, "error": error}
    except Exception as exc:
        logger.error(f"[github] migrate_repo({repo_name}) failed: {exc}")
        return {"status": "error", "repo": repo_name, "error": str(exc)}


# ---------------------------------------------------------------------------
# CLI test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json
    print("=== NEW ACCOUNT REPOS ===")
    repos = list_repos("new")
    for r in repos[:10]:
        print(f"  {'🔒' if r['private'] else '📂'} {r['name']} ({r['language']}) — {r['url']}")
    print(f"\nTotal: {len(repos)} repos on {NEW_USER}")

    print("\n=== OLD ACCOUNT REPOS ===")
    old_repos = list_repos("old")
    for r in old_repos[:10]:
        print(f"  {'🔒' if r['private'] else '📂'} {r['name']} ({r['language']}) — {r['url']}")
    print(f"\nTotal: {len(old_repos)} repos on {OLD_USER}")
