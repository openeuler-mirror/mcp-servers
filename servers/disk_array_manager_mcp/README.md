# 磁盘阵列管理MCP服务器

## 功能
- 创建RAID阵列
- 删除RAID阵列  
- 查询RAID状态
- 添加/移除磁盘

## 依赖
- mdadm工具

## 使用示例

```bash
# 创建RAID 1阵列
mcp disk_array_manager_mcp create_raid /dev/md0 raid1 /dev/sda /dev/sdb

# 查看RAID状态
mcp disk_array_manager_mcp raid_status /dev/md0

# 添加磁盘到阵列
mcp disk_array_manager_mcp add_disk /dev/md0 /dev/sdc

# 移除磁盘
mcp disk_array_manager_mcp remove_disk /dev/md0 /dev/sdc
```

## 注意事项
1. 需要root权限执行RAID管理操作
2. 确保已安装mdadm工具
3. 操作前请备份重要数据