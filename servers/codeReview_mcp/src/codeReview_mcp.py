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
    result_json = get_project_rag(
        json=json_file,
        func=args.get("--func"),
        struct=args.get("--struct"),
        macro=args.get("--macro"),
        globalvar=args.get("--globalvar"),
        enum=args.get("--enum"))

    return result_json[0]


mcp = FastMCP("CodeReview")

@mcp.tool()
def get_project_code(
    project_path: str = Field(..., description="项目所在的绝对目录路径，不能是文件名"),
    query_type: Optional[str] = Field(None, description="one of [--func, --struct, --macro, --globalvar, --enum]"),
    query_names: list[str] = Field(None, description="需要获取远吗的符号名列表")
) -> dict:
    """
    本工具提供相关代码的查询，不能直接给出检视意见，需要给予查询结果进行代码检视。

    Args:
        project_path : 需要查询代码的项目路径，使用绝对路径, 注意是项目路径, 不是包含type_name的文件路径
        query_type: one of [--func, --struct, --macro, --globalvar]
            "--func": {"type": "string", "description": "需要查询的函数名字"},
            "--struct": {"type": "string", "description": "结构体名字"},
            "--macro": {"type": "string", "description": "宏名字"},
            "--globalvar": {"type": "string", "description": "全局变量名字"},
            "--enum": {"type": "string", "description": "枚举名字"}
        query_name: 待查询的符号名列表

    Returns:
        Returns: 返回查询到的远吗内容及相关提示语。
    """
    # Check if the project_path is empty
    if not os.path.exists(project_path):
        return f" {project_path} file is empty. Please provide a valid code file."

    # 查看项目json是否存在，如果存在则创建
    project_json_file = gen_project_json(project_path)

    code_content = ""
    for idx, symbol in enumerate(query_names, start=1):
        query_func = call_getcode({query_type: symbol}, project_json_file)
        if 'notfound' in query_func:
            code_content += f"符号{idx}：{symbol} 未查询到相关源码。"
            continue
        code_content += f"符号{idx}："
        code_content += f"  类型：{query_func['type']}\n  源码：\n```c\n{query_func['code']}\n```\n"

    return prompt_user(content=code_content, append=False, checktype='issue') + prompt_system(checktype='issue')


if __name__ == "__main__":
    # Run the server with stdio/sse transport
    mcp.run()
