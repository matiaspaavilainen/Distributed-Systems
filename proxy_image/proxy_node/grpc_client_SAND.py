import grpc
import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), "../main_server"))

from main_server import data_pb2
from main_server import data_pb2_grpc

DEBUG = True


def make_request(stub, name):
    name = data_pb2.Request(name=name)
    reply = stub.RequestData(name)
    if DEBUG:
        print("reply: " + str(reply))
    return reply


def run(query, port):
    with grpc.insecure_channel(f"main_server:{port}") as channel:
        stub = data_pb2_grpc.RequestServiceStub(channel)
        if DEBUG:
            print(f"-------------- Make request to port {port} --------------")
        return make_request(stub, query)
