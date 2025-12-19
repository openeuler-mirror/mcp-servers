"""
基于 mugen 测试用例，借助 LLM 自动生成业务软件的 MCP Server。

设计目标（类比 backporting.run_backport_from_config）：

- 输入：一个配置字典或命令行参数，核心字段：
    - test_suite_dir: 测试套目录，例如 /home/xxx/mugen/testcases/feature-test/epol/tig
    - software_name : 业务软件名称，例如 tig / hbase / mpv 等
    - api_key       : LLM API 密钥
    - llm_provider  : LLM 提供商，支持 openai / deepseek（与 invoke_llm.py 一致）
    - server_root   : 生成的 MCP server 所在 servers 根目录（默认推断当前仓库根下的 servers/）

- 过程：
    1. 扫描 test_suite_dir 下的 *.sh 测试脚本，只关心 run_test 函数里的命令行部分。
    2. 汇总成结构化上下文（脚本名、测试目的注释、run_test 核心命令）。
    3. 调用 LLM（复用 cvekit.utils.agent.invoke_llm._get_llm_config 的 provider/model 配置），
       用一段较长的 system prompt 说明 MCP 设计规范，让 LLM 输出：
         - server.py 源码
         - mcp_config.json 内容
         - mcp-rpm.yaml 内容
    4. 将这些内容写入 servers/<software_name>_mcp/ 目录下，对齐现有 MCP 仓库结构。

- 输出：与 backporting.run_backport_from_config 类似的结果字典：
    {
        "status": "success" | "failed",
        "message": "人类可读总结",
        "logfile": ".../testsuite-mcp-YYYYmmddHHMM.log",
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
  也可以被其他 MCP server（例如 mugen_feature_mcp）通过子进程或 Python 导入方式复用。
"""

from __future__ import annotations

import argparse
import datetime
import json
import logging
import os
import re
import textwrap
from typing import Dict, List, Tuple

from langchain_openai import ChatOpenAI

from .agent.invoke_llm import _get_llm_config  # 复用 provider/model 配置
from .tools.logger import add_file_handler, logger


def _extract_comment_and_run_test(script_path: str) -> Dict[str, object]:
    """
    从单个 mugen shell 测试脚本中提取：
    - 顶部中文注释（测试目的）
    - run_test 函数体（我们最关心的命令行）
    """
    try:
        with open(script_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except UnicodeDecodeError:
        # 避免因为编码问题导致整个流程中断
        return {
            "script": os.path.basename(script_path),
            "description": "",
            "run_test": "",
        }

    description_lines: List[str] = []
    in_header_comment = True

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#!"):
            continue
        if stripped.startswith("#"):
            if in_header_comment:
                # 去掉开头的 "# " 前缀
                desc = stripped.lstrip("#").strip()
                description_lines.append(desc)
            continue
        # 非注释非 shebang，说明头部注释结束
        if stripped:
            in_header_comment = False
            break

    # 提取 run_test 函数体（与 mugen 框架结构兼容）
    in_run = False
    brace_depth = 0
    body_lines: List[str] = []

    for line in lines:
        stripped = line.strip()
        if not in_run:
            if re.match(r"^function\s+run_test\s*\(\)\s*{?", stripped):
                in_run = True
                brace_depth = stripped.count("{") - stripped.count("}")
                continue
        else:
            brace_depth += line.count("{") - line.count("}")
            if brace_depth < 0 or (brace_depth == 0 and stripped == "}"):
                break
            body_lines.append(line.rstrip("\n"))

    return {
        "script": os.path.basename(script_path),
        "description": "\n".join(description_lines),
        "run_test": "\n".join(body_lines),
    }


def _collect_testsuite_context(test_suite_dir: str) -> List[Dict[str, object]]:
    """遍历测试套目录，汇总所有脚本的测试目的和 run_test 函数体。"""
    if not os.path.isdir(test_suite_dir):
        raise FileNotFoundError(f"测试套目录不存在: {test_suite_dir}")

    result: List[Dict[str, object]] = []
    for name in sorted(os.listdir(test_suite_dir)):
        if not name.endswith(".sh"):
            continue
        script_path = os.path.join(test_suite_dir, name)
        info = _extract_comment_and_run_test(script_path)
        result.append(info)
    return result


def _build_system_prompt() -> str:
    """
    构造给 LLM 的 system prompt，综合用户在对话中给出的 MCP 设计规范。
    这里用 textwrap.dedent 保持源码可读性。
    """
    return textwrap.dedent(
        """
        你现在是一个熟悉 openEuler、MCP Server（Model Context Protocol Server）和 mugen 测试框架的资深工程师。

        任务：根据给定测试套目录中的 shell 测试用例，设计并实现一个【只面向业务软件本身命令行能力】的 MCP server。

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

             build_dependencies:
               system:
                 - python3
                 - uv

             runtime_dependencies:
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
             build_dependencies, runtime_dependencies, files, install_script。
           - 其中只有 summary/description 和 runtime_dependencies.packages 的具体内容
             可以根据不同软件做适当调整，其余字段名称和结构必须保持不变。

        5. 重要限制：
           - 严禁在对外暴露的名称/描述/参数中出现：
             mugen / OET_PATH / common_lib.sh / pre_test / post_test / CHECK_RESULT 等测试框架细节。
           - 可以借鉴测试脚本中的命令行写法，但对用户只暴露“软件命令行本身”的功能。

        **从测试用例抽象 MCP tools 的规则（用户视角）：**
        1. 只关注 run_test 函数中的命令行。
        2. 对于当前测试套，只关注一个软件，例如 tig / hbase / mpv 等。
        3. 按“用户能理解的功能”分组命令，设计 MCP tool 名称：
           - 例如 tig_status / tig_log / tig_blame / tig_grep 等；
           - 例如 hbase_version / hbase_shell / hbase_daemons_restart_regionservers 等。
        4. 对每个 MCP tool，提炼合理的输入参数：
           - 例如：paths: List[str]、revision: str、pattern: str、work_tree: str 等；
           - 参数类型使用简单 Python 类型：str / int / bool / List[str]；
           - 在 docstring 中用中文解释清楚。
        5. 所有 tool 的返回 JSON 结构必须统一（见上）。
        6. 数量与覆盖要求（非常重要）：
           - 对于测试套中的【每一个 shell 测试脚本】（每一个 script 条目），至少设计一个独立的 MCP tool；
           - 如果额外给出了 suite2cases JSON 中的用例 name 列表，你必须确保每一个 name 至少被一个 MCP tool 覆盖；
           - 禁止把多个测试脚本/用例完全合并为一个过于笼统的 tool（例如只生成 2~3 个大而泛的工具）。

        **输出格式要求（非常重要，务必逐字遵守）：**
        你必须返回【纯文本】，不要使用 Markdown 代码块（例如 ```json），也不要添加解释性文字。
        你【必须同时输出下面 4 个完整的分段】，缺一不可；即使某一段你暂时写不出完整内容，也要输出占位内容或 TODO 注释。
        所有标记必须单独占一行，且不要更改标记内容或顺序：

        <<<DESIGN_SUMMARY_START>>>
        （这里是若干中文段落，简要说明你设计了哪些 MCP tools 以及它们来源于哪些测试脚本）
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


def _build_user_prompt(software_name: str, test_suite_dir: str, scripts: List[Dict[str, object]]) -> str:
    """
    将测试套中提取出的信息拼成用户消息内容。
    为避免 prompt 过长，对每个脚本的 run_test 内容做适当截断。
    """
    header = textwrap.dedent(
        f"""
        下面是软件 {software_name} 在测试套目录 {test_suite_dir} 中的 shell 测试用例摘要。
        请严格按照 system prompt 中的规范，为该软件设计并生成对应的 MCP server。

        每个条目包含：
          - script: 测试脚本文件名
          - description: 顶部中文注释（测试目的）
          - run_test: run_test 函数体（核心命令行逻辑，可能已被截断）
        """
    ).strip()

    # 如果存在 suite2cases/<software_name>.json，则附加用例清单，要求“一例一 tool”
    suite_cases_note = ""
    try:
        # 假定 suite2cases 目录与 testcases 同级，例如：
        #   /home/liping/mugen/testcases/cli-test/ceph
        #   /home/liping/mugen/suite2cases/ceph.json
        mugen_root = os.path.abspath(os.path.join(test_suite_dir, "..", ".."))
        suite2cases_dir = os.path.join(mugen_root, "suite2cases")
        suite_json_path = os.path.join(suite2cases_dir, f"{software_name}.json")
        if os.path.isfile(suite_json_path):
            with open(suite_json_path, "r", encoding="utf-8") as f:
                suite_data = json.load(f)
            case_names = [
                str(c.get("name", "")).strip()
                for c in suite_data.get("cases", [])
                if c.get("name")
            ]
            if case_names:
                lines = "\n".join(f"  - {name}" for name in case_names)
                suite_cases_note = textwrap.dedent(
                    f"""

                    另外，来自 suite2cases/{software_name}.json 的用例名称列表如下（每个 name 理论上都应至少对应一个 MCP tool）：
                    {lines}
                    """
                ).strip()
    except Exception:
        # 读取失败时忽略，不影响主流程
        suite_cases_note = ""

    blocks: List[str] = []
    max_run_lines = 80  # 每个脚本最多保留多少行 run_test 内容，避免上下文过长

    for info in scripts:
        run_lines = str(info.get("run_test", "")).splitlines()
        truncated = run_lines[:max_run_lines]
        if len(run_lines) > max_run_lines:
            truncated.append("# ... （后续行已截断）")

        block = {
            "script": info.get("script", ""),
            "description": info.get("description", ""),
            "run_test": "\n".join(truncated),
        }
        blocks.append(block)

    full_header = header
    if suite_cases_note:
        full_header = header + "\n\n" + suite_cases_note

    return full_header + "\n\n测试脚本摘要 JSON 列表如下（请优先从 run_test 中提炼命令行用法）：\n" + json.dumps(
        blocks, ensure_ascii=False, indent=2
    )


def _clean_llm_json_output(content: str) -> str:
    """
    尝试从 LLM 原始输出中清洗出“更像 JSON 的部分”，以提高解析成功率。

    处理策略（尽量保守，只做常见清洗）：
      1. 去掉首尾空白。
      2. 如果包含 ``` 代码块，只保留第一个 ``` 与最后一个 ``` 之间的内容，
         并去掉开头可能存在的语言标记（如 ```json）。
      3. 从第一个 '{' 开始截断掉前缀说明文字（如“下面是 JSON：”等）。
    """
    text = content.strip()

    # 处理 ``` 包裹的代码块
    if "```" in text:
        first = text.find("```")
        second = text.rfind("```")
        if first != -1 and second != -1 and second > first + 3:
            fenced = text[first + 3 : second]
            # 去掉起始处可能的语言标签行，例如 "json\n"
            fenced = fenced.lstrip()
            # 如果第一行是类似 "json" 或 "JSON"，去掉这一行
            first_newline = fenced.find("\n")
            if first_newline != -1:
                first_line = fenced[:first_newline].strip().lower()
                if first_line in {"json", "javascript", "ts", "python"}:
                    fenced = fenced[first_newline + 1 :]
            text = fenced.strip()

    # 从第一个 '{' 开始截断，丢弃前面的自然语言说明
    brace_idx = text.find("{")
    if brace_idx > 0:
        text = text[brace_idx:]

    return text


def _escape_newlines_inside_strings(json_like: str) -> str:
    """
    将【字符串内部】的换行符转换为 \\n，缓解部分 LLM 输出未正确转义换行导致的
    `Unterminated string` JSON 解析错误。

    说明：
    - 只在成对的双引号之间（in_string=True）替换换行符；
    - 保留字符串外部的换行（便于人类阅读，且不影响 JSON 语法）。
    """
    result_chars: List[str] = []
    in_string = False
    escape = False

    for ch in json_like:
        if escape:
            # 当前字符被前面的反斜杠转义，直接加入
            result_chars.append(ch)
            escape = False
            continue

        if ch == "\\":
            # 下一个字符将被转义
            result_chars.append(ch)
            escape = True
            continue

        if ch == '"':
            in_string = not in_string
            result_chars.append(ch)
            continue

        if ch == "\n" and in_string:
            # 字符串内部的真实换行，替换为转义形式
            result_chars.append("\\n")
            continue

        result_chars.append(ch)

    return "".join(result_chars)


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

def run_generate_mcp_from_config(config: Dict[str, object], debug_mode: bool = False) -> Dict[str, object]:
    """
    主入口：从配置字典运行“测试套 → MCP server”生成流程。

    配置字段：
        - test_suite_dir (str): 必选，测试套目录。
        - software_name  (str): 必选，业务软件名，用于命名 server。
        - api_key        (str): 必选，LLM API key。
        - llm_provider   (str): 可选，默认 "openai"，支持 "openai" / "deepseek"。
        - server_root    (str): 可选，MCP server 生成到的 servers 根目录，
                                默认推断为当前文件所在仓库根目录下的 "servers"。

    返回值：
        status: "success" / "failed"
        message: 人类可读总结
        logfile: 日志文件路径
        server_name: 生成的 server 名称（例如 "tig_mcp"）
        server_dir: server 根目录绝对路径
        files: 各核心文件的路径
    """
    logger.debug("=" * 80)
    logger.debug("[run_generate_mcp_from_config] 开始执行测试套 → MCP server 生成流程")
    logger.debug("=" * 80)

    test_suite_dir = str(config.get("test_suite_dir", "")).strip()
    software_name = str(config.get("software_name", "")).strip()
    # 统一使用 api_key 命名，同时兼容历史 openai_key 字段和 OPENAI_KEY 环境变量
    api_key = (
        str(config.get("api_key", "")).strip()
        or str(config.get("openai_key", "")).strip()
        or os.environ.get("API_KEY", "")
        or os.environ.get("OPENAI_KEY", "")
    )
    llm_provider = str(config.get("llm_provider", "")).strip() or "openai"

    if not test_suite_dir or not os.path.isdir(test_suite_dir):
        msg = f"无效的测试套目录: {test_suite_dir}"
        logger.error(msg)
        return {"status": "failed", "message": msg}

    if not software_name:
        msg = "software_name 不能为空"
        logger.error(msg)
        return {"status": "failed", "message": msg}

    if not api_key:
        msg = "api_key 未提供（既没有在配置中也没有在环境变量 API_KEY/OPENAI_KEY 中找到）"
        logger.error(msg)
        return {"status": "failed", "message": msg}

    # 日志准备
    log_dir = os.path.join(os.path.expanduser("~"), ".testsuite_mcp_generator", "logs")
    os.makedirs(log_dir, exist_ok=True)
    now = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    logfile = os.path.join(log_dir, f"{software_name}-testsuite-mcp-{now}.log")
    add_file_handler(logger, logfile)

    if debug_mode:
        logger.setLevel(logging.DEBUG)

    logger.info("开始基于测试套生成 MCP server: software=%s, dir=%s", software_name, test_suite_dir)

    try:
        # 1. 收集测试套上下文
        scripts = _collect_testsuite_context(test_suite_dir)
        logger.debug("共解析到 %d 个测试脚本", len(scripts))

        # 2. 构造 prompt
        system_prompt = _build_system_prompt()
        user_prompt = _build_user_prompt(software_name, test_suite_dir, scripts)

        base_url, model_name = _get_llm_config(llm_provider)
        logger.info("使用 LLM provider=%s, model=%s, base_url=%s", llm_provider, model_name, base_url)

        llm = ChatOpenAI(
            temperature=0.4,
            model=model_name,
            api_key=api_key,
            openai_api_base=base_url,
            verbose=debug_mode,
        )

        logger.debug("开始调用 LLM 生成 MCP server 模板...")
        response = llm.invoke(
            [
                ("system", system_prompt),
                ("user", user_prompt),
            ]
        )
        content = response.content if hasattr(response, "content") else str(response)

        logger.debug("LLM 原始输出前 400 字符:\n%s", content[:400])

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
            repo_root = os.path.abspath(os.path.join(here, "..", "..", "..", ".."))
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

        msg = f"已根据测试套生成 MCP server: {server_name}"
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
        python -m cvekit.utils.testsuite_mcp_generator \\
            --test-suite-dir /home/xxx/mugen/testcases/feature-test/epol/tig \\
            --software-name tig \\
            --api-key xxxxx \\
            --llm-provider openai
    """
    parser = argparse.ArgumentParser(
        description="Generate MCP server from mugen test suite with help of LLM"
    )
    parser.add_argument(
        "--test-suite-dir",
        required=True,
        help="测试套目录路径，例如 /home/xxx/mugen/testcases/feature-test/epol/tig",
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
        choices=["openai", "deepseek"],
        help="LLM 提供商，默认 openai",
    )
    parser.add_argument(
        "--server-root",
        required=False,
        help="servers 根目录（默认推断为当前仓库根目录下的 servers/）",
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
        "test_suite_dir": args.test_suite_dir,
        "software_name": args.software_name,
        "api_key": args.api_key,
        "llm_provider": args.llm_provider,
        "server_root": args.server_root,
    }

    result = run_generate_mcp_from_config(config, debug_mode=args.debug)
    # 直接以 JSON 形式打印结果，便于脚本或其他工具消费
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
