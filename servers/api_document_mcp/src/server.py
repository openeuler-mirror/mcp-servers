import os
import subprocess
import json
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("API文档生成工具")

def generate_doxygen_docs(project_path):
    """使用doxygen生成API文档"""
    try:
        # 检查是否存在Doxyfile
        doxyfile = os.path.join(project_path, "Doxyfile")
        if not os.path.exists(doxyfile):
            return {"error": "Doxyfile not found in project directory"}
            
        result = subprocess.run(
            ["doxygen", "Doxyfile"],
            cwd=project_path,
            check=True,
            capture_output=True,
            text=True
        )
        return {"status": "success", "output": result.stdout}
    except subprocess.CalledProcessError as e:
        return {"error": str(e), "output": e.stderr}

def generate_sphinx_docs(project_path):
    """使用sphinx生成API文档"""
    try:
        # 检查是否存在conf.py
        conf_py = os.path.join(project_path, "conf.py")
        if not os.path.exists(conf_py):
            return {"error": "conf.py not found in project directory"}
            
        result = subprocess.run(
            ["sphinx-build", "-b", "html", ".", "_build"],
            cwd=project_path,
            check=True,
            capture_output=True,
            text=True
        )
        return {"status": "success", "output": result.stdout}
    except subprocess.CalledProcessError as e:
        return {"error": str(e), "output": e.stderr}

@mcp.tool()
def generate_docs(project_path: str, doc_type: str) -> dict:
    """
    生成API文档
    :param project_path: 项目路径
    :param doc_type: 文档类型 (doxygen|sphinx)
    :return: 生成结果
    """
    if not os.path.exists(project_path):
        return {"error": f"项目路径 {project_path} 不存在"}
    
    if doc_type == "doxygen":
        return generate_doxygen_docs(project_path)
    elif doc_type == "sphinx":
        return generate_sphinx_docs(project_path)
    else:
        return {"error": f"不支持的文档类型: {doc_type}"}

if __name__ == "__main__":
    mcp.run()