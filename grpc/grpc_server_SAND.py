from concurrent import futures
import logging
import math
import time

import grpc
import data_pb2
import data_pb2_grpc
import grpc_server_db

DEBUG = True


def get_data(db, name):
    """Returns Feature at given location or None."""
    for item in db:
        #print(item + " " + name)
        if item == name.name:
            if DEBUG:
                print("Found item")
            return data_pb2.RequestReply(data = db[item])

    return None

class RequestServicer(data_pb2_grpc.RequestServiceServicer):
    def __init__(self):

        self.db = grpc_server_db.read_database()

    def RequestData(self, request, context):
        feature = get_data(self.db, request)
        if feature is None:
            return data_pb2.RequestReply(data="")
        else:
            return feature

def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    data_pb2_grpc.add_RequestServiceServicer_to_server(
        RequestServicer(), server)
    server.add_insecure_port("[::]:50051")
    server.start()
    server.wait_for_termination()

if __name__ == "__main__":
    logging.basicConfig()
    serve()