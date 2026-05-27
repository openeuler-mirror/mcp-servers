# Message Queue MCP Server

## Function Description

It provides RabbitMQ and Kafka message queue management functions, including:

- Message queue connection management
- Message publishing and consumption
- Queue/Topic creation

## Dependency Installation

```bash
yum install -y rabbitmq-server kafka python3-mcp
```

## Usage

1. Configure the MCP client to add this server.
2. Call the provided tools and methods.

## Available Tools

- `connect_rabbitmq`: Connect to the RabbitMQ server.
- `connect_kafka`: Connect to the Kafka server.
- `publish_message`: Publish messages to a queue/topic.
- `consume_message`: Consume messages from a queue/topic.
- `create_queue`: Create a new queue/topic.

## RPM Packaging

```bash
# Generate a spec file.
python3 generate-mcp-spec.py

# Build an RPM package.
rpmbuild -ba mcp-servers.spec
```
