import sys
import runpy
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest


# 确保可以导入 `cvekit` 包（src 作为项目根目录）
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _bin_script_path() -> str:
    """返回 bin/cvekit 脚本的绝对路径。"""
    return str(PROJECT_ROOT / "bin" / "cvekit")


def test_bin_cvekit_calls_cli_main():
    """
    验证入口脚本 src/bin/cvekit 在作为主程序运行时会调用 cvekit.cli.main。
    """
    script_path = _bin_script_path()

    with mock.patch("cvekit.cli.main") as mock_main:
        # 使用 runpy 以 __main__ 方式执行脚本，模拟命令行调用
        runpy.run_path(script_path, run_name="__main__")

        mock_main.assert_called_once()


def test_main_setup_env_calls_setup_repository_and_format_output(monkeypatch):
    """
    验证 cli.main 在 setup-env 模式下会调用 setup_repository 和 format_output。
    使用最小参数集：只需要 --action setup-env 和 --fork-repo-url。
    """
    from cvekit import cli

    # 构造假的返回值；本用例只验证 main 是否把结果传给 format_output，
    # 不关心 handle_action / setup_repository 的内部实现细节。
    fake_result = {"status": "success", "repo_path": "/tmp/fake-repo"}

    monkeypatch.setenv("CLONE_DIR", "/tmp/clone-dir")

    with mock.patch.object(cli, "format_output") as mock_format_output, \
            mock.patch.object(cli, "handle_action", return_value=fake_result) as mock_handle_action:

        argv_backup = sys.argv[:]
        try:
            sys.argv = [
                "cvekit",
                "--action",
                "setup-env",
                "--fork-repo-url",
                "https://example.com/fork.git",
            ]

            # 不应抛出异常，也不应调用 sys.exit
            cli.main()
        finally:
            sys.argv = argv_backup

    # main 应该调用 handle_action 并把返回值交给 format_output
    mock_handle_action.assert_called_once()
    mock_format_output.assert_called_once()
    called_result, called_args = mock_format_output.call_args[0]
    assert called_result == fake_result
    # action 应该是 setup-env
    assert called_args.action == "setup-env"


def test_main_missing_gitee_token_raises_system_exit(monkeypatch):
    """
    当 action 不是 setup-env/backport 且没有提供 gitee-token 时，应通过 parser.error 触发 SystemExit。
    """
    from cvekit import cli

    # 确保环境变量中也没有 token
    monkeypatch.delenv("GITEE_TOKEN", raising=False)

    argv_backup = sys.argv[:]
    try:
        # analyze-branches 需要 gitee-token、fork-repo-url 和 issue/cve 信息
        sys.argv = [
            "cvekit",
            "--action",
            "analyze-branches",
            "--fork-repo-url",
            "https://example.com/fork.git",
            "--issue-url",
            "https://gitee.com/org/repo/issues/1",
        ]

        with pytest.raises(SystemExit) as exc_info:
            cli.main()

        # argparse 在 error 时通常退出码为 2
        assert exc_info.value.code != 0
    finally:
        sys.argv = argv_backup


def _make_args(**overrides):
    """
    构造一个与 cli.handle_action 兼容的 argparse.Namespace。
    只在测试中使用，避免真正访问网络/仓库。
    """
    from argparse import Namespace

    base = dict(
        action="parse-issue",
        cve_id=None,
        issue_url="https://gitee.com/org/repo/issues/1",
        no_cache=False,
        fork_repo_url="https://example.com/fork.git",
        repo_url="https://gitee.com/org/repo",
        gitee_token="fake-token",
        clone_dir="/tmp/clone-dir",
        branches="OLK-5.10,OLK-6.6,master",
        branch=None,
        signer_name=None,
        signer_email=None,
        openai_key="",
        llm_provider="openai",
        patch_dataset_dir="/tmp/patch-dataset",
        patch_path=None,
        json=False,
        table=False,
        debug=False,
        error_message=None,
        sanitizer=None,
    )
    base.update(overrides)
    return Namespace(**base)


def test_handle_action_parse_issue_uses_handle_parse_issue(monkeypatch):
    """
    验证 handle_action 在 parse-issue 模式下会调用 handle_parse_issue 并返回其结果。
    同时通过 fake fetch_cve_id 避免真实网络访问。
    """
    from cvekit import cli

    args = _make_args(action="parse-issue")

    fake_result = {"action": "parse-issue", "ok": True}

    with mock.patch.object(cli, "fetch_cve_id", return_value="CVE-TEST-1") as mock_fetch, \
            mock.patch.object(cli, "handle_parse_issue", return_value=fake_result) as mock_handle:

        result = cli.handle_action(args)

    mock_fetch.assert_called_once()
    mock_handle.assert_called_once_with(args)
    assert result == fake_result


def test_handle_action_get_commits_calls_handle_get_commits(monkeypatch):
    """
    验证 handle_action 在 get-commits 模式下会调用 handle_get_commits。
    """
    from cvekit import cli

    args = _make_args(action="get-commits", cve_id=None)

    fake_result = {
        "action": "get-commits",
        "cve_id": "CVE-TEST-2",
        "introduced": "abcd",
        "fixed": "efgh",
    }

    with mock.patch.object(cli, "fetch_cve_id", return_value="CVE-TEST-2") as mock_fetch, \
            mock.patch.object(cli, "handle_get_commits", return_value=fake_result) as mock_handle:

        result = cli.handle_action(args)

    mock_fetch.assert_called_once()
    mock_handle.assert_called_once_with("CVE-TEST-2", True)
    assert result == fake_result


def test_handle_action_analyze_branches_calls_handle_analyze_branches(monkeypatch):
    """
    验证 handle_action 在 analyze-branches 模式下会调用 handle_analyze_branches。
    """
    from cvekit import cli

    args = _make_args(
        action="analyze-branches",
        cve_id=None,
        issue_url="https://gitee.com/org/repo/issues/123",
    )

    fake_result = [{"branch": "OLK-6.6"}]

    with mock.patch.object(cli, "fetch_cve_id", return_value="CVE-TEST-4") as mock_fetch, \
            mock.patch.object(cli, "handle_analyze_branches", return_value=fake_result) as mock_handle:

        result = cli.handle_action(args)

    mock_fetch.assert_called_once()
    mock_handle.assert_called_once_with(args)
    assert result == fake_result


def test_handle_action_apply_patch_calls_handle_apply_patch():
    """
    验证 handle_action 在 apply-patch 模式下会把 cve_id 和 args 传给 handle_apply_patch。
    """
    from cvekit import cli

    args = _make_args(
        action="apply-patch",
        cve_id="CVE-TEST-5",
        issue_url="https://gitee.com/org/repo/issues/5",
        patch_path="/tmp/fix.patch",
        branch="OLK-5.10",
    )

    fake_result = {"status": "ok"}

    with mock.patch.object(cli, "handle_apply_patch", return_value=fake_result) as mock_handle:
        result = cli.handle_action(args)

    mock_handle.assert_called_once()
    called_cve_id, called_args = mock_handle.call_args[0]
    assert called_cve_id == "CVE-TEST-5"
    assert called_args is args
    assert result == fake_result


def test_handle_action_create_pr_calls_handle_create_pr():
    """
    验证 handle_action 在 create-pr 模式下会把 cve_id 和 args 传给 handle_create_pr。
    """
    from cvekit import cli

    args = _make_args(
        action="create-pr",
        cve_id="CVE-TEST-6",
        issue_url="https://gitee.com/org/repo/issues/6",
        branch="OLK-6.6",
    )

    fake_result = {"status": "pr-created"}

    with mock.patch.object(cli, "handle_create_pr", return_value=fake_result) as mock_handle:
        result = cli.handle_action(args)

    mock_handle.assert_called_once()
    called_cve_id, called_args = mock_handle.call_args[0]
    assert called_cve_id == "CVE-TEST-6"
    assert called_args is args
    assert result == fake_result


def test_handle_action_backport_builds_config_and_calls_run_backport(monkeypatch):
    """
    验证 backport 流程中：
    - 会根据 commits 和参数构造 config_dict；
    - 调用 run_backport_from_config；
    - 返回结构中包含 i18n 后的关键信息。
    """
    from cvekit import cli

    args = _make_args(
        action="backport",
        cve_id="CVE-TEST-3",
        branch="OLK-6.6",
        clone_dir="/tmp/clone-dir",
        patch_dataset_dir="/tmp/custom-dataset",
        debug=True,
    )

    # fake commits: (introduced_commit, fixed_commit)
    fake_commits = ("commit-intro", "commit-fixed")
    fake_backport_result = {
        "status": "success",
        "backported_patch_path": "/tmp/patches/CVE-TEST-3.patch",
        "time_cost": 1.23,
    }

    with mock.patch.object(cli, "get_vulnerability_commits", return_value=fake_commits) as mock_commits, \
            mock.patch.object(cli, "run_backport_from_config", return_value=fake_backport_result) as mock_run, \
            mock.patch.object(cli, "i18n", side_effect=lambda x: x):

        result = cli.handle_action(args)

    mock_commits.assert_called_once_with("CVE-TEST-3", True)

    # run_backport_from_config 应该收到构造好的 config_dict
    mock_run.assert_called_once()
    called_config, = mock_run.call_args[0]
    called_kwargs = mock_run.call_args[1]
    assert called_kwargs.get("debug_mode") is True

    assert called_config["project"] == "linux"
    assert called_config["target_release"] == "OLK-6.6"
    assert called_config["new_patch"] == "commit-fixed"
    assert called_config["tag"] == "CVE-TEST-3"
    assert called_config["patch_dataset_dir"] == "/tmp/custom-dataset/CVE-TEST-3"

    # 返回结果结构应与 cli 中构造逻辑一致
    assert result["补丁ID"] == "CVE-TEST-3"
    assert result["目标分支"] == "OLK-6.6"
    assert result["适配状态"] == "成功"
    assert result["details"]["fixed_commit"] == "commit-fixed"
    assert result["details"]["status"] == "success"


def test_handle_mystique_returns_original_patch_file_path():
    from cvekit import cli

    args = _make_args(
        action="mystique",
        branch="OLK-6.6",
        commit_id="fixed-commit",
        project_dir="/tmp/linux",
        target_path="/tmp/kernel",
        output="/tmp/output",
        api_key="test-key",
        llm_base_url=None,
        llm_model_name=None,
        format_mode="changed",
    )
    fake_config = SimpleNamespace(
        configure_llm=mock.Mock(),
        configure_format_normalization=mock.Mock(),
    )
    fake_main = SimpleNamespace(
        main_from_repo=mock.Mock(return_value=[{
            "status": "ported",
            "original_patch_path": "/tmp/output/original_fixed-commit.patch",
            "backported_patch_path": "/tmp/output/backported.patch",
            "logfile": "/tmp/mystique.log",
        }])
    )

    with mock.patch.dict(sys.modules, {"config": fake_config, "main": fake_main}), \
            mock.patch.object(cli, "i18n", side_effect=lambda value: value):
        result = cli.handle_mystique("CVE-TEST-MYSTIQUE", args)

    assert result["details"]["fixed_commit"] == "fixed-commit"
    assert (
        result["details"]["original_patch_path"]
        == "/tmp/output/original_fixed-commit.patch"
    )


def test_handle_action_invalid_action_raises_runtime_error():
    """
    当传入未知 action 时，handle_action 应抛出 RuntimeError。
    为避免真实网络访问，这里直接提供 cve_id 且不提供 issue_url。
    """
    from cvekit import cli

    # 这里同时提供 cve_id 和 issue_url，避免在 handle_action 内部触发
    # get_issue_url_from_cve_id / fetch_cve_id 等真实网络调用。
    args = _make_args(
        action="invalid-action",
        cve_id="CVE-TEST-INVALID",
    )

    with pytest.raises(RuntimeError):
        cli.handle_action(args)


def test_format_output_json(capsys, monkeypatch):
    """
    当指定 --json 参数时，应以 JSON 形式输出。
    """
    from argparse import Namespace
    from cvekit import cli

    result = {"key": "value", "num": 1}
    args = Namespace(json=True, table=False)

    cli.format_output(result, args)

    captured = capsys.readouterr()
    # 简单检查 JSON 结构关键字符
    assert "key" in captured.out
    assert '"num": 1' in captured.out


def test_format_output_table_uses_display_function(monkeypatch):
    """
    当 result 为列表且指定 --table 时，应调用 _display_branch_table。
    """
    from argparse import Namespace
    from cvekit import cli

    args = Namespace(json=False, table=True)
    branches = [{"分支": "OLK-6.6"}]

    called = {"table": False}

    def fake_display(data):
        called["table"] = True
        assert data is branches

    monkeypatch.setattr(cli, "_display_branch_table", fake_display)

    cli.format_output(branches, args)

    assert called["table"] is True


def test_format_output_default_prints_human_readable(capsys, monkeypatch):
    """
    未指定 json/table 时，应打印“分析结果:”和结果内容。
    """
    from argparse import Namespace
    from cvekit import cli

    args = Namespace(json=False, table=False)

    # i18n 返回原文，便于断言
    monkeypatch.setattr(cli, "i18n", lambda x: x)

    result = {"status": "success", "action": "test"}
    cli.format_output(result, args)

    captured = capsys.readouterr()
    assert "分析结果:" in captured.out
    assert "'status': 'success'" in captured.out


def test_main_backport_calls_handle_action_and_format_output(monkeypatch):
    """
    验证 cli.main 在 backport 模式下会调用 handle_action 和 format_output，
    且传入的 args.action 为 backport。
    """
    from cvekit import cli

    fake_result = {"status": "success", "action": "backport"}

    argv_backup = sys.argv[:]
    try:
        sys.argv = [
            "cvekit",
            "--action",
            "backport",
            "--cve-id",
            "CVE-TEST-MAIN",
            "--gitee-token",
            "fake-token",
        ]

        with mock.patch.object(cli, "handle_action", return_value=fake_result) as mock_handle, \
                mock.patch.object(cli, "format_output") as mock_format:

            cli.main()
    finally:
        sys.argv = argv_backup

    mock_handle.assert_called_once()
    mock_format.assert_called_once()
    called_result, called_args = mock_format.call_args[0]
    assert called_result == fake_result
    assert called_args.action == "backport"
