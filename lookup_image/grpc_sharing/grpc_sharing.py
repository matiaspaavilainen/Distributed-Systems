import json
import grpc
from concurrent import futures
from . import lookup_sharing_pb2, lookup_sharing_pb2_grpc


class LookupServicer(lookup_sharing_pb2_grpc.LookupServicer):
    def __init__(self, collection, vector_clock, update_table_func):
        self.collection = collection
        self.vector_clock = vector_clock
        self.update_table = update_table_func  # Pass the function as dependency

    def ReceivePeerUpdate(self, request, context):
        try:
            data = json.loads(request.data)
            remote_vector_clock = json.loads(request.vector_clock)

            # Update local vector clock
            for node_id, clock in remote_vector_clock.items():
                current = self.vector_clock.clocks.get(node_id, 0)
                if clock > current:
                    self.vector_clock.clocks[node_id] = clock

            # Process update with from_peer flag to prevent loops
            self.update_table(
                data, request.type, from_peer=True
            )  # Use the passed function
            return lookup_sharing_pb2.UpdateResponse(success=True)
        except Exception as e:
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return lookup_sharing_pb2.UpdateResponse(success=False)


def broadcast_to_peers(data, update_type, vector_clock, peer_lookups):
    for peer in peer_lookups:
        try:
            with grpc.insecure_channel(peer) as channel:
                stub = lookup_sharing_pb2_grpc.LookupStub(channel)
                request = lookup_sharing_pb2.UpdateRequest(
                    data=json.dumps(data),
                    type=update_type,
                    vector_clock=json.dumps(vector_clock.clocks),
                )
                stub.ReceivePeerUpdate(request)  # Changed from PropagateUpdate
        except Exception as e:
            print(f"Failed to propagate to peer {peer}: {e}")


def start_grpc_server(collection, vector_clock, port, update_table_func):
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    lookup_sharing_pb2_grpc.add_LookupServicer_to_server(
        LookupServicer(collection, vector_clock, update_table_func), server
    )
    server.add_insecure_port(f"[::]:{port}")
    server.start()
    return server
