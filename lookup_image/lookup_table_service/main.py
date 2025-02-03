import signal
import sys
import os
import threading
import time
from pymongo import MongoClient
import subprocess
import json
import grpc

# Add paths
sys.path.append(os.path.join(os.path.dirname(__file__), "../kafka_messaging/consumer"))
sys.path.append(os.path.join(os.path.dirname(__file__), "../kafka_messaging/producer"))
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from kafka_messaging.consumer import consumer_pb2, consumer_pb2_grpc
from kafka_messaging.producer import producer_pb2, producer_pb2_grpc

# Constants
CONSUMER_PORT = 40000
PRODUCER_PORT = 40001
NODE_UPDATES_TOPIC = "node-updates"
LOOKUP_UPDATES_TOPIC = "lookup-updates"
LOOKUP_TABLE_TOPIC = "lookup-table"

DEBUG = True

stop_event = threading.Event()


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


def start_kafka_producer_service(port):
    producer_service_path = os.path.join(
        os.path.dirname(__file__), "../kafka_messaging/producer/producer_service.py"
    )
    return subprocess.Popen(
        [
            "python",
            producer_service_path,
            str(port),
        ],
        preexec_fn=os.setsid,
    )


def broadcast_table():
    try:
        with grpc.insecure_channel(f"localhost:{PRODUCER_PORT}") as channel:
            stub = producer_pb2_grpc.ProducerStub(channel)
            table_data = {str(doc["port"]): doc["values"] for doc in collection.find()}
            request = producer_pb2.SendMessageRequest(
                topic=LOOKUP_TABLE_TOPIC, data=json.dumps(table_data)
            )
            stub.SendMessage(request)
            if DEBUG:
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


def update_table(data, update_type):
    try:
        if update_type == "A":
            for port, values in data.items():
                port = int(port)
                # Add or update values
                collection.update_one(
                    {"port": port},
                    {"$addToSet": {"values": {"$each": values}}},
                    upsert=True,
                )
        elif update_type == "D":
            for port in data:
                port = int(port)
                # Remove the entire entry for the given port
                collection.delete_one({"port": port})

        elif update_type == "I":
            for port in data:
                port = int(port)
                # Initialize the entry with an empty values list
                collection.update_one(
                    {"port": port}, {"$set": {"values": []}}, upsert=True
                )

        # Send the update to the lookup-updates topic
        send_update(data, update_type)
        # broadcast the updated table
        broadcast_table()
    except Exception as e:
        print(f"Error updating table: {e}")


def process_updates():
    while not stop_event.is_set():
        # try:
        #     with grpc.insecure_channel(f"localhost:{CONSUMER_PORT}") as channel:
        #         stub = consumer_pb2_grpc.ConsumerStub(channel)
        #         for response in stub.ListenForNewMessages(
        #             consumer_pb2.ListenForNewMessagesRequest()
        #         ):
        #             if stop_event.is_set():
        #                 break
        #             message = json.loads(response.data)
        #             update_table(message["data"], message["type"])
        # except Exception as e:
        #     print(f"Error processing updates: {e}, {e.__traceback__}")
        #     time.sleep(1)
        with grpc.insecure_channel(f"localhost:{CONSUMER_PORT}") as channel:
            stub = consumer_pb2_grpc.ConsumerStub(channel)
            for response in stub.ListenForNewMessages(
                consumer_pb2.ListenForNewMessagesRequest(topic=NODE_UPDATES_TOPIC)
            ):
                if stop_event.is_set():
                    break
                message = json.loads(response.data)
                update_table(message["data"], message["type"])


def shutdown_gracefully(*args):
    print("Shutting down gracefully...")
    stop_event.set()

    try:
        kafka_consumer_process.terminate()
        kafka_consumer_process.wait(timeout=5)
        kafka_producer_process.terminate()
        kafka_producer_process.wait(timeout=5)
    except Exception as e:
        print(f"Error terminating Kafka process: {e}")

    if process_thread.is_alive():
        process_thread.join(timeout=5)

    print("Shutdown complete.")
    os._exit(
        0
    )  # Forcefully exit the process to ensure the terminal returns to a usable state


def main():
    global collection, kafka_consumer_process, process_thread, kafka_producer_process

    # Database setup
    client = MongoClient(
        "mongo", 27017, username="root", password="example", authSource="admin"
    )
    db = client["LOOKUP"]
    collection = db["lookup"]
    collection.drop()
    collection.create_index("port", unique=True)

    # Start Kafka services
    kafka_consumer_process = start_kafka_consumer_service(CONSUMER_PORT)
    kafka_producer_process = start_kafka_producer_service(PRODUCER_PORT)

    # Allow services to start
    time.sleep(5)

    # Register signal handlers for SIGINT and SIGTERM
    signal.signal(signal.SIGINT, shutdown_gracefully)
    signal.signal(signal.SIGTERM, shutdown_gracefully)

    # Start update processing thread
    process_thread = threading.Thread(target=process_updates)
    process_thread.daemon = True
    process_thread.start()

    # Keep the main thread running
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        shutdown_gracefully()
    except Exception as e:
        print(f"Error in main: {e}")
        shutdown_gracefully()


if __name__ == "__main__":
    main()
