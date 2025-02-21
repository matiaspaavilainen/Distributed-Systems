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
CONSUMER_PORT = 30052
PORT = 40404
LOOKUP_UPDATES_TOPIC = "lookup-updates"
DEBUG = True

app = FastAPI()
stop_event = threading.Event()
updates_thread = None

# LOADBALANCING WITH NGINX REVERSE PROXY OR SOMETHING BETTER


class VMLoadBalancer:
    def __init__(self):
        self.vm_nodes = {}  # VM IP -> Set of nodes
        self.vm_weights = {}  # VM IP -> node count
        self.current_vm = 0
        self.lock = threading.Lock()

    def add_node(self, node_info):
        with self.lock:
            vm_ip = node_info.split(":")[0]
            if vm_ip not in self.vm_nodes:
                self.vm_nodes[vm_ip] = set()
                self.vm_weights[vm_ip] = 0
            self.vm_nodes[vm_ip].add(node_info)
            self.vm_weights[vm_ip] += 1
            if DEBUG:
                print(
                    f"Added node to VM {vm_ip}, now has {self.vm_weights[vm_ip]} nodes"
                )

    def get_next_vm_node(self):
        with self.lock:
            if not self.vm_nodes:
                return None, None

            # Get VM with least load
            vm_ips = list(self.vm_nodes.keys())
            vm_ip = vm_ips[self.current_vm]
            self.current_vm = (self.current_vm + 1) % len(vm_ips)

            # Get random node from that VM
            nodes = list(self.vm_nodes[vm_ip])
            if not nodes:
                return None, None

            node_info = nodes[0]
            _, nodeport, _, _ = node_info.split(":")
            return vm_ip, int(nodeport)


load_balancer = VMLoadBalancer()


@app.get("/resource/{query}")
async def handle_request(query: str):
    vm_ip, nodeport = load_balancer.get_next_vm_node()  # or get_vm_for_query(query)
    if not vm_ip:
        raise HTTPException(status_code=503, detail="No nodes available")

    target_url = f"http://{vm_ip}:{nodeport}/resource/{query}"
    if DEBUG:
        print(f"Redirecting to VM {vm_ip}")
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
                            print(f"Updated active nodes: {load_balancer.vm_nodes}")
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
