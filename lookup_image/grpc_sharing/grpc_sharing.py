import json
import threading
import time
import grpc
from concurrent import futures
from concurrent.futures import ThreadPoolExecutor
import socket

from . import lookup_sharing_pb2, lookup_sharing_pb2_grpc


class LookupServicer(lookup_sharing_pb2_grpc.LookupSharingServicer):
    def __init__(self, collection, vector_clock, update_table_func):
        self.collection = collection
        self.vector_clock = vector_clock
        self.update_table = update_table_func

    def ReceivePeerUpdate(self, request, context):
        try:
            start_time = time.time()
            data = json.loads(request.data)
            remote_vector_clock = json.loads(request.vector_clock)
            print(
                f"Received peer update: type={request.type}, data length={len(str(data))}"
            )

            # Update local vector clock using the remote one
            for node_id, remote_clock in remote_vector_clock.items():
                local_clock = self.vector_clock.clocks.get(node_id, 0)
                # Take the maximum value for each node
                if remote_clock > local_clock:
                    self.vector_clock.clocks[node_id] = remote_clock

            # Process update
            self.update_table(data, request.type, from_peer=True)

            # Log processing time
            elapsed = time.time() - start_time
            print(f"Processed peer update in {elapsed:.4f} seconds")

            return lookup_sharing_pb2.UpdateResponse(success=True)
        except Exception as e:
            print(f"Error in ReceivePeerUpdate: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return lookup_sharing_pb2.UpdateResponse(success=False)


# Create a global connection pool
connection_pool = {}
connection_lock = threading.Lock()


def get_channel(peer):
    """Gets or creates a gRPC channel with DNS pre-warming"""
    with connection_lock:
        if peer not in connection_pool:
            # Pre-warm DNS resolution
            try:
                host = peer.split(":")[0]
                port = int(peer.split(":")[1])
                print(f"Pre-warming DNS for {host}:{port}...")
                socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_STREAM)
            except Exception as e:
                print(f"DNS pre-warming failed for {peer}: {e}")

            # Create channel
            channel = grpc.insecure_channel(peer)
            connection_pool[peer] = channel
        return connection_pool[peer]


def broadcast_to_peers(data, update_type, vector_clock, peer_lookups):
    """Broadcast updates to peers with better timing and error handling"""

    def send_to_peer(peer):
        # Progressive retry with increasing timeouts
        timeouts = [5, 15, 30]  # Increased timeouts

        for attempt, timeout in enumerate(timeouts):
            try:
                # Use connection pool for efficiency
                channel = get_channel(peer)
                stub = lookup_sharing_pb2_grpc.LookupSharingStub(channel)
                request = lookup_sharing_pb2.UpdateRequest(
                    data=json.dumps(data),
                    type=update_type,
                    vector_clock=json.dumps(vector_clock.clocks),
                )

                print(
                    f"Sending update to {peer} (attempt {attempt+1}/{len(timeouts)}, timeout={timeout}s)"
                )
                stub.ReceivePeerUpdate(request, timeout=timeout)
                print(f"✓ Successfully sent update to {peer}")
                return  # Success
            except grpc.RpcError as e:
                status_code = e.code()
                print(f"gRPC error to {peer}: {status_code} - {e.details()}")
                time.sleep(2)  # Slightly longer delay between retries
            except Exception as e:
                print(f"Error sending to {peer}: {str(e)[:100]}")
                time.sleep(2)

        print(f"⚠ Failed to reach {peer} after {len(timeouts)} attempts")

    # Use thread pool with a reasonable concurrency limit
    with ThreadPoolExecutor(max_workers=min(3, len(peer_lookups))) as executor:
        for peer in peer_lookups:
            # Skip self-connections to avoid unnecessary traffic
            if socket.gethostname() in peer:
                continue
            executor.submit(send_to_peer, peer)


def start_grpc_server_threaded(collection, vector_clock, port, update_table_func):
    """Start the gRPC server with more workers"""

    def run_server():
        # Increase max_workers from 10 to 20
        server = grpc.server(futures.ThreadPoolExecutor(max_workers=20))
        lookup_sharing_pb2_grpc.add_LookupSharingServicer_to_server(
            LookupServicer(collection, vector_clock, update_table_func), server
        )
        server.add_insecure_port(f"[::]:{port}")
        server.start()
        print(f"gRPC server started on port {port}")
        server.wait_for_termination()

    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()
    return server_thread
