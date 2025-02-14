import sys
import json
import time
import grpc
from concurrent import futures
from kafka import KafkaProducer
import producer_pb2
import producer_pb2_grpc


class ProducerService(producer_pb2_grpc.ProducerServicer):
    def __init__(self, stop_event):
        self.producer = KafkaProducer(
            bootstrap_servers=["broker:9092"],
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        )
        self.stop_event = stop_event

    def SendMessage(self, request, context):
        data = json.loads(request.data)
        future = self.producer.send(request.topic, data)
        try:
            result = future.get(timeout=10)
            return producer_pb2.SendMessageResponse(
                status="success",
                topic=result.topic,
                partition=result.partition,
                offset=result.offset,
            )
        except Exception as excp:
            return producer_pb2.SendMessageResponse(status=f"error: {excp}")


def serve(port, stop_event):
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    producer_pb2_grpc.add_ProducerServicer_to_server(
        ProducerService(stop_event), server
    )
    server.add_insecure_port(f"localhost:{port}")
    server.start()
    print(f"Started producer service on port: {port}")

    try:
        while not stop_event.is_set():
            time.sleep(1)
    finally:
        server.stop(0)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python producer_service.py <port>")
        sys.exit(1)
    port = int(sys.argv[1])
    serve(port)
