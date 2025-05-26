# 文件系统修复MCP服务器

## 功能描述
提供文件系统修复功能，支持以下操作：
- 检测和修复损坏的文件系统
- 支持ext2/3/4、xfs等常见文件系统类型
- 支持强制修复和交互式修复模式

## 依赖
- e2fsprogs (提供fsck工具)
- xfsprogs (提供xfs_repair工具)

## 使用方法
```json
{
  "type": "tool",
  "name": "fsck",
  "parameters": {
    "device": "/dev/sda1",
    "fs_type": "ext4",
    "force": true,
    "interactive": false
  }
}
```

## 参数说明
| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| device | string | 是 | 要修复的设备路径(如/dev/sda1) |
| fs_type | string | 否 | 文件系统类型(如ext4,xfs) |
| force | boolean | 否 | 是否强制修复(默认false) |
| interactive | boolean | 否 | 是否交互式修复(默认false) |

## 返回结果
```json
{
  "success": true,
  "output": "修复结果输出",
  "error": "错误信息",
  "exit_code": 0
}
```

## 注意事项
1. 需要root权限执行修复操作
2. 强制修复可能导致数据丢失，请谨慎使用