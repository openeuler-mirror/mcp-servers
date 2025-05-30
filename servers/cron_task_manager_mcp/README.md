# 定时任务管理MCP服务器

## 功能描述
提供管理cron定时任务的MCP工具，包括添加、删除、列出和编辑cron任务。

## 依赖
- cronie
- python3
- python3-mcp
- uv

## 可用工具

### add_cron_job
添加新的cron任务

参数:
- schedule: cron时间表达式(如"* * * * *")
- command: 要执行的命令
- user: 用户名(默认为root)

### remove_cron_job 
删除匹配的cron任务

参数:
- command_pattern: 要删除的命令模式
- user: 用户名(默认为root)

### list_cron_jobs
列出所有cron任务

参数:
- user: 用户名(默认为root)

### edit_cron_job
编辑现有的cron任务

参数:
- old_pattern: 要替换的旧命令模式
- new_schedule: 新的cron时间表达式
- new_command: 新的命令
- user: 用户名(默认为root)

## 示例
```python
from mcp.client import MCPClient

client = MCPClient()
# 添加每天凌晨3点执行的备份任务
client.cron_task_manager_mcp.add_cron_job(
    "0 3 * * *",
    "/usr/bin/backup.sh"
)
# 列出所有任务
print(client.cron_task_manager_mcp.list_cron_jobs())