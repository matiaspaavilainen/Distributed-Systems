from concurrent import futures
import logging
import math
import time

import grpc
import data_pb2
import data_pb2_grpc
import grpc_server_db

DEBUG = True
PORT = "50051"

def make_request(stub, name):
    
    name = data_pb2.Request(name = name) 
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