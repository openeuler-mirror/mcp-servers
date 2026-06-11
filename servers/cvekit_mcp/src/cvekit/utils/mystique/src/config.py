"""
This file is based on the project "Mystique":
  https://github.com/Mystique-OpenSource/mystique-opensource.github.io
The original code is licensed under the GNU General Public License v3.0.
See third_party/mystique/LICENSE for the full license text.

本文件在 Mystique-OpenSource/mystique 项目的基础上进行了修改，以适配 CVEKit 的自动回移植流程。

Modifications for CVEKit MCP backport workflow:
  Copyright (c) 2025 CVEKit contributors
  Licensed under the Mulan PSL v2.
"""


import os


def _join_url(base: str, path: str) -> str:
    return base.rstrip("/") + "/" + path.lstrip("/")


JOERN_PATH = os.getenv("JOERN_PATH", os.path.expanduser("~/.local/joern/joern-cli"))
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "minimax")
BASE_URL = os.getenv("BASE_URL", "").strip()

GPT_API_KEY = os.getenv("GPT_API_KEY", "")
LLM_API_KEY = os.getenv("LLM_API_KEY", os.getenv("API_KEY", ""))

default_style = "openai_chat"
LLM_API_STYLE = os.getenv("LLM_API_STYLE", default_style)
LLM_MODEL = os.getenv("LLM_MODEL", os.getenv("MODEL_NAME", "MiniMax-M2.7-highspeed"))
_FORMAT_MODE_ALIASES = {
    "full": "full_function",
    "changed": "changed_regions",
}
_format_mode_env = os.getenv("MYSTIQUE_FORMAT_MODE", "full").strip().lower()
FORMAT_NORMALIZATION_MODE = _FORMAT_MODE_ALIASES.get(_format_mode_env, _format_mode_env)

if os.getenv("LLM_API_URL"):
    LLM_API_URL = os.getenv("LLM_API_URL", "").strip()
elif BASE_URL:
    LLM_API_URL = _join_url(BASE_URL, "/chat/completions")
else:
    LLM_API_URL = "https://api.openai.com/v1/chat/completions"

# 本地模式示例:
# LLM_API_STYLE=legacy_instruct
# LLM_API_URL=http://127.0.0.1:5000/v1/completions
# LLM_API_URL=http://127.0.0.1:11434/api/generate
CTAGS_PATH = "/usr/bin/ctags"
SLICE_LEVEL = 1
PLACE_HOLDER = "    /* PLACEHOLDER: DO NOT DELETE THIS COMMENT */"
PROMPT_TEMPLATE = {
    "instruction": (
        "You're a professional and cautious C programmer, and you're very good at patching programs. Now I'm going to give you a patch and a piece of code to fix, but it's worth noting that the patch you've been given won't necessarily work directly with this code; you'll need to adapt it. You only need to adapt and fix the patch part, do not make any other fixes or improvements. Do not delete or add any comments in the code."
        " You may notice that there are some missing parts in the code I gave you, but it's okay, don't fill in the missing parts. You just need to output the fixed code!\n"
        "IMPORTANT: preserve the EXACT formatting of the target code:\n"
        "  - Use 1 tab per indent level (NOT spaces) for code statements.\n"
        "  - Function definitions: '{' on the NEXT line (e.g., `int foo()\\n{`).\n"
        "  - Control flow: '{' on the SAME line (e.g., `if (x) {`).\n"
        "  - Do NOT add or remove blank lines.\n"
        "  - Comment body lines must use the same indentation style as the target.\n\n"
        "IMPORTANT: handle function signature changes correctly:\n"
        "  - Compare the function parameters between the original patch (pre/post) and the target code.\n"
        "  - If the patch introduces new parameters (e.g., `ocred`) or removes parameters (e.g., `ns`, `label`) that the target doesn't have, you MUST adapt all call sites accordingly.\n"
        "  - For removed parameters: if the name suggests a credential (e.g., `cred`), replace with `current_cred()`; if it suggests a namespace (e.g., `ns`), replace with `NULL`; otherwise use `NULL` or remove the argument entirely depending on the target function signature.\n"
        "  - For newly added parameters in the patch, pass them through exactly as the patch does.\n"
        "  - NEVER use an identifier in the function body that is not declared as a parameter, local variable, or known macro.\n\n"
        "IMPORTANT: do NOT generate dead code:\n"
        "  - If a function returns unconditionally (e.g., `return error;`), do NOT place any executable statements after it before the closing brace.\n\n"
        "You have 1 tool: `compile_check`\n\n"
        "- `compile_check` allows you to verify C code for syntax and compilation errors using gcc.\n"
        "0. code: The C source code you want to compile check.\n"
        "1. language: Programming language (\"C\" or \"Java\"). Only C is supported for now.\n"
        "Returns: Empty string if compilation succeeds, error message otherwise.\n"
        "[IMPORTANT] Before outputting your final answer, use `compile_check` to verify your code compiles. "
        "If there are errors, fix them and check again.\n\n"
    ),
    "context": (
        "### Original Function Patch:\n{patch_original}\n\n"
        "### Function Before:\n{func_before_target}\n\n"
    ),
    "output": "{func_after_target}"
}

PROMPT_TEMPLATE_DICT = {
    "trans_patch": PROMPT_TEMPLATE,
}


def configure_llm(
    *,
    provider: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    model_name: str | None = None,
) -> None:
    global LLM_PROVIDER, GPT_API_KEY, LLM_API_KEY, BASE_URL, LLM_MODEL, LLM_API_URL
    if provider is not None:
        LLM_PROVIDER = provider
    if api_key is not None:
        LLM_API_KEY = api_key
        GPT_API_KEY = api_key
    if base_url is not None:
        BASE_URL = base_url
        LLM_API_URL = _join_url(base_url, "/chat/completions")
    if model_name is not None:
        LLM_MODEL = model_name


def configure_format_normalization(mode: str | None = None) -> None:
    """Select full-function or changed-region LLM formatting."""
    global FORMAT_NORMALIZATION_MODE
    if mode is None:
        return
    normalized = _FORMAT_MODE_ALIASES.get(mode.strip().lower(), mode.strip().lower())
    if normalized not in {"full_function", "changed_regions"}:
        raise ValueError(
            "Unsupported format normalization mode: "
            f"{mode!r}; expected 'full' or 'changed'"
        )
    FORMAT_NORMALIZATION_MODE = normalized
