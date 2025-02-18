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


class LoadBalancer:
    def __init__(self):
        self.nodes = {}  # Store node:grpc_port mapping
        self.current_index = 0
        self.lock = threading.Lock()

    def add_node(self, node_info):
        with self.lock:
            # node_info format: 'proxy-node-X-internal:GRPC_PORT'
            if node_info not in self.nodes:
                hostname, grpc_port = node_info.split(":")
                grpc_port = int(grpc_port)
                # Convert internal to external service name and calculate HTTP port
                external_hostname = hostname.replace("-internal", "-external")
                http_port = grpc_port + 1
                self.nodes[node_info] = (external_hostname, http_port)
                if DEBUG:
                    print(f"Added node: {external_hostname} with HTTP port {http_port}")

    def remove_node(self, node_info):
        with self.lock:
            if node_info in self.nodes:
                hostname, http_port = self.nodes[node_info]
                if DEBUG:
                    print(f"Removing node: {hostname} with HTTP port {http_port}")
                del self.nodes[node_info]

    def get_next_node(self):
        with self.lock:
            if not self.nodes:
                return None, None
            nodes = list(self.nodes.items())
            _, (hostname, http_port) = nodes[self.current_index]
            self.current_index = (self.current_index + 1) % len(nodes)
            return hostname, http_port


load_balancer = LoadBalancer()


@app.get("/resource/{query}")
async def handle_request(query: str):
    hostname, port = load_balancer.get_next_node()
    if not hostname:
        raise HTTPException(status_code=503, detail="No nodes available")

    # Extract node ID from hostname (e.g., "proxy-node-0-external" -> "0")
    node_id = hostname.split("-")[2]
    target_url = f"http://localhost/node-{node_id}/resource/{query}"
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
                            print(f"Updated active nodes: {load_balancer.nodes}")
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
