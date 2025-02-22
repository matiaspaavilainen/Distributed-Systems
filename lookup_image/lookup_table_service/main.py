import os
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
from grpc_sharing import broadcast_to_peers, start_grpc_server

# Constants
CONSUMER_PORT = 30002
PRODUCER_PORT = 30003
NODE_UPDATES_TOPIC = "node-updates"
LOOKUP_UPDATES_TOPIC = "lookup-updates"
LOOKUP_TABLE_TOPIC = "lookup-table"
MONGO_URL = os.getenv("MONGO_URL", "mongodb://root:example@mongodb-node-service:27017")

PEER_LOOKUPS = ["lookup-0:50051", "lookup-1:50051", "lookup-2:50051"]
GRPC_PORT = 50051

# Global variables
stop_event = threading.Event()
collection = None
process_thread = None
server = None


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
            print(table_data)
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
                collection.update_one(
                    {"address": str(address)},
                    {"$addToSet": {"values": {"$each": values}}},
                    upsert=True,
                )
        elif update_type == "D":
            for address in data:
                collection.delete_one({"address": str(address)})
        elif update_type == "I":
            for address in data:
                collection.update_one(
                    {"address": str(address)},
                    {"$set": {"values": []}},
                    upsert=True,
                )

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


def shutdown_gracefully(*args):
    global server
    print("Received termination signal, shutting down gracefully...")

    # Stop accepting new requests
    stop_event.set()

    # Wait for Kafka consumer thread to finish
    if process_thread and process_thread.is_alive():
        process_thread.join(timeout=5)

    # Gracefully stop gRPC server
    if server:
        print("Stopping gRPC server...")
        server.stop(grace=5)  # Give 5 seconds for ongoing RPCs to complete
        server.wait_for_termination(timeout=5)

    print("Shutdown complete")
    os._exit(0)


def main():
    global collection, process_thread, vector_clock, server

    vector_clock = VectorClock({})
    signal.signal(signal.SIGTERM, shutdown_gracefully)

    client = MongoClient(MONGO_URL)
    db = client["LOOKUP"]
    collection = db["lookup"]
    collection.drop()
    collection.create_index("address", unique=True)

    # Start gRPC server
    server = start_grpc_server(collection, vector_clock, GRPC_PORT, update_table)

    # Start Kafka consumer thread
    process_thread = threading.Thread(target=process_updates)
    process_thread.daemon = True
    process_thread.start()

    print("Started service successfully")

    try:
        while True:
            if not process_thread.is_alive():
                process_thread = threading.Thread(target=process_updates)
                process_thread.daemon = True
                process_thread.start()
            time.sleep(5)
    except KeyboardInterrupt:
        server.stop(0)
        shutdown_gracefully()
    except Exception as e:
        print(f"Error in main: {e}")
        shutdown_gracefully()


if __name__ == "__main__":
    main()
