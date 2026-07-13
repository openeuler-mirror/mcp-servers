import json
import sys
from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest
import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from cvekit.utils import backport_batch
from cvekit.utils import backport_sort
from cvekit.utils import commit_message_template
from cvekit.utils.config_layout import ConfigError
from cvekit.utils import git_subject_index_cache


def _write_test_patch(path: Path, subject: str) -> None:
    path.write_text(
        "\n".join(
            [
                f"Subject: [PATCH] {subject}",
                "",
                "---",
                " file.txt | 1 +",
                " 1 file changed, 1 insertion(+)",
            ]
        ),
        encoding="utf-8",
    )


def test_normalize_backport_batch_commits_accepts_mapping_values():
    commit_items = {
        "abc123": {"commit_title": "Fix one", "target_branch": "OLK-6.6"},
        "def456": "Fix two",
    }

    normalized = backport_batch._normalize_backport_batch_commits(commit_items)

    assert normalized == [
        {"commit": "abc123", "commit_title": "Fix one", "target_branch": "OLK-6.6"},
        {"commit": "def456", "commit_title": "Fix two"},
    ]


def test_is_report_config_requires_report_suffix_even_with_report_fields():
    commit_items = [
        {
            "commit": "abc123",
            "has_conflict": True,
            "conflict_check_method": "git-apply",
            "merged_in_target": False,
        }
    ]

    assert backport_batch._is_report_config("batch.yml", commit_items) is False
    assert backport_batch._is_report_config("batch.report.yml", commit_items) is True


def test_conflict_summary_enabled_defaults_to_false():
    args = Namespace()

    assert backport_batch._conflict_summary_enabled(args, {}) is False


def test_conflict_summary_enabled_accepts_cli_or_config():
    assert backport_batch._conflict_summary_enabled(
        Namespace(enable_conflict_summary=True),
        {},
    ) is True
    assert backport_batch._conflict_summary_enabled(
        Namespace(enable_conflict_summary=False),
        {"enable_conflict_summary": True},
    ) is True


def test_apply_conflict_summaries_only_summarizes_complete_conflict_items(monkeypatch):
    calls = []

    def fake_summarize(**kwargs):
        calls.append(kwargs)
        return {
            "status": "success",
            "provider": "opencode",
            "score": 5,
            "reason": "summary",
            "error": "",
        }

    monkeypatch.setattr(backport_batch, "summarize_conflict_item", fake_summarize)
    report_items = [
        {
            "commit": "abc123",
            "commit_title": "Fix A",
            "target_branch": "OLK-6.6",
            "has_conflict": True,
            "original_patch_path": "/tmp/source.patch",
            "backported_patch_path": "/tmp/resolved.patch",
        },
        {
            "commit": "def456",
            "has_conflict": True,
            "original_patch_path": "/tmp/source.patch",
            "backported_patch_path": "",
        },
        {
            "commit": "ghi789",
            "has_conflict": False,
            "original_patch_path": "/tmp/source.patch",
            "backported_patch_path": "/tmp/resolved.patch",
        },
    ]

    backport_batch._apply_conflict_summaries(report_items, "/tmp/target")

    assert len(calls) == 1
    assert calls[0]["target_branch"] == "OLK-6.6"
    assert calls[0]["target_path"] == "/tmp/target"
    assert report_items[0]["conflict_summary"]["status"] == "success"
    assert report_items[1]["conflict_summary"]["status"] == "skipped"
    assert "conflict_summary" not in report_items[2]


def test_apply_conflict_summaries_records_single_item_failure(monkeypatch):
    def fake_summarize(**kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(backport_batch, "summarize_conflict_item", fake_summarize)
    report_items = [
        {
            "commit": "abc123",
            "has_conflict": True,
            "original_patch_path": "/tmp/source.patch",
            "backported_patch_path": "/tmp/resolved.patch",
        }
    ]

    backport_batch._apply_conflict_summaries(report_items, "/tmp/target")

    assert report_items[0]["conflict_summary"]["status"] == "failed"
    assert report_items[0]["conflict_summary"]["error"] == "boom"


def test_find_commit_title_in_target_ignores_reverted_title_match():
    title = "drm/hisilicon/hibmc: Replace module initialization with DRM helpers"
    target_repo = SimpleNamespace(
        git=SimpleNamespace(
            log=lambda *args: "\n".join(
                [
                    f'222\x00Revert "{title}"',
                    f"111\x00{title}",
                ]
            )
        )
    )

    matched_sha, error = backport_batch._find_commit_title_in_target(
        target_repo,
        "target-branch",
        title,
    )

    assert matched_sha is None
    assert error == "matched title was later reverted by: 222"


def test_find_commit_title_in_target_accepts_title_match_after_revert():
    title = "drm/hisilicon/hibmc: Replace module initialization with DRM helpers"
    target_repo = SimpleNamespace(
        git=SimpleNamespace(
            log=lambda *args: "\n".join(
                [
                    f"333\x00{title}",
                    f'222\x00Revert "{title}"',
                    f"111\x00{title}",
                ]
            )
        )
    )

    matched_sha, error = backport_batch._find_commit_title_in_target(
        target_repo,
        "target-branch",
        title,
    )

    assert matched_sha == "333"
    assert error is None


def test_matching_revert_subject_collapses_whitespace():
    assert backport_batch._matching_revert_subject(
        "drm/hisilicon/hibmc: Replace module initialization with DRM helpers",
        '  Revert   "drm/hisilicon/hibmc:  Replace module initialization with DRM helpers"  ',
    )


def test_matching_revert_subject_allows_case_and_colon_variants():
    assert backport_batch._matching_revert_subject(
        "drm/hisilicon/hibmc: Replace module initialization with DRM helpers",
        'revert: "DRM/HISILICON/HIBMC: replace module initialization with DRM helpers"',
    )


def test_handle_backport_batch_rejects_execute_with_raw_config_suffix():
    args = Namespace(
        preview_commit_message=False,
        apply=None,
        execute=True,
        backport_config="batch.yml",
    )

    with pytest.raises(ValueError, match=r"\.report\.yml"):
        backport_batch.handle_backport_batch(args)


def test_execute_backport_batch_items_stops_after_first_conflict_and_marks_rest_pending():
    args = Namespace(stop_at_first_conflict=True)
    sorted_items = [
        {
            "commit": "c1",
            "input_commit": "c1",
            "commit_title": "first",
            "git_describe": "v1",
            "committed_datetime": "2025-01-01T00:00:00",
            "item_config": {"target_branch": "branch-1", "patch_path": "/tmp/one.patch"},
        },
        {
            "commit": "c2",
            "input_commit": "c2",
            "commit_title": "second",
            "git_describe": "v2",
            "committed_datetime": "2025-01-02T00:00:00",
            "item_config": {"target_release": "branch-2", "patch_path": "/tmp/two.patch"},
        },
        {
            "commit": "c3",
            "input_commit": "c3",
            "commit_title": "third",
            "git_describe": "v3",
            "committed_datetime": "2025-01-03T00:00:00",
            "item_config": {"patch_path": "/tmp/three.patch"},
        },
    ]

    processed = {
        "skip": False,
        "did_backport": False,
        "result": {"tag": "c1"},
        "report_item": {"commit": "c1", "status": "success", "has_conflict": True},
    }

    with mock.patch.object(
        backport_batch, "_process_backport_batch_item", return_value=processed
    ) as process_mock:
        results, report_items = backport_batch._execute_backport_batch_items(
            sorted_items=sorted_items,
            sort_errors=[],
            is_report_config=False,
            base_config={"target_branch": "default-branch"},
            base_project_dir="/tmp/project",
            base_target_path="/tmp/target",
            default_target_branch="default-branch",
            linux_subject_allowlist=frozenset(),
            filtered_subject_index_cache=backport_batch.FilteredSubjectIndexCache(),
            target_title_allowlist=frozenset(),
            target_title_index_cache=backport_batch.FilteredTitleIndexCache(),
            prepared_patch_batch_token="test-batch-token",
            args=args,
        )

    process_mock.assert_called_once()
    assert results == [{"tag": "c1"}]
    assert [item["commit"] for item in report_items] == ["c1", "c2", "c3"]
    assert report_items[1]["status"] == "pending"
    assert report_items[1]["target_branch"] == "branch-2"
    assert report_items[1]["patch_path"] == "/tmp/two.patch"
    assert report_items[2]["status"] == "pending"
    assert report_items[2]["target_branch"] == "default-branch"


def test_execute_backport_batch_items_report_mode_resumes_from_first_pending():
    args = Namespace(stop_at_first_conflict=True)
    sorted_items = [
        {"commit": "done-1", "status": "success", "target_branch": "branch-a"},
        {"commit": "todo-1", "status": "pending", "target_branch": "branch-b"},
        {"commit": "todo-2", "status": "pending", "target_branch": "branch-c"},
    ]

    process_results = [
        {
            "skip": False,
            "did_backport": False,
            "result": {"tag": "todo-1"},
            "report_item": {
                "commit": "todo-1",
                "status": "success",
                "has_conflict": False,
            },
        },
        {
            "skip": False,
            "did_backport": False,
            "result": {"tag": "todo-2"},
            "report_item": {
                "commit": "todo-2",
                "status": "success",
                "has_conflict": False,
            },
        },
    ]

    with mock.patch.object(
        backport_batch, "_process_backport_batch_item", side_effect=process_results
    ) as process_mock:
        results, report_items = backport_batch._execute_backport_batch_items(
            sorted_items=sorted_items,
            sort_errors=[],
            is_report_config=True,
            base_config={"target_branch": "default-branch"},
            base_project_dir="/tmp/project",
            base_target_path="/tmp/target",
            default_target_branch="default-branch",
            linux_subject_allowlist=frozenset(),
            filtered_subject_index_cache=backport_batch.FilteredSubjectIndexCache(),
            target_title_allowlist=frozenset(),
            target_title_index_cache=backport_batch.FilteredTitleIndexCache(),
            prepared_patch_batch_token="test-batch-token",
            args=args,
        )

    assert process_mock.call_count == 2
    assert report_items[0] == sorted_items[0]
    assert [item["commit"] for item in report_items] == ["done-1", "todo-1", "todo-2"]
    assert results == [{"tag": "todo-1"}, {"tag": "todo-2"}]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("Commit Title", "committitle"),
        (" commit-hash ", "commithash"),
        ("Subject/Title", "subjecttitle"),
        (None, ""),
        ("", ""),
    ],
)
def test_normalize_excel_header(value, expected):
    assert backport_batch._normalize_excel_header(value) == expected


def test_resolve_excel_commit_columns_accepts_aliases():
    header_row = ("Patch Title", "SHA", "Other")

    title_idx, hash_idx = backport_batch._resolve_excel_commit_columns(header_row)

    assert title_idx == 0
    assert hash_idx == 1


def test_resolve_excel_commit_columns_requires_both_columns():
    with pytest.raises(ValueError, match="Excel 缺少必需列"):
        backport_batch._resolve_excel_commit_columns(("title", "owner"))


@pytest.mark.parametrize(
    ("row", "idx", "expected"),
    [
        (("abc", "def"), 0, "abc"),
        (("abc", " def "), 1, "def"),
        (("abc", None), 1, ""),
        (("abc",), 3, ""),
        ((), 0, ""),
    ],
)
def test_normalize_excel_cell_value(row, idx, expected):
    assert backport_batch._normalize_excel_cell_value(row, idx) == expected


@pytest.mark.parametrize(
    ("provider", "item_config", "base_config", "expected"),
    [
        ("cli", {"commit_message_source": "item"}, {"commit_message_source": "base"}, "item"),
        ("", {"commit_message_source": "item"}, {"commit_message_source": "base"}, "item"),
        ("", {}, {"commit_message_source": "base"}, "base"),
        ("", {}, {}, "auto"),
    ],
)
def test_resolve_commit_message_source(provider, item_config, base_config, expected):
    args = SimpleNamespace(commit_message_source=provider)

    assert (
        backport_batch._resolve_commit_message_source(args, item_config, base_config)
        == expected
    )


@pytest.mark.parametrize(
    ("cli_value", "item_value", "base_value", "expected"),
    [
        ("mystique", "", "", "mystique"),
        ("", "mystique", "", "mystique"),
        ("", "", "mystique", "mystique"),
        ("", "", "", "portgpt"),
        ("PORTGPT", "", "", "portgpt"),
    ],
)
def test_resolve_backport_engine(cli_value, item_value, base_value, expected):
    args = SimpleNamespace(backport_engine=cli_value)

    assert (
        backport_batch._resolve_backport_engine(
            args,
            {"backport_engine": item_value} if item_value else {},
            {"backport_engine": base_value} if base_value else {},
        )
        == expected
    )


def test_resolve_complete_linux_subject_allowlist_collects_generated_preview_subjects(tmp_path):
    generated_patch = tmp_path / "generated.patch"
    skipped_patch = tmp_path / "skipped.patch"
    _write_test_patch(generated_patch, "Need generated preview")
    _write_test_patch(skipped_patch, "Already has preview")
    sorted_items = [
        {
            "commit": "c1",
            "item_config": {
                "target_branch": "branch-1",
            },
        },
        {
            "commit": "c2",
            "item_config": {
                "target_branch": "branch-2",
                "patch_path": str(skipped_patch),
                "commit_message_preview": "existing preview",
            },
        },
    ]

    def prepare_side_effect(**kwargs):
        if kwargs["fixed_commit"] == "c1":
            return "c1-full", str(generated_patch), False, False
        return kwargs["fixed_commit"], kwargs["patch_path"], False, False

    with mock.patch.object(
        backport_batch,
        "_prepare_backport_patch_and_commit",
        side_effect=prepare_side_effect,
    ):
        allowlist = backport_batch._resolve_complete_linux_subject_allowlist(
            sorted_items,
            is_report_config=False,
            base_project_dir=str(tmp_path),
            prepared_patch_batch_token="batch-token",
            generate_missing_patch=False,
        )

    assert allowlist == frozenset({"Need generated preview"})
    assert sorted_items[0]["commit"] == "c1-full"
    assert sorted_items[0]["item_config"]["patch_path"] == str(generated_patch)
    assert sorted_items[0]["item_config"]["_prepared_patch_batch_token"] == "batch-token"
    assert sorted_items[0]["item_config"]["_prepared_patch_path"] == str(generated_patch)


def test_resolve_complete_linux_subject_allowlist_covers_report_items_needing_report_preview(tmp_path):
    original_patch = tmp_path / "report-original.patch"
    _write_test_patch(original_patch, "Need report preview")
    sorted_items = [
        {
            "commit": "c3",
            "status": "success",
            "target_branch": "branch-report",
            "original_patch_path": str(original_patch),
        }
    ]

    with mock.patch.object(
        backport_batch,
        "_prepare_backport_patch_and_commit",
        return_value=("c3", str(original_patch), False, False),
    ):
        allowlist = backport_batch._resolve_complete_linux_subject_allowlist(
            sorted_items,
            is_report_config=True,
            base_project_dir=str(tmp_path),
            prepared_patch_batch_token="batch-token",
            generate_missing_patch=False,
        )

    assert allowlist == frozenset({"Need report preview"})
    assert sorted_items[0]["patch_path"] == str(original_patch)
    assert sorted_items[0]["_prepared_patch_batch_token"] == "batch-token"


def test_resolve_complete_linux_subject_allowlist_skips_stale_patch_when_generation_fails(tmp_path):
    stale_patch = tmp_path / "stale.patch"
    _write_test_patch(stale_patch, "Stale subject")
    sorted_items = [
        {
            "commit": "c4",
            "item_config": {
                "patch_path": str(stale_patch),
            },
        }
    ]

    with mock.patch.object(
        backport_batch,
        "_prepare_backport_patch_and_commit",
        return_value=("c4", str(stale_patch), False, True),
    ):
        allowlist = backport_batch._resolve_complete_linux_subject_allowlist(
            sorted_items,
            is_report_config=False,
            base_project_dir=str(tmp_path),
            prepared_patch_batch_token="batch-token",
            generate_missing_patch=False,
        )

    assert allowlist == frozenset()
    assert "_prepared_patch_batch_token" not in sorted_items[0]["item_config"]
    assert "_prepared_patch_path" not in sorted_items[0]["item_config"]


def test_source_detector_allowlist_hits_filtered_index_without_grep(tmp_path):
    repo = SimpleNamespace(git=mock.Mock())
    detector = commit_message_template.SourceDetector(
        linux_repo_path=str(tmp_path),
        subject_allowlist=frozenset({"Indexed subject"}),
        filtered_subject_index_cache=commit_message_template.FilteredSubjectIndexCache(),
    )

    with mock.patch.object(detector, "_repo", return_value=repo), mock.patch.object(
        detector,
        "_filtered_subject_index",
        return_value={"Indexed subject": ("sha1",)},
    ) as index_mock:
        matches = detector._find_commits_by_subject("Indexed subject")

    assert matches == ["sha1"]
    index_mock.assert_called_once_with(repo)
    repo.git.log.assert_not_called()


def test_git_subject_index_cache_reuses_full_index_for_different_allowlists(tmp_path, monkeypatch):
    db_path = tmp_path / "backport-index.sqlite"
    repo_path = tmp_path / "linux"
    repo_path.mkdir()
    calls = []

    def fake_git_log_subject_rows(path: str, ref_name: str, *, no_merges: bool = False):
        calls.append((path, ref_name, no_merges))
        return [
            ("sha1", "First subject"),
            ("sha2", "Second subject"),
        ]

    monkeypatch.setenv(git_subject_index_cache.ENV_CACHE_DB, str(db_path))
    monkeypatch.setattr(git_subject_index_cache, "_git_log_subject_rows", fake_git_log_subject_rows)

    stored = git_subject_index_cache.build_and_store_subject_index(
        repo_path=str(repo_path),
        ref_name="origin/master",
        ref_sha="master-a",
        index_kind=git_subject_index_cache.INDEX_KIND_LINUX_SUBJECT,
    )
    first = git_subject_index_cache.load_subject_matches(
        repo_path=str(repo_path),
        ref_name="origin/master",
        ref_sha="master-a",
        subjects={"First subject"},
        index_kind=git_subject_index_cache.INDEX_KIND_LINUX_SUBJECT,
    )
    second = git_subject_index_cache.load_subject_matches(
        repo_path=str(repo_path),
        ref_name="origin/master",
        ref_sha="master-a",
        subjects={"Second subject"},
        index_kind=git_subject_index_cache.INDEX_KIND_LINUX_SUBJECT,
    )
    changed_ref = git_subject_index_cache.load_subject_matches(
        repo_path=str(repo_path),
        ref_name="origin/master",
        ref_sha="master-b",
        subjects={"First subject"},
        index_kind=git_subject_index_cache.INDEX_KIND_LINUX_SUBJECT,
    )

    assert stored == 2
    assert first == {"First subject": ("sha1",)}
    assert second == {"Second subject": ("sha2",)}
    assert changed_ref is None
    assert calls == [(str(repo_path.resolve()), "origin/master", False)]


def test_git_subject_index_cache_incrementally_updates_fast_forward_ref(tmp_path, monkeypatch):
    db_path = tmp_path / "backport-index.sqlite"
    repo_path = tmp_path / "source"
    repo_path.mkdir()
    calls = []

    def fake_git_log_subject_rows(path: str, ref_name: str, *, no_merges: bool = False):
        calls.append((ref_name, no_merges))
        if ref_name == "source-a":
            return [("old-sha", "Old subject")]
        if ref_name == "source-a..source-b":
            return [("new-sha", "New subject")]
        raise AssertionError(f"unexpected git log ref: {ref_name}")

    monkeypatch.setenv(git_subject_index_cache.ENV_CACHE_DB, str(db_path))
    monkeypatch.setattr(git_subject_index_cache, "_git_log_subject_rows", fake_git_log_subject_rows)
    monkeypatch.setattr(git_subject_index_cache, "_is_ancestor", lambda repo, old, new: True)

    first_status = git_subject_index_cache.ensure_subject_index(
        repo_path=str(repo_path),
        ref_name="source-branch",
        ref_sha="source-a",
        index_kind=git_subject_index_cache.INDEX_KIND_SOURCE_SUBJECT_NO_MERGES,
        no_merges=True,
    )
    second_status = git_subject_index_cache.ensure_subject_index(
        repo_path=str(repo_path),
        ref_name="source-branch",
        ref_sha="source-b",
        index_kind=git_subject_index_cache.INDEX_KIND_SOURCE_SUBJECT_NO_MERGES,
        no_merges=True,
    )
    matches = git_subject_index_cache.load_subject_matches(
        repo_path=str(repo_path),
        ref_name="source-branch",
        ref_sha="source-b",
        subjects={"Old subject", "New subject"},
        index_kind=git_subject_index_cache.INDEX_KIND_SOURCE_SUBJECT_NO_MERGES,
    )

    assert first_status == "built"
    assert second_status == "incremental"
    assert matches == {
        "New subject": ("new-sha",),
        "Old subject": ("old-sha",),
    }
    assert calls == [("source-a", True), ("source-a..source-b", True)]


def test_git_subject_index_cache_rebuilds_non_fast_forward_ref(tmp_path, monkeypatch):
    db_path = tmp_path / "backport-index.sqlite"
    repo_path = tmp_path / "source"
    repo_path.mkdir()
    calls = []

    def fake_git_log_subject_rows(path: str, ref_name: str, *, no_merges: bool = False):
        calls.append(ref_name)
        if ref_name == "source-a":
            return [("old-sha", "Old subject")]
        if ref_name == "source-c":
            return [("new-sha", "New subject")]
        raise AssertionError(f"unexpected git log ref: {ref_name}")

    monkeypatch.setenv(git_subject_index_cache.ENV_CACHE_DB, str(db_path))
    monkeypatch.setattr(git_subject_index_cache, "_git_log_subject_rows", fake_git_log_subject_rows)
    monkeypatch.setattr(git_subject_index_cache, "_is_ancestor", lambda repo, old, new: False)

    git_subject_index_cache.ensure_subject_index(
        repo_path=str(repo_path),
        ref_name="source-branch",
        ref_sha="source-a",
        index_kind=git_subject_index_cache.INDEX_KIND_SOURCE_SUBJECT_NO_MERGES,
        no_merges=True,
    )
    status = git_subject_index_cache.ensure_subject_index(
        repo_path=str(repo_path),
        ref_name="source-branch",
        ref_sha="source-c",
        index_kind=git_subject_index_cache.INDEX_KIND_SOURCE_SUBJECT_NO_MERGES,
        no_merges=True,
    )
    matches = git_subject_index_cache.load_subject_matches(
        repo_path=str(repo_path),
        ref_name="source-branch",
        ref_sha="source-c",
        subjects={"Old subject", "New subject"},
        index_kind=git_subject_index_cache.INDEX_KIND_SOURCE_SUBJECT_NO_MERGES,
    )

    assert status == "built"
    assert matches == {
        "Old subject": (),
        "New subject": ("new-sha",),
    }
    assert calls == ["source-a", "source-c"]


def test_source_detector_allowlist_uses_disk_cache_across_instances(tmp_path, monkeypatch):
    db_path = tmp_path / "backport-index.sqlite"
    repo_path = tmp_path / "linux"
    repo_path.mkdir()
    monkeypatch.setenv(git_subject_index_cache.ENV_CACHE_DB, str(db_path))
    monkeypatch.setattr(
        git_subject_index_cache,
        "_git_log_subject_rows",
        lambda path, ref_name, *, no_merges=False: [("sha1", "Indexed subject")],
    )
    git_subject_index_cache.build_and_store_subject_index(
        repo_path=str(repo_path),
        ref_name="origin/master",
        ref_sha="master-a",
        index_kind=git_subject_index_cache.INDEX_KIND_LINUX_SUBJECT,
    )
    repo = SimpleNamespace(
        working_tree_dir=str(repo_path),
        commit=lambda ref: SimpleNamespace(hexsha="master-a"),
    )
    detector = commit_message_template.SourceDetector(
        linux_repo_path=str(repo_path),
        subject_allowlist=frozenset({"Indexed subject"}),
        filtered_subject_index_cache=commit_message_template.FilteredSubjectIndexCache(),
    )

    with mock.patch.object(detector, "_repo", return_value=repo), mock.patch(
        "cvekit.utils.commit_message_template.subprocess.Popen"
    ) as popen_mock:
        matches = detector._find_commits_by_subject("Indexed subject")

    assert matches == ["sha1"]
    popen_mock.assert_not_called()


def test_source_detector_no_cache_skips_disk_cache(tmp_path, monkeypatch):
    repo_path = tmp_path / "linux"
    repo_path.mkdir()
    repo = SimpleNamespace(
        working_tree_dir=str(repo_path),
        commit=lambda ref: SimpleNamespace(hexsha="master-a"),
    )

    class FakeProcess:
        returncode = 0

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def communicate(self):
            return "sha-fallback\x00Indexed subject\n", ""

    detector = commit_message_template.SourceDetector(
        linux_repo_path=str(repo_path),
        subject_allowlist=frozenset({"Indexed subject"}),
        filtered_subject_index_cache=commit_message_template.FilteredSubjectIndexCache(),
        use_disk_subject_index_cache=False,
    )

    with mock.patch.object(detector, "_repo", return_value=repo), mock.patch(
        "cvekit.utils.commit_message_template.git_subject_index_cache.load_subject_matches"
    ) as load_mock, mock.patch(
        "cvekit.utils.commit_message_template.subprocess.Popen",
        return_value=FakeProcess(),
    ) as popen_mock:
        matches = detector._find_commits_by_subject("Indexed subject")

    assert matches == ["sha-fallback"]
    load_mock.assert_not_called()
    popen_mock.assert_called_once()


def test_source_sort_subject_index_uses_disk_cache(tmp_path, monkeypatch):
    db_path = tmp_path / "backport-index.sqlite"
    repo_path = tmp_path / "source"
    repo_path.mkdir()
    monkeypatch.setenv(git_subject_index_cache.ENV_CACHE_DB, str(db_path))
    monkeypatch.setattr(
        git_subject_index_cache,
        "_git_log_subject_rows",
        lambda path, ref_name, *, no_merges=False: [("sha1", "Source title")],
    )
    git_subject_index_cache.build_and_store_subject_index(
        repo_path=str(repo_path),
        ref_name="source-branch",
        ref_sha="source-a",
        index_kind=git_subject_index_cache.INDEX_KIND_SOURCE_SUBJECT_NO_MERGES,
        no_merges=True,
    )
    repo = SimpleNamespace(
        working_tree_dir=str(repo_path),
        working_dir=str(repo_path),
        commit=lambda ref: SimpleNamespace(hexsha="source-a"),
        git=SimpleNamespace(log=mock.Mock()),
    )

    index, error = backport_sort._build_commit_subject_index(
        repo,
        "source-branch",
        {"Source title"},
    )

    assert error is None
    assert index == [("sha1", "Source title", "source title")]
    repo.git.log.assert_not_called()


def test_target_title_index_uses_disk_cache_across_cache_instances(tmp_path, monkeypatch):
    db_path = tmp_path / "backport-index.sqlite"
    repo_path = tmp_path / "target"
    repo_path.mkdir()
    monkeypatch.setenv(git_subject_index_cache.ENV_CACHE_DB, str(db_path))
    monkeypatch.setattr(
        git_subject_index_cache,
        "_git_log_subject_rows",
        lambda path, ref_name, *, no_merges=False: [
            ("sha1", "Target title"),
            ("sha2", 'Revert "Old title"'),
        ],
    )
    git_subject_index_cache.build_and_store_subject_index(
        repo_path=str(repo_path),
        ref_name="target-branch",
        ref_sha="target-a",
        index_kind=git_subject_index_cache.INDEX_KIND_TARGET_SUBJECT,
    )
    target_repo = SimpleNamespace(
        working_tree_dir=str(repo_path),
        working_dir=str(repo_path),
        commit=lambda ref: SimpleNamespace(hexsha="target-a"),
    )

    with mock.patch("cvekit.utils.backport_batch.subprocess.Popen") as popen_mock:
        matches = backport_batch._filtered_commit_title_index_in_target(
            target_repo,
            "target-branch",
            {"Target title", "Old title"},
            backport_batch.FilteredTitleIndexCache(),
        )

    assert matches == {
        "Old title": (("revert", "sha2", 'Revert "Old title"'),),
        "Target title": (("match", "sha1", "Target title"),),
    }
    popen_mock.assert_not_called()


def test_target_title_index_uses_fixed_baseline_sha(tmp_path, monkeypatch):
    db_path = tmp_path / "backport-index.sqlite"
    repo_path = tmp_path / "target"
    repo_path.mkdir()
    logged_refs = []

    def fake_git_log_subject_rows(path: str, ref_name: str, *, no_merges: bool = False):
        logged_refs.append(ref_name)
        return [("base-sha", "Target title")]

    monkeypatch.setenv(git_subject_index_cache.ENV_CACHE_DB, str(db_path))
    monkeypatch.setattr(git_subject_index_cache, "_git_log_subject_rows", fake_git_log_subject_rows)
    monkeypatch.setattr(git_subject_index_cache, "_is_ancestor", lambda repo, old, new: True)
    target_repo = SimpleNamespace(
        working_tree_dir=str(repo_path),
        working_dir=str(repo_path),
        commit=lambda ref: SimpleNamespace(hexsha="moving-head-sha"),
    )

    matches = backport_batch._filtered_commit_title_index_in_target(
        target_repo,
        "target-branch",
        {"Target title"},
        backport_batch.FilteredTitleIndexCache(),
        index_ref_sha="baseline-sha",
    )

    assert matches == {"Target title": (("match", "base-sha", "Target title"),)}
    assert logged_refs == ["baseline-sha"]


def test_prepare_context_uses_report_target_title_index_baseline(monkeypatch):
    args = Namespace(backport_config="batch.report.yml", interactive=False)
    config = {
        "project_dir": "/src/project",
        "target_path": "/src/target",
        "target_branch": "OLK-6.6",
        "target_title_index_ref_sha": "pinned-target-sha",
        "commits": [{"commit": "abc123"}],
    }
    sorted_items = [{"commit": "abc123", "status": "pending"}]

    monkeypatch.setattr(backport_batch, "_load_backport_batch_config", lambda path: (config, config["commits"]))
    monkeypatch.setattr(backport_batch, "_is_report_config", lambda path, items: True)
    monkeypatch.setattr(
        backport_batch,
        "_resolve_sorted_backport_items",
        lambda commit_items, is_report_config, base_project_dir, base_config, args: (sorted_items, []),
    )
    monkeypatch.setattr(backport_batch, "_resolve_complete_target_title_allowlist", lambda items, project_dir: frozenset())
    monkeypatch.setattr(
        backport_batch,
        "_resolve_complete_linux_subject_allowlist",
        lambda *args, **kwargs: frozenset(),
    )
    monkeypatch.setattr(
        backport_batch,
        "_resolve_target_title_index_ref_sha",
        mock.Mock(side_effect=AssertionError("should use pinned baseline")),
    )

    context = backport_batch._prepare_backport_batch_context(args)

    assert context.target_title_index_ref_sha == "pinned-target-sha"


def test_resolve_backport_engine_rejects_unknown_engine():
    args = SimpleNamespace(backport_engine="unknown")

    with pytest.raises(ValueError, match="不支持的 backport_engine"):
        backport_batch._resolve_backport_engine(args, {}, {})


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("true", True),
        ("TRUE", True),
        ("yes", True),
        ("false", False),
        ("No", False),
        ("none", "invalid"),
        ("whatever", "invalid"),
        (None, "invalid"),
    ],
)
def test_parse_bool_text(value, expected):
    assert backport_batch._parse_bool_text(value) == expected


@pytest.mark.parametrize(
    ("value", "allow_skipped", "expected"),
    [
        ("true", False, True),
        ("False", False, False),
        ("none", False, None),
        ("n/a", False, None),
        ("skipped", True, "skipped"),
        ("skipped", False, "invalid"),
        ("bad", False, "invalid"),
        (None, False, None),
    ],
)
def test_parse_merged_in_target_value(value, allow_skipped, expected):
    assert (
        backport_batch._parse_merged_in_target_value(
            value, allow_skipped=allow_skipped
        )
        == expected
    )


@pytest.mark.parametrize(
    ("item", "query", "expected"),
    [
        ({"commit_title": "drm fix bug"}, "title:drm", (True, None)),
        ({"commit_title": "drm fix bug"}, "commit_title=drm", (True, None)),
        ({"commit_title": "drm fix bug"}, "drm", (True, None)),
        ({"commit": "abc1234"}, "commit:abc", (True, None)),
        ({"input_commit": "def5678"}, "sha:def", (True, None)),
        ({"has_conflict": True}, "has_conflict=true", (True, None)),
        ({"has_conflict": False}, "conflict=false", (True, None)),
        ({"merged_in_target": True}, "merged=true", (True, None)),
        ({"merged_in_target": None}, "merged_in_target=none", (True, None)),
        (
            {"merged_in_target": "skipped", "is_merge_commit": True},
            "merged=skipped",
            (True, None),
        ),
        ({}, "unknown:value", (False, "不支持的搜索字段: unknown")),
        ({}, "has_conflict=maybe", (False, "has_conflict 只支持 true/false")),
        ({}, "merged=maybe", (False, "merged_in_target 只支持 true/false/none/skipped")),
    ],
)
def test_match_commit_item_with_query(item, query, expected):
    assert backport_batch._match_commit_item_with_query(item, query) == expected


def test_filter_commit_items_returns_only_matches():
    commit_items = [
        {"commit": "a1", "commit_title": "drm fix", "has_conflict": True},
        {"commit": "b2", "commit_title": "net cleanup", "has_conflict": False},
        {"commit": "c3", "commit_title": "drm refactor", "has_conflict": False},
    ]

    filtered, error = backport_batch._filter_commit_items(commit_items, "title:drm")

    assert error is None
    assert [item["commit"] for item in filtered] == ["a1", "c3"]


def test_filter_commit_items_stops_on_query_error():
    filtered, error = backport_batch._filter_commit_items(
        [{"commit": "a1"}], "merged=maybe"
    )

    assert filtered is None
    assert "merged_in_target" in error


@pytest.mark.parametrize(
    ("text", "max_index", "expected", "error"),
    [
        ("0", 3, [0], None),
        ("0,2", 3, [0, 2], None),
        ("0-2", 4, [0, 1, 2], None),
        ("2-0", 4, [0, 1, 2], None),
        ("0, 2-3", 5, [0, 2, 3], None),
        ("", 5, [], "请输入索引或区间"),
        ("a", 5, [], "索引格式无效: a"),
        ("x-y", 5, [], "区间格式无效: x-y"),
        ("9", 5, [], "索引超出范围: 9"),
        ("4-9", 5, [], "索引超出范围: 4-9"),
    ],
)
def test_parse_index_ranges(text, max_index, expected, error):
    indexes, parse_error = backport_batch._parse_index_ranges(text, max_index)

    assert indexes == expected
    assert parse_error == error


def test_parse_index_ranges_handles_empty_dataset():
    indexes, error = backport_batch._parse_index_ranges("0", 0)

    assert indexes == []
    assert error == "当前没有可操作的提交"


def test_build_filtered_report_path_uses_incremented_name_when_file_exists(tmp_path):
    config_path = tmp_path / "batch.report.yml"
    first_candidate = tmp_path / "batch.filtered.report.yml"
    first_candidate.write_text("exists", encoding="utf-8")

    path = backport_batch._build_filtered_report_path(str(config_path))

    assert path.endswith("batch.filtered.1.report.yml")


def test_build_filtered_report_path_supports_raw_config_name(tmp_path):
    path = backport_batch._build_filtered_report_path(str(tmp_path / "batch.yml"))

    assert path.endswith("batch.yml.filtered.report.yml")


def test_save_filtered_report_config_writes_selected_commits(tmp_path):
    config_path = tmp_path / "batch.report.yml"
    config = {"project_dir": "/src/project", "target_path": "/src/target"}
    commit_items = [{"commit": "abc123", "status": "pending"}]

    output_path = backport_batch._save_filtered_report_config(
        str(config_path), config, commit_items
    )

    saved = yaml.safe_load(Path(output_path).read_text(encoding="utf-8"))
    assert saved["project_dir"] == "/src/project"
    assert saved["commits"] == commit_items


def test_interactive_items_changed_uses_deep_equality():
    original = [{"commit": "a"}]
    same = [{"commit": "a"}]
    changed = [{"commit": "b"}]

    assert backport_batch._interactive_items_changed(original, same) is False
    assert backport_batch._interactive_items_changed(original, changed) is True


def test_extract_commit_item_supports_multiple_input_shapes():
    assert backport_batch._extract_commit_item("abc123") == ("abc123", None, {})
    assert backport_batch._extract_commit_item(("abc123", "Fix title")) == (
        "abc123",
        "Fix title",
        {},
    )
    assert backport_batch._extract_commit_item(
        {"sha": "def456", "subject": "Fix subject", "x": 1}
    ) == ("def456", "Fix subject", {"sha": "def456", "subject": "Fix subject", "x": 1})


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("abcdef1", True),
        ("ABCDEF123456", True),
        ("123456", False),
        ("g123456", False),
        ("", False),
        (None, False),
    ],
)
def test_looks_like_commit_sha(value, expected):
    assert backport_batch._looks_like_commit_sha(value) is expected


def test_is_pending_backport_item_checks_status_case_insensitively():
    assert backport_batch._is_pending_backport_item({"status": "pending"}) is True
    assert backport_batch._is_pending_backport_item({"status": "PENDING"}) is True
    assert backport_batch._is_pending_backport_item({"status": "success"}) is False
    assert backport_batch._is_pending_backport_item("pending") is False


def test_copy_existing_report_item_deep_copies_dicts():
    item = {"commit": "abc", "nested": {"status": "pending"}}

    copied = backport_batch._copy_existing_report_item(item)
    copied["nested"]["status"] = "success"

    assert item["nested"]["status"] == "pending"


def test_append_sort_error_report_item_uses_commit_and_target_branch():
    report_items = []
    item = {
        "commit": "abc123",
        "commit_title": "Fix title",
        "target_branch": "OLK-6.6",
    }

    backport_batch._append_sort_error_report_item(report_items, item, "bad commit order")

    assert report_items == [
        {
            "commit": None,
            "input_commit": "abc123",
            "commit_title": "Fix title",
            "committed_datetime": None,
            "target_branch": "OLK-6.6",
            "status": "failed",
            "has_conflict": None,
            "conflict_check_method": None,
            "conflict_check_error": "bad commit order",
            "original_patch_path": None,
            "backported_patch_path": None,
            "patch_path": None,
            "error": "bad commit order",
        }
    ]


def test_resolve_target_branch_prefers_item_then_base_then_default():
    assert (
        backport_batch._resolve_target_branch(
            {"target_branch": "item-branch"},
            {"target_branch": "base-branch"},
            "default-branch",
        )
        == "item-branch"
    )
    assert (
        backport_batch._resolve_target_branch(
            {"target_release": "item-release"},
            {"target_branch": "base-branch"},
            "default-branch",
        )
        == "item-release"
    )
    assert (
        backport_batch._resolve_target_branch(
            {},
            {"target_release": "base-release"},
            "default-branch",
        )
        == "base-release"
    )
    assert (
        backport_batch._resolve_target_branch({}, {}, "default-branch")
        == "default-branch"
    )


def test_append_remaining_pending_items_preserves_report_fields_in_report_mode():
    report_items = []
    remaining_items = [
        {
            "commit": "abc123",
            "input_commit": "abc123",
            "commit_title": "Fix title",
            "git_describe": "v1.0",
            "committed_datetime": "2025-01-01T00:00:00",
            "status": "failed",
            "merged_in_target": True,
            "merged_check_error": "stale",
            "has_conflict": False,
            "conflict_check_method": "git-apply",
            "conflict_check_error": "old error",
            "original_patch_path": "/tmp/original.patch",
            "backport_engine": "mystique",
        }
    ]

    backport_batch._append_remaining_pending_items(
        report_items=report_items,
        remaining_items=remaining_items,
        is_report_config=True,
        base_config={"target_branch": "base-branch"},
        default_target_branch="default-branch",
    )

    assert report_items == [
        {
            "commit": "abc123",
            "input_commit": "abc123",
            "commit_title": "Fix title",
            "committed_datetime": "2025-01-01T00:00:00",
            "git_describe": "v1.0",
            "target_branch": "base-branch",
            "status": "failed",
            "merged_in_target": True,
            "merged_check_error": "stale",
            "is_merge_commit": None,
            "has_conflict": False,
            "conflict_check_method": "git-apply",
            "conflict_check_error": "old error",
            "original_patch_path": "/tmp/original.patch",
            "backported_patch_path": None,
            "patch_path": "/tmp/original.patch",
            "error": None,
            "backport_engine": "mystique",
            "target_config_layout": "none",
            "target_config_layout_opts": {},
        }
    ]


def test_append_remaining_pending_items_uses_item_config_for_raw_mode():
    report_items = []
    remaining_items = [
        {
            "commit": "def456",
            "input_commit": "def456",
            "commit_title": "Fix two",
            "git_describe": "v2.0",
            "committed_datetime": "2025-02-01T00:00:00",
            "item_config": {
                "target_release": "raw-branch",
                "patch_path": "/tmp/raw.patch",
                "merged_in_target": None,
                "has_conflict": True,
            },
        }
    ]

    backport_batch._append_remaining_pending_items(
        report_items=report_items,
        remaining_items=remaining_items,
        is_report_config=False,
        base_config={"target_branch": "base-branch"},
        default_target_branch="default-branch",
    )

    assert report_items[0]["target_branch"] == "raw-branch"
    assert report_items[0]["patch_path"] == "/tmp/raw.patch"
    assert report_items[0]["status"] == "pending"
    assert report_items[0]["has_conflict"] is True


def test_prepare_backport_batch_context_requires_project_and_target_paths():
    args = Namespace(backport_config="batch.yml", interactive=False)

    with mock.patch.object(
        backport_batch,
        "_load_backport_batch_config",
        return_value=({"commits": [{"commit": "abc"}]}, [{"commit": "abc"}]),
    ), mock.patch.object(
        backport_batch, "_is_report_config", return_value=False
    ), mock.patch.object(
        backport_batch, "_resolve_sorted_backport_items", return_value=([], [])
    ):
        with pytest.raises(ValueError, match="project_dir"):
            backport_batch._prepare_backport_batch_context(args)


def test_prepare_backport_batch_context_builds_context_with_sorted_items():
    args = Namespace(backport_config="batch.report.yml", interactive=False)
    config = {
        "project_dir": "/src/project",
        "target_path": "/src/target",
        "target_branch": "OLK-6.6",
        "commits": [{"commit": "abc123"}],
    }
    sorted_items = [{"commit": "abc123", "status": "pending"}]
    sort_errors = [("tag", {"commit": "bad"}, "error")]

    with mock.patch.object(
        backport_batch,
        "_load_backport_batch_config",
        return_value=(config, config["commits"]),
    ), mock.patch.object(
        backport_batch, "_is_report_config", return_value=True
    ), mock.patch.object(
        backport_batch,
        "_resolve_sorted_backport_items",
        return_value=(sorted_items, sort_errors),
    ):
        context = backport_batch._prepare_backport_batch_context(args)

    assert context.base_project_dir == "/src/project"
    assert context.base_target_path == "/src/target"
    assert context.is_report_config is True
    assert context.sorted_items == sorted_items
    assert context.sort_errors == sort_errors
    assert context.report_output_path == "batch.report.yml"


def test_prepare_backport_batch_context_returns_none_when_interactive_quit():
    args = Namespace(backport_config="batch.report.yml", interactive=True)
    config = {
        "project_dir": "/src/project",
        "target_path": "/src/target",
        "commits": [{"commit": "abc123"}],
    }

    with mock.patch.object(
        backport_batch,
        "_load_backport_batch_config",
        return_value=(config, config["commits"]),
    ), mock.patch.object(
        backport_batch, "_is_report_config", return_value=True
    ), mock.patch.object(
        backport_batch, "_interactive_adjust_merged_in_target", return_value="quit"
    ):
        context = backport_batch._prepare_backport_batch_context(args)

    assert context is None


def test_prepare_backport_batch_context_uses_filtered_report_path_from_interactive_save():
    args = Namespace(backport_config="batch.report.yml", interactive=True)
    config = {
        "project_dir": "/src/project",
        "target_path": "/src/target",
        "commits": [{"commit": "abc123"}],
        "_interactive_output_report_path": "batch.filtered.report.yml",
    }

    with mock.patch.object(
        backport_batch,
        "_load_backport_batch_config",
        return_value=(config, config["commits"]),
    ), mock.patch.object(
        backport_batch, "_is_report_config", return_value=True
    ), mock.patch.object(
        backport_batch, "_interactive_adjust_merged_in_target", return_value="continue"
    ), mock.patch.object(
        backport_batch, "_resolve_sorted_backport_items", return_value=([], [])
    ):
        context = backport_batch._prepare_backport_batch_context(args)

    assert context.report_output_path == "batch.filtered.report.yml"


def test_write_backport_batch_report_uses_report_suffix_for_raw_config(tmp_path):
    config_path = tmp_path / "batch.yml"
    report = {"commits": [{"commit": "abc123"}]}

    backport_batch._write_backport_batch_report(str(config_path), False, report)

    saved_path = tmp_path / "batch.yml.report.yml"
    assert saved_path.exists()
    assert yaml.safe_load(saved_path.read_text(encoding="utf-8")) == report


def test_write_backport_batch_report_overwrites_report_config_in_place(tmp_path):
    config_path = tmp_path / "batch.report.yml"
    report = {"commits": [{"commit": "abc123", "status": "pending"}]}

    backport_batch._write_backport_batch_report(str(config_path), True, report)

    assert yaml.safe_load(config_path.read_text(encoding="utf-8")) == report


class TestResolveTargetConfigLayout:
    def test_priority_per_commit_over_cli(self):
        args = SimpleNamespace(target_config_layout="anolis")
        item = {"target_config_layout": "none"}
        base = {}
        result = backport_batch._resolve_target_config_layout(args, item, base)
        assert result == "none"

    def test_priority_cli_over_yaml(self):
        args = SimpleNamespace(target_config_layout="anolis")
        item = {}
        base = {"target_config_layout": "none"}
        result = backport_batch._resolve_target_config_layout(args, item, base)
        assert result == "anolis"

    def test_priority_yaml_over_default(self):
        args = SimpleNamespace(target_config_layout="")
        item = {}
        base = {"target_config_layout": "anolis"}
        result = backport_batch._resolve_target_config_layout(args, item, base)
        assert result == "anolis"

    def test_default_is_none(self):
        args = SimpleNamespace(target_config_layout="")
        item = {}
        base = {}
        result = backport_batch._resolve_target_config_layout(args, item, base)
        assert result == "none"

    def test_rejects_unknown_value(self):
        args = SimpleNamespace(target_config_layout="unknown")
        with pytest.raises(ConfigError, match="未知的 target_config_layout"):
            backport_batch._resolve_target_config_layout(args, {}, {})

    def test_case_insensitive_normalization(self):
        args = SimpleNamespace(target_config_layout="ANOLIS")
        result = backport_batch._resolve_target_config_layout(args, {}, {})
        assert result == "anolis"


class TestResolveTargetConfigLayoutOpts:
    def test_parses_cli_json(self):
        args = SimpleNamespace(
            target_config_layout_opts='{"default_level":"L2-OPTIONAL"}'
        )
        result = backport_batch._resolve_target_config_layout_opts(args, {}, {})
        assert result == {"default_level": "L2-OPTIONAL"}

    def test_merges_per_commit_over_base(self):
        args = SimpleNamespace(target_config_layout_opts="")
        item = {"target_config_layout_opts": {"default_level": "L0-MANDATORY"}}
        base = {"target_config_layout_opts": {"default_level": "L1-RECOMMEND"}}
        result = backport_batch._resolve_target_config_layout_opts(args, item, base)
        assert result == {"default_level": "L0-MANDATORY"}

    def test_empty_when_no_config(self):
        args = SimpleNamespace(target_config_layout_opts="")
        result = backport_batch._resolve_target_config_layout_opts(args, {}, {})
        assert result == {}

    def test_invalid_json_raises(self):
        args = SimpleNamespace(target_config_layout_opts="{bad json}")
        with pytest.raises(ConfigError, match="JSON"):
            backport_batch._resolve_target_config_layout_opts(args, {}, {})


class TestTargetConfigLayoutPropagation:
    def test_layout_in_runtime_config(self):
        """验证 target_config_layout 出现在运行时配置字典中。"""
        args = SimpleNamespace(
            target_config_layout="anolis",
            target_config_layout_opts='{"default_level":"L2-OPTIONAL"}',
            api_key="test-key",
            patch_dataset_dir="/tmp/test",
            commit_message_source="",
            commit_message_template="",
            backport_engine="",
            signer_name="",
            signer_email="",
            linux_repo_path="",
            llm_provider="",
            error_message="",
            sanitizer="",
        )
        item_config = {"commit_id": "abc123"}
        base_config = {
            "project": "linux",
            "project_dir": "/tmp/test_project",
            "target_path": "/tmp/test_target",
            "project_url": "https://example.com",
        }
        runtime = backport_batch._build_backport_runtime_config(
            item_config=item_config,
            base_config=base_config,
            base_project_dir="/tmp/test_project",
            base_target_path="/tmp/test_target",
            fixed_commit="abc123",
            target_branch="devel-6.6",
            tag="test-tag",
            commit_id="abc123",
            args=args,
        )
        assert runtime["target_config_layout"] == "anolis"
        assert runtime["target_config_layout_opts"] == {"default_level": "L2-OPTIONAL"}


class TestPatchContainsDefconfig:
    def test_modify_defconfig(self, tmp_path):
        """修改 defconfig 的 patch 应返回 True。"""
        patch = tmp_path / "modify.patch"
        patch.write_text(
            "\n".join([
                "diff --git a/arch/arm64/configs/defconfig b/arch/arm64/configs/defconfig",
                "index abc..def 100644",
                "--- a/arch/arm64/configs/defconfig",
                "+++ b/arch/arm64/configs/defconfig",
                "@@ -1 +1,2 @@",
                " CONFIG_BASE=y",
                "+CONFIG_FOO=y",
            ]),
            encoding="utf-8",
        )
        assert backport_batch._patch_contains_defconfig(str(patch)) is True

    def test_delete_defconfig(self, tmp_path):
        """删除 defconfig 的 patch 应返回 True。"""
        patch = tmp_path / "delete.patch"
        patch.write_text(
            "\n".join([
                "diff --git a/arch/x86/configs/i386_defconfig b/arch/x86/configs/i386_defconfig",
                "deleted file mode 100644",
                "--- a/arch/x86/configs/i386_defconfig",
                "+++ /dev/null",
                "@@ -1,1 +0,0 @@",
                "-CONFIG_BASE=y",
            ]),
            encoding="utf-8",
        )
        assert backport_batch._patch_contains_defconfig(str(patch)) is True

    def test_no_defconfig(self, tmp_path):
        """不含 defconfig 的 patch 应返回 False。"""
        patch = tmp_path / "code.patch"
        patch.write_text(
            "\n".join([
                "diff --git a/kernel/sched/core.c b/kernel/sched/core.c",
                "index 111..222 100644",
                "--- a/kernel/sched/core.c",
                "+++ b/kernel/sched/core.c",
                "@@ -1 +1,2 @@",
                " old",
                "+new",
            ]),
            encoding="utf-8",
        )
        assert backport_batch._patch_contains_defconfig(str(patch)) is False

    def test_missing_file(self):
        """不存在的文件应返回 False。"""
        assert backport_batch._patch_contains_defconfig("/nonexistent/patch.patch") is False

    def test_empty_path(self):
        """空路径应返回 False。"""
        assert backport_batch._patch_contains_defconfig("") is False
