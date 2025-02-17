import datetime
import os
import threading
import time
import signal
import grpc
from pymongo import MongoClient
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
import uvicorn

from messaging import (
    init_lookup_table,
    listen_for_new_messages,
    update_lookup_table,
    get_lookup_table,
    send_message,
)

import grpc_client_SAND
import grpc_server_SAND

# Constants
DEBUG = True
MAIN_SERVER_ADDRESS = "server-service:40002"
MONGO_URL = os.getenv("MONGO_URL", "mongodb://root:example@mongodb-service:27017")

# Topics
LOOKUP_UPDATES_TOPIC = "lookup-updates"
LOOKUP_TABLE_TOPIC = "lookup-table"
NODE_UPDATES = "node-updates"

app = FastAPI()
stop_event = threading.Event()


@app.get("/resource/{query}")
async def get_resource(query: str):
    item = find_item_from_any_db(query)
    if item:
        return JSONResponse(
            content={"data": item}, status_code=200, media_type="application/json"
        )
    else:
        raise HTTPException(status_code=404, detail="Item not found")


def search_local_db(query):
    item = collection.find_one({"name": query})
    return item


def process_item_response(item, query):
    """Helper function to process item response and update local storage"""
    if item:
        # Create user_data without _id field
        user_data = {
            "name": query,
            "email": item.email,
            "age": item.age,
            "address": {
                "street": item.address.street,
                "city": item.address.city,
                "state": item.address.state,
                "zipCode": item.address.zipCode,
            },
            "created_at": item.created_at,
            "orders": item.orders,
            "status": item.status,
            "premium": item.premium,
        }
        # Insert into MongoDB (will create its own _id)
        collection.insert_one(
            user_data.copy()
        )  # Use copy to avoid MongoDB adding _id to our response
        print("Added " + str(user_data.get("name")) + " to the local database")
        update_lookup_table(
            {get_node_address(): [query]},
            message_type="A",
            received_from_message=False,
            kafka_producer_port=KAFKA_PROD_PORT,
            topic=NODE_UPDATES,
        )
        return user_data  # Return clean data without _id
    return None


def find_item_from_any_db(query):
    item = search_local_db(query)
    if item is not None:
        if DEBUG:
            print("Found item from the local database: " + str(item))
        return process_item_response(item, query)

    lookup_table = get_lookup_table()
    for address, values in lookup_table.items():
        if query in values:
            if DEBUG:
                print(f"Item found in lookup table at {address}")
            item = grpc_client_SAND.run(query, address)
            result = process_item_response(item, query)
            if result:
                return result

    if DEBUG:
        print("Item not found in lookup table, sending request to the main server")
    item = grpc_client_SAND.run(query, MAIN_SERVER_ADDRESS)
    return process_item_response(item, query)


def get_node_address():
    """Get the node's internal service address for gRPC"""
    pod_name = os.getenv("POD_NAME")
    if not pod_name:
        raise RuntimeError("POD_NAME environment variable not set")

    # Extract the numeric ID from the deployment name
    # Format will be like 'proxy-node-0-xyz' or 'proxy-node-1-xyz'
    try:
        node_id = pod_name.split("-")[2]  # Get the numeric ID
    except IndexError:
        raise RuntimeError(f"Unexpected pod name format: {pod_name}")

    return f"proxy-node-{node_id}-internal:{PORT}"


def test_server_connection():
    try:
        with grpc.insecure_channel(MAIN_SERVER_ADDRESS) as channel:
            grpc.channel_ready_future(channel).result(timeout=5)
            print(f"Successfully connected to {MAIN_SERVER_ADDRESS}")
            return True
    except Exception as e:
        print(f"Failed to connect to {MAIN_SERVER_ADDRESS}: {e}")
        return False


def start_http_server(port):
    uvicorn.run(app, host="0.0.0.0", port=port)


def shutdown_gracefully(*args):
    print("Received termination signal, shutting down gracefully...")
    send_message(
        NODE_UPDATES,
        {"data": [get_node_address()], "type": "D"},
        KAFKA_PROD_PORT,
    )
    time.sleep(2)  # Give time for message to be sent
    stop_event.set()

    # Wait for threads to finish
    kafka_thread.join(timeout=5)
    grpc_thread.join(timeout=5)
    http_thread.join(timeout=5)

    print("Shutdown complete.")
    os._exit(0)


def main(port):
    global PORT, collection, KAFKA_PROD_PORT, kafka_thread, grpc_thread, http_thread
    PORT = port
    HTTP_PORT = port + 1
    KAFKA_CON_PORT = port + 2
    KAFKA_PROD_PORT = port + 3

    # Register signal handler for Kubernetes pod termination
    signal.signal(signal.SIGTERM, shutdown_gracefully)

    client = MongoClient(MONGO_URL)
    db_name = f"SAND{port}"
    db = client[db_name]
    collection = db["users"]
    collection.drop()

    if DEBUG:
        test_server_connection()

    # need to wait for kafka to have started
    time.sleep(5)

    print("Initializing lookup table")
    init_lookup_table(KAFKA_CON_PORT, LOOKUP_TABLE_TOPIC)

    kafka_thread = threading.Thread(
        target=listen_for_new_messages, args=(KAFKA_CON_PORT, LOOKUP_UPDATES_TOPIC)
    )
    kafka_thread.start()
    print("Started Kafka listener thread")

    grpc_thread = threading.Thread(
        target=grpc_server_SAND.serve, args=(collection, PORT)
    )
    grpc_thread.start()
    print("Started gRPC server thread")

    http_thread = threading.Thread(target=start_http_server, args=(HTTP_PORT,))
    http_thread.start()
    print("Started HTTP server thread")

    send_message(
        NODE_UPDATES,
        {"data": [get_node_address()], "type": "I"},
        KAFKA_PROD_PORT,
    )

    print("Lookuptable: ", get_lookup_table())

    try:
        while True:
            time.sleep(1)
    except Exception as e:
        print(f"Error in main: {e}")
        shutdown_gracefully()


if __name__ == "__main__":
    port = int(os.getenv("PORT"))
    main(port)
