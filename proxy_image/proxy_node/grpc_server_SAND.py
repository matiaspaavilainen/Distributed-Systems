from concurrent import futures
import grpc

from grpc_server import data_pb2
from grpc_server import data_pb2_grpc

DEBUG = False


def get_data(db, name):
    """Returns Feature at given location or None."""
    item = db.find_one({"name": name.name})
    if item is not None:
        if DEBUG:
            print("Found item")
        return data_pb2.RequestReply(
            name=item["name"],
            email=item["email"],
            age=item["age"],
            address=data_pb2.Address(
                street=item["address"]["street"],
                city=item["address"]["city"],
                state=item["address"]["state"],
                zipCode=item["address"]["zipCode"],
            ),
            created_at=item["created_at"],
            orders=item["orders"],
            status=item["status"],
            premium=item["premium"],
        )
    return None


class RequestServicer(data_pb2_grpc.RequestServiceServicer):
    def __init__(self, db):
        self.db = db

    def RequestData(self, request, context):
        feature = get_data(self.db, request)
        if feature is None:
            return data_pb2.RequestReply(data="")
        else:
            return feature


def serve(db, port):
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    data_pb2_grpc.add_RequestServiceServicer_to_server(RequestServicer(db), server)
    server.add_insecure_port(f"[::]:{port}")
    server.start()
    print(f"Started gRPC server on port {port}")
    server.wait_for_termination()
