import sys
import json
import grpc
from concurrent import futures
from kafka import KafkaConsumer
import consumer_pb2
import consumer_pb2_grpc


class ConsumerService(consumer_pb2_grpc.ConsumerServicer):
    def __init__(self, topic):
        self.consumer = KafkaConsumer(
            topic,
            bootstrap_servers=["localhost:9092"],
            value_deserializer=lambda v: json.loads(v.decode("utf-8")),
            auto_offset_reset="latest",
            enable_auto_commit=False,
        )

    def GetLatestMessage(self, request, context):
        latest_message = None
        for partition in self.consumer.assignment():
            self.consumer.seek_to_end(partition)
        messages = self.consumer.poll(timeout_ms=1000)
        if not messages:
            for partition in self.consumer.assignment():
                self.consumer.seek_to_beginning(partition)
            messages = self.consumer.poll(timeout_ms=1000)
        for tp, msgs in messages.items():
            for msg in msgs:
                if latest_message is None or msg.timestamp > latest_message.timestamp:
                    latest_message = msg
        if latest_message:
            return consumer_pb2.GetLatestMessageResponse(
                data=json.dumps(latest_message.value)
            )
        else:
            return consumer_pb2.GetLatestMessageResponse(data="")

    def ListenForNewMessages(self, request, context):
        for message in self.consumer:
            yield consumer_pb2.ListenForNewMessagesResponse(
                data=json.dumps(message.value)
            )


def serve(topic, port):
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    consumer_pb2_grpc.add_ConsumerServicer_to_server(ConsumerService(topic), server)
    server.add_insecure_port(f"[::]:{port}")
    server.start()
    print(f"Started service on topic: {topic} on port: {port}")
    server.wait_for_termination()


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python consumer_service.py <topic> <port>")
        sys.exit(1)
    topic = sys.argv[1]
    port = int(sys.argv[2])
    serve(topic, port)
