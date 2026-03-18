"""
基于命令行软件的使用手册（man7 HTML 抽取片段），借助 LLM 自动生成业务软件的 MCP Server。

设计目标（类比 backporting.run_backport_from_config）：

- 输入：一个配置字典或命令行参数，核心字段：
    - manual_path  : man 手册抽取文本路径（由 get_man.py 生成）
    - software_name: 业务软件名称，例如 tig / hbase / mpv 等
    - api_key      : LLM API 密钥
    - llm_provider : LLM 提供商，支持 openai / deepseek（与 invoke_llm.py 一致）
    - server_root  : 生成的 MCP server 所在 servers 根目录（默认推断当前仓库根下的 servers/）

- 过程：
    1. 读取 manual_path 中的手册片段（通常包含 NAME/SYNOPSIS/OPTIONS/EXAMPLES）。
    2. 调用 LLM（复用 cvekit.utils.agent.invoke_llm._get_llm_config 的 provider/model 配置），
       用一段较长的 system prompt 说明 MCP 设计规范，让 LLM 输出：
         - server.py 源码
         - mcp_config.json 内容
         - mcp-rpm.yaml 内容
    3. 将这些内容写入 servers/<software_name>_mcp/ 目录下，对齐现有 MCP 仓库结构。

- 输出：与 backporting.run_backport_from_config 类似的结果字典：
    {
        "status": "success" | "failed",
        "message": "人类可读总结",
        "logfile": ".../manual-mcp-YYYYmmddHHMM.log",
        "server_name": "<software_name>_mcp",
        "server_dir": "/abs/path/to/servers/<software_name>_mcp",
        "files": {
            "server.py": "/abs/...",
            "mcp_config.json": "/abs/...",
            "mcp-rpm.yaml": "/abs/..."
        }
    }

注意：
- 这个模块是一个“工具脚本”，和 MCP server 本身不同；它可以被 CLI 调用，
  也可以被其他 MCP server 通过子进程或 Python 导入方式复用。
"""

from __future__ import annotations

import argparse
import ast
import datetime
import json
import logging
import os
import sys
import textwrap
from pathlib import Path
from typing import Dict, List

from langchain_openai import ChatOpenAI

_SCRIPT_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPT_DIR.parent
_CVEKIT_SRC = _REPO_ROOT / "servers" / "cvekit_mcp" / "src"
if _CVEKIT_SRC.is_dir():
    sys.path.insert(0, str(_CVEKIT_SRC))

from cvekit.utils.agent.invoke_llm import _get_llm_config  # 复用 provider/model 配置
from cvekit.utils.tools.logger import add_file_handler, logger
from get_man import (
    fetch_manual_html,
    parse_sections,
    render_sections,
    truncate_text,
)
from jinja2 import Template
from dotenv import load_dotenv

def _truncate_text(text: str, max_chars: int) -> str:
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "\n...[truncated]"


def _load_manual_text(manual_path: str, max_chars: int) -> str:
    with open(manual_path, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()
    return _truncate_text(content.strip(), max_chars)


def _fetch_manual_with_get_man(
    software_name: str,
    out_dir: Path,
    sections: str = "NAME,SYNOPSIS,OPTIONS,EXAMPLES",
    max_section_chars: int = 1200,
    max_total_chars: int = 3000,
) -> str:
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{software_name}.extract.txt"
    html_path, url = fetch_manual_html(software_name, out_dir=str(out_dir))
    html = Path(html_path).read_text(encoding="utf-8", errors="replace")
    section_list = [s.strip().upper() for s in sections.split(",") if s.strip()]
    extracted = parse_sections(html, section_list)
    if not extracted:
        raise RuntimeError(f"no manual sections found for: {software_name}")
    output = render_sections(extracted, max_section_chars)
    output = truncate_text(output, max_total_chars)
    if not output.strip():
        raise RuntimeError(f"manual content empty after extraction for: {software_name}")
    out_path.write_text(output, encoding="utf-8")
    logger.info("manual source: %s", url)
    return str(out_path)


def _build_system_prompt() -> str:
    """
    构造给 LLM 的 system prompt，综合用户在对话中给出的 MCP 设计规范。
    这里用 textwrap.dedent 保持源码可读性。
    """
    return textwrap.dedent(
        """
        你现在是一个熟悉 openEuler、MCP Server（Model Context Protocol Server）和命令行软件手册的资深工程师。

        任务：根据用户给定的软件包的常用命令，设计并实现一个【只面向业务软件本身与开发者真实需求的命令行能力】的 MCP server。

        **整体要求：**
        1. MCP server 目录结构示例（以 <software>_mcp 为例）：
           servers/
             └── <software>_mcp/
                 ├── mcp_config.json
                 ├── mcp-rpm.yaml
                 └── src/
                     └── server.py

        2. server.py 要求：
           - 使用 `from mcp.server.fastmcp import FastMCP, Context` 创建服务器实例，例如：
               mcp = FastMCP("<Software> MCP Server")
           - 顶部有清晰中文 docstring，说明：
               * 面向哪个软件（如：tig / hbase / mpv）
               * 所有 MCP tool 的列表：名称 / 用途 / 参数 / 返回结构
           - 每个 MCP tool：
               * 使用 `@mcp.tool()` 装饰
               * 有清晰中文 docstring（用途、参数含义、返回 JSON 结构）
               * 内部用 `subprocess.run` 调用真实命令行
               * 返回统一 JSON 结构：
                 {
                   "success": bool,
                   "command": str,
                   "exit_code": int,
                   "stdout": str,
                   "stderr": str
                 }
           - 末尾包含：
               if __name__ == "__main__":
                   mcp.run()

        3. mcp_config.json 要求：
           - 形如：
             {
               "mcpServers": {
                 "<software>_mcp": {
                   "command": "uv",
                   "args": [
                     "--directory",
                     "/opt/mcp-servers/servers/<software>_mcp/src",
                     "run",
                     "server.py"
                   ],
                   "disabled": false,
                   "alwaysAllow": []
                 }
               }
             }

        4. mcp-rpm.yaml 要求（字段必须统一，严格使用下面的结构，不能增删顶层字段）：

           - 你必须生成一个类似下面的模板（用当前软件名 <software> 和 <Software> 替换占位符）：

             name: "<software>_mcp"
             summary: "MCP server for <Software> command-line operations"
             description: |-
               Provides MCP tools that wrap <Software> command-line operations, so AI can call it safely.

             version: "1.0.0"
             release: "1"

             license: "MIT"

             dependencies:
               system:
                 - python3
                 - uv
                 - python3-mcp
                 - jq
               packages:
                 - <software>

             files:
               required:
                 - mcp_config.json
                 - src/server.py

             install_script: |
               mkdir -p /opt/mcp-servers/servers/<software>_mcp/src
               cp mcp_config.json /opt/mcp-servers/servers/<software>_mcp/
               cp src/server.py /opt/mcp-servers/servers/<software>_mcp/src/
               chmod +x /opt/mcp-servers/servers/<software>_mcp/src/server.py

           - 顶层字段顺序和名称必须与上面完全一致：
             name, summary, description, version, release, license,
             dependencies, files, install_script。
           - 其中只有 summary/description 和 dependencies.packages 的具体内容
             可以根据不同软件做适当调整，其余字段名称和结构必须保持不变。

        **工具命名与描述规范（强制）：**
        1. 每个 tool 名称必须以软件名为前缀，例如 tcpdump_capture / tcpdump_count / yelp_build。
        2. tool docstring 第一行必须包含“使用 <命令> ...”句式，明确对应的实际命令。
        3. tool 用途描述必须显式提到软件包名（如“使用 tcpdump …”），避免泛化词（如“统计包数量”）。
        4. 对应命令名需要出现在 docstring 中（例如 yelp-build / tcpdump）。

        **从用户视角设计 MCP tools 的规则：**
        1. 只关注当前软件本身的命令行能力。
        1.1 工具设计以开发者真实需求为导向，优先覆盖开发者最常使用的核心操作命令与用法，避免罗列冷门子命令。
        1.2 如果用户消息提供了“常见命令列表”，必须优先围绕这些命令设计 tools，
        2. 对每个 MCP tool，提炼合理的输入参数，例如：paths: List[str]、revision: str、pattern: str、work_tree: str 等；
           - 参数类型使用简单 Python 类型：str / int / bool / List[str]；
           - 在 docstring 中用中文解释清楚。
        3. 工具数目不得少于4个，不得多于10个
        4. 所有 tool 的返回 JSON 结构必须统一（见上）。

        **输出格式要求（非常重要，务必逐字遵守）：**
        你必须返回【纯文本】，不要使用 Markdown 代码块（例如 ```json），也不要添加解释性文字。
        你【必须同时输出下面 4 个完整的分段】，缺一不可；即使某一段你暂时写不出完整内容，也要输出占位内容或 TODO 注释。
        所有标记必须单独占一行，且不要更改标记内容或顺序：

        <<<DESIGN_SUMMARY_START>>>
        （这里是若干中文段落，简要说明你设计了哪些 MCP tools 以及它们来源于命令行）
        <<<DESIGN_SUMMARY_END>>>

        <<<SERVER_PY_START>>>
        （这里是完整的 server.py 源码）
        <<<SERVER_PY_END>>>

        <<<MCP_CONFIG_JSON_START>>>
        （这里是完整的 mcp_config.json 文件内容）
        <<<MCP_CONFIG_JSON_END>>>

        <<<MCP_RPM_YAML_START>>>
        （这里是完整的 mcp-rpm.yaml 文件内容）
        <<<MCP_RPM_YAML_END>>>

        额外要求：
        - 不要在这些标记之外输出任何其它内容（不要再输出 JSON 对象或自然语言说明）。
        - 各段内部可以包含任意引号、换行和缩进，无需进行 JSON 转义。
        - 不要使用 ``` 包裹任何内容。
        - 如果你没有足够信息生成某一段的完整内容，可以在该段内部输出清晰的 TODO 注释，但仍然必须保留对应的 START/END 标记。
        """
    ).strip()


def _build_common_commands_prompt(software_name: str, manual_text: str) -> str:
    """
    构造用于提取常见命令的提示词。
    """
    template = textwrap.dedent(
        """
        你是命令行软件专家。
        请列出开发者最常用的和软件包{{ software_name }}相关的 10 条命令或用法（只输出命令/用法本身，不要解释）。
        每条命令一行，不要输出额外文本。
        {% if manual_text %}
        下面是 {{ software_name }} 的手册片段。手册片段如下：
        {{ manual_text }}
        {% endif %}
        """
        ).strip()
    return Template(template).render(
        software_name=software_name,
        manual_text=manual_text,
    )


def _extract_command_list(text: str, max_items: int = 8) -> List[str]:
    """
    从 LLM 输出中提取命令列表，最多 max_items 条。
    """
    items: List[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        # 去掉常见编号/项目符号
        if line[:2].isdigit() and line[2:3] in {".", "、"}:
            line = line[3:].strip()
        if line.startswith(("-", "*", "•")):
            line = line[1:].strip()
        if not line:
            continue
        items.append(line)
        if len(items) >= max_items:
            break
    return items


def _build_user_prompt(
    software_name: str, manual_text: str, common_commands: List[str]
) -> str:
    """
    将手册片段拼成用户消息内容。
    """
    header = textwrap.dedent(
        f"""
        下面是软件 {software_name} 的命令行手册或者帮助文档的片段。
        请严格按照 system prompt 中的规范，为该软件设计并生成对应的 MCP server。

        """
    ).strip()

    common_section = ""
    if common_commands:
        common_lines = "\n".join(f"- {cmd}" for cmd in common_commands)
        common_section = (
            "\n\n常见命令列表（请优先围绕这些命令设计 MCP tools）：\n" + common_lines
        )

    return (
        header
        + "\n\n手册片段如下（通常包含 NAME/SYNOPSIS/OPTIONS/EXAMPLES）：\n"
        + manual_text
        + common_section
    )

def _extract_between_markers(text: str, start: str, end: str) -> str:
    """
    从 LLM 输出中按标记提取内容块。

    如果任一标记不存在，则返回空字符串。
    """
    start_idx = text.find(start)
    if start_idx == -1:
        return ""
    start_idx += len(start)
    end_idx = text.find(end, start_idx)
    if end_idx == -1:
        return ""
    # 去掉首尾多余的换行和空白
    return text[start_idx:end_idx].strip("\r\n ")

def _check_python_syntax(text: str) -> tuple[bool, str]:
    """
    语法检查：只做 Python 语法解析，不执行代码。
    """
    try:
        ast.parse(text, filename="server.py")
        return True, ""
    except SyntaxError as e:
        location = ""
        if e.lineno is not None and e.offset is not None:
            location = f" (line {e.lineno}, col {e.offset})"
        return False, f"SyntaxError: {e.msg}{location}"
    except Exception as e:  # noqa: BLE001
        return False, f"{type(e).__name__}: {e}"

def run_generate_mcp_from_config(config: Dict[str, object], debug_mode: bool = False) -> Dict[str, object]:
    """
    主入口：从配置字典运行“手册 → MCP server”生成流程。

    配置字段：
        - manual_path   (str): 必选，手册片段文件路径（由 get_man.py 生成）。
        - software_name (str): 必选，业务软件名，用于命名 server。
        - api_key       (str): 必选，LLM API key。
        - llm_provider  (str): 可选，默认 "openai"，支持 "openai" / "deepseek"。
        - server_root   (str): 可选，MCP server 生成到的 servers 根目录，
                               默认推断为当前文件所在仓库根目录下的 "servers"。
        - max_manual_chars (int): 可选，手册片段最大字符数（0 = 不限制）。

    返回值：
        status: "success" / "failed"
        message: 人类可读总结
        logfile: 日志文件路径
        server_name: 生成的 server 名称（例如 "tig_mcp"）
        server_dir: server 根目录绝对路径
        files: 各核心文件的路径
    """
    logger.debug("=" * 80)
    logger.debug("[run_generate_mcp_from_config] 开始执行手册 → MCP server 生成流程")
    logger.debug("=" * 80)

    manual_path = str(config.get("manual_path", "")).strip()
    software_name = str(config.get("software_name", "")).strip()
    max_manual_chars = int(config.get("max_manual_chars", 8000) or 0)
    manual_out_dir = Path(str(config.get("manual_out_dir", "")).strip() or _SCRIPT_DIR / "manuals")
    manual_sections = str(config.get("manual_sections", "")).strip() or "NAME,SYNOPSIS,OPTIONS,EXAMPLES"
    manual_max_section_chars = int(config.get("manual_max_section_chars", 1200) or 0)
    manual_max_total_chars = int(config.get("manual_max_total_chars", 3000) or 0)
    load_dotenv()
    # 统一使用 api_key 命名，同时兼容历史 openai_key 字段和 OPENAI_KEY 环境变量
    api_key = (
        (config.get("api_key") or "").strip()
        or (config.get("openai_key") or "").strip()
        or os.environ.get("API_KEY", "")
        or os.environ.get("OPENAI_KEY", "")
    )
    llm_provider = str(config.get("llm_provider", "")).strip() or "openai"
    if not software_name:
        msg = "software_name 不能为空"
        logger.error(msg)
        return {"status": "failed", "message": msg}

    if not api_key:
        msg = "api_key 未提供（既没有在配置中也没有在环境变量 API_KEY/OPENAI_KEY 中找到）"
        logger.error(msg)
        return {"status": "failed", "message": msg}

    if not manual_path:
        logger.info("manual_path 未提供，开始通过 get_man.py 抓取手册片段...")
        try:
            manual_path = _fetch_manual_with_get_man(
                software_name=software_name,
                out_dir=manual_out_dir,
                sections=manual_sections,
                max_section_chars=manual_max_section_chars,
                max_total_chars=manual_max_total_chars,
            )
            logger.info("手册片段已生成: %s", manual_path)
        except Exception as e:  # noqa: BLE001
            logger.warning("自动获取手册片段失败，将继续生成: %s", e)
            manual_path = ""

    if manual_path and not os.path.isfile(manual_path):
        msg = f"无效的手册片段路径: {manual_path}"
        manual_path = ""

    # 日志准备
    log_dir = os.path.join(os.path.expanduser("~"), ".manual_mcp_generator", "logs")
    os.makedirs(log_dir, exist_ok=True)
    now = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    logfile = os.path.join(log_dir, f"{software_name}-testsuite-mcp-{now}.log")
    add_file_handler(logger, logfile)

    if debug_mode:
        logger.setLevel(logging.DEBUG)

    logger.info("开始基于手册生成 MCP server: software=%s, manual=%s", software_name, manual_path)

    try:
        # 1. 读取手册片段（可为空）
        if manual_path:
            manual_text = _load_manual_text(manual_path, max_manual_chars)
            logger.debug("手册片段长度: %d 字符", len(manual_text))
        else:
            manual_text = ""
            logger.info("未提供手册片段，将基于模型常识生成常用命令")

        # 2. 构造 prompt
        system_prompt = _build_system_prompt()

        base_url, model_name = _get_llm_config(llm_provider)
        logger.info("使用 LLM provider=%s, model=%s, base_url=%s", llm_provider, model_name, base_url)

        llm = ChatOpenAI(
            temperature=0.4,
            model=model_name,
            api_key=api_key,
            openai_api_base=base_url,
            verbose=debug_mode,
        )

        # 2.1 先提取常见命令
        common_prompt = _build_common_commands_prompt(software_name, manual_text)
        logger.info("开始调用 LLM 提取常见命令...")
        common_response = llm.invoke(
            [
                ("system", "你是命令行软件专家。"),
                ("user", common_prompt),
            ]
        )
        common_content = (
            common_response.content if hasattr(common_response, "content") else str(common_response)
        )
        common_commands = _extract_command_list(common_content, max_items=10)
        logger.info("常见命令提取结果: %s", common_commands)
        user_prompt = _build_user_prompt(
            software_name, manual_text, common_commands
        )
        

        logger.info("开始调用 LLM 生成 MCP server 模板...")
        response = llm.invoke(
            [
                ("system", system_prompt),
                ("user", user_prompt),
            ]
        )
        content = response.content if hasattr(response, "content") else str(response)

        logger.info("LLM 原始输出前 400 字符:\n%s", content[:400])

        # 3. 只按标记块解析 LLM 输出（不再尝试 JSON 解析，避免各种 JSONDecodeError）
        design_summary = _extract_between_markers(
            content, "<<<DESIGN_SUMMARY_START>>>", "<<<DESIGN_SUMMARY_END>>>"
        )
        server_py_text = _extract_between_markers(
            content, "<<<SERVER_PY_START>>>", "<<<SERVER_PY_END>>>"
        )
        mcp_config_text = _extract_between_markers(
            content, "<<<MCP_CONFIG_JSON_START>>>", "<<<MCP_CONFIG_JSON_END>>>"
        )
        mcp_rpm_text = _extract_between_markers(
            content, "<<<MCP_RPM_YAML_START>>>", "<<<MCP_RPM_YAML_END>>>"
        )

        if not (server_py_text and mcp_config_text and mcp_rpm_text):
            msg = (
                "LLM 输出未按约定的标记格式返回内容，"
                "缺少 <<<SERVER_PY_START>>> / <<<MCP_CONFIG_JSON_START>>> / <<<MCP_RPM_YAML_START>>> 等标记。"
            )
            logger.error("%s 原始输出前 800 字符如下：\n%s", msg, content[:800])
            return {
                "status": "failed",
                "message": msg,
                "logfile": logfile,
            }

        logger.info("已通过标记块成功解析出 server.py / mcp_config.json / mcp-rpm.yaml。")

        # 3.5 语法检查（仅针对 server.py），失败则重试生成 server.py（最多 2 次）
        max_retry = 2
        retry_count = 0
        ok, err = _check_python_syntax(server_py_text)
        while not ok and retry_count < max_retry:
            retry_count += 1
            logger.warning(
                "server.py 语法检查失败：%s，开始第 %d/%d 次重试生成 server.py",
                err,
                retry_count,
                max_retry,
            )
            retry_prompt = (
                user_prompt
                + "\n\n上一次生成的 server.py 语法错误如下：\n"
                + err
                + "\n请仅修复 server.py 的语法问题，其他输出可保持不变。"
            )
            retry_response = llm.invoke(
                [
                    ("system", system_prompt),
                    ("user", retry_prompt),
                ]
            )
            retry_content = (
                retry_response.content
                if hasattr(retry_response, "content")
                else str(retry_response)
            )
            retry_server_py = _extract_between_markers(
                retry_content, "<<<SERVER_PY_START>>>", "<<<SERVER_PY_END>>>"
            )
            if not retry_server_py:
                err = "未找到 <<<SERVER_PY_START>>> / <<<SERVER_PY_END>>> 标记"
                logger.error(
                    "重试输出未包含 server.py 标记，无法更新 server.py：%s",
                    err,
                )
                ok = False
                continue
            server_py_text = retry_server_py
            ok, err = _check_python_syntax(server_py_text)

        if not ok:
            msg = f"server.py 语法检查失败，已重试 {max_retry} 次：{err}"
            logger.error(msg)
            return {
                "status": "failed",
                "message": msg,
                "logfile": logfile,
            }

        # 4. 写入文件
        server_name = f"{software_name}_mcp"

        # 处理 server_root：
        # - 如果配置中是 None / "" / "None" / "null" 等，都视为“未指定”，走自动推断逻辑
        raw_server_root = config.get("server_root", "")
        server_root = ""
        if raw_server_root is not None:
            server_root = str(raw_server_root).strip()
        if not server_root or server_root.lower() in {"none", "null"}:
            # 推断仓库根目录：当前文件位于 servers/cvekit_mcp/src/cvekit/utils/，向上四层再进入 servers
            here = os.path.abspath(__file__)
            repo_root = "new_generate_mcps"
            server_root = os.path.join(repo_root, "servers")

        server_dir = os.path.join(server_root, server_name)
        src_dir = os.path.join(server_dir, "src")
        os.makedirs(src_dir, exist_ok=True)

        server_py_path = os.path.join(src_dir, "server.py")
        mcp_config_path = os.path.join(server_dir, "mcp_config.json")
        mcp_rpm_path = os.path.join(server_dir, "mcp-rpm.yaml")

        with open(server_py_path, "w", encoding="utf-8") as f:
            f.write(server_py_text)
        with open(mcp_config_path, "w", encoding="utf-8") as f:
            f.write(mcp_config_text)
        with open(mcp_rpm_path, "w", encoding="utf-8") as f:
            f.write(mcp_rpm_text)

        msg = f"已根据手册生成 MCP server: {server_name}"
        logger.info(msg)

        return {
            "status": "success",
            "message": msg,
            "logfile": logfile,
            "server_name": server_name,
            "server_dir": server_dir,
            "files": {
                "server.py": server_py_path,
                "mcp_config.json": mcp_config_path,
                "mcp-rpm.yaml": mcp_rpm_path,
            },
            "design_summary": design_summary,
        }

    except Exception as e:  # noqa: BLE001
        logger.exception("生成 MCP server 过程中发生异常: %s", e)
        return {
            "status": "failed",
            "message": f"异常: {e}",
            "logfile": logfile,
        }


def main() -> None:
    """
    CLI 入口，类似 backporting.main：

    用法示例：
        python manual_mcp_generator.py \\
            --manual-path /home/xxx/manuals/tig.extract.txt \\
            --software-name tig \\
            --api-key xxxxx \\
            --llm-provider openai
    """
    parser = argparse.ArgumentParser(
        description="Generate MCP server from man manual snippets with help of LLM"
    )
    parser.add_argument(
        "--manual-path",
        required=False,
        default = "",
        help="手册片段路径，例如 /home/xxx/manuals/tig.extract.txt（不传则自动抓取）",
    )
    parser.add_argument(
        "--software-name",
        required=True,
        help="业务软件名称，例如 tig / hbase / mpv 等",
    )
    parser.add_argument(
        "--api-key",
        required=False,
        help="LLM API key，可选；如果不传则从环境变量 API_KEY 或 OPENAI_KEY 读取",
    )
    parser.add_argument(
        "--llm-provider",
        default="openai",
        choices=["openai", "deepseek","siliconflow"],
        help="LLM 提供商，默认 openai",
    )
    parser.add_argument(
        "--server-root",
        required=False,
        help="servers 根目录（默认推断为当前仓库根目录下的 servers/）",
    )
    parser.add_argument(
        "--max-manual-chars",
        required=False,
        type=int,
        default=8000,
        help="手册片段最大字符数（0 = 不限制）",
    )
    parser.add_argument(
        "-d",
        "--debug",
        action="store_true",
        help="启用调试日志",
    )

    args = parser.parse_args()

    if not logging.getLogger().handlers:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        )

    config = {
        "manual_path": args.manual_path,
        "software_name": args.software_name,
        "api_key": args.api_key,
        "llm_provider": args.llm_provider,
        "server_root": args.server_root,
        "max_manual_chars": args.max_manual_chars,
    }

    result = run_generate_mcp_from_config(config, debug_mode=args.debug)
    # 直接以 JSON 形式打印结果，便于脚本或其他工具消费
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()