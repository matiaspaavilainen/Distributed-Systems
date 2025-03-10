import os
import grpc
import json
import threading

from kafka_messaging.consumer import consumer_pb2, consumer_pb2_grpc
from kafka_messaging.producer import producer_pb2, producer_pb2_grpc
from grpc_sharing import lookup_sharing_pb2, lookup_sharing_pb2_grpc


lookup_table = {}
lookup_table_lock = threading.Lock()

# CHANGE in lookupservice as well
MAX_VALUES_PER_ADDRESS = os.getenv("MAX_VALUES_PER_ADDRESS")

DEBUG = True


def init_lookup_table(LOOKUP_SERVICE):
    """Initialize lookup table by fetching it from the lookup service via gRPC"""
    try:
        print(f"Fetching lookup table from lookup service at {LOOKUP_SERVICE}")

        # Connect to the lookup service
        with grpc.insecure_channel(LOOKUP_SERVICE) as channel:
            # Create a stub for the lookup sharing service
            stub = lookup_sharing_pb2_grpc.LookupSharingStub(channel)

            # Create request with default pagination (can be adjusted in the future)
            request = lookup_sharing_pb2.LookupTableRequest(page_size=0, page=1)

            # Call the GetLookupTable RPC
            response = stub.GetLookupTable(request)

            if response.success:
                # Parse the table data and update the local lookup table
                table_data = json.loads(response.table_data)

                # Use the existing update_lookup_table function to apply updates
                # topic can be anything, as this is a local update, not going to
                update_lookup_table(table_data, "A", True, 0, "topic")
                print(
                    f"Successfully initialized lookup table with {len(table_data)} entries"
                )
            else:
                print(f"Failed to fetch lookup table: {response.error_message}")

    except Exception as e:
        print(f"Error initializing lookup table from lookup service: {e}")


def listen_for_new_messages(port, topic):
    try:
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
                        # Initialize with values, limited to MAX_VALUES_PER_ADDRESS
                        lookup_table[address] = (
                            values[-MAX_VALUES_PER_ADDRESS:]
                            if len(values) > MAX_VALUES_PER_ADDRESS
                            else values
                        )
                    else:
                        # Add new values
                        for value in values:
                            if value not in lookup_table[address]:
                                lookup_table[address].append(value)

                        # Trim to max size if needed
                        if len(lookup_table[address]) > MAX_VALUES_PER_ADDRESS:
                            lookup_table[address] = lookup_table[address][
                                -MAX_VALUES_PER_ADDRESS:
                            ]
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
