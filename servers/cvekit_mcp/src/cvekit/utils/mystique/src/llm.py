import base64
import logging
import re

import requests
from langchain.agents import create_tool_calling_agent, AgentExecutor
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.tools import tool

import config
from ast_parser import ASTParser
from common import Language
from config import LLM_API_URL, PROMPT_TEMPLATE


@tool
def compile_check(code: str, language: str = "C") -> str:
    """Parse C code with tree-sitter to check for basic syntax errors.

    Args:
        code: The C source code to check.
        language: Programming language ("C" or "Java"). Only C is supported for now.

    Returns:
        Empty string if parsing succeeds, error message otherwise.
    """
    if language != "C":
        return ""

    # Only check the portion that looks like C code — skip any
    # surrounding markdown/code fences the LLM may have added.
    cleaned = code
    if "```" in cleaned:
        import re
        match = re.search(r"```(?:c|C)?\n(.*?)```", cleaned, re.DOTALL)
        if match:
            cleaned = match.group(1)

    try:
        parser = ASTParser(cleaned, Language.C)
        # tree-sitter returns error nodes for syntax issues
        errors = []
        _collect_errors(parser.root_node, errors)
        if errors:
            return "; ".join(errors)[:2000]
        return ""
    except Exception as e:
        return f"Parse error: {str(e)[:2000]}"


@tool
def validate_formatting(original_code: str, formatted_code: str) -> str:
    """Validate that reformatted code preserved ALL content — only whitespace changed.

    Call this after reformatting to verify correctness. Returns empty string on success,
    or a detailed error message describing exactly what was modified (with line numbers).

    Args:
        original_code: The original code before formatting.
        formatted_code: The reformatted code to validate.

    Returns:
        Empty string if valid. Otherwise error describing what changed.
    """
    orig_stripped = re.sub(r'\s+', '', original_code)
    new_stripped = re.sub(r'\s+', '', formatted_code)

    errors = []

    # 1. Full content check
    if orig_stripped != new_stripped:
        # Find the first differing position with context
        min_len = min(len(orig_stripped), len(new_stripped))
        diff_pos = 0
        for i in range(min_len):
            if orig_stripped[i] != new_stripped[i]:
                diff_pos = i
                break
        else:
            diff_pos = min_len

        ctx_start = max(0, diff_pos - 30)
        ctx_end_orig = min(len(orig_stripped), diff_pos + 50)
        ctx_end_new = min(len(new_stripped), diff_pos + 50)
        errors.append(
            f"Content changed at position {diff_pos}: "
            f"original has '{orig_stripped[ctx_start:ctx_end_orig]}' "
            f"but formatted has '{new_stripped[ctx_start:ctx_end_new]}'"
        )

        # Also check for added/removed characters at a high level
        if len(orig_stripped) != len(new_stripped):
            errors.append(
                f"Length mismatch: original={len(orig_stripped)} chars, "
                f"formatted={len(new_stripped)} chars "
                f"(diff={len(new_stripped) - len(orig_stripped):+d})"
            )

    # 2. Control flow node count check
    try:
        from ast_parser import ASTParser
        from common import Language
        orig_parser = ASTParser(original_code, Language.C)
        new_parser = ASTParser(formatted_code, Language.C)
        ctrl_types = {
            "if_statement", "else", "for_statement", "while_statement",
            "do_statement", "switch_statement", "return_statement",
            "break_statement", "continue_statement", "goto_statement",
        }
        orig_counts = {}
        new_counts = {}
        for node in orig_parser.root_node.descendants():
            if node.type in ctrl_types:
                orig_counts[node.type] = orig_counts.get(node.type, 0) + 1
        for node in new_parser.root_node.descendants():
            if node.type in ctrl_types:
                new_counts[node.type] = new_counts.get(node.type, 0) + 1

        for ct in sorted(set(list(orig_counts.keys()) + list(new_counts.keys()))):
            o = orig_counts.get(ct, 0)
            n = new_counts.get(ct, 0)
            if o != n:
                errors.append(
                    f"Control flow changed: '{ct}' count {o} -> {n}"
                )
    except Exception:
        pass  # tree-sitter parse failed, skip

    if errors:
        return "VALIDATION FAILED:\n" + "\n".join(f"  - {e}" for e in errors)
    return ""


def _collect_errors(node, errors: list[str]) -> None:
    """Recursively collect tree-sitter error nodes."""
    if node.type == "ERROR" or node.is_missing:
        start_line = node.start_point[0] + 1
        text_preview = (node.text or b"").decode(errors="replace")[:80]
        errors.append(f"Syntax error at line {start_line}: {text_preview!r}")
    for child in node.children:
        _collect_errors(child, errors)


def llm_generate(
    prompt: str,
    temperature: float = 0,
    tools: list | None = None,
    max_iterations: int = 10,
    system_message: str = "You are a professional and cautious code patching assistant.",
    max_tokens: int = 16384,
) -> str | None:
    """Generate text/code using LLM.

    If tools are provided, creates a LangChain tool-calling agent that
    allows the LLM to call tools (like compile_check) during generation.
    Without tools, uses the existing direct API call.

    Args:
        prompt: User prompt/task description.
        temperature: LLM temperature.
        tools: Optional list of LangChain @tool decorated functions.
        max_iterations: Maximum agent iterations (only used with tools).
        system_message: System prompt for the LLM.

    Returns:
        LLM response text, or None on failure.
    """
    # If tools provided, use LangChain agent
    if tools:
        api_key = config.LLM_API_KEY or config.GPT_API_KEY or "EMPTY_KEY"
        base_url = LLM_API_URL.replace("/chat/completions", "")

        llm = ChatOpenAI(
            model=config.LLM_MODEL,
            api_key=api_key,
            base_url=base_url,
            max_tokens=max_tokens,
            temperature=temperature,
        )

        prompt_template = ChatPromptTemplate.from_messages([
            ("system", system_message),
            ("placeholder", "{chat_history}"),
            ("human", "{input}"),
            ("placeholder", "{agent_scratchpad}"),
        ])
        agent = create_tool_calling_agent(llm, tools, prompt_template)
        agent_executor = AgentExecutor(
            agent=agent, tools=tools, verbose=True,
            max_iterations=max_iterations,
        )

        try:
            result = agent_executor.invoke({"input": prompt})
            logging.info(
                "Agent invoke returned: type=%s, keys=%s",
                type(result).__name__,
                list(result.keys()) if isinstance(result, dict) else "N/A",
            )
            # AgentExecutor returns {"output": "final answer", "intermediate_steps": [...]}
            if isinstance(result, dict):
                output = result.get("output")
                if output:
                    logging.info("Agent returned output: %d chars", len(str(output)))
                    return str(output)
            logging.warning("Unexpected agent result type: %s", type(result).__name__)
            return str(result)
        except Exception as e:
            logging.error(f"💥 Agent execution failed: {e}")
            return None

    # No tools: use original direct API call
    headers = {"Content-Type": "application/json"}
    api_key = config.LLM_API_KEY or config.GPT_API_KEY
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    style = config.LLM_API_STYLE.strip().lower()
    if style == "openai_chat":
        data = {
            "model": config.LLM_MODEL,
            "messages": [
                {"role": "system", "content": "You are a professional and cautious code patching assistant."},
                {"role": "user", "content": prompt},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
    elif style == "openai_completion":
        data = {
            "model": config.LLM_MODEL,
            "prompt": prompt,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
    else:
        data = {
            "mode": "instruct",
            "prompt": prompt,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "top_p": 0.5,
            "seed": 10,
            "do_sample": True,
        }

    try:
        response = requests.post(LLM_API_URL, headers=headers, json=data, verify=False, timeout=120)
        if response.status_code != 200:
            logging.error(f"❌ LLM通用请求失败: {response.status_code} - {response.text}")
            return None
        result_data = response.json()
        if "choices" in result_data and len(result_data["choices"]) > 0:
            choice0 = result_data["choices"][0]
            if isinstance(choice0, dict):
                if "text" in choice0 and isinstance(choice0["text"], str):
                    return choice0["text"]
                message = choice0.get("message")
                if isinstance(message, dict) and isinstance(message.get("content"), str):
                    return message["content"]
        if "response" in result_data and isinstance(result_data["response"], str):
            return result_data["response"]
        logging.error(f"❌ LLM通用请求返回格式异常: {result_data}")
        return None
    except Exception as e:
        logging.error(f"💥 LLM通用请求异常: {e}")
        return None


def clean_llm_output(output: str, language: Language) -> str:
    if language == Language.JAVA:
        output = output.replace("```java", "").replace("```", "")
    elif language == Language.C:
        output = output.replace("```c", "").replace("```", "")
    ast_parser = ASTParser(output, language)
    if language == Language.JAVA:
        func_node = ast_parser.query_oneshot("(method_declaration)@func")
    elif language == Language.C:
        func_node = ast_parser.query_oneshot("(function_definition)@func")
    if func_node is not None:
        assert func_node.text is not None
        output = func_node.text.decode()
    return output


def llm_fix(patch: str, vulcode: str, language: Language) -> None | str:
    logging.info("🔄 开始LLM修复流程")
    logging.info(f"📊 输入参数 - 补丁长度: {len(patch)}, 目标代码长度: {len(vulcode)}, 语言: {language}")
    
    llm_output = codellama_fix(patch, vulcode, language)
    
    if llm_output is None:
        logging.error("❌ LLM修复失败，codellama_fix返回None")
        return None
    
    logging.info(f"✅ LLM原始输出获取成功，长度: {len(llm_output)} 字符")
    logging.debug(f"📝 LLM原始输出预览: {llm_output[:200]}...")
    
    fixed_code = clean_llm_output(llm_output, language)
    
    if fixed_code:
        logging.info(f"✅ LLM修复完成，清理后代码长度: {len(fixed_code)} 字符")
        logging.debug(f"🔧 修复后代码预览: {fixed_code[:200]}...")
    else:
        logging.warning("⚠️ LLM修复后代码为空")
    
    return fixed_code


def codellama_fix(patch: str, vulcode: str, language: Language) -> None | str:
    logging.info(f"🔧 开始CodeLlama修复 - 语言: {language}")
    logging.info(f"📊 输入参数统计 - 补丁长度: {len(patch)}, 目标代码长度: {len(vulcode)}")
    logging.info(f"📝 输入补丁预览: {patch[:200]}...")
    logging.info(f"📝 目标代码预览: {vulcode[:200]}...")
    
    example = {
        "patch_original": patch,
        "func_before_target": vulcode}
    prompt = PROMPT_TEMPLATE["instruction"].format_map(example) + PROMPT_TEMPLATE["context"].format_map(example)
    
    logging.info(f"📋 生成的提示词长度: {len(prompt)} 字符")
    logging.info(f"📋 提示词预览: {prompt[:300]}...")
    
    logging.info(f"🌐 发送请求到: {LLM_API_URL}")
    result = llm_generate(prompt, temperature=0)
    if result is None:
        logging.error("❌ LLM修复请求失败")
        return None
    logging.info(f"✅ 成功获取修复结果，长度: {len(result)} 字符")
    logging.info(f"🔧 修复结果预览: {result[:300]}...")
    return result


def llm_merge(patch: str, vulcode: str, language: Language) -> None | str:
    llm_output = gpt_merge(patch, vulcode, language)
    logging.debug(f"LLM output: \n{llm_output}")
    if llm_output is None:
        return
    fixed_code = clean_llm_output(llm_output, language)
    return fixed_code


def gpt_fix(patch: str, vulcode: str, language: Language) -> str | None:
    logging.info(f"🔧 开始GPT修复 - 语言: {language}")
    logging.debug(f"📝 输入补丁: {patch[:100]}...")
    logging.debug(f"📝 目标代码: {vulcode[:100]}...")
    
    code_language = "Java" if language == Language.JAVA else "C"
    content = f"""
Patch:
{patch}

Code to be fixed:
{vulcode}
"""
    logging.debug(f"🤖 GPT 修复输入: {content[:200]}...")
    
    example = {
        "patch_original": patch,
        "func_before_target": vulcode}
    prompt = PROMPT_TEMPLATE["instruction"].format_map(example) + PROMPT_TEMPLATE["context"].format_map(example)
    result = llm_generate(prompt, temperature=0)
    if result is None:
        logging.error("❌ GPT 修复失败")
        return None
    return result


def gpt_merge(patch: str, vulcode: str, language: Language) -> str | None:
    logging.info(f"🔀 开始GPT合并 - 语言: {language}")
    logging.debug(f"📝 输入补丁: {patch[:100]}...")
    logging.debug(f"📝 目标代码: {vulcode[:100]}...")
    
    content = f"""
Patch:
{patch}

Code to be fixed:
{vulcode}
"""
    logging.debug(f"🤖 GPT 合并输入: {content[:200]}...")
    
    example = {
        "patch_original": patch,
        "func_before_target": vulcode}
    prompt = PROMPT_TEMPLATE["instruction"].format_map(example) + PROMPT_TEMPLATE["context"].format_map(example)
    result = llm_generate(prompt, temperature=0.3)
    if result is None:
        logging.error("❌ GPT 合并失败")
        return None
    return result


def gpt_ppathf(pre_method: str, post_method: str, target_method: str) -> str | None:
    logging.info(f"🔄 开始补丁路径适配")
    logging.debug(f"📝 R1函数前: {pre_method[:100]}...")
    logging.debug(f"📝 R1函数后: {post_method[:100]}...")
    logging.debug(f"📝 R2函数前: {target_method[:100]}...")
    
    content = f"""
Below is a patch (including function before and function after) from R1, paired with a corresponding function before from R2. Adapt the patch from R1 to R2 by generating the function after based on the given function before.


Function Before R1:
{pre_method}


Function After R1:
{post_method}

Function Before R2:
{target_method}

Function After R2:

"""
    logging.debug(f"🤖 GPT 补丁适配输入: {content[:200]}...")
    logging.info(f"🌐 发送请求到: {LLM_API_URL}")
    
    result = llm_generate(content, temperature=0.5)
    if result is None:
        logging.error("❌ 补丁适配失败")
        return None
    logging.info(f"✅ 成功获取适配结果，长度: {len(result)} 字符")
    logging.debug(f"🔄 适配结果: {result[:200]}...")
    return result
