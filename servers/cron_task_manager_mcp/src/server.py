import subprocess
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("定时任务管理工具")

def run_crontab_command(command: str) -> str:
    """执行crontab命令并返回结果"""
    try:
        result = subprocess.check_output(
            command,
            shell=True,
            stderr=subprocess.STDOUT,
            text=True
        )
        return result or "操作成功"
    except subprocess.CalledProcessError as e:
        return f"操作失败: {e.output}"

@mcp.tool()
def add_cron_job(schedule: str, command: str, user: str = "root") -> str:
    """添加新的cron任务"""
    cron_line = f"{schedule} {command}"
    return run_crontab_command(f'(crontab -u {user} -l 2>/dev/null; echo "{cron_line}") | crontab -u {user} -')

@mcp.tool() 
def remove_cron_job(command_pattern: str, user: str = "root") -> str:
    """删除匹配的cron任务"""
    return run_crontab_command(f'crontab -u {user} -l | grep -v "{command_pattern}" | crontab -u {user} -')

@mcp.tool()
def list_cron_jobs(user: str = "root") -> str:
    """列出所有cron任务"""
    return run_crontab_command(f'crontab -u {user} -l')

@mcp.tool()
def edit_cron_job(old_pattern: str, new_schedule: str, new_command: str, user: str = "root") -> str:
    """编辑现有的cron任务"""
    # 先删除旧任务
    remove_result = remove_cron_job(old_pattern, user)
    if "失败" in remove_result:
        return remove_result
    # 添加新任务
    return add_cron_job(new_schedule, new_command, user)

if __name__ == "__main__":
    mcp.run()