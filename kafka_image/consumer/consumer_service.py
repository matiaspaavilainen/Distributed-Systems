import sys
import json
import time
import grpc
from concurrent import futures
from kafka import KafkaConsumer
import consumer_pb2
import consumer_pb2_grpc


class ConsumerService(consumer_pb2_grpc.ConsumerServicer):
    def __init__(self, stop_event):
        self.consumers = {}
        self.stop_event = stop_event

    def get_consumer(self, topic):
        if topic not in self.consumers:
            self.consumers[topic] = KafkaConsumer(
                topic,
                bootstrap_servers=["broker:9092"],
                value_deserializer=lambda v: json.loads(v.decode("utf-8")),
                auto_offset_reset="latest",
                enable_auto_commit=False,
            )
        return self.consumers[topic]

    def GetLatestMessage(self, request, context):
        print("GetLatestMessage called")
        print(f"Request received: {request}")
        topic = request.topic
        consumer = self.get_consumer(topic)
        latest_message = None
        for partition in consumer.assignment():
            consumer.seek_to_end(partition)
        messages = consumer.poll(timeout_ms=1000)
        if not messages:
            for partition in consumer.assignment():
                consumer.seek_to_beginning(partition)
            messages = consumer.poll(timeout_ms=1000)
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
        topic = request.topic
        consumer = self.get_consumer(topic)
        while not self.stop_event.is_set():
            messages = consumer.poll(timeout_ms=1000)
            for tp, msgs in messages.items():
                for message in msgs:
                    yield consumer_pb2.ListenForNewMessagesResponse(
                        data=json.dumps(message.value)
                    )


def serve(port, stop_event):
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    consumer_pb2_grpc.add_ConsumerServicer_to_server(
        ConsumerService(stop_event), server
    )
    server.add_insecure_port(f"localhost:{port}")
    server.start()
    print(f"Started consumer service on port: {port}")

    try:
        while not stop_event.is_set():
            time.sleep(1)
    finally:
        server.stop(0)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python consumer_service.py <port>")
        sys.exit(1)
    port = int(sys.argv[1])
    serve(port)
