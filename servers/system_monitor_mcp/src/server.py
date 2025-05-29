from pydantic import Field
from typing import Optional, Dict, List
from mcp.server.fastmcp import FastMCP
import psutil
import argparse
import time
import os
from typing import Any

mcp = FastMCP("systemMonitorMcp")

# 全局配置
global_config = {
    'MONITOR_INTERVAL': 5,
    'CPU_THRESHOLD': 90,
    'MEMORY_THRESHOLD': 85,
    'DISK_THRESHOLD': 90,
    'LOG_DIR': '/var/log/system_monitor'
}

@mcp.tool()
def get_system_stats(
    interval: Optional[float] = Field(default=None, description="监控间隔(秒)，默认使用全局配置")
) -> Dict[str, Any]:
    """获取系统资源使用情况
    
    示例用法:
    1. 获取当前系统资源使用情况
    2. 每2秒获取一次系统资源使用情况
    
    返回:
    {
        "cpu_percent": float,  # CPU使用率(%)
        "memory_percent": float,  # 内存使用率(%)
        "disk_percent": Dict[str, float],  # 各磁盘分区使用率
        "process_count": int  # 进程数量
    }
    """
    interval = interval or global_config['MONITOR_INTERVAL']
    time.sleep(interval)  # 等待指定间隔
    
    return {
        "cpu_percent": psutil.cpu_percent(),
        "memory_percent": psutil.virtual_memory().percent,
        "disk_percent": {part.mountpoint: part.percent 
                        for part in psutil.disk_partitions() 
                        if part.mountpoint},
        "process_count": len(psutil.pids())
    }

@mcp.tool()
def check_thresholds(
    cpu_threshold: Optional[float] = Field(default=None, description="CPU告警阈值(%)"),
    memory_threshold: Optional[float] = Field(default=None, description="内存告警阈值(%)"),
    disk_threshold: Optional[float] = Field(default=None, description="磁盘告警阈值(%)")
) -> Dict[str, Any]:
    """检查系统资源是否超过阈值
    
    示例用法:
    1. 检查系统资源是否超过默认阈值
    2. 检查CPU使用率是否超过95%
    
    返回:
    {
        "cpu_alert": bool,  # CPU是否超过阈值
        "memory_alert": bool,  # 内存是否超过阈值
        "disk_alerts": Dict[str, bool]  # 各磁盘分区是否超过阈值
    }
    """
    stats = get_system_stats(0.1)  # 立即获取状态
    
    cpu_threshold = cpu_threshold or global_config['CPU_THRESHOLD']
    memory_threshold = memory_threshold or global_config['MEMORY_THRESHOLD']
    disk_threshold = disk_threshold or global_config['DISK_THRESHOLD']
    
    return {
        "cpu_alert": stats["cpu_percent"] > cpu_threshold,
        "memory_alert": stats["memory_percent"] > memory_threshold,
        "disk_alerts": {mount: percent > disk_threshold 
                       for mount, percent in stats["disk_percent"].items()}
    }

@mcp.tool()
def list_processes(
    name_filter: Optional[str] = Field(default=None, description="进程名过滤"),
    user_filter: Optional[str] = Field(default=None, description="用户名过滤"),
    limit: int = Field(default=20, description="返回结果数量限制")
) -> List[Dict[str, Any]]:
    """列出系统进程
    
    示例用法:
    1. 列出所有python进程
    2. 列出用户aaa的所有进程
    
    返回:
    [{
        "pid": int,  # 进程ID
        "name": str,  # 进程名
        "username": str,  # 所属用户
        "cpu_percent": float,  # CPU使用率
        "memory_percent": float,  # 内存使用率
        "status": str  # 进程状态
    }, ...]
    """
    processes = []
    for proc in psutil.process_iter(['pid', 'name', 'username', 'cpu_percent', 'memory_percent', 'status']):
        try:
            info = proc.info
            if name_filter and name_filter.lower() not in info['name'].lower():
                continue
            if user_filter and user_filter != info['username']:
                continue
                
            processes.append({
                "pid": info['pid'],
                "name": info['name'],
                "username": info['username'],
                "cpu_percent": info['cpu_percent'],
                "memory_percent": info['memory_percent'],
                "status": info['status']
            })
            
            if len(processes) >= limit:
                break
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
            
    return processes

@mcp.tool()
def manage_process(
    action: str = Field(..., description="操作类型: kill(终止)/suspend(挂起)/resume(恢复)"),
    pid: Optional[int] = Field(default=None, description="进程ID"),
    name: Optional[str] = Field(default=None, description="进程名(模糊匹配)")
) -> Dict[str, Any]:
    """管理进程
    
    示例用法:
    1. 终止PID为1234的进程
    2. 挂起所有python进程
    
    返回:
    {
        "success": bool,  # 操作是否成功
        "message": str,  # 详细信息
        "affected_pids": List[int]  # 受影响的进程ID列表
    }
    """
    if not pid and not name:
        return {"success": False, "message": "必须提供pid或name参数"}
        
    affected_pids = []
    
    try:
        if pid:
            proc = psutil.Process(pid)
            processes = [proc]
        else:
            processes = []
            for proc in psutil.process_iter(['pid', 'name']):
                try:
                    if name.lower() in proc.info['name'].lower():
                        processes.append(psutil.Process(proc.info['pid']))
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
                    
        for proc in processes:
            try:
                if action == "kill":
                    proc.kill()
                elif action == "suspend":
                    proc.suspend()
                elif action == "resume":
                    proc.resume()
                else:
                    return {"success": False, "message": f"无效的操作类型: {action}"}
                    
                affected_pids.append(proc.pid)
            except Exception as e:
                return {"success": False, "message": str(e), "affected_pids": affected_pids}
                
        return {
            "success": True,
            "message": f"成功执行{action}操作",
            "affected_pids": affected_pids
        }
    except Exception as e:
        return {"success": False, "message": str(e), "affected_pids": affected_pids}

def init_config():
    parser = argparse.ArgumentParser()
    parser.add_argument('--MONITOR_INTERVAL', type=float, default=5)
    parser.add_argument('--CPU_THRESHOLD', type=float, default=90)
    parser.add_argument('--MEMORY_THRESHOLD', type=float, default=85)
    parser.add_argument('--DISK_THRESHOLD', type=float, default=90)
    parser.add_argument('--LOG_DIR', default='/var/log/system_monitor')
    
    args = parser.parse_args()
    
    global_config.update({
        'MONITOR_INTERVAL': args.MONITOR_INTERVAL,
        'CPU_THRESHOLD': args.CPU_THRESHOLD,
        'MEMORY_THRESHOLD': args.MEMORY_THRESHOLD,
        'DISK_THRESHOLD': args.DISK_THRESHOLD,
        'LOG_DIR': args.LOG_DIR
    })
    
    # 不再创建日志目录，仅打印日志

if __name__ == "__main__":
    init_config()
    mcp.run()