import json
import os
import hashlib
from typing import Optional
from pydantic import Field

from mcp.server.fastmcp import FastMCP

from utils.prompt import prompt_system, prompt_user
from utils.getcode import gen_project_rag, get_project_rag

# 设置当前路径为工作路径
current_path = os.path.dirname(os.path.abspath(__file__))
get_code_file = os.path.join(current_path, "getcode.py")

def gen_project_json(project_path: str) -> bool:
    """生成json文件"""
    project_path = project_path.strip()
    project_path_hash = hashlib.md5(project_path.encode('utf-8')).hexdigest()
    project_name = os.path.basename(project_path)
    project_json_file = f"/tmp/.rag/{project_path_hash}_{project_name}.json"

    if not os.path.exists(project_json_file):
        os.makedirs(os.path.dirname(project_json_file), exist_ok=True)
        gen_project_rag(path=project_path, json=project_json_file)
    return project_json_file

def call_getcode(args: dict, json_file: str) -> str:
    """调用getcode.py工具查询代码信息"""
    result_json = get_project_rag(json=json_file,
                                  func=args.get("--func"),
                                  struct=args.get("--struct"),
                                  macro=args.get("--macro"),
                                  globalvar=args.get("--globalvar"))

    if 'notfound' in result_json[0]:
        print(f"所请求的符号不存在：{args}")
    return result_json[0]


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
        Returns: list, code content and Review prompt
    """
    # Check if the project_path is empty
    # if not project_path:
    if not os.path.exists(project_path):
        return f" {project_path} file is empty. Please provide a valid code file."

    # 查看项目json是否存在，如果存在则创建
    project_json_file = gen_project_json(project_path)

    query_func = call_getcode({query_type: query_name}, project_json_file)

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
