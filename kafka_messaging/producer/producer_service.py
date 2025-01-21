from concurrent import futures
import grpc
import json
from kafka import KafkaProducer
import producer_pb2
import producer_pb2_grpc


class ProducerService(producer_pb2_grpc.ProducerServicer):
    def __init__(self):
        self.producer = KafkaProducer(
            bootstrap_servers=["localhost:9092"],
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        )

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


def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    producer_pb2_grpc.add_ProducerServicer_to_server(ProducerService(), server)
    server.add_insecure_port("[::]:50051")
    server.start()
    print("Started service")
    server.wait_for_termination()


if __name__ == "__main__":
    serve()
