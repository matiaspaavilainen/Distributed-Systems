import os
import sys
import threading
import time
import signal
import json
import grpc
import socket
from dataclasses import dataclass
from typing import Dict
from pymongo import MongoClient

from kafka_messaging.consumer import consumer_pb2, consumer_pb2_grpc
from kafka_messaging.producer import producer_pb2, producer_pb2_grpc
from grpc_sharing.grpc_sharing import (
    broadcast_to_peers,
    start_grpc_server_threaded,
)

# Constants
WORKER_NAME = os.getenv("WORKER_NAME")
kafka_port = int(os.getenv("KAFKA_SERVICE_PORT"))
CONSUMER_PORT = kafka_port + 2
PRODUCER_PORT = kafka_port + 3

NODE_UPDATES_TOPIC = "node-updates"
LOOKUP_UPDATES_TOPIC = "lookup-updates"
LOOKUP_TABLE_TOPIC = "lookup-table"

MONGO_URL = "mongodb://root:example@localhost:27017"
PEER_LOOKUPS = [
    "lookup-service-control:50051",
    "worker-0:50051",
    "worker-1:50051",
    "worker-2:50051",
]
GRPC_SERVER_PORT = 50051

# Global variables
stop_event = threading.Event()
collection = None
process_thread = None


@dataclass
class VectorClock:
    clocks: Dict[str, int]


def broadcast_table():
    try:
        with grpc.insecure_channel(f"localhost:{PRODUCER_PORT}") as channel:
            stub = producer_pb2_grpc.ProducerStub(channel)
            table_data = {
                str(doc["address"]): doc["values"] for doc in collection.find()
            }
            request = producer_pb2.SendMessageRequest(
                topic=LOOKUP_TABLE_TOPIC, data=json.dumps(table_data)
            )
            stub.SendMessage(request)
            print("Lookuptable:", table_data)
    except Exception as e:
        print(f"Error broadcasting table: {e}")


def send_update(data, update_type):
    try:
        with grpc.insecure_channel(f"localhost:{PRODUCER_PORT}") as channel:
            stub = producer_pb2_grpc.ProducerStub(channel)
            update_data = {"data": data, "type": update_type}
            request = producer_pb2.SendMessageRequest(
                topic=LOOKUP_UPDATES_TOPIC, data=json.dumps(update_data)
            )
            stub.SendMessage(request)
    except Exception as e:
        print(f"Error sending update: {e}")


def update_table(data, update_type, from_peer=False):
    try:
        # Update vector clock
        node_id = socket.gethostname()
        vector_clock.clocks[node_id] = vector_clock.clocks.get(node_id, 0) + 1

        # MongoDB updates
        if update_type == "A":
            for address, values in data.items():
                print(f"Processing address: {address}")
                collection.update_one(
                    {"address": str(address)},
                    {"$addToSet": {"values": {"$each": values}}},
                    upsert=True,
                )
        elif update_type == "I":
            for address in data:
                print(f"Initializing address: {address}")
                collection.update_one(
                    {"address": str(address)},
                    {"$set": {"values": []}},
                    upsert=True,
                )
        elif update_type == "D":
            for address in data:
                print(f"Deleting address: {address}")
                collection.delete_one({"address": str(address)})

        # Broadcast to Kafka always
        send_update(data, update_type)
        broadcast_table()

        # Only propagate to peers if update is local
        if not from_peer:
            peer_lookups = [p for p in PEER_LOOKUPS if not p.startswith(node_id)]
            broadcast_to_peers(data, update_type, vector_clock, peer_lookups)

    except Exception as e:
        print(f"Error updating table: {e}")


def process_updates():
    while not stop_event.is_set():
        try:
            with grpc.insecure_channel(f"localhost:{CONSUMER_PORT}") as channel:
                grpc.channel_ready_future(channel).result(timeout=5)
                stub = consumer_pb2_grpc.ConsumerStub(channel)
                request = consumer_pb2.ListenForNewMessagesRequest(
                    topic=NODE_UPDATES_TOPIC
                )
                for response in stub.ListenForNewMessages(request):
                    if stop_event.is_set():
                        break
                    message = json.loads(response.data)
                    update_table(message["data"], message["type"], from_peer=False)
        except Exception:
            time.sleep(1)


def wait_for_dependencies():
    # Wait for MongoDB
    mongo_ready = False
    max_attempts = 10
    for attempt in range(max_attempts):
        try:
            client = MongoClient(MONGO_URL, serverSelectionTimeoutMS=1000)
            client.admin.command("ping")
            mongo_ready = True
            print("MongoDB connection successful")
            break
        except Exception as e:
            print(f"Mongo not ready, attempt {attempt+1}/{max_attempts}: {str(e)}")
            time.sleep(2)

    if not mongo_ready:
        return False

    # Wait for Kafka consumer service
    kafka_ready = False
    for attempt in range(max_attempts):
        try:
            with grpc.insecure_channel(f"localhost:{CONSUMER_PORT}") as channel:
                grpc.channel_ready_future(channel).result(timeout=1)
                kafka_ready = True
                print("Kafka services ready")
                break
        except Exception as e:
            print(f"Kafka not ready, attempt {attempt+1}/{max_attempts}: {str(e)}")
            time.sleep(2)

    return mongo_ready and kafka_ready


def shutdown_gracefully(*args):
    global server_thread
    print("Received termination signal, shutting down gracefully...")

    # Stop accepting new requests
    stop_event.set()

    try:
        # Get all entries for this node and remove them
        entries_to_delete = []

        worker_num = WORKER_NAME.split("-")[1]  # Extract the number (e.g. "0")

        # Find all entries that belong to this worker node
        # Format: "proxy-node-0-1-grpc.default.svc.cluster.local:50060"
        for doc in collection.find():
            address = doc["address"]

            # Check if the service name contains the worker's ID as the first number
            # We're looking for "proxy-node-{worker_num}-" pattern
            if f"proxy-node-{worker_num}-" in address:
                entries_to_delete.append(address)
                print(f"Found entry to delete: {address}")

        # If we have entries to delete, update the table
        if entries_to_delete:
            print(f"Cleaning up {len(entries_to_delete)} entries for {WORKER_NAME}")
            update_table(entries_to_delete, "D", from_peer=False)
        else:
            print(f"No entries found for worker {WORKER_NAME}")

    except Exception as e:
        print(f"Error during cleanup: {e}")

    # Time for messages to be sent
    time.sleep(5)

    # Wait for Kafka consumer thread to finish
    if process_thread and process_thread.is_alive():
        process_thread.join(timeout=10)

    if server_thread and server_thread.is_alive():
        server_thread.join(timeout=10)

    print("Shutdown complete")
    os._exit(0)


def main():
    global collection, process_thread, vector_clock, server_thread

    vector_clock = VectorClock({})
    signal.signal(signal.SIGTERM, shutdown_gracefully)

    if not wait_for_dependencies():
        print("Critical dependencies not available, exiting")
        sys.exit(1)

    client = MongoClient(MONGO_URL, serverSelectionTimeoutMS=5000)
    db = client["LOOKUP"]
    collection = db["lookup"]
    collection.drop()
    collection.create_index("address", unique=True)

    # Start Kafka consumer thread
    process_thread = threading.Thread(target=process_updates)
    process_thread.daemon = True
    process_thread.start()

    # wait for kafka
    time.sleep(5)

    # Start gRPC server in its own thread
    server_thread = start_grpc_server_threaded(
        collection, vector_clock, GRPC_SERVER_PORT, update_table
    )

    print("Started service successfully")

    try:
        while True:
            if not process_thread.is_alive():
                process_thread = threading.Thread(target=process_updates)
                process_thread.daemon = True
                process_thread.start()

            time.sleep(5)
    except KeyboardInterrupt:
        shutdown_gracefully()
    except Exception as e:
        print(f"Error in main: {e}")
        shutdown_gracefully()


if __name__ == "__main__":
    main()
