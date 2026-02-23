# 备份管理MCP服务器

## 功能
- 创建文件/目录备份（支持tar.gz压缩）
- 从备份文件恢复数据
- 查看和管理备份列表
- 自动清理旧备份（保留最新N个）
- 完整的审计日志记录

## 使用方法


3. 调用功能：
- 创建备份：`create_backup(source_path)`
- 恢复备份：`restore_backup(backup_file, target_path)`
- 查看备份列表：`list_backups()`

## 示例
```python
# 创建备份
result = create_backup("/home/user/docs")

# 查看所有备份
backups = list_backups()

# 恢复备份
result = restore_backup("/var/backups/mcp/docs_20260223.tar.gz", "/tmp/restore")
```

## 配置说明
在 `src/server.py` 中可修改以下配置：
- `BACKUP_DIR`: 备份存储目录（默认: /var/backups/mcp）
- `MAX_BACKUPS`: 保留最大备份数量（默认: 10）
- `COMPRESSION`: 是否启用压缩（默认: True）
- `ALLOWED_BACKUP_DIRS`: 允许备份的目录白名单
- `ALLOWED_RESTORE_DIRS`: 允许恢复的目录白名单
- `ENABLE_AUDIT_LOG`: 是否启用审计日志（默认: True）

## 注意事项
1. 默认备份目录 `/var/backups/mcp` 需要创建并设置适当权限
2. 审计日志默认存储在 `/var/log/mcp/backup_manager.log`
3. 路径白名单限制确保操作安全
4. 备份文件会自动清理，只保留最新的 MAX_BACKUPS 个
