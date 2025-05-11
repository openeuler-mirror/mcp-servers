from pydantic import Field
import json
from typing import Optional
import subprocess
import os
from mcp.server.fastmcp import FastMCP
from prompt import prompt_system, prompt_user

# 设置当前路径为工作路径
current_path = os.path.dirname(os.path.abspath(__file__))
get_code_file = os.path.join(current_path, "getcode.py")

def gen_json(codefile: str) -> bool:
    """生成json文件"""
    codefile = codefile.strip()
    json_file = os.path.join(codefile.strip(), "rag/code.json")
    
    if not os.path.exists(json_file):
        # 如果文件不存在创建一个空文件
        os.makedirs(os.path.dirname(json_file), exist_ok=True)
        cmd = ['python3', get_code_file, '--path', codefile, '--output', json_file]
        result = subprocess.run(cmd, capture_output=True, text=True)
        print(result.stderr)
        if result.returncode != 0:
            raise RuntimeError(f"{result}")
    return True

def call_getcode(args: dict, json_file: str) -> str:
    """调用getcode.py工具查询代码信息"""
    args_list = [item for pair in args.items() for item in pair]
    cmd = ['python3', get_code_file, '--json', json_file]
    cmd += args_list
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"getcode.py failed: {result.stderr}")
    result_json = json.loads(result.stdout.strip())

    if 'notfound' in result_json:
        print(f"所请求的符号不存在：{args}")
    return result_json



mcp = FastMCP("CodeReview")


@mcp.tool()
def review_code(
    project_path: str = Field(..., description="The project_path to be reviewed"),
    query_type: Optional[str] = Field(None, description="one of [--func, --struct, --macro, --globalvar]"),
    query_name: Optional[str] = Field(None, description="type name")
) -> dict:
    """
    查询项目代码中的各种相关要素源码，只需要列出需要查询的

    Args:
        project_path : 需要被检视的项目路径，使用绝对路径, 注意是项目路径, 不是包含type_name的文件路径
        query_type: one of [--func, --struct, --macro, --globalvar]
            "--func": {"type": "string", "description": "需要查询的函数名字"},
            "--struct": {"type": "string", "description": "结构体名字"},
            "--macro": {"type": "string", "description": "宏名字"},
            "--globalvar": {"type": "string", "description": "全局变量名字"}
        query_name: the name that need to check

    Returns:
        codeReview issue
    """
    # Check if the project_path is empty
    # if not project_path:
    if not os.path.exists(project_path):
        return f" {project_path} file is empty. Please provide a valid code file."

    # 查看项目json是否存在，如果存在则创建
    if not gen_json(project_path):
        return "rag/code.json gen failed"

    json_file = os.path.join(project_path.strip(), "rag/code.json")
    query_func = call_getcode({query_type: query_name}, json_file)
    if "notfound" in query_func:
        print(f"查询的函数不存在：{query_name}")
        return
    code_content = f"Type: {query_func['type']}\nCode:\n```c\n{query_func['code']}\n```"
    messages = [
        {"role": "system", "content": prompt_system(checktype="issue")},
        {"role": "user", "content": prompt_user(code_content, append=False, checktype="issue")},
        {"role": "user", "content": "基于上面的内容继续进行检视，可以进一步深入查看下层的--func, --struct, --macro, --globalvar, 可以一次性进行多次调用"}
    ]

    return messages


if __name__ == "__main__":
    # Run the server with stdio transport
    mcp.run()
