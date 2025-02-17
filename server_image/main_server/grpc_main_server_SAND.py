from concurrent import futures
import logging
import socket
import grpc
import data_pb2
import data_pb2_grpc
import grpc_main_server_db

DEBUG = False


def get_data(db, name):
    """Returns Feature at given location or None."""
    if name.name in db:
        item = db[name.name]
        if DEBUG:
            print(f"Found item: {item}")
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
            created_at=item["created_at"].isoformat(),
            orders=item["orders"],
            status=item["status"],
            premium=item["premium"],
        )

    if DEBUG:
        print(f"Item not found: {name.name}")
    return None


class RequestServicer(data_pb2_grpc.RequestServiceServicer):
    def __init__(self):
        if DEBUG:
            print("Initializing RequestServicer")
        self.db = grpc_main_server_db.mongo_read_database()
        if DEBUG:
            print(f"Loaded database: {self.db}")

    def RequestData(self, request, context):
        if DEBUG:
            print(f"Received request for: {request.name}")
        feature = get_data(self.db, request)
        if feature is None:
            if DEBUG:
                print("No data found, returning empty reply")
            return data_pb2.RequestReply(data="")
        return feature


def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    data_pb2_grpc.add_RequestServiceServicer_to_server(RequestServicer(), server)
    server.add_insecure_port("[::]:40002")
    server.start()
    print(f"Started service at: {socket.gethostname()}:40002")
    server.wait_for_termination()


if __name__ == "__main__":
    logging.basicConfig()
    serve()
