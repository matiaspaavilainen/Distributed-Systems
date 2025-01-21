import sys
import os
import threading
from pymongo import MongoClient

# add current dir to path because python imports are annoying
sys.path.append(os.path.dirname(__file__))

from messaging import (
    get_latest_message,
    listen_for_new_messages,
    update_lookup_table,
    get_lookup_table,
)
import grpc_client_SAND

# Initialization of the nodes database #TODO: Parametrizise the database and collection addresses for easier node initialization
client = MongoClient()
db = client.SAND2
collection = db["test_collection"]
DEBUG = True

PORT = 50069  # placeholder

stop_event = threading.Event()


def find_item_from_any_db(query):
    item = collection.find_one({"name": query})
    if item is not None:
        item = item["email"]
        if DEBUG:
            print("Found item from the local database: " + str(item))
    else:
        if DEBUG:
            print(
                "Item not found from the local database, sending request to the other node"
            )
        item = grpc_client_SAND.run(query)
        if item and item.data:
            collection.insert_one({"name": query, "email": item.data})
            print("Added " + str(item) + " to the local database")
            update_lookup_table({query: PORT})
    return item


def handle_client_requests():
    while not stop_event.is_set():
        try:
            query = input("Give your query: ")
            data = find_item_from_any_db(query)
            print("Found: " + str(data))
        except KeyboardInterrupt:
            stop_event.set()
            print("Stopping client requests...")


def main():
    # Initialize the lookup table with the latest message
    get_latest_message()

    print("Lookuptable", get_lookup_table())

    # Start the Kafka listener thread
    kafka_thread = threading.Thread(target=listen_for_new_messages)
    kafka_thread.start()

    try:
        # Start handling client requests in the main thread
        handle_client_requests()
    except KeyboardInterrupt:
        print("Shutting down gracefully...")
        stop_event.set()
        kafka_thread.join()  # Ensure the Kafka listener thread is properly terminated
        print("Shutdown complete.")


if __name__ == "__main__":
    main()
