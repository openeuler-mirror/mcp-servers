import builtins
import io
import importlib.util
import os
from typing import Dict, List

import pytest


class NonClosingStringIO(io.StringIO):
    """一个不会在 close() 时真正关闭的 StringIO，用于配合 with open()."""

    def close(self) -> None:  # noqa: D401
        """覆盖 close，避免被 with 语句关闭，从而可以在测试后读取内容。"""
        # 不调用父类 close，保持缓冲区可读
        pass


def _load_generate_mcp_spec_module():
    """
    通过文件路径动态加载 generate-mcp-spec.py，
    并赋予一个合法的模块名，便于在测试中调用。
    """
    script_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "generate-mcp-spec.py",
    )
    spec = importlib.util.spec_from_file_location("generate_mcp_spec", script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)  # type: ignore[assignment]
    return module


@pytest.fixture(scope="module")
def generate_mcp_spec_module():
    return _load_generate_mcp_spec_module()


def test_generate_spec_file_servers_dir_not_found(monkeypatch, generate_mcp_spec_module):
    """当 servers 目录不存在时应抛出 FileNotFoundError。"""

    real_exists = os.path.exists

    def fake_exists(path: str) -> bool:
        # 对于函数内部推导出来的 servers_dir 直接返回 False，其他路径保持默认行为
        if path.endswith(os.path.join("..", "servers")) or path.endswith("servers"):
            return False
        return real_exists(path)

    monkeypatch.setattr(os.path, "exists", fake_exists)

    with pytest.raises(FileNotFoundError):
        generate_mcp_spec_module.generate_spec_file()


def test_generate_spec_file_no_yaml_files(monkeypatch, generate_mcp_spec_module):
    """当 servers 子目录下没有 mcp-rpm.yaml 时应抛出 FileNotFoundError。"""

    # 让 servers_dir 存在
    monkeypatch.setattr(os.path, "exists", lambda path: True)
    # 但 glob 不返回任何 yaml
    monkeypatch.setattr(
        generate_mcp_spec_module.glob,
        "glob",
        lambda pattern: [],
    )

    with pytest.raises(FileNotFoundError):
        generate_mcp_spec_module.generate_spec_file()


def test_generate_spec_file_success(monkeypatch, generate_mcp_spec_module):
    """
    正常路径：
    - 伪造两个 mcp-rpm.yaml 文件内容
    - 捕获写出的 spec 文本，检查关键段落是否包含。
    """

    yaml_contents: Dict[str, str] = {
        "/fake/server1/mcp-rpm.yaml": """
name: server1
summary: Server1 summary
description: Server1 description
dependencies:
  system:
    - sys_dep1
  packages:
    - pkg_dep1
""",
        "/fake/server2/mcp-rpm.yaml": """
name: server2
summary: Server2 summary
description: Server2 description
dependencies:
  system: []
  packages:
    - pkg_dep2
""",
    }

    # 伪造 servers_dir 存在
    monkeypatch.setattr(os.path, "exists", lambda path: True)

    # 只返回我们伪造的 yaml 文件列表
    monkeypatch.setattr(
        generate_mcp_spec_module.glob,
        "glob",
        lambda pattern: list(yaml_contents.keys()),
    )

    written_spec = NonClosingStringIO()

    real_open = builtins.open

    def fake_open(file: str, mode: str = "r", *args, **kwargs):
        # 读取 mcp-rpm.yaml 时返回预置内容
        if file in yaml_contents and "r" in mode:
            return io.StringIO(yaml_contents[file])
        # 写入 mcp-servers.spec 时，用 StringIO 捕获内容
        if file == "mcp-servers.spec" and "w" in mode:
            # 重置缓冲区
            written_spec.seek(0)
            written_spec.truncate(0)
            return written_spec
        return real_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", fake_open)

    generate_mcp_spec_module.generate_spec_file()

    spec_text = written_spec.getvalue()
    assert spec_text, "应当写出 spec 文件内容"

    # 顶部元数据
    assert "Name:           mcp-servers" in spec_text
    # 包定义中应该包含我们两个 server 的 name/summary 等信息
    assert "%package server1" in spec_text
    assert "%package server2" in spec_text
    assert "Summary:        Server1 summary" in spec_text
    assert "Summary:        Server2 summary" in spec_text

    # 依赖信息：sys_dep1 与 pkg_dep1/pkg_dep2 应该被展开为 Requires 行
    assert "Requires:       sys_dep1" in spec_text
    assert "Requires:       pkg_dep1" in spec_text
    assert "Requires:       pkg_dep2" in spec_text

    # %files 段中应包含各 server 目录
    assert "/opt/mcp-servers/servers/server1/*" in spec_text
    assert "/opt/mcp-servers/servers/server2/*" in spec_text

from pathlib import Path

import yaml


def _load_module():
    """Load scripts/generate-mcp-spec.py as a module."""
    import importlib.util

    script_path = Path(__file__).resolve().parents[1] / "generate-mcp-spec.py"
    spec = importlib.util.spec_from_file_location("generate_mcp_spec", script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)  # type: ignore[assignment]
    return module


def test_generate_spec_file_creates_spec_with_single_server(tmp_path, monkeypatch):
    mod = _load_module()

    # 构造虚拟的目录结构：
    #   tmp_root/
    #     servers/
    #       demo_server/
    #         mcp-rpm.yaml
    tmp_root = tmp_path / "repo_root"
    servers_dir = tmp_root / "servers"
    server_dir = servers_dir / "demo_server"
    server_dir.mkdir(parents=True)

    yaml_path = server_dir / "mcp-rpm.yaml"
    yaml_content = {
        "name": "demo-server",
        "summary": "Demo MCP server",
        "description": "Demo description",
        "dependencies": {
            "system": ["python3-demo"],
            "packages": ["demo-pkg"],
        },
    }
    yaml_path.write_text(yaml.safe_dump(yaml_content, sort_keys=False), encoding="utf-8")

    # 让被测模块认为自身位于 tmp_root/scripts/generate-mcp-spec.py
    fake_script_dir = tmp_root / "scripts"
    fake_script_dir.mkdir()
    fake_file = fake_script_dir / "generate-mcp-spec.py"
    fake_file.write_text("# dummy", encoding="utf-8")
    mod.__file__ = str(fake_file)

    # 在临时目录中运行，避免在真实仓库里生成 mcp-servers.spec
    monkeypatch.chdir(tmp_root)

    mod.generate_spec_file()

    spec_path = tmp_root / "mcp-servers.spec"
    assert spec_path.is_file()

    content = spec_path.read_text(encoding="utf-8")
    # 基本字段检查
    assert "Name:           mcp-servers" in content
    assert "demo-server" in content
    # 依赖是否被渲染到 Requires 字段
    assert "Requires:       python3-demo" in content
    assert "Requires:       demo-pkg" in content
    # %files 中应包含该 server 目录
    assert "/opt/mcp-servers/servers/demo_server/*" in content


def test_generate_spec_file_raises_when_no_servers_dir(tmp_path, monkeypatch):
    mod = _load_module()

    # 构造一个没有 servers 目录的 fake script 位置
    tmp_root = tmp_path / "no_servers_root"
    script_dir = tmp_root / "scripts"
    script_dir.mkdir(parents=True)
    fake_file = script_dir / "generate-mcp-spec.py"
    fake_file.write_text("# dummy", encoding="utf-8")
    mod.__file__ = str(fake_file)

    monkeypatch.chdir(tmp_root)

    # 由于 servers 目录不存在，应抛出 FileNotFoundError
    import pytest

    with pytest.raises(FileNotFoundError):
        mod.generate_spec_file()


