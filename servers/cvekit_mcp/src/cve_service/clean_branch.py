#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GitCode fork branch cleaner.

This script is designed to delete fork branches whose PRs are merged into upstream.
It does not enumerate all upstream PRs.

It is designed to be run periodically, e.g. every day.

Usage:
    python3 clean_branch.py --repo-dir <repo-dir> [--token <token>] [--apply]
"""

import argparse
import json
import os
import subprocess
import sys
import time
from typing import Dict, List, Optional, Tuple

try:
    import requests
except ImportError:
    print("Missing dependency: requests. Install via: pip install requests", file=sys.stderr)
    sys.exit(1)

API_BASE = os.environ.get("GITCODE_API_BASE", "https://api.gitcode.com")


def sh(cmd: List[str], cwd: Optional[str] = None, check: bool = True) -> Tuple[int, str]:
    p = subprocess.run(
        cmd,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    if check and p.returncode != 0:
        raise RuntimeError(f"Command failed ({p.returncode}): {' '.join(cmd)}\n{p.stdout}")
    return p.returncode, p.stdout


def ensure_git_repo(repo_dir: str) -> None:
    sh(["git", "rev-parse", "--show-toplevel"], cwd=repo_dir, check=True)


def list_remotes(repo_dir: str) -> List[str]:
    _, out = sh(["git", "remote"], cwd=repo_dir, check=True)
    return [x.strip() for x in out.splitlines() if x.strip()]


def fetch_remote(repo_dir: str, remote: str) -> None:
    sh(["git", "fetch", remote, "--prune"], cwd=repo_dir, check=True)


def list_remote_branches(repo_dir: str, remote: str, exclude: Optional[List[str]] = None) -> List[str]:
    """
    Return branch names under refs/remotes/<remote>/* without the '<remote>/' prefix.
    """
    exclude_set = set(exclude or [])
    exclude_set.update({"HEAD", "master", "main"})

    ref_prefix = f"refs/remotes/{remote}"
    # If remote hasn't been fetched, this can be empty.
    _, out = sh(["git", "for-each-ref", "--format=%(refname:short)", ref_prefix], cwd=repo_dir, check=True)

    branches: List[str] = []
    prefix = f"{remote}/"
    for line in out.splitlines():
        line = line.strip()
        if not line.startswith(prefix):
            continue
        br = line[len(prefix):]

        # skip symbolic refs like "<remote>/HEAD -> ..."
        if " -> " in br:
            continue
        if br in exclude_set:
            continue
        if not br.startswith("fix"):
            continue
        branches.append(br)

    return sorted(set(branches))


def local_branch_exists(repo_dir: str, branch: str) -> bool:
    code, _ = sh(["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"], cwd=repo_dir, check=False)
    return code == 0


def delete_local_branch(repo_dir: str, branch: str, force: bool, apply: bool) -> None:
    cmd = ["git", "branch", "-D" if force else "-d", branch]
    if apply:
        sh(cmd, cwd=repo_dir, check=True)
    else:
        print("[dry-run]", " ".join(cmd))


def delete_remote_branch(repo_dir: str, remote: str, branch: str, apply: bool) -> None:
    cmd = ["git", "push", remote, "--delete", branch]
    if apply:
        sh(cmd, cwd=repo_dir, check=True)
    else:
        print("[dry-run]", " ".join(cmd))


def is_merged_pr(pr: dict) -> bool:
    merged_at = pr.get("merged_at") or pr.get("mergedAt")
    if merged_at:
        return True
    merged_flag = pr.get("merged")
    if isinstance(merged_flag, bool):
        return merged_flag
    st = (pr.get("state") or "").lower()
    return st == "merged"


def get_author_login(pr: dict) -> str:
    user = pr.get("user")
    return str(user.get("login"))


def get_head_info(pr: dict) -> Tuple[str, str]:
    head = pr.get("head") or {}
    ref = head.get("ref") or head.get("label") or ""
    repo = head.get("repo") or {}
    full_name = repo.get("full_name") or repo.get("path_with_namespace") or repo.get("fullName") or ""
    return str(full_name), str(ref)


def get_base_branch(pr: dict) -> str:
    base = pr.get("base") or {}
    return str(base.get("ref") or "")


def pulls_by_head_branch(owner: str, repo: str, token: str, head_branch: str, per_page: int = 20, state: str="merged") -> List[dict]:
    """
    Query upstream PRs filtered by head branch name.
    IMPORTANT: GitCode's `head` filter works with branch name ONLY, e.g. head=fix-OLK-6.6-13368.
    """
    url = f"{API_BASE}/api/v5/repos/{owner}/{repo}/pulls"
    params: Dict[str, object] = {
        "state": state,
        "head": head_branch,
        "page": 1,
        "per_page": per_page,
        "sort": "created",
        "direction": "desc",
    }
    if token:
        params["access_token"] = token

    r = requests.get(url, params=params, timeout=(5, 30))
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code} when GET {r.url}\n{r.text[:300]}")

    try:
        data = r.json()
    except Exception:
        raise RuntimeError(f"Non-JSON response, status={r.status_code}, head={r.text[:200]!r}")

    if not isinstance(data, list):
        raise RuntimeError(f"Unexpected response (not list): {json.dumps(data, ensure_ascii=False)[:300]}")
    return data


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Delete fork branches whose PRs are merged into upstream, without enumerating all upstream PRs."
    )
    ap.add_argument("--repo-dir", required=True, help="Local git repo directory (your devstation-robot/kernel clone)")
    ap.add_argument("--token", default=os.environ.get("GITCODE_TOKEN", ""), help="GitCode token (or env GITCODE_TOKEN)")

    ap.add_argument("--owner", default="openeuler", help="Upstream owner (default: openeuler)")
    ap.add_argument("--repo", default="kernel", help="Upstream repo (default: kernel)")

    ap.add_argument("--author", default="devstation-robot", help="PR author login (default: devstation-robot)")
    ap.add_argument("--head-owner", default="devstation-robot", help="Expected head repo owner (default: devstation-robot)")
    ap.add_argument("--head-repo", default="kernel", help="Expected head repo name (default: kernel)")

    ap.add_argument("--fork-remote", default="origin", help="Remote name that contains your fork branches")
    ap.add_argument("--exclude", default="", help="Comma-separated branch names to exclude")
    ap.add_argument("--only-prefix", default="", help="Only consider branches with this prefix")
    ap.add_argument("--per-page", type=int, default=20, help="PR page size for head query (default: 20)")
    ap.add_argument("--sleep", type=float, default=0.15, help="Sleep seconds between API calls (default: 0.15)")

    ap.add_argument("--force", action="store_true", help="Force delete local branches (git branch -D)")
    ap.add_argument("--remote", default="origin", help="Also delete remote branches from this remote name")
    ap.add_argument("--apply", action="store_true", help="Actually perform deletions (default is dry-run)")
    ap.add_argument("--state", default="merged", help="PR state to query (default: merged)")
    args = ap.parse_args()

    repo_dir = args.repo_dir
    ensure_git_repo(repo_dir)

    remotes = list_remotes(repo_dir)
    if args.fork_remote not in remotes:
        raise RuntimeError(
            f"--fork-remote '{args.fork_remote}' not found. Available remotes: {', '.join(remotes)}"
        )

    # Make sure remote-tracking refs exist
    fetch_remote(repo_dir, args.fork_remote)

    exclude_list = [x.strip() for x in args.exclude.split(",") if x.strip()]
    branches = list_remote_branches(repo_dir, args.fork_remote, exclude=exclude_list)
    
    if args.only_prefix:
        branches = [b for b in branches if b.startswith(args.only_prefix)]

    target_head_full = f"{args.head_owner}/{args.head_repo}".lower()

    print(f"Fork remote: {args.fork_remote}")
    print(f"Scanning {len(branches)} branch(es) under refs/remotes/{args.fork_remote}/*")
    print(f"Upstream: {args.owner}/{args.repo} | Expected head repo: {target_head_full} | Author: {args.author}")
    print(f"API_BASE: {API_BASE}\n")

    branches_to_delete: List[str] = []
    
    for br in branches:
        try:
            prs = pulls_by_head_branch(args.owner, args.repo, args.token, br, per_page=args.per_page, state=args.state)
        except Exception as e:
            print(f"[ERROR] head={br}: {e}", file=sys.stderr)
            time.sleep(max(args.sleep, 0.3))
            continue

        if prs:
            hit = None
            for pr in prs:
                if get_author_login(pr) != args.author:
                    continue
                if not is_merged_pr(pr):
                    continue
                head_full, head_ref = get_head_info(pr)
                if head_ref != br:
                    continue
                if head_full.lower() != target_head_full:
                    continue
                hit = pr
                break

            if hit:
                branches_to_delete.append(br)
                number = hit.get("number") or hit.get("id") or ""
                title = hit.get("title", "")
                html_url = hit.get("html_url") or hit.get("url") or ""
                base_ref = get_base_branch(hit)
                print(f"[MERGED] {br} -> {base_ref} | PR#{number} {title}")
                if html_url:
                    print(f"  {html_url}")

        if args.sleep > 0:
            time.sleep(args.sleep)

    branches_to_delete = sorted(set(branches_to_delete))
    
    if not branches_to_delete:
        print("\nNo branches matched merged PR criteria. Nothing to delete.")
        return

    print("\nBranches to delete:")
    for br in branches_to_delete:
        print(f"  - {br}")

    print("\nLocal deletion plan:")
    for br in branches_to_delete:
        if local_branch_exists(repo_dir, br):
            delete_local_branch(repo_dir, br, force=args.force, apply=args.apply)
        else:
            print(f"[skip] local branch not found: {br}")

    if args.remote:
        if args.remote not in remotes:
            raise RuntimeError(f"--remote '{args.remote}' not found. Available remotes: {', '.join(remotes)}")
        print(f"\nRemote deletion plan on remote='{args.remote}':")
        for br in branches_to_delete:
            delete_remote_branch(repo_dir, args.remote, br, apply=args.apply)

    print("\nDone.")
    if not args.apply:
        print("This was a dry-run. Re-run with --apply to actually delete branches.")


if __name__ == "__main__":
    main()
