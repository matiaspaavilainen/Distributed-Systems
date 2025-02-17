import grpc
import time

from grpc_server import data_pb2
from grpc_server import data_pb2_grpc

DEBUG = False


def make_request(stub, name):
    try:
        request = data_pb2.RequestMessage(name=name)
        if DEBUG:
            print(f"Sending request: {request}")
        reply = stub.RequestData(request)
        if DEBUG:
            print(f"Received reply: {reply}")
        return reply
    except grpc.RpcError as e:
        print(f"RPC Error: {e.code()}: {e.details()}")
        return None
    except Exception as e:
        print(f"Error in make_request: {e}")
        return None


def run(query, address, max_retries=3):
    for attempt in range(max_retries):
        try:
            with grpc.insecure_channel(address) as channel:
                try:
                    grpc.channel_ready_future(channel).result(timeout=5)
                except grpc.FutureTimeoutError:
                    print(f"Timeout connecting to {address}")
                    continue

                if DEBUG:
                    print(f"Connected to {address}")
                stub = data_pb2_grpc.RequestServiceStub(channel)
                return make_request(stub, query)
        except Exception as e:
            print(f"Attempt {attempt + 1} failed: {e}")
            if attempt < max_retries - 1:
                time.sleep(1 * (attempt + 1))
    return None
