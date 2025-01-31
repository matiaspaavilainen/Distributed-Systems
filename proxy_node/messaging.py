import grpc
import json
import os
import sys
import threading

# Add the kafka_messaging/consumer and kafka_messaging/producer directories to the PYTHONPATH
sys.path.append(os.path.join(os.path.dirname(__file__), "../kafka_messaging/consumer"))
sys.path.append(os.path.join(os.path.dirname(__file__), "../kafka_messaging/producer"))

from kafka_messaging.consumer import consumer_pb2
from kafka_messaging.consumer import consumer_pb2_grpc
from kafka_messaging.producer import producer_pb2
from kafka_messaging.producer import producer_pb2_grpc

# New microservice that has a db to keep the table in
lookup_table = {}
lookup_table_lock = threading.Lock()


def init_lookup_table(port):
    try:
        with grpc.insecure_channel(f"localhost:{port}") as channel:
            stub = consumer_pb2_grpc.ConsumerStub(channel)
            response = stub.GetLatestMessage(consumer_pb2.GetLatestMessageRequest())
            update_lookup_table(response.data, True, 0)
    except grpc.RpcError as e:
        print(f"Failed to connect to gRPC server: {e}")


def listen_for_new_messages(port):
    try:
        with grpc.insecure_channel(f"localhost:{port}") as channel:
            stub = consumer_pb2_grpc.ConsumerStub(channel)
            for response in stub.ListenForNewMessages(
                consumer_pb2.ListenForNewMessagesRequest()
            ):
                update_lookup_table(response.data, True, 0)
    except grpc.RpcError as e:
        if e.code() == grpc.StatusCode.UNAVAILABLE:
            print("gRPC server unavailable, shutting down listener.")
        else:
            print(f"gRPC error: {e}")


def update_lookup_table(data, received_from_message, kafka_producer_port):
    global lookup_table
    try:
        # Parse the data if it's a JSON string
        if isinstance(data, str):
            data = json.loads(data)

        # Update the lookup table with the received data
        with lookup_table_lock:
            for port, values in data.items():
                port = int(port)  # Ensure port is an integer
                if port not in lookup_table:
                    lookup_table[port] = values
                else:
                    for value in values:
                        if value not in lookup_table[port]:
                            lookup_table[port].append(value)

        # Send the entire lookup table if the update was not received from a message
        if not received_from_message:
            send_message("lookup_table", lookup_table, kafka_producer_port)
            print("Updated lookup table:", lookup_table)
    except json.JSONDecodeError as e:
        print(f"Failed to decode JSON data: {e}")
    except AttributeError as e:
        print(f"Data is not in the expected format: {e}")


def get_lookup_table():
    with lookup_table_lock:
        return lookup_table.copy()


def send_message(topic, data, kafka_producer_port):
    try:
        with grpc.insecure_channel(f"localhost:{kafka_producer_port}") as channel:
            stub = producer_pb2_grpc.ProducerStub(channel)
            request = producer_pb2.SendMessageRequest(
                topic=topic, data=json.dumps(data)
            )
            response = stub.SendMessage(request)
            print(f"Sent message status: {response.status}")
    except grpc.RpcError as e:
        print(f"Failed to send message: {e}")
