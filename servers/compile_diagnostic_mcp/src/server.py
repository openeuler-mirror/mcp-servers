import os
import re
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("编译诊断工具")

# 编译错误正则表达式
GCC_ERROR_REGEX = re.compile(
    r'(?P<file>[^:]+):(?P<line>\d+):(?P<column>\d+): '
    r'(?P<type>error|warning|note): (?P<message>.+)'
)

CLANG_ERROR_REGEX = re.compile(
    r'(?P<file>[^:]+):(?P<line>\d+):(?P<column>\d+): '
    r'(?P<type>error|warning|note): (?P<message>.+)'
)

def parse_compile_log(log_content):
    """解析编译日志内容"""
    errors = []
    warnings = []
    
    for line in log_content.split('\n'):
        # 尝试匹配GCC/Clang错误格式
        match = GCC_ERROR_REGEX.match(line) or CLANG_ERROR_REGEX.match(line)
        if match:
            entry = {
                'file': match.group('file'),
                'line': int(match.group('line')),
                'column': int(match.group('column')),
                'message': match.group('message'),
                'type': match.group('type')
            }
            
            if match.group('type') == 'error':
                errors.append(entry)
            else:
                warnings.append(entry)
    
    return {'errors': errors, 'warnings': warnings}

@mcp.tool()
def analyze_compile_log(log: str) -> dict:
    """
    分析编译日志
    :param log: 编译日志内容或文件路径
    :return: 结构化的错误和警告信息
    """
    # 如果是文件路径，读取文件内容
    if os.path.exists(log):
        with open(log, 'r') as f:
            log_content = f.read()
    else:
        log_content = log
    
    return parse_compile_log(log_content)

if __name__ == "__main__":
    mcp.run()