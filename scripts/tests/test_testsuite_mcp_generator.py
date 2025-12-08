from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest


FAKE_LLM_OUTPUT = """
<<<DESIGN_SUMMARY_START>>>
这里是设计摘要
<<<DESIGN_SUMMARY_END>>>

<<<SERVER_PY_START>>>
print("hello from server")
<<<SERVER_PY_END>>>

<<<MCP_CONFIG_JSON_START>>>
{"mcpServers": {"demo_mcp": {}}}
<<<MCP_CONFIG_JSON_END>>>

<<<MCP_RPM_YAML_START>>>
name: demo_mcp
summary: demo
description: demo
version: "1.0.0"
release: "1"
license: MIT
build_dependencies:
  system: []
runtime_dependencies:
  system: []
  packages: []
files:
  required: []
install_script: ""
<<<MCP_RPM_YAML_END>>>
"""


def _load_module():
    """以自定义包名加载 scripts/testsuite_mcp_generator.py，便于解析相对导入。"""
    import importlib.util

    # 准备伪造的依赖模块，以避免真正访问网络或外部依赖
    # 1) 伪造 langchain_openai.ChatOpenAI
    lo_mod = types.ModuleType("langchain_openai")

    class DummyChatOpenAI:
        def __init__(self, *args, **kwargs) -> None:  # noqa: D401, D417
            """Fake init."""

        def invoke(self, messages):
            # 返回一个拥有 content 属性的简单对象
            return types.SimpleNamespace(content=FAKE_LLM_OUTPUT)

    lo_mod.ChatOpenAI = DummyChatOpenAI
    sys.modules["langchain_openai"] = lo_mod

    # 2) 构造一个虚假的包层级 testscripts.tools.logger & testscripts.agent.invoke_llm
    pkg = types.ModuleType("testscripts")
    pkg.__path__ = []  # type: ignore[attr-defined]
    sys.modules["testscripts"] = pkg

    agent_pkg = types.ModuleType("testscripts.agent")
    agent_pkg.__path__ = []  # type: ignore[attr-defined]
    sys.modules["testscripts.agent"] = agent_pkg

    invoke_mod = types.ModuleType("testscripts.agent.invoke_llm")

    def _get_llm_config(provider: str):
        # 返回任意 base_url 和 model 名称即可
        return "https://example.com", f"fake-model-{provider}"

    invoke_mod._get_llm_config = _get_llm_config
    sys.modules["testscripts.agent.invoke_llm"] = invoke_mod

    tools_pkg = types.ModuleType("testscripts.tools")
    tools_pkg.__path__ = []  # type: ignore[attr-defined]
    sys.modules["testscripts.tools"] = tools_pkg

    logger_mod = types.ModuleType("testscripts.tools.logger")

    class DummyLogger:
        def debug(self, *args, **kwargs) -> None:
            pass

        def info(self, *args, **kwargs) -> None:
            pass

        def error(self, *args, **kwargs) -> None:
            pass

        def exception(self, *args, **kwargs) -> None:
            pass

    def add_file_handler(logger, logfile) -> None:  # noqa: D401
        """测试中无需真正写入日志文件。"""
        return None

    logger_mod.logger = DummyLogger()
    logger_mod.add_file_handler = add_file_handler
    sys.modules["testscripts.tools.logger"] = logger_mod

    # 3) 以 testscripts.testsuite_mcp_generator 为模块名加载源码文件
    script_path = Path(__file__).resolve().parents[1] / "testsuite_mcp_generator.py"
    spec = importlib.util.spec_from_file_location(
        "testscripts.testsuite_mcp_generator",
        script_path,
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["testscripts.testsuite_mcp_generator"] = module
    spec.loader.exec_module(module)  # type: ignore[assignment]
    return module


def test_extract_comment_and_run_test_basic(tmp_path):
    mod = _load_module()

    script = tmp_path / "case.sh"
    script.write_text(
        """#!/bin/bash
# 这是测试用例
# 第二行注释

function pre_test() {
    :
}

function run_test() {
    echo "hello"
    ls /
}

""",
        encoding="utf-8",
    )

    info = mod._extract_comment_and_run_test(str(script))
    assert info["script"] == "case.sh"
    # 头部注释应被拼接为多行文本
    assert "这是测试用例" in info["description"]
    assert "第二行注释" in info["description"]
    # run_test 内容应包含核心命令
    assert 'echo "hello"' in info["run_test"]
    assert "ls /" in info["run_test"]


def test_collect_testsuite_context_and_invalid_dir(tmp_path):
    mod = _load_module()

    # 正常目录
    suite_dir = tmp_path / "suite"
    suite_dir.mkdir()
    (suite_dir / "a.sh").write_text("function run_test() { echo a; }\n", encoding="utf-8")
    (suite_dir / "b.txt").write_text("not shell", encoding="utf-8")

    result = mod._collect_testsuite_context(str(suite_dir))
    # 只有 .sh 文件被收集
    assert len(result) == 1
    assert result[0]["script"] == "a.sh"

    # 非法目录应抛出 FileNotFoundError
    with pytest.raises(FileNotFoundError):
        mod._collect_testsuite_context(str(tmp_path / "not_exist"))


def test_extract_between_markers():
    mod = _load_module()

    text = "AAA<<<X>>>\nhello\n<<<Y>>>BBB"
    assert mod._extract_between_markers(text, "<<<X>>>", "<<<Y>>>") == "hello"
    # 缺少标记时应返回空字符串
    assert mod._extract_between_markers(text, "<<<NO>>>", "<<<Y>>>") == ""


def test_run_generate_mcp_from_config_success(tmp_path, monkeypatch):
    # 重新加载模块，确保使用临时 HOME 目录
    monkeypatch.setenv("HOME", str(tmp_path / "home"))

    # 保证 _load_module 使用的 sys.modules 处于干净状态
    for name in list(sys.modules):
        if name.startswith("testscripts") or name == "langchain_openai":
            sys.modules.pop(name)

    mod = _load_module()

    # 构造简易测试套目录
    suite_dir = tmp_path / "suite"
    suite_dir.mkdir()
    (suite_dir / "demo.sh").write_text(
        """#!/bin/bash
# demo case
function run_test() {
    echo demo
}
""",
        encoding="utf-8",
    )

    server_root = tmp_path / "servers_root"

    config = {
        "test_suite_dir": str(suite_dir),
        "software_name": "demo",
        "openai_key": "dummy-key",
        "llm_provider": "openai",
        "server_root": str(server_root),
    }

    result = mod.run_generate_mcp_from_config(config, debug_mode=False)
    assert result["status"] == "success"
    assert result["server_name"] == "demo_mcp"

    files = result["files"]
    server_py = Path(files["server.py"])
    mcp_cfg = Path(files["mcp_config.json"])
    mcp_rpm = Path(files["mcp-rpm.yaml"])

    for p in (server_py, mcp_cfg, mcp_rpm):
        assert p.is_file()

    # design_summary 也应被解析出来
    assert "设计摘要" in result["design_summary"]


def test_run_generate_mcp_from_config_invalid_inputs(tmp_path, monkeypatch):
    # 清理 stub 模块
    for name in list(sys.modules):
        if name.startswith("testscripts") or name == "langchain_openai":
            sys.modules.pop(name)

    mod = _load_module()

    # 无效的 test_suite_dir
    bad = mod.run_generate_mcp_from_config(
        {
            "test_suite_dir": str(tmp_path / "not-exist"),
            "software_name": "demo",
            "openai_key": "dummy",
        }
    )
    assert bad["status"] == "failed"
    assert "无效的测试套目录" in bad["message"]

    # 缺少 software_name
    ok_dir = tmp_path / "suite"
    ok_dir.mkdir()
    bad2 = mod.run_generate_mcp_from_config(
        {
            "test_suite_dir": str(ok_dir),
            "software_name": "",
            "openai_key": "dummy",
        }
    )
    assert bad2["status"] == "failed"
    assert "software_name 不能为空" in bad2["message"]

    # 缺少 openai_key（配置和环境变量都没有）
    monkeypatch.delenv("OPENAI_KEY", raising=False)
    bad3 = mod.run_generate_mcp_from_config(
        {
            "test_suite_dir": str(ok_dir),
            "software_name": "demo",
        }
    )
    assert bad3["status"] == "failed"
    assert "openai_key 未提供" in bad3["message"]


