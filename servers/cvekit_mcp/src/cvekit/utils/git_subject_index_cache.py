"""对于要查找git log的情况建立数据库，加快后续查找速度，支持不同进程复用"""
from __future__ import annotations

import logging
import os
import sqlite3
import subprocess
import time
from contextlib import closing
from pathlib import Path
from typing import Iterable

logger = logging.getLogger(__name__)

ENV_CACHE_DB = "CVEKIT_BACKPORT_INDEX_DB"

#Linux upstream 自动判断
INDEX_KIND_LINUX_SUBJECT = "linux_subject"
#源仓 Excel title -> commit 解析/排序
INDEX_KIND_SOURCE_SUBJECT_NO_MERGES = "source_subject_no_merges"
#目标仓 title 检查
INDEX_KIND_TARGET_SUBJECT = "target_subject"


def default_cache_db_path() -> Path:
    raw_path = os.environ.get(ENV_CACHE_DB, "").strip()
    if raw_path:
        return Path(raw_path).expanduser()
    return Path("~/.cvekit/.cache/backport-index.sqlite").expanduser()


def normalize_subject(subject: str) -> str:
    # MVP 保持现有语义：只 strip，不做大小写或 patch 前缀归一化。
    return str(subject or "").strip()


def load_subject_matches(
    *,
    repo_path: str,
    ref_name: str,
    ref_sha: str,
    subjects: Iterable[str],
    index_kind: str,
    db_path: str | os.PathLike[str] | None = None,
) -> dict[str, tuple[str, ...]] | None:
    started_at = time.perf_counter()
    subject_list = [normalize_subject(subject) for subject in subjects if normalize_subject(subject)]
    if not subject_list:
        return {}

    repo_realpath = _repo_realpath(repo_path)
    repo_cache_id = _repo_cache_id(repo_realpath)
    db_file = Path(db_path).expanduser() if db_path else default_cache_db_path()
    with closing(_connect(db_file)) as conn:
        _ensure_schema(conn)
        meta = conn.execute(
            """
            SELECT tip_sha, status
            FROM repo_ref_index
            WHERE repo_realpath = ?
              AND ref_name = ?
              AND index_kind = ?
            """,
            (repo_cache_id, ref_name, index_kind),
        ).fetchone()
        if not meta or meta[0] != ref_sha or meta[1] != "complete":
            logger.info(
                "git subject disk cache miss repo=%s ref=%s sha=%s kind=%s subjects=%d elapsed=%.3fs",
                repo_realpath,
                ref_name,
                ref_sha,
                index_kind,
                len(subject_list),
                time.perf_counter() - started_at,
            )
            return None

        placeholders = ",".join("?" for _ in subject_list)
        rows = conn.execute(
            f"""
            SELECT subject, commit_id
            FROM git_commit_subjects
            WHERE repo_realpath = ?
              AND index_kind = ?
              AND subject IN ({placeholders})
            ORDER BY subject, commit_time DESC, commit_id
            """,
            (repo_cache_id, index_kind, *subject_list),
        ).fetchall()
        _touch_ref(conn, repo_cache_id, ref_name, index_kind)
        conn.commit()

    reachable = _reachable_commits(repo_realpath, ref_sha, [commit_id for _, commit_id in rows])
    matches: dict[str, list[str]] = {subject: [] for subject in subject_list}
    for subject, commit_id in rows:
        if commit_id not in reachable:
            continue
        matches.setdefault(subject, []).append(commit_id)
    matched_subjects = sum(1 for commit_ids in matches.values() if commit_ids)
    matched_commits = sum(len(commit_ids) for commit_ids in matches.values())
    logger.info(
        "git subject disk cache load repo=%s ref=%s sha=%s kind=%s subjects=%d candidate_rows=%d "
        "reachable_commits=%d matched_subjects=%d matched_commits=%d elapsed=%.3fs",
        repo_realpath,
        ref_name,
        ref_sha,
        index_kind,
        len(subject_list),
        len(rows),
        len(reachable),
        matched_subjects,
        matched_commits,
        time.perf_counter() - started_at,
    )
    return {subject: tuple(dict.fromkeys(commit_ids)) for subject, commit_ids in matches.items()}


def ensure_subject_index(
    *,
    repo_path: str,
    ref_name: str,
    ref_sha: str,
    index_kind: str,
    no_merges: bool = False,
    db_path: str | os.PathLike[str] | None = None,
) -> str:
    """Ensure subject facts for commits reachable from ref_sha exist.

    Returns one of: ``hit``, ``built``, ``incremental``.
    """
    repo_realpath = _repo_realpath(repo_path)
    repo_cache_id = _repo_cache_id(repo_realpath)
    db_file = Path(db_path).expanduser() if db_path else default_cache_db_path()
    db_file.parent.mkdir(parents=True, exist_ok=True)
    started_at = time.perf_counter()

    with closing(_connect(db_file)) as conn:
        _ensure_schema(conn)
        previous = _ref_meta(conn, repo_cache_id, ref_name, index_kind)
        if previous and previous["tip_sha"] == ref_sha:
            _touch_ref(conn, repo_cache_id, ref_name, index_kind)
            conn.commit()
            logger.info(
                "git subject disk cache hit repo=%s ref=%s sha=%s kind=%s elapsed=%.3fs",
                repo_realpath,
                ref_name,
                ref_sha,
                index_kind,
                time.perf_counter() - started_at,
            )
            return "hit"

    if previous:
        previous_tip = previous["tip_sha"]
        if _is_ancestor(repo_realpath, ref_sha, previous_tip):
            _store_ref_tip(
                db_file=db_file,
                repo_cache_id=repo_cache_id,
                ref_name=ref_name,
                ref_sha=ref_sha,
                index_kind=index_kind,
                item_count=0,
            )
            logger.info(
                "git subject disk cache ref moved backward repo=%s ref=%s old_sha=%s new_sha=%s kind=%s",
                repo_realpath,
                ref_name,
                previous_tip,
                ref_sha,
                index_kind,
            )
            return "hit"

        base_sha = _merge_base(repo_realpath, previous_tip, ref_sha)
        log_ref = f"{base_sha}..{ref_sha}" if base_sha else ref_sha
        status = "incremental" if base_sha else "built"
        rows_added = _import_subject_rows(
            db_file=db_file,
            repo_realpath=repo_realpath,
            repo_cache_id=repo_cache_id,
            ref_name=ref_name,
            ref_sha=ref_sha,
            index_kind=index_kind,
            log_ref=log_ref,
            no_merges=no_merges,
        )
        logger.info(
            "git subject disk cache imported repo=%s ref=%s old_sha=%s new_sha=%s base_sha=%s kind=%s rows_added=%d status=%s",
            repo_realpath,
            ref_name,
            previous_tip,
            ref_sha,
            base_sha or "",
            index_kind,
            rows_added,
            status,
        )
        return status

    build_and_store_subject_index(
        repo_path=repo_realpath,
        ref_name=ref_name,
        ref_sha=ref_sha,
        index_kind=index_kind,
        no_merges=no_merges,
        db_path=db_file,
        log_ref=ref_sha,
    )
    return "built"


def build_and_store_subject_index(
    *,
    repo_path: str,
    ref_name: str,
    ref_sha: str,
    index_kind: str,
    no_merges: bool = False,
    db_path: str | os.PathLike[str] | None = None,
    log_ref: str | None = None,
) -> int:
    repo_realpath = _repo_realpath(repo_path)
    repo_cache_id = _repo_cache_id(repo_realpath)
    db_file = Path(db_path).expanduser() if db_path else default_cache_db_path()
    started_at = time.perf_counter()
    rows_added = _import_subject_rows(
        db_file=db_file,
        repo_realpath=repo_realpath,
        repo_cache_id=repo_cache_id,
        ref_name=ref_name,
        ref_sha=ref_sha,
        index_kind=index_kind,
        log_ref=log_ref or ref_sha,
        no_merges=no_merges,
    )

    elapsed = time.perf_counter() - started_at
    logger.info(
        "git subject disk cache built repo=%s ref=%s sha=%s kind=%s rows=%d elapsed=%.3fs",
        repo_realpath,
        ref_name,
        ref_sha,
        index_kind,
        rows_added,
        elapsed,
    )
    return rows_added


def _repo_realpath(repo_path: str) -> str:
    return os.path.realpath(os.path.abspath(os.path.expanduser(repo_path)))


def _repo_cache_id(repo_realpath: str) -> str:
    return repo_realpath


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS repo_ref_index (
            repo_realpath TEXT NOT NULL,
            ref_name TEXT NOT NULL,
            index_kind TEXT NOT NULL,
            tip_sha TEXT NOT NULL,
            built_at TEXT NOT NULL,
            last_used_at TEXT,
            item_count INTEGER,
            status TEXT NOT NULL DEFAULT 'complete',
            PRIMARY KEY (
                repo_realpath,
                ref_name,
                index_kind
            )
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS git_commit_subjects (
            repo_realpath TEXT NOT NULL,
            index_kind TEXT NOT NULL,
            commit_id TEXT NOT NULL,
            subject TEXT NOT NULL,
            commit_time INTEGER NOT NULL DEFAULT 0,
            first_seen_at TEXT NOT NULL,
            PRIMARY KEY (
                repo_realpath,
                index_kind,
                commit_id
            )
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_git_commit_subject_lookup
        ON git_commit_subjects (
            repo_realpath,
            index_kind,
            subject,
            commit_time
        )
        """
    )


def _ref_meta(
    conn: sqlite3.Connection,
    repo_realpath: str,
    ref_name: str,
    index_kind: str,
) -> dict[str, str] | None:
    row = conn.execute(
        """
        SELECT tip_sha, built_at, last_used_at
        FROM repo_ref_index
        WHERE repo_realpath = ?
          AND ref_name = ?
          AND index_kind = ?
          AND status = 'complete'
        """,
        (repo_realpath, ref_name, index_kind),
    ).fetchone()
    if not row:
        return None
    return {"tip_sha": row[0], "built_at": row[1], "last_used_at": row[2] or ""}


def _store_ref_tip(
    *,
    db_file: Path,
    repo_cache_id: str,
    ref_name: str,
    ref_sha: str,
    index_kind: str,
    item_count: int,
) -> None:
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with closing(_connect(db_file)) as conn:
        _ensure_schema(conn)
        conn.execute(
            """
            INSERT OR REPLACE INTO repo_ref_index (
                repo_realpath,
                ref_name,
                index_kind,
                tip_sha,
                built_at,
                last_used_at,
                item_count,
                status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'complete')
            """,
            (repo_cache_id, ref_name, index_kind, ref_sha, now, now, item_count),
        )
        conn.commit()


def _import_subject_rows(
    *,
    db_file: Path,
    repo_realpath: str,
    repo_cache_id: str,
    ref_name: str,
    ref_sha: str,
    index_kind: str,
    log_ref: str,
    no_merges: bool,
) -> int:
    rows = [_coerce_subject_row(row) for row in _git_log_subject_rows(repo_realpath, log_ref, no_merges=no_merges)]
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    db_file.parent.mkdir(parents=True, exist_ok=True)
    with closing(_connect(db_file)) as conn:
        _ensure_schema(conn)
        conn.execute("BEGIN")
        before_changes = conn.total_changes
        conn.executemany(
            """
            INSERT OR IGNORE INTO git_commit_subjects (
                repo_realpath,
                index_kind,
                commit_id,
                subject,
                commit_time,
                first_seen_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (repo_cache_id, index_kind, commit_id, subject, commit_time, now)
                for commit_id, subject, commit_time in rows
                if subject
            ],
        )
        inserted = conn.total_changes - before_changes
        conn.execute(
            """
            INSERT OR REPLACE INTO repo_ref_index (
                repo_realpath,
                ref_name,
                index_kind,
                tip_sha,
                built_at,
                last_used_at,
                item_count,
                status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'complete')
            """,
            (repo_cache_id, ref_name, index_kind, ref_sha, now, now, len(rows)),
        )
        conn.commit()
    return int(inserted)


def _touch_ref(
    conn: sqlite3.Connection,
    repo_realpath: str,
    ref_name: str,
    index_kind: str,
) -> None:
    conn.execute(
        """
        UPDATE repo_ref_index
        SET last_used_at = ?
        WHERE repo_realpath = ?
          AND ref_name = ?
          AND index_kind = ?
        """,
        (
            time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            repo_realpath,
            ref_name,
            index_kind,
        ),
    )


def _is_ancestor(repo_path: str, old_sha: str, new_sha: str) -> bool:
    process = subprocess.run(
        [
            "git",
            "-C",
            repo_path,
            "merge-base",
            "--is-ancestor",
            old_sha,
            new_sha,
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return process.returncode == 0


def _merge_base(repo_path: str, old_sha: str, new_sha: str) -> str | None:
    process = subprocess.run(
        [
            "git",
            "-C",
            repo_path,
            "merge-base",
            old_sha,
            new_sha,
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if process.returncode != 0:
        return None
    base_sha = process.stdout.strip().splitlines()[0] if process.stdout.strip() else ""
    return base_sha or None


def _reachable_commits(repo_path: str, tip_sha: str, commit_ids: Iterable[str]) -> set[str]:
    candidates = list(dict.fromkeys(commit_id.strip() for commit_id in commit_ids if commit_id and commit_id.strip()))
    if not candidates:
        return set()
    existing_candidates = _existing_commits(repo_path, candidates)
    if not existing_candidates:
        return set()
    candidate_set = set(existing_candidates)
    process = subprocess.run(
        [
            "git",
            "-C",
            repo_path,
            "rev-list",
            "--stdin",
            "--not",
            tip_sha,
        ],
        input="\n".join(existing_candidates) + "\n",
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if process.returncode != 0:
        logger.warning(
            "git subject disk cache reachability filter failed repo=%s tip=%s: %s",
            repo_path,
            tip_sha,
            process.stderr.strip() or f"git rev-list exited with {process.returncode}",
        )
        return candidate_set
    unreachable = {
        line.strip()
        for line in process.stdout.splitlines()
        if line.strip() in candidate_set
    }
    return candidate_set - unreachable


def _existing_commits(repo_path: str, commit_ids: Iterable[str]) -> list[str]:
    candidates = list(dict.fromkeys(commit_id.strip() for commit_id in commit_ids if commit_id and commit_id.strip()))
    if not candidates:
        return []
    process = subprocess.run(
        [
            "git",
            "-C",
            repo_path,
            "cat-file",
            "--batch-check=%(objectname) %(objecttype)",
        ],
        input="\n".join(candidates) + "\n",
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if process.returncode != 0:
        logger.warning(
            "git subject disk cache object check failed repo=%s: %s",
            repo_path,
            process.stderr.strip() or f"git cat-file exited with {process.returncode}",
        )
        return candidates
    existing: list[str] = []
    for line in process.stdout.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1] == "commit":
            existing.append(parts[0])
    return existing


def _coerce_subject_row(row) -> tuple[str, str, int]:
    if len(row) == 2:
        commit_id, subject = row
        return str(commit_id), str(subject), 0
    commit_id, subject, commit_time = row[:3]
    try:
        parsed_time = int(commit_time)
    except (TypeError, ValueError):
        parsed_time = 0
    return str(commit_id), str(subject), parsed_time


def _git_log_subject_rows(repo_path: str, ref_name: str, *, no_merges: bool = False) -> list[tuple[str, str, int]]:
    command = [
        "git",
        "-C",
        repo_path,
        "log",
        ref_name,
    ]
    if no_merges:
        command.append("--no-merges")
    command.append("--format=%H%x00%ct%x00%s")
    process = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if process.returncode != 0:
        raise RuntimeError(
            process.stderr.strip() or f"git log exited with {process.returncode}"
        )

    rows: list[tuple[str, str, int]] = []
    for line in process.stdout.splitlines():
        parts = line.split("\x00", 2)
        if len(parts) != 3:
            continue
        commit_id, commit_time, subject = parts
        normalized = normalize_subject(subject)
        if not commit_id.strip() or not normalized:
            continue
        try:
            parsed_time = int(commit_time)
        except ValueError:
            parsed_time = 0
        rows.append((commit_id.strip(), normalized, parsed_time))
    return rows
