# 备份管理工具 MCP 服务

## 功能描述
提供文件目录的简单备份、恢复、管理功能，支持自动清理旧备份和压缩存储

## 核心功能
- **目录备份**: 支持目录和文件的压缩备份（tar.gz格式）
- **备份恢复**: 支持从备份文件恢复目录和文件
- **备份管理**: 自动清理旧备份，保留最新的N个备份
- **压缩存储**: 支持tar.gz格式压缩，节省存储空间

## 依赖
- tar (系统自带)
- python3
- uv
- python3-mcp

## 使用方法

### 创建备份
```bash
mcp backup_manager_mcp create_backup /path/to/source
```

**参数说明**:
- `source_path`: 要备份的路径，例如 `/home/user/docs` 或 `/home/user/docs/`

**功能特点**:
- 自动生成带时间戳的备份文件名（例如：`docs_20260223_143022.tar.gz`）
- 自动压缩为 tar.gz 格式
- 备份成功后自动清理旧备份（保留最新的10个）

**返回示例**:
```json
{
  "状态": "成功",
  "备份文件": "/var/backups/mcp/docs_20260223_143022.tar.gz",
  "大小": "12.5 MB"
}
```

### 恢复备份
```bash
mcp backup_manager_mcp restore_backup /var/backups/mcp/docs_20260223_143022.tar.gz /path/to/target
```

**参数说明**:
- `backup_file`: 备份文件路径（从 list_backups 里复制）
- `target_path`: 恢复到哪个位置

**返回示例**:
```json
{
  "状态": "成功",
  "恢复到": "/path/to/target"
}
```

### 查看所有备份
```bash
mcp backup_manager_mcp list_backups
```

**功能特点**:
- 显示所有备份文件的详细信息
- 按时间倒序排列（最新的在最上面）
- 显示文件大小和创建时间

**返回示例**:
```json
{
  "状态": "成功",
  "备份列表": [
    {
      "文件名": "docs_20260223_143022.tar.gz",
      "完整路径": "/var/backups/mcp/docs_20260223_143022.tar.gz",
      "大小": "12.5 MB",
      "创建时间": "2026-02-23 14:30:22"
    },
    {
      "文件名": "docs_20260222_103015.tar.gz",
      "完整路径": "/var/backups/mcp/docs_20260222_103015.tar.gz",
      "大小": "12.3 MB",
      "创建时间": "2026-02-22 10:30:15"
    }
  ]
}
```

## 安装与配置

### 系统依赖

- Python 3.8+
- tar (用于备份/恢复)
- uv (Python包管理器)

### 自动初始化

MCP服务器会在启动时自动创建以下目录：
- `/var/backups/mcp` - 备份文件存储目录
- `/var/log/mcp` - 审计日志目录

**注意**：如果当前用户没有权限创建这些目录，服务器会显示提示信息。此时您需要手动运行以下命令：

```bash
sudo mkdir -p /var/backups/mcp /var/log/mcp
sudo chown -R $USER:$USER /var/backups/mcp /var/log/mcp
```

### 配置说明

备份配置在 `server.py` 文件顶部直接修改：

```python
BACKUP_DIR = "/var/backups/mcp"  # 备份存储目录
MAX_BACKUPS = 10                  # 最多保留几个备份
COMPRESSION = True                # 是否压缩（True=tar.gz，False=tar）
```

**配置参数**:
- `BACKUP_DIR`: 备份文件存储目录（默认: `/var/backups/mcp`）
- `MAX_BACKUPS`: 保留的最大备份数量（默认: 10）
- `COMPRESSION`: 是否压缩备份（默认: True）

## 示例

### 1. 备份项目目录
```bash
# 备份项目目录
mcp backup_manager_mcp create_backup ~/my_project

# 返回结果
{
  "状态": "成功",
  "备份文件": "/var/backups/mcp/my_project_20260223_143022.tar.gz",
  "大小": "45.2 MB"
}
```

### 2. 查看所有备份
```bash
mcp backup_manager_mcp list_backups

# 返回结果
{
  "状态": "成功",
  "备份列表": [
    {
      "文件名": "my_project_20260223_143022.tar.gz",
      "完整路径": "/var/backups/mcp/my_project_20260223_143022.tar.gz",
      "大小": "45.2 MB",
      "创建时间": "2026-02-23 14:30:22"
    }
  ]
}
```

### 3. 恢复项目备份
```bash
mcp backup_manager_mcp restore_backup /var/backups/mcp/my_project_20260223_143022.tar.gz ~/restored_project

# 返回结果
{
  "状态": "成功",
  "恢复到": "/home/user/restored_project"
}
```

### 4. 备份单个文件
```bash
mcp backup_manager_mcp create_backup ~/important_file.txt

# 返回结果
{
  "状态": "成功",
  "备份文件": "/var/backups/mcp/important_file.txt_20260223_143022.tar.gz",
  "大小": "0.5 MB"
}
```

## 特性

- **自动命名**: 自动生成带时间戳的备份文件名
- **压缩存储**: 支持 tar.gz 格式压缩，节省存储空间
- **自动清理**: 创建新备份时自动清理超过限制的旧备份
- **详细信息**: 提供备份大小、创建时间等详细信息
- **简单易用**: 只需提供源路径，其他全部自动处理
- **错误处理**: 完善的错误处理和状态返回

## 工作流程

1. **创建备份**:
   - 检查源路径是否存在
   - 创建备份目录（如果不存在）
   - 生成带时间戳的备份文件名
   - 使用 tar 命令创建压缩备份
   - 自动清理旧备份（保留最新的 MAX_BACKUPS 个）

2. **恢复备份**:
   - 检查备份文件是否存在
   - 创建目标目录（如果不存在）
   - 使用 tar 命令解压备份

3. **查看备份**:
   - 列出备份目录中的所有文件
   - 按时间倒序排列
   - 返回详细的备份信息

## 注意事项

1. **存储空间**: 备份目录需要有足够的存储空间
2. **权限要求**: 默认备份目录 `/var/backups/mcp` 需要适当的权限创建
3. **文件大小**: 大文件备份可能需要较长时间
4. **备份文件**: 备份文件包含敏感信息，请妥善保管
5. **恢复覆盖**: 恢复备份时会覆盖目标目录中的同名文件
6. **路径规范**: 建议使用绝对路径，避免相对路径的问题

## 故障排查

### 问题: 找不到路径
```
{"状态": "失败", "原因": "找不到路径: /path/to/source"}
```
**解决方案**: 检查源路径是否正确，确保路径存在

### 问题: 权限不足
```
PermissionError: [Errno 13] Permission denied
```
**解决方案**: 检查是否有权限访问源路径和备份目录

### 问题: 磁盘空间不足
```
{"状态": "失败", "原因": "No space left on device"}
```
**解决方案**: 清理磁盘空间或调整备份目录到其他位置

### 问题: 还没有备份文件
```
{"状态": "提示", "信息": "还没有备份文件"}
```
**解决方案**: 先使用 create_backup 创建备份

## 技术细节

- **备份格式**: tar.gz (gzip 压缩的 tar 归档)
- **文件命名**: `{basename}_{timestamp}.tar.gz`
- **时间戳格式**: `YYYYMMDD_HHMMSS`
- **清理策略**: 保留最新的 MAX_BACKUPS 个备份，删除旧的
- **压缩级别**: 使用 tar 的默认压缩级别

## 未来改进

- 支持增量备份
- 支持数据库备份
- 支持备份加密
- 支持远程备份存储
- 支持备份验证
- 支持备份计划任务