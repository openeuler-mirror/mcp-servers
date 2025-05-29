import difflib
import subprocess
import json
import yaml
import configparser
from pathlib import Path
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("系统配置迁移工具")

@mcp.tool()
def compare_configs(source: str, target: str) -> str:
    """比较两个配置文件的差异"""
    try:
        with open(source) as f1, open(target) as f2:
            diff = difflib.unified_diff(
                f1.readlines(),
                f2.readlines(),
                fromfile=source,
                tofile=target
            )
        return ''.join(diff)
    except Exception as e:
        return f"比较失败: {str(e)}"

@mcp.tool()
def sync_configs(source: str, target: str, dry_run: bool = True) -> str:
    """同步配置文件"""
    try:
        cmd = ['rsync', '-avz', '--dry-run' if dry_run else '', source, target]
        result = subprocess.run(
            [arg for arg in cmd if arg],
            capture_output=True,
            text=True
        )
        return result.stdout if result.returncode == 0 else result.stderr
    except Exception as e:
        return f"同步失败: {str(e)}"

@mcp.tool()
def parse_config(file_path: str) -> str:
    """解析配置文件(支持JSON/YAML/INI)"""
    path = Path(file_path)
    if not path.exists():
        return "文件不存在"
    
    try:
        if path.suffix == '.json':
            with open(path) as f:
                return json.dumps(json.load(f), indent=2)
        elif path.suffix in ('.yaml', '.yml'):
            with open(path) as f:
                return yaml.dump(yaml.safe_load(f))
        elif path.suffix == '.ini':
            config = configparser.ConfigParser()
            config.read(path)
            return '\n'.join([f"[{section}]\n{dict(config[section])}" 
                           for section in config.sections()])
        else:
            return "不支持的格式"
    except Exception as e:
        return f"解析失败: {str(e)}"

if __name__ == "__main__":
    mcp.run()