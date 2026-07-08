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

SCHEMA_VERSION = 1
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
    subject_list = [normalize_subject(subject) for subject in subjects if normalize_subject(subject)]
    if not subject_list:
        return {}

    repo_realpath = _repo_realpath(repo_path)
    db_file = Path(db_path).expanduser() if db_path else default_cache_db_path()
    with closing(_connect(db_file)) as conn:
        _ensure_schema(conn)
        meta = conn.execute(
            """
            SELECT status
            FROM index_meta
            WHERE repo_realpath = ?
              AND ref_name = ?
              AND ref_sha = ?
              AND index_kind = ?
              AND schema_version = ?
            """,
            (repo_realpath, ref_name, ref_sha, index_kind, SCHEMA_VERSION),
        ).fetchone()
        if not meta or meta[0] != "complete":
            return None

        placeholders = ",".join("?" for _ in subject_list)
        rows = conn.execute(
            f"""
            SELECT subject, commit_id
            FROM git_subject_index
            WHERE repo_realpath = ?
              AND ref_name = ?
              AND ref_sha = ?
              AND index_kind = ?
              AND subject IN ({placeholders})
            ORDER BY subject, position
            """,
            (repo_realpath, ref_name, ref_sha, index_kind, *subject_list),
        ).fetchall()
        _touch_meta(conn, repo_realpath, ref_name, ref_sha, index_kind)
        conn.commit()

    matches: dict[str, list[str]] = {subject: [] for subject in subject_list}
    for subject, commit_id in rows:
        matches.setdefault(subject, []).append(commit_id)
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
    """Ensure an index for ref_sha exists.

    Returns one of: ``hit``, ``built``, ``incremental``.
    """
    repo_realpath = _repo_realpath(repo_path)
    db_file = Path(db_path).expanduser() if db_path else default_cache_db_path()
    db_file.parent.mkdir(parents=True, exist_ok=True)

    with closing(_connect(db_file)) as conn:
        _ensure_schema(conn)
        if _meta_complete(conn, repo_realpath, ref_name, ref_sha, index_kind):
            _touch_meta(conn, repo_realpath, ref_name, ref_sha, index_kind)
            conn.commit()
            return "hit"

        previous = _latest_complete_meta(conn, repo_realpath, ref_name, index_kind)

    if previous and _is_ancestor(repo_realpath, previous["ref_sha"], ref_sha):
        started_at = time.perf_counter()
        added_rows = _git_log_subject_rows(
            repo_realpath,
            f"{previous['ref_sha']}..{ref_sha}",
            no_merges=no_merges,
        )
        _store_incremental_index(
            db_file=db_file,
            repo_realpath=repo_realpath,
            ref_name=ref_name,
            old_ref_sha=previous["ref_sha"],
            new_ref_sha=ref_sha,
            index_kind=index_kind,
            added_rows=added_rows,
        )
        elapsed = time.perf_counter() - started_at
        logger.info(
            "git subject disk cache incrementally updated repo=%s ref=%s old_sha=%s new_sha=%s kind=%s rows_added=%d elapsed=%.3fs",
            repo_realpath,
            ref_name,
            previous["ref_sha"],
            ref_sha,
            index_kind,
            len(added_rows),
            elapsed,
        )
        return "incremental"

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
    db_file = Path(db_path).expanduser() if db_path else default_cache_db_path()
    started_at = time.perf_counter()
    rows = _git_log_subject_rows(repo_realpath, log_ref or ref_name, no_merges=no_merges)
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    db_file.parent.mkdir(parents=True, exist_ok=True)
    with closing(_connect(db_file)) as conn:
        _ensure_schema(conn)
        conn.execute("BEGIN")
        conn.execute(
            """
            DELETE FROM git_subject_index
            WHERE repo_realpath = ?
              AND ref_name = ?
              AND ref_sha = ?
              AND index_kind = ?
            """,
            (repo_realpath, ref_name, ref_sha, index_kind),
        )
        conn.executemany(
            """
            INSERT INTO git_subject_index (
                repo_realpath,
                ref_name,
                ref_sha,
                index_kind,
                subject,
                commit_id,
                position
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (repo_realpath, ref_name, ref_sha, index_kind, subject, commit_id, index)
                for index, (commit_id, subject) in enumerate(rows)
                if subject
            ],
        )
        conn.execute(
            """
            INSERT OR REPLACE INTO index_meta (
                repo_realpath,
                ref_name,
                ref_sha,
                index_kind,
                schema_version,
                built_at,
                last_used_at,
                item_count,
                status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'complete')
            """,
            (repo_realpath, ref_name, ref_sha, index_kind, SCHEMA_VERSION, now, now, len(rows)),
        )
        conn.commit()

    elapsed = time.perf_counter() - started_at
    logger.info(
        "git subject disk cache built repo=%s ref=%s sha=%s kind=%s rows=%d elapsed=%.3fs",
        repo_realpath,
        ref_name,
        ref_sha,
        index_kind,
        len(rows),
        elapsed,
    )
    return len(rows)


def _repo_realpath(repo_path: str) -> str:
    return os.path.realpath(os.path.abspath(os.path.expanduser(repo_path)))


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS index_meta (
            repo_realpath TEXT NOT NULL,
            ref_name TEXT NOT NULL,
            ref_sha TEXT NOT NULL,
            index_kind TEXT NOT NULL,
            schema_version INTEGER NOT NULL,
            built_at TEXT NOT NULL,
            last_used_at TEXT,
            item_count INTEGER,
            status TEXT NOT NULL DEFAULT 'complete',
            PRIMARY KEY (
                repo_realpath,
                ref_name,
                ref_sha,
                index_kind,
                schema_version
            )
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS git_subject_index (
            repo_realpath TEXT NOT NULL,
            ref_name TEXT NOT NULL,
            ref_sha TEXT NOT NULL,
            index_kind TEXT NOT NULL,
            subject TEXT NOT NULL,
            commit_id TEXT NOT NULL,
            position INTEGER NOT NULL,
            PRIMARY KEY (
                repo_realpath,
                ref_name,
                ref_sha,
                index_kind,
                subject,
                commit_id
            )
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_git_subject_lookup
        ON git_subject_index (
            repo_realpath,
            ref_name,
            ref_sha,
            index_kind,
            subject
        )
        """
    )


def _meta_complete(
    conn: sqlite3.Connection,
    repo_realpath: str,
    ref_name: str,
    ref_sha: str,
    index_kind: str,
) -> bool:
    row = conn.execute(
        """
        SELECT status
        FROM index_meta
        WHERE repo_realpath = ?
          AND ref_name = ?
          AND ref_sha = ?
          AND index_kind = ?
          AND schema_version = ?
        """,
        (repo_realpath, ref_name, ref_sha, index_kind, SCHEMA_VERSION),
    ).fetchone()
    return bool(row and row[0] == "complete")


def _latest_complete_meta(
    conn: sqlite3.Connection,
    repo_realpath: str,
    ref_name: str,
    index_kind: str,
) -> dict[str, str] | None:
    row = conn.execute(
        """
        SELECT ref_sha, built_at, last_used_at
        FROM index_meta
        WHERE repo_realpath = ?
          AND ref_name = ?
          AND index_kind = ?
          AND schema_version = ?
          AND status = 'complete'
        ORDER BY COALESCE(last_used_at, built_at) DESC
        LIMIT 1
        """,
        (repo_realpath, ref_name, index_kind, SCHEMA_VERSION),
    ).fetchone()
    if not row:
        return None
    return {"ref_sha": row[0], "built_at": row[1], "last_used_at": row[2] or ""}


def _store_incremental_index(
    *,
    db_file: Path,
    repo_realpath: str,
    ref_name: str,
    old_ref_sha: str,
    new_ref_sha: str,
    index_kind: str,
    added_rows: list[tuple[str, str]],
) -> None:
    """保留旧 sha 的索引，再生成一份新 sha 的索引"""
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    offset = len([row for row in added_rows if row[1]])
    with closing(_connect(db_file)) as conn:
        _ensure_schema(conn)
        old_count = conn.execute(
            """
            SELECT COUNT(1)
            FROM git_subject_index
            WHERE repo_realpath = ?
              AND ref_name = ?
              AND ref_sha = ?
              AND index_kind = ?
            """,
            (repo_realpath, ref_name, old_ref_sha, index_kind),
        ).fetchone()[0]
        conn.execute("BEGIN")
        conn.execute(
            """
            DELETE FROM git_subject_index
            WHERE repo_realpath = ?
              AND ref_name = ?
              AND ref_sha = ?
              AND index_kind = ?
            """,
            (repo_realpath, ref_name, new_ref_sha, index_kind),
        )
        conn.executemany(
            """
            INSERT INTO git_subject_index (
                repo_realpath,
                ref_name,
                ref_sha,
                index_kind,
                subject,
                commit_id,
                position
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (repo_realpath, ref_name, new_ref_sha, index_kind, subject, commit_id, index)
                for index, (commit_id, subject) in enumerate(added_rows)
                if subject
            ],
        )
        conn.execute(
            """
            INSERT INTO git_subject_index (
                repo_realpath,
                ref_name,
                ref_sha,
                index_kind,
                subject,
                commit_id,
                position
            )
            SELECT
                repo_realpath,
                ref_name,
                ?,
                index_kind,
                subject,
                commit_id,
                position + ?
            FROM git_subject_index
            WHERE repo_realpath = ?
              AND ref_name = ?
              AND ref_sha = ?
              AND index_kind = ?
            """,
            (new_ref_sha, offset, repo_realpath, ref_name, old_ref_sha, index_kind),
        )
        conn.execute(
            """
            INSERT OR REPLACE INTO index_meta (
                repo_realpath,
                ref_name,
                ref_sha,
                index_kind,
                schema_version,
                built_at,
                last_used_at,
                item_count,
                status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'complete')
            """,
            (
                repo_realpath,
                ref_name,
                new_ref_sha,
                index_kind,
                SCHEMA_VERSION,
                now,
                now,
                old_count + offset,
            ),
        )
        conn.commit()


def _touch_meta(
    conn: sqlite3.Connection,
    repo_realpath: str,
    ref_name: str,
    ref_sha: str,
    index_kind: str,
) -> None:
    conn.execute(
        """
        UPDATE index_meta
        SET last_used_at = ?
        WHERE repo_realpath = ?
          AND ref_name = ?
          AND ref_sha = ?
          AND index_kind = ?
          AND schema_version = ?
        """,
        (
            time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            repo_realpath,
            ref_name,
            ref_sha,
            index_kind,
            SCHEMA_VERSION,
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


def _git_log_subject_rows(repo_path: str, ref_name: str, *, no_merges: bool = False) -> list[tuple[str, str]]:
    command = [
        "git",
        "-C",
        repo_path,
        "log",
        ref_name,
    ]
    if no_merges:
        command.append("--no-merges")
    command.append("--format=%H%x00%s")
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

    rows: list[tuple[str, str]] = []
    for line in process.stdout.splitlines():
        if "\x00" not in line:
            continue
        commit_id, subject = line.split("\x00", 1)
        normalized = normalize_subject(subject)
        if not commit_id.strip() or not normalized:
            continue
        rows.append((commit_id.strip(), normalized))
    return rows
