#!/usr/bin/env python3
from mcp.server.fastmcp import FastMCP
from pydantic import Field
from typing import Dict, Any, Optional
import logging
import debugpy
import argparse
import os

# 初始化FastMCP实例
mcp = FastMCP("debugAssistantMcp")

# 全局配置
global_config = {
    'LOG_LEVEL': 'INFO',
    'MAX_DEBUG_SESSIONS': 5,
    'DEBUG_TIMEOUT': 3600
}

# 调试会话存储
debug_sessions: Dict[str, Dict] = {}

def init_config():
    """初始化配置"""
    parser = argparse.ArgumentParser()
    parser.add_argument('--LOG_LEVEL', default='INFO')
    parser.add_argument('--MAX_DEBUG_SESSIONS', type=int, default=5)
    parser.add_argument('--DEBUG_TIMEOUT', type=int, default=3600)
    
    args = parser.parse_args()
    
    global_config.update({
        'LOG_LEVEL': args.LOG_LEVEL,
        'MAX_DEBUG_SESSIONS': args.MAX_DEBUG_SESSIONS,
        'DEBUG_TIMEOUT': args.DEBUG_TIMEOUT
    })
    
    # 配置日志
    logging.basicConfig(
        level=getattr(logging, global_config['LOG_LEVEL']),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

@mcp.tool()
def start_debug_session(
    session_id: str = Field(..., description="调试会话ID，必须唯一"),
    port: int = Field(default=5678, description="调试端口，默认为5678"),
    wait_for_client: bool = Field(default=False, description="是否等待客户端连接")
) -> Dict[str, Any]:
    """启动调试会话
    
    示例用法:
    1. 启动一个调试会话，使用默认端口5678
    2. 启动一个调试会话，指定端口为6789并等待客户端连接
    
    注意:
    - 每个会话ID必须唯一
    - 默认最多同时运行5个调试会话(可通过MAX_DEBUG_SESSIONS配置)
    """
    if session_id in debug_sessions:
        return {"status": "error", "message": "Session already exists"}
    
    if len(debug_sessions) >= global_config['MAX_DEBUG_SESSIONS']:
        return {"status": "error", "message": "Maximum sessions reached"}
    
    debugpy.listen(port)
    if wait_for_client:
        debugpy.wait_for_client()
    
    debug_sessions[session_id] = {
        "port": port,
        "status": "waiting" if wait_for_client else "active"
    }
    return {
        "status": "success", 
        "session_id": session_id, 
        "port": port,
        "message": f"Debug session started on port {port}"
    }

@mcp.tool()
def stop_debug_session(
    session_id: str = Field(..., description="要停止的调试会话ID")
) -> Dict[str, Any]:
    """停止调试会话
    
    示例用法:
    1. 停止ID为test_session的调试会话
    """
    if session_id not in debug_sessions:
        return {"status": "error", "message": "Session not found"}
    
    del debug_sessions[session_id]
    return {"status": "success", "session_id": session_id}

@mcp.tool()
def analyze_logs(
    log_data: str = Field(..., description="要分析的日志数据"),
    error_pattern: Optional[str] = Field(default=None, description="自定义错误匹配模式"),
    warning_pattern: Optional[str] = Field(default=None, description="自定义警告匹配模式")
) -> Dict[str, Any]:
    """分析日志数据
    
    示例用法:
    1. 分析给定的日志数据，统计错误和警告数量
    2. 使用自定义模式分析日志中的特定错误
    
    返回:
    - error_count: 错误数量
    - warning_count: 警告数量
    - patterns_found: 匹配到的自定义模式数量
    """
    error_count = log_data.count("ERROR") if not error_pattern else len(
        [line for line in log_data.split('\n') if error_pattern in line]
    )
    warning_count = log_data.count("WARNING") if not warning_pattern else len(
        [line for line in log_data.split('\n') if warning_pattern in line]
    )
    
    result = {
        "error_count": error_count,
        "warning_count": warning_count,
        "analysis": "Log analysis completed"
    }
    
    if error_pattern or warning_pattern:
        result["patterns_found"] = {
            "error_pattern": error_pattern,
            "warning_pattern": warning_pattern,
            "matches": error_count + warning_count
        }
    
    return result

@mcp.tool()
def get_performance_stats(
    detailed: bool = Field(default=False, description="是否返回详细性能数据")
) -> Dict[str, Any]:
    """获取系统性能统计
    
    示例用法:
    1. 获取基本性能统计
    2. 获取详细性能统计
    
    返回:
    - cpu_percent: CPU使用率
    - memory_usage: 内存使用率
    - disk_usage: 磁盘使用率
    - (详细模式下)各进程资源占用
    """
    import psutil
    
    stats = {
        "cpu_percent": psutil.cpu_percent(),
        "memory_usage": psutil.virtual_memory().percent,
        "disk_usage": psutil.disk_usage('/').percent
    }
    
    if detailed:
        stats["processes"] = [
            {
                "pid": p.pid,
                "name": p.name(),
                "cpu_percent": p.cpu_percent(),
                "memory_percent": p.memory_percent()
            }
            for p in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent'])
        ]
    
    return stats

if __name__ == "__main__":
    init_config()
    mcp.run()