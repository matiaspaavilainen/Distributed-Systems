import os
import threading
import time
import grpc
import uvicorn
import json
import signal
from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse
from kafka_messaging.consumer import consumer_pb2, consumer_pb2_grpc

# Constants
CONSUMER_PORT = int(os.getenv("KAFKA_SERVICE_PORT")) + 2
PORT = 40404
LOOKUP_UPDATES_TOPIC = "lookup-updates"
DEBUG = True

app = FastAPI()
stop_event = threading.Event()
updates_thread = None


class VMLoadBalancer:
    def __init__(self):
        self.vm_nodes = {}  # VM IP -> List of nodes (changing from Set to List)
        self.vm_weights = {}  # VM IP -> node count
        self.current_vm = 0
        self.lock = threading.Lock()

    def add_node(self, node_info):
        with self.lock:
            vm_ip = node_info.split(":")[0]
            if vm_ip not in self.vm_nodes:
                self.vm_nodes[vm_ip] = []
                self.vm_weights[vm_ip] = 0

            # Add to list (no need to check for uniqueness)
            self.vm_nodes[vm_ip].append(node_info)
            self.vm_weights[vm_ip] += 1

    def remove_node(self, node_info):
        with self.lock:
            vm_ip = node_info.split(":")[0]
            if vm_ip in self.vm_nodes:
                if node_info in self.vm_nodes[vm_ip]:
                    self.vm_nodes[vm_ip].remove(node_info)  # Remove from list
                    self.vm_weights[vm_ip] -= 1

                # Clean up VM entry if no nodes left
                if not self.vm_nodes[vm_ip]:
                    del self.vm_nodes[vm_ip]
                    del self.vm_weights[vm_ip]

    def get_next_vm_node(self):
        """Simple round-robin between available VMs"""
        with self.lock:
            if not self.vm_nodes:
                return None

            # Get next VM in round-robin fashion
            vm_ips = list(self.vm_nodes.keys())
            vm_ip = vm_ips[self.current_vm]
            self.current_vm = (self.current_vm + 1) % len(vm_ips)

            return vm_ip


load_balancer = VMLoadBalancer()


@app.get("/resource/{query}")
async def handle_request(query: str):
    vm_ip = load_balancer.get_next_vm_node()
    if not vm_ip:
        raise HTTPException(status_code=503, detail="No nodes available")

    target_url = f"http://{vm_ip}:30080/resource/{query}"
    if DEBUG:
        print(f"Redirecting to VM {target_url}")
    return RedirectResponse(url=target_url, status_code=307)


def listen_for_updates():
    channel = grpc.insecure_channel(f"localhost:{CONSUMER_PORT}")
    try:
        stub = consumer_pb2_grpc.ConsumerStub(channel)
        while not stop_event.is_set():
            try:
                for response in stub.ListenForNewMessages(
                    consumer_pb2.ListenForNewMessagesRequest(topic=LOOKUP_UPDATES_TOPIC)
                ):
                    if stop_event.is_set():
                        break
                    try:
                        message = json.loads(response.data)
                        data = message["data"]
                        message_type = message.get("type")
                        if message_type == "I":
                            for address in data:
                                load_balancer.add_node(address)
                        elif message_type == "D":
                            for address in data:
                                load_balancer.remove_node(address)
                        if DEBUG:
                            # Simple output of the raw VM nodes structure
                            print(f"Updated active nodes:")
                            for vm_ip, nodes in load_balancer.vm_nodes.items():
                                print(f"  VM {vm_ip}: {len(nodes)} nodes")
                                for node in nodes:
                                    print(f"    - {node}")
                    except (KeyError, json.JSONDecodeError) as e:
                        print(f"Error processing message: {e}")
            except grpc.RpcError as e:
                print(f"gRPC error: {e}")
                if e.code() == grpc.StatusCode.UNAVAILABLE:
                    break
    finally:
        channel.close()


def shutdown_gracefully(*args):
    print("Shutting down gracefully...")
    stop_event.set()
    # Give the thread a moment to clean up
    if updates_thread.is_alive():
        updates_thread.join(timeout=2)
    print("Shutdown complete.")
    os._exit(0)


def main():
    global updates_thread

    signal.signal(signal.SIGINT, shutdown_gracefully)
    signal.signal(signal.SIGTERM, shutdown_gracefully)

    time.sleep(2)  # wait for kafka to start just in case

    # Start the updates listener in a separate thread
    updates_thread = threading.Thread(target=listen_for_updates)
    updates_thread.daemon = True  # Thread will exit when main thread exits
    updates_thread.start()

    print("Starting gateway server...")
    if DEBUG:
        print(f"Listening for updates on port {CONSUMER_PORT}")
        print(f"HTTP server running on port {PORT}")

    # Start FastAPI server
    uvicorn.run(app, host="0.0.0.0", port=PORT)


if __name__ == "__main__":
    main()
