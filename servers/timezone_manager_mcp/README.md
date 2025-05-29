# Timezone Manager MCP Server

## 功能描述
提供系统时区管理的MCP工具，包括：
- 获取当前时区
- 设置新时区
- 列出可用时区

## 依赖
- tzdata
- python3
- fastapi
- uvicorn

## API接口

### 获取当前时区
`POST /get_timezone`
返回当前系统时区

### 设置新时区
`POST /set_timezone`
参数:
- timezone: 要设置的时区名称 (如"Asia/Shanghai")

### 列出可用时区
`POST /list_timezones`
返回所有可用时区列表

## 使用方法
1. 确保已安装依赖
2. 运行服务器:
```bash
uvicorn server:app --reload