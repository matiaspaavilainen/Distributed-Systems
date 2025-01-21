from concurrent import futures
import logging
import grpc
import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), "../main_server"))

from main_server import data_pb2
from main_server import data_pb2_grpc

DEBUG = True
PORT = "50053"


def make_request(stub, name):

    name = data_pb2.Request(name=name)
    reply = stub.RequestData(name)
    if DEBUG:
        print("reply: " + str(reply))
    return reply


def run(input):
    # NOTE(gRPC Python Team): .close() is possible on a channel and should be
    # used in circumstances in which the with statement does not fit the needs
    # of the code.
    with grpc.insecure_channel("localhost:" + PORT) as channel:
        stub = data_pb2_grpc.RequestServiceStub(channel)
        print("-------------- Make request --------------")
        return make_request(stub, input)


if __name__ == "__main__":
    logging.basicConfig()
    run()
