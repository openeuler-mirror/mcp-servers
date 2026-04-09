from pydantic import Field
from typing import Optional, List, Dict, Any
from mcp.server.fastmcp import FastMCP
import os
import subprocess
import json
import re

mcp = FastMCP("middlewareManagerMcp")

@mcp.tool()
def list_middleware() -> str:
    """列出系统中常见的中间件服务及其状态"""
    try:
        middleware_list = [
            "redis",
            "kafka",
            "rabbitmq",
            "mysql",
            "postgresql",
            "mongodb",
            "elasticsearch",
            "nginx",
            "apache2",
            "memcached"
        ]
        
        result = []
        for middleware in middleware_list:
            status = get_middleware_status_internal(middleware)
            result.append(f"{middleware}: {status}")
        
        return "已安装的中间件及其状态:\n" + "\n".join(result)
    except Exception as e:
        return f"错误: {str(e)}"

@mcp.tool()
def get_middleware_status(middleware_name: str = Field(description="中间件名称")) -> str:
    """获取指定中间件的状态"""
    try:
        status = get_middleware_status_internal(middleware_name)
        return f"{middleware_name} 状态: {status}"
    except Exception as e:
        return f"错误: {str(e)}"

@mcp.tool()
def start_middleware(middleware_name: str = Field(description="中间件名称")) -> str:
    """启动指定的中间件服务"""
    try:
        if os.name == 'nt':
            # Windows系统
            subprocess.run(["net", "start", middleware_name], check=True)
        else:
            # Linux系统
            subprocess.run(["sudo", "systemctl", "start", middleware_name], check=True)
        return f"成功启动 {middleware_name} 服务"
    except subprocess.CalledProcessError as e:
        return f"启动 {middleware_name} 服务失败: {str(e)}"
    except Exception as e:
        return f"错误: {str(e)}"

@mcp.tool()
def stop_middleware(middleware_name: str = Field(description="中间件名称")) -> str:
    """停止指定的中间件服务"""
    try:
        if os.name == 'nt':
            # Windows系统
            subprocess.run(["net", "stop", middleware_name], check=True)
        else:
            # Linux系统
            subprocess.run(["sudo", "systemctl", "stop", middleware_name], check=True)
        return f"成功停止 {middleware_name} 服务"
    except subprocess.CalledProcessError as e:
        return f"停止 {middleware_name} 服务失败: {str(e)}"
    except Exception as e:
        return f"错误: {str(e)}"

@mcp.tool()
def restart_middleware(middleware_name: str = Field(description="中间件名称")) -> str:
    """重启指定的中间件服务"""
    try:
        if os.name == 'nt':
            # Windows系统
            subprocess.run(["net", "stop", middleware_name], check=True)
            subprocess.run(["net", "start", middleware_name], check=True)
        else:
            # Linux系统
            subprocess.run(["sudo", "systemctl", "restart", middleware_name], check=True)
        return f"成功重启 {middleware_name} 服务"
    except subprocess.CalledProcessError as e:
        return f"重启 {middleware_name} 服务失败: {str(e)}"
    except Exception as e:
        return f"错误: {str(e)}"

@mcp.tool()
def get_middleware_info(middleware_name: str = Field(description="中间件名称")) -> str:
    """获取指定中间件的详细信息，包括版本、配置文件位置等"""
    try:
        info = {}
        
        # 获取版本信息
        version = get_middleware_version(middleware_name)
        if version:
            info["version"] = version
        
        # 获取配置文件位置
        config_path = get_middleware_config_path(middleware_name)
        if config_path:
            info["config_path"] = config_path
        
        # 获取状态信息
        status = get_middleware_status_internal(middleware_name)
        info["status"] = status
        
        return json.dumps(info, indent=2, ensure_ascii=False)
    except Exception as e:
        return f"错误: {str(e)}"

@mcp.tool()
def view_middleware_config(middleware_name: str = Field(description="中间件名称"), config_path: Optional[str] = Field(default=None, description="配置文件路径（可选）")) -> str:
    """查看中间件的配置文件内容"""
    try:
        if not config_path:
            config_path = get_middleware_config_path(middleware_name)
            if not config_path:
                return f"无法找到 {middleware_name} 的配置文件路径"
        
        if not os.path.exists(config_path):
            return f"配置文件不存在: {config_path}"
        
        with open(config_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        
        return f"{middleware_name} 配置文件内容:\n{content}"
    except Exception as e:
        return f"错误: {str(e)}"

@mcp.tool()
def get_middleware_logs(middleware_name: str = Field(description="中间件名称"), lines: int = Field(default=50, description="要查看的日志行数")) -> str:
    """查看中间件的日志文件"""
    try:
        log_path = get_middleware_log_path(middleware_name)
        if not log_path:
            return f"无法找到 {middleware_name} 的日志文件路径"
        
        if not os.path.exists(log_path):
            return f"日志文件不存在: {log_path}"
        
        with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines_list = f.readlines()
        
        # 取最后lines行
        recent_lines = lines_list[-lines:]
        content = ''.join(recent_lines)
        
        return f"{middleware_name} 最近 {lines} 行日志:\n{content}"
    except Exception as e:
        return f"错误: {str(e)}"

# 内部辅助函数
def get_middleware_status_internal(middleware_name: str) -> str:
    """获取中间件状态的内部函数"""
    try:
        if os.name == 'nt':
            # Windows系统
            result = subprocess.run(["sc", "query", middleware_name], capture_output=True, text=True)
            if "RUNNING" in result.stdout:
                return "运行中"
            elif "STOPPED" in result.stdout:
                return "已停止"
            else:
                return "未知状态"
        else:
            # Linux系统
            result = subprocess.run(["systemctl", "is-active", middleware_name], capture_output=True, text=True)
            if result.returncode == 0 and "active" in result.stdout:
                return "运行中"
            else:
                return "已停止"
    except Exception:
        return "未安装"

def get_middleware_version(middleware_name: str) -> Optional[str]:
    """获取中间件版本信息"""
    version_commands = {
        "redis": ["redis-server", "--version"],
        "kafka": ["kafka-server-start.sh", "--version"],
        "rabbitmq": ["rabbitmqctl", "version"],
        "mysql": ["mysql", "--version"],
        "postgresql": ["psql", "--version"],
        "mongodb": ["mongod", "--version"],
        "elasticsearch": ["elasticsearch", "--version"],
        "nginx": ["nginx", "-v"],
        "apache2": ["apache2", "-v"],
        "memcached": ["memcached", "-V"]
    }
    
    if middleware_name not in version_commands:
        return None
    
    try:
        result = subprocess.run(version_commands[middleware_name], capture_output=True, text=True)
        if result.returncode == 0:
            # 提取版本号
            output = result.stdout or result.stderr
            version_match = re.search(r'\d+\.\d+\.\d+', output)
            if version_match:
                return version_match.group(0)
            return output.strip()
    except Exception:
        pass
    
    return None

def get_middleware_config_path(middleware_name: str) -> Optional[str]:
    """获取中间件配置文件路径"""
    config_paths = {
        "redis": "/etc/redis/redis.conf",
        "kafka": "/etc/kafka/server.properties",
        "rabbitmq": "/etc/rabbitmq/rabbitmq.conf",
        "mysql": "/etc/mysql/my.cnf",
        "postgresql": "/etc/postgresql/main/postgresql.conf",
        "mongodb": "/etc/mongod.conf",
        "elasticsearch": "/etc/elasticsearch/elasticsearch.yml",
        "nginx": "/etc/nginx/nginx.conf",
        "apache2": "/etc/apache2/apache2.conf",
        "memcached": "/etc/memcached.conf"
    }
    
    return config_paths.get(middleware_name)

def get_middleware_log_path(middleware_name: str) -> Optional[str]:
    """获取中间件日志文件路径"""
    log_paths = {
        "redis": "/var/log/redis/redis-server.log",
        "kafka": "/var/log/kafka/server.log",
        "rabbitmq": "/var/log/rabbitmq/rabbit@localhost.log",
        "mysql": "/var/log/mysql/error.log",
        "postgresql": "/var/log/postgresql/postgresql-13-main.log",
        "mongodb": "/var/log/mongodb/mongod.log",
        "elasticsearch": "/var/log/elasticsearch/elasticsearch.log",
        "nginx": "/var/log/nginx/error.log",
        "apache2": "/var/log/apache2/error.log",
        "memcached": "/var/log/memcached.log"
    }
    
    return log_paths.get(middleware_name)

if __name__ == "__main__":
    mcp.run()