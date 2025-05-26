# 入侵检测系统MCP服务器

基于aide工具实现的入侵检测系统MCP服务器，提供系统文件完整性检查和入侵检测功能。

## 功能

- 检查aide安装状态
- 初始化aide数据库
- 执行系统扫描
- 更新aide数据库
- 查看扫描结果
- 配置IDS规则

## 使用说明

### 1. 安装依赖

```bash
yum install aide
```

### 2. 初始化aide数据库

首次使用前需要初始化数据库：

```bash
aide --init
```

### 3. 使用MCP功能

通过MCP客户端调用以下功能：

- `check_aide_installed`: 检查aide是否安装
- `initialize_aide`: 初始化aide数据库
- `perform_scan`: 执行扫描
- `update_aide_db`: 更新数据库
- `get_scan_results`: 获取扫描结果
- `configure_rule`: 配置IDS规则

## 示例

```json
{
  "tool": "perform_scan",
  "args": {}
}
```

## RPM打包

本MCP服务器已配置RPM打包支持，可使用项目中的打包脚本构建RPM包。