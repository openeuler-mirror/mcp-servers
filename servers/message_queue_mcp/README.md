# Message Queue MCP Server

## 功能描述
提供RabbitMQ和Kafka消息队列管理功能，包括：
- 消息队列连接管理
- 消息发布与消费
- 队列/主题创建

## 依赖安装
```bash
yum install -y rabbitmq-server kafka python3-mcp
```

## 使用方法
1. 配置MCP客户端添加此服务器
2. 调用提供的工具方法

## 可用工具
- `connect_rabbitmq`: 连接RabbitMQ服务器
- `connect_kafka`: 连接Kafka服务器
- `publish_message`: 发布消息到队列/主题
- `consume_message`: 从队列/主题消费消息
- `create_queue`: 创建新的队列/主题

## RPM打包
```bash
# 生成spec文件
python3 generate-mcp-spec.py

# 构建RPM包
rpmbuild -ba mcp-servers.spec