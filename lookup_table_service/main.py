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
UPDATES_TOPIC = "node-updates"
LOOKUP_UPDATES_TOPIC = "lookup-updates"
LOOKUP_TABLE_TOPIC = "lookup-table"

DEBUG = True


def start_kafka_consumer_service(topic, port):
    consumer_service_path = os.path.join(
        os.path.dirname(__file__), "../kafka_messaging/consumer/consumer_service.py"
    )
    return subprocess.Popen(
        [
            "python",
            consumer_service_path,
            topic,
            str(port),
        ]
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
        ]
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

        # Send the update to the lookup-updates topic
        send_update(data, update_type)
        # broadcast the updated table
        broadcast_table()
    except Exception as e:
        print(f"Error updating table: {e}")


def process_updates():
    while True:
        try:
            with grpc.insecure_channel(f"localhost:{CONSUMER_PORT}") as channel:
                stub = consumer_pb2_grpc.ConsumerStub(channel)
                for response in stub.ListenForNewMessages(
                    consumer_pb2.ListenForNewMessagesRequest()
                ):
                    message = json.loads(response.data)
                    update_table(message["data"], message["type"])
        except Exception as e:
            print(f"Error processing updates: {e}")
            time.sleep(1)


def main():
    global collection

    # Database setup
    client = MongoClient()
    db = client["LOOKUP"]
    collection = db["lookup"]
    collection.create_index("port", unique=True)

    # Start Kafka services
    consumer_process = start_kafka_consumer_service(UPDATES_TOPIC, CONSUMER_PORT)
    producer_process = start_kafka_producer_service(PRODUCER_PORT)

    # Allow services to start
    time.sleep(5)

    # Start update processing thread
    process_thread = threading.Thread(target=process_updates)
    process_thread.daemon = True
    process_thread.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Shutting down...")
        consumer_process.kill()
        producer_process.kill()
        consumer_process.wait()
        producer_process.wait()
        print("Shutdown complete")


if __name__ == "__main__":
    main()
