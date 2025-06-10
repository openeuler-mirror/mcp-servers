from mcp.server.fastmcp import FastMCP
import os

# Initialize FastMCP server
mcp = FastMCP("LTO分析工具", log_level="ERROR")

@mcp.tool()
async def show_lto_summary(input_file: str) -> str:
    """显示LTO摘要信息
    
    Args:
        input_file: 输入文件路径
    """
    return "请帮我执行: { " + f"""
lto-dump {input_file} --summary
""" + " }"

@mcp.tool()
async def list_symbols(input_file: str) -> str:
    """列出LTO符号表
    
    Args:
        input_file: 输入文件路径
    """
    return "请帮我执行: { " + f"""
lto-dump {input_file} --symbols
""" + " }"

@mcp.tool()
async def show_ir_code(input_file: str) -> str:
    """显示LTO IR代码
    
    Args:
        input_file: 输入文件路径
    """
    return "请帮我执行: { " + f"""
lto-dump {input_file} --ir
""" + " }"

@mcp.tool()
async def analyze_optimizations(input_file: str) -> str:
    """分析LTO优化信息
    
    Args:
        input_file: 输入文件路径
    """
    return "请帮我执行: { " + f"""
lto-dump {input_file} --optimization-records
""" + " }"

if __name__ == "__main__":
    # Initialize and run the server
    mcp.run(transport='stdio')