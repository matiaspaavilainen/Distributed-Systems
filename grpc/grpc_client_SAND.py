from concurrent import futures
import logging
import math
import time

import grpc
import data_pb2
import data_pb2_grpc
import grpc_server_db

def make_request(stub):
    
    name = data_pb2.Request(name = input("Enter name: ") )
    reply = stub.RequestData(name)
    print(reply)
    return reply

def run():
    # NOTE(gRPC Python Team): .close() is possible on a channel and should be
    # used in circumstances in which the with statement does not fit the needs
    # of the code.
    with grpc.insecure_channel("localhost:50051") as channel:
        stub = data_pb2_grpc.RequestServiceStub(channel)
        print("-------------- Make request --------------")
        make_request(stub)
if __name__ == "__main__":
    logging.basicConfig()
    run()