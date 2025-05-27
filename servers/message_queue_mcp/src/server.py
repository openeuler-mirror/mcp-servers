import pika
from kafka import KafkaProducer, KafkaConsumer
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("Message Queue Tool")

class MessageQueueManager:
    @staticmethod
    def connect_rabbitmq(host: str, port: int = 5672, 
                       username: str = "guest", password: str = "guest",
                       vhost: str = "/") -> pika.BlockingConnection:
        """Establish RabbitMQ connection"""
        credentials = pika.PlainCredentials(username, password)
        parameters = pika.ConnectionParameters(
            host=host,
            port=port,
            virtual_host=vhost,
            credentials=credentials
        )
        return pika.BlockingConnection(parameters)

    @staticmethod
    def connect_kafka(bootstrap_servers: str, client_id: str = "mcp-client"):
        """Create Kafka producer/consumer connection"""
        return {
            "producer": KafkaProducer(
                bootstrap_servers=bootstrap_servers,
                client_id=client_id
            ),
            "consumer": None  # Consumer created per topic
        }

    @staticmethod
    def publish_message(queue_type: str, queue_name: str, 
                       message: str, properties: dict = None):
        """Publish message to queue/topic"""
        if queue_type == "rabbitmq":
            conn = MessageQueueManager.connect_rabbitmq(**properties)
            channel = conn.channel()
            channel.basic_publish(
                exchange='',
                routing_key=queue_name,
                body=message
            )
            conn.close()
            return f"Message published to RabbitMQ queue: {queue_name}"
        
        elif queue_type == "kafka":
            producer = MessageQueueManager.connect_kafka(
                properties["bootstrap_servers"],
                properties.get("client_id", "mcp-client")
            )["producer"]
            producer.send(queue_name, value=message.encode('utf-8'))
            return f"Message published to Kafka topic: {queue_name}"
        
        return "Invalid queue type"

    @staticmethod
    def consume_message(queue_type: str, queue_name: str, 
                       auto_ack: bool = False, properties: dict = None):
        """Consume message from queue/topic"""
        if queue_type == "rabbitmq":
            conn = MessageQueueManager.connect_rabbitmq(**properties)
            channel = conn.channel()
            method_frame, _, body = channel.basic_get(queue_name, auto_ack=auto_ack)
            if method_frame:
                return body.decode('utf-8')
            return "No messages in queue"
        
        elif queue_type == "kafka":
            consumer = KafkaConsumer(
                queue_name,
                bootstrap_servers=properties["bootstrap_servers"],
                auto_offset_reset='earliest',
                enable_auto_commit=auto_ack
            )
            for msg in consumer:
                return msg.value.decode('utf-8')
            return "No messages in topic"
        
        return "Invalid queue type"

    @staticmethod
    def create_queue(queue_type: str, queue_name: str, 
                    durable: bool = True, properties: dict = None):
        """Create new queue/topic"""
        if queue_type == "rabbitmq":
            conn = MessageQueueManager.connect_rabbitmq(**properties)
            channel = conn.channel()
            channel.queue_declare(queue=queue_name, durable=durable)
            conn.close()
            return f"RabbitMQ queue created: {queue_name}"
        
        elif queue_type == "kafka":
            # Kafka topics are automatically created on first message
            return f"Kafka topic will be created on first publish: {queue_name}"
        
        return "Invalid queue type"

# Register tools
@mcp.tool()
def connect_rabbitmq(host: str, port: int = 5672, 
                    username: str = "guest", password: str = "guest",
                    vhost: str = "/") -> str:
    """Connect to RabbitMQ server"""
    try:
        conn = MessageQueueManager.connect_rabbitmq(host, port, username, password, vhost)
        conn.close()
        return "RabbitMQ connection established successfully"
    except Exception as e:
        return f"RabbitMQ connection failed: {e}"

@mcp.tool()
def connect_kafka(bootstrap_servers: str, client_id: str = "mcp-client") -> str:
    """Connect to Kafka server"""
    try:
        MessageQueueManager.connect_kafka(bootstrap_servers, client_id)
        return "Kafka connection established successfully"
    except Exception as e:
        return f"Kafka connection failed: {e}"

@mcp.tool()
def publish_message(queue_type: str, queue_name: str, 
                   message: str, properties: dict = None) -> str:
    """Publish message to queue/topic"""
    return MessageQueueManager.publish_message(queue_type, queue_name, message, properties or {})

@mcp.tool()
def consume_message(queue_type: str, queue_name: str, 
                   auto_ack: bool = False, properties: dict = None) -> str:
    """Consume message from queue/topic"""
    return MessageQueueManager.consume_message(queue_type, queue_name, auto_ack, properties or {})

@mcp.tool()
def create_queue(queue_type: str, queue_name: str, 
                durable: bool = True, properties: dict = None) -> str:
    """Create new queue/topic"""
    return MessageQueueManager.create_queue(queue_type, queue_name, durable, properties or {})

if __name__ == "__main__":
    mcp.run()