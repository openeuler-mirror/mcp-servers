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
from cvekit.utils import commit_message_template


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
