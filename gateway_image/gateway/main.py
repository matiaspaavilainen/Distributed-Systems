import sys
import os
import threading
import time
import grpc
import uvicorn
import json
import signal
import subprocess
from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse

# Add paths
sys.path.append(os.path.join(os.path.dirname(__file__), "../kafka_messaging/consumer"))
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from kafka_messaging.consumer import consumer_pb2, consumer_pb2_grpc

# Constants
CONSUMER_PORT = 40003
PORT = 40404
EXTERNAL_HOST = os.getenv("EXTERNAL_HOST", "localhost")
LOOKUP_UPDATES_TOPIC = "lookup-updates"
DEBUG = True

# Global variables
app = FastAPI()
active_nodes = []
lock = threading.Lock()
stop_event = threading.Event()
kafka_consumer_process = None
fastapi_thread = None


def start_kafka_consumer_service(port):
    consumer_service_path = os.path.join(
        os.path.dirname(__file__), "../kafka_messaging/consumer/consumer_service.py"
    )
    return subprocess.Popen(
        [
            "python",
            consumer_service_path,
            str(port),
        ],
        preexec_fn=os.setsid,
    )


def listen_for_updates():
    # Kafka localhost
    with grpc.insecure_channel(f"localhost:{CONSUMER_PORT}") as channel:
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
                            with lock:
                                for address in data:
                                    if address not in active_nodes:
                                        active_nodes.append(address)
                        elif message_type == "D":
                            with lock:
                                for address in data:
                                    if address in active_nodes:
                                        active_nodes.remove(address)
                        if DEBUG:
                            print(f"Updated active nodes: {active_nodes}")
                    except (KeyError, json.JSONDecodeError) as e:
                        print(f"Error processing message: {e}")
            except grpc.RpcError as e:
                if e.code() == grpc.StatusCode.UNAVAILABLE:
                    print("gRPC server unavailable, shutting down listener.")
                    break
                else:
                    print(f"gRPC error: {e}")
                    break


@app.get("/query/{query}")
async def redirect_request(query: str):
    with lock:
        if not active_nodes:
            raise HTTPException(status_code=503, detail="No active nodes available")
        node_address = active_nodes.pop(0)
        active_nodes.append(node_address)

    port = str(node_address).split(":")[-1]
    redirect_port = int(port) + 1

    # Build complete URL with http:// prefix
    redirect_url = f"http://{EXTERNAL_HOST}:{redirect_port}/resource/{query}"
    print("Redirecting to:", redirect_url)

    return RedirectResponse(url=redirect_url)


def start_fastapi_server():
    uvicorn.run(app, host="0.0.0.0", port=PORT)


def shutdown_gracefully(*args):
    print("Shutting down gracefully...")
    stop_event.set()

    try:
        kafka_consumer_process.terminate()
        kafka_consumer_process.wait(timeout=5)
    except Exception as e:
        print(f"Error terminating Kafka consumer process: {e}")

    try:
        if fastapi_thread.is_alive():
            fastapi_thread.join(timeout=5)
    except Exception as e:
        print(f"Error joining FastAPI thread: {e}")

    print("Shutdown complete.")
    os._exit(
        0
    )  # Forcefully exit the process to ensure the terminal returns to a usable state


def main():
    global kafka_consumer_process, fastapi_thread
    try:
        # Start the Kafka consumer service
        kafka_consumer_process = start_kafka_consumer_service(CONSUMER_PORT)

        time.sleep(3)

        # Start the FastAPI server in a separate thread
        fastapi_thread = threading.Thread(target=start_fastapi_server)
        fastapi_thread.start()

        # Register signal handlers for SIGINT and SIGTERM
        signal.signal(signal.SIGINT, shutdown_gracefully)
        signal.signal(signal.SIGTERM, shutdown_gracefully)

        # Listen for updates from the lookup-updates topic
        listen_for_updates()

        # Keep the main thread running
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        shutdown_gracefully()
    except Exception as e:
        print(f"Error in main: {e}")
        shutdown_gracefully()


if __name__ == "__main__":
    main()
