import sys
import os
import threading
import time
import json
import grpc
from pymongo import MongoClient

# Add paths
sys.path.append(os.path.join(os.path.dirname(__file__), "../kafka_messaging/consumer"))
sys.path.append(os.path.join(os.path.dirname(__file__), "../kafka_messaging/producer"))

from kafka_messaging.consumer import consumer_pb2, consumer_pb2_grpc
from kafka_messaging.producer import producer_pb2, producer_pb2_grpc

# Constants
CONSUMER_PORT = 30002
PRODUCER_PORT = 30003
NODE_UPDATES_TOPIC = "node-updates"
LOOKUP_UPDATES_TOPIC = "lookup-updates"
LOOKUP_TABLE_TOPIC = "lookup-table"
DEBUG = False

# Global variables
stop_event = threading.Event()
collection = None
process_thread = None


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


def update_table(data, update_type):
    try:
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
        send_update(data, update_type)
        broadcast_table()
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
                    update_table(message["data"], message["type"])
        except Exception:
            time.sleep(1)


def shutdown_gracefully(*args):
    stop_event.set()
    if process_thread.is_alive():
        process_thread.join(timeout=5)
    os._exit(0)


MONGO_URL = os.getenv("MONGO_URL", "mongodb://root:example@mongodb-service:27017")


def main():
    global collection, process_thread
    client = MongoClient(MONGO_URL)
    db = client["LOOKUP"]
    collection = db["lookup"]
    collection.drop()
    collection.create_index("address", unique=True)

    print("Starting thread")
    process_thread = threading.Thread(target=process_updates)
    process_thread.daemon = True
    process_thread.start()
    print("Succesfully started listener")

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
