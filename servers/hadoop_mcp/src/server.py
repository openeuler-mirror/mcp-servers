#!/usr/bin/env python3
"""
Hadoop MCP Server

面向 Hadoop 分布式计算框架的命令行操作 MCP 服务器。
提供 Hadoop 各个组件的服务管理功能。

MCP tools 列表：
- hadoop_datanode_service: 管理 Hadoop DataNode 服务
- hadoop_historyserver_service: 管理 Hadoop HistoryServer 服务  
- hadoop_journalnode_service: 管理 Hadoop JournalNode 服务
- hadoop_namenode_service: 管理 Hadoop NameNode 服务
- hadoop_nodemanager_service: 管理 Hadoop NodeManager 服务
- hadoop_proxyserver_service: 管理 Hadoop ProxyServer 服务
- hadoop_resourcemanager_service: 管理 Hadoop ResourceManager 服务
- hadoop_secondarynamenode_service: 管理 Hadoop SecondaryNameNode 服务
- hadoop_timelineserver_service: 管理 Hadoop TimelineServer 服务
- hadoop_zkfc_service: 管理 Hadoop ZKFC 服务，支持格式化 ZK

所有工具返回统一的 JSON 结构：
{
  "success": bool,      # 命令是否成功执行
  "command": str,       # 实际执行的命令
  "exit_code": int,     # 命令退出码
  "stdout": str,        # 标准输出内容
  "stderr": str         # 标准错误内容
}
"""

from mcp.server.fastmcp import FastMCP, Context
import subprocess
import shlex

mcp = FastMCP("Hadoop MCP Server")

def run_command(command: str) -> dict:
    """执行 shell 命令并返回统一格式的结果"""
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=30
        )
        return {
            "success": result.returncode == 0,
            "command": command,
            "exit_code": result.returncode,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip()
        }
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "command": command,
            "exit_code": -1,
            "stdout": "",
            "stderr": "Command execution timeout"
        }
    except Exception as e:
        return {
            "success": False,
            "command": command,
            "exit_code": -1,
            "stdout": "",
            "stderr": str(e)
        }

@mcp.tool()
def hadoop_datanode_service(action: str) -> dict:
    """
    管理 Hadoop DataNode 服务
    
    参数:
        action: 服务操作，支持 'start', 'stop', 'restart', 'reload', 'status'
    
    返回:
        统一 JSON 结构，包含命令执行结果
    """
    valid_actions = ['start', 'stop', 'restart', 'reload', 'status']
    if action not in valid_actions:
        return {
            "success": False,
            "command": f"systemctl {action} hadoop-datanode.service",
            "exit_code": -1,
            "stdout": "",
            "stderr": f"Invalid action. Must be one of: {', '.join(valid_actions)}"
        }
    
    command = f"systemctl {action} hadoop-datanode.service"
    return run_command(command)

@mcp.tool()
def hadoop_historyserver_service(action: str) -> dict:
    """
    管理 Hadoop HistoryServer 服务
    
    参数:
        action: 服务操作，支持 'start', 'stop', 'restart', 'reload', 'status'
    
    返回:
        统一 JSON 结构，包含命令执行结果
    """
    valid_actions = ['start', 'stop', 'restart', 'reload', 'status']
    if action not in valid_actions:
        return {
            "success": False,
            "command": f"systemctl {action} hadoop-historyserver.service",
            "exit_code": -1,
            "stdout": "",
            "stderr": f"Invalid action. Must be one of: {', '.join(valid_actions)}"
        }
    
    command = f"systemctl {action} hadoop-historyserver.service"
    return run_command(command)

@mcp.tool()
def hadoop_journalnode_service(action: str) -> dict:
    """
    管理 Hadoop JournalNode 服务
    
    参数:
        action: 服务操作，支持 'start', 'stop', 'restart', 'reload', 'status'
    
    返回:
        统一 JSON 结构，包含命令执行结果
    """
    valid_actions = ['start', 'stop', 'restart', 'reload', 'status']
    if action not in valid_actions:
        return {
            "success": False,
            "command": f"systemctl {action} hadoop-journalnode.service",
            "exit_code": -1,
            "stdout": "",
            "stderr": f"Invalid action. Must be one of: {', '.join(valid_actions)}"
        }
    
    command = f"systemctl {action} hadoop-journalnode.service"
    return run_command(command)

@mcp.tool()
def hadoop_namenode_service(action: str) -> dict:
    """
    管理 Hadoop NameNode 服务
    
    参数:
        action: 服务操作，支持 'start', 'stop', 'restart', 'reload', 'status'
    
    返回:
        统一 JSON 结构，包含命令执行结果
    """
    valid_actions = ['start', 'stop', 'restart', 'reload', 'status']
    if action not in valid_actions:
        return {
            "success": False,
            "command": f"systemctl {action} hadoop-namenode.service",
            "exit_code": -1,
            "stdout": "",
            "stderr": f"Invalid action. Must be one of: {', '.join(valid_actions)}"
        }
    
    command = f"systemctl {action} hadoop-namenode.service"
    return run_command(command)

@mcp.tool()
def hadoop_nodemanager_service(action: str) -> dict:
    """
    管理 Hadoop NodeManager 服务
    
    参数:
        action: 服务操作，支持 'start', 'stop', 'restart', 'reload', 'status'
    
    返回:
        统一 JSON 结构，包含命令执行结果
    """
    valid_actions = ['start', 'stop', 'restart', 'reload', 'status']
    if action not in valid_actions:
        return {
            "success": False,
            "command": f"systemctl {action} hadoop-nodemanager.service",
            "exit_code": -1,
            "stdout": "",
            "stderr": f"Invalid action. Must be one of: {', '.join(valid_actions)}"
        }
    
    command = f"systemctl {action} hadoop-nodemanager.service"
    return run_command(command)

@mcp.tool()
def hadoop_proxyserver_service(action: str) -> dict:
    """
    管理 Hadoop ProxyServer 服务
    
    参数:
        action: 服务操作，支持 'start', 'stop', 'restart', 'reload', 'status'
    
    返回:
        统一 JSON 结构，包含命令执行结果
    """
    valid_actions = ['start', 'stop', 'restart', 'reload', 'status']
    if action not in valid_actions:
        return {
            "success": False,
            "command": f"systemctl {action} hadoop-proxyserver.service",
            "exit_code": -1,
            "stdout": "",
            "stderr": f"Invalid action. Must be one of: {', '.join(valid_actions)}"
        }
    
    command = f"systemctl {action} hadoop-proxyserver.service"
    return run_command(command)

@mcp.tool()
def hadoop_resourcemanager_service(action: str) -> dict:
    """
    管理 Hadoop ResourceManager 服务
    
    参数:
        action: 服务操作，支持 'start', 'stop', 'restart', 'reload', 'status'
    
    返回:
        统一 JSON 结构，包含命令执行结果
    """
    valid_actions = ['start', 'stop', 'restart', 'reload', 'status']
    if action not in valid_actions:
        return {
            "success": False,
            "command": f"systemctl {action} hadoop-resourcemanager.service",
            "exit_code": -1,
            "stdout": "",
            "stderr": f"Invalid action. Must be one of: {', '.join(valid_actions)}"
        }
    
    command = f"systemctl {action} hadoop-resourcemanager.service"
    return run_command(command)

@mcp.tool()
def hadoop_secondarynamenode_service(action: str) -> dict:
    """
    管理 Hadoop SecondaryNameNode 服务
    
    参数:
        action: 服务操作，支持 'start', 'stop', 'restart', 'reload', 'status'
    
    返回:
        统一 JSON 结构，包含命令执行结果
    """
    valid_actions = ['start', 'stop', 'restart', 'reload', 'status']
    if action not in valid_actions:
        return {
            "success": False,
            "command": f"systemctl {action} hadoop-secondarynamenode.service",
            "exit_code": -1,
            "stdout": "",
            "stderr": f"Invalid action. Must be one of: {', '.join(valid_actions)}"
        }
    
    command = f"systemctl {action} hadoop-secondarynamenode.service"
    return run_command(command)

@mcp.tool()
def hadoop_timelineserver_service(action: str) -> dict:
    """
    管理 Hadoop TimelineServer 服务
    
    参数:
        action: 服务操作，支持 'start', 'stop', 'restart', 'reload', 'status'
    
    返回:
        统一 JSON 结构，包含命令执行结果
    """
    valid_actions = ['start', 'stop', 'restart', 'reload', 'status']
    if action not in valid_actions:
        return {
            "success": False,
            "command": f"systemctl {action} hadoop-timelineserver.service",
            "exit_code": -1,
            "stdout": "",
            "stderr": f"Invalid action. Must be one of: {', '.join(valid_actions)}"
        }
    
    command = f"systemctl {action} hadoop-timelineserver.service"
    return run_command(command)

@mcp.tool()
def hadoop_zkfc_service(action: str, format_zk: bool = False) -> dict:
    """
    管理 Hadoop ZKFC 服务，支持 ZK 格式化
    
    参数:
        action: 服务操作，支持 'start', 'stop', 'restart', 'reload', 'status'
        format_zk: 是否在启动前格式化 ZK，默认为 False
    
    返回:
        统一 JSON 结构，包含命令执行结果
    """
    valid_actions = ['start', 'stop', 'restart', 'reload', 'status']
    if action not in valid_actions:
        return {
            "success": False,
            "command": f"systemctl {action} hadoop-zkfc.service",
            "exit_code": -1,
            "stdout": "",
            "stderr": f"Invalid action. Must be one of: {', '.join(valid_actions)}"
        }
    
    results = []
    
    # 如果需要格式化 ZK
    if format_zk and action in ['start', 'restart']:
        format_command = "echo -e 'Y\\nY' | hdfs zkfc -formatZK"
        format_result = run_command(format_command)
        results.append(format_result)
    
    # 执行服务操作
    service_command = f"systemctl {action} hadoop-zkfc.service"
    service_result = run_command(service_command)
    results.append(service_result)
    
    # 返回最后一个操作的结果
    return service_result

if __name__ == "__main__":
    mcp.run()