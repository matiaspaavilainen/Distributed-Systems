import grpc
import json
import threading

from kafka_messaging.consumer import consumer_pb2, consumer_pb2_grpc
from kafka_messaging.producer import producer_pb2, producer_pb2_grpc


lookup_table = {}
lookup_table_lock = threading.Lock()

DEBUG = True


def init_lookup_table(port, topic):
    try:
        print(f"Connecting to Kafka consumer service on port {port} for topic {topic}")
        # Comms with the kafka service, can be localhost for now
        with grpc.insecure_channel(f"localhost:{port}") as channel:
            stub = consumer_pb2_grpc.ConsumerStub(channel)
            request = consumer_pb2.GetLatestMessageRequest(topic=topic)
            response = stub.GetLatestMessage(request)
            # Default to add type "A" here so it updates locally
            # Port and topic not used for local updates
            update_lookup_table(response.data, "A", True, 0, topic)

    except grpc.RpcError as e:
        print(f"Failed to connect to gRPC server: {e}")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")


def listen_for_new_messages(port, topic):
    try:
        # Comms with the kafka service, can be localhost for now
        with grpc.insecure_channel(f"localhost:{port}") as channel:
            stub = consumer_pb2_grpc.ConsumerStub(channel)
            for response in stub.ListenForNewMessages(
                consumer_pb2.ListenForNewMessagesRequest(topic=topic)
            ):
                # Extract message type if present
                # Otherwise default to "A"
                try:
                    message = json.loads(response.data)
                    data = message["data"]
                    message_type = message.get("type", "A")
                    update_lookup_table(data, message_type, True, 0, topic)
                except (KeyError, json.JSONDecodeError):
                    # Fall back to old behavior if the message isn't properly formatted
                    print("error: ", KeyError, json.JSONDecodeError)
    except grpc.RpcError as e:
        if e.code() == grpc.StatusCode.UNAVAILABLE:
            print("gRPC server unavailable, shutting down listener.")
        else:
            print(f"gRPC error: {e}")


def update_lookup_table(
    data, message_type, received_from_message, kafka_producer_port, topic
):
    global lookup_table
    try:
        # If data is a JSON string, parse it
        if isinstance(data, str):
            data = json.loads(data)

        with lookup_table_lock:
            if message_type == "A":
                # Add or update
                for address, values in data.items():
                    address = str(address)
                    if address not in lookup_table:
                        lookup_table[address] = values
                    else:
                        for value in values:
                            if value not in lookup_table[address]:
                                lookup_table[address].append(value)
            elif message_type == "D":
                # Delete the entire entry for the given port(s)
                for address in data:
                    address = str(address)
                    if address in lookup_table:
                        del lookup_table[address]

        # Send only the updated value if the update was not received from a message
        if not received_from_message:
            message_payload = {"data": data, "type": message_type}
            send_message(topic, message_payload, kafka_producer_port)
            if DEBUG:
                print("Message sent:", message_payload)
    except json.JSONDecodeError as e:
        print(f"Failed to decode JSON data: {e}")
    except AttributeError as e:
        print(f"Data is not in the expected format: {e}")


def get_lookup_table():
    with lookup_table_lock:
        return lookup_table.copy()


def send_message(topic, data, kafka_producer_port):
    try:
        # Kafka can be localhost for now
        with grpc.insecure_channel(f"localhost:{kafka_producer_port}") as channel:
            stub = producer_pb2_grpc.ProducerStub(channel)
            request = producer_pb2.SendMessageRequest(
                topic=topic, data=json.dumps(data)
            )
            response = stub.SendMessage(request)
            if DEBUG:
                print(f"Sent message status: {response.status}")
    except grpc.RpcError as e:
        print(f"Failed to send message: {e}")
