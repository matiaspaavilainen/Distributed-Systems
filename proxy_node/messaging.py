import grpc
import json
import os
import sys

# Add the kafka_messaging/consumer and kafka_messaging/producer directories to the PYTHONPATH
sys.path.append(os.path.join(os.path.dirname(__file__), "../kafka_messaging/consumer"))
sys.path.append(os.path.join(os.path.dirname(__file__), "../kafka_messaging/producer"))

from kafka_messaging.consumer import consumer_pb2
from kafka_messaging.consumer import consumer_pb2_grpc
from kafka_messaging.producer import producer_pb2
from kafka_messaging.producer import producer_pb2_grpc

# New microservice that has a db to keep the tabel in
lookup_table = {}


def get_latest_message():
    with grpc.insecure_channel("localhost:50052") as channel:
        stub = consumer_pb2_grpc.ConsumerStub(channel)
        response = stub.GetLatestMessage(consumer_pb2.GetLatestMessageRequest())
        print(f"Latest message: {response.data}")
        update_lookup_table(response.data)


def listen_for_new_messages():
    with grpc.insecure_channel("localhost:50052") as channel:
        stub = consumer_pb2_grpc.ConsumerStub(channel)
        for response in stub.ListenForNewMessages(
            consumer_pb2.ListenForNewMessagesRequest()
        ):
            update_lookup_table(response.data)


def update_lookup_table(data):
    global lookup_table
    try:
        # Parse the data if it's a JSON string
        if isinstance(data, str):
            data = json.loads(data)

        # Check if the lookup table already contains the information
        updated = False
        for name, port in data.items():
            if lookup_table.get(name) != port:
                lookup_table[name] = port
                updated = True

        # Only send a message if the lookup table was updated
        if updated:
            send_message("lookup_table", lookup_table)
            print(lookup_table)
    except json.JSONDecodeError as e:
        print(f"Failed to decode JSON data: {e}")
    except AttributeError as e:
        print(f"Data is not in the expected format: {e}")


def get_lookup_table():
    return lookup_table


def send_message(topic, data):
    with grpc.insecure_channel("localhost:50051") as channel:
        stub = producer_pb2_grpc.ProducerStub(channel)
        request = producer_pb2.SendMessageRequest(topic=topic, data=json.dumps(data))
        response = stub.SendMessage(request)
        print(f"Send message status: {response.status}")
