import sys
import os
import threading
import time
import socket
import grpc
from pymongo import MongoClient
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
import uvicorn

# Add paths
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

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
    if item is not None:
        return item["email"]
    return None


def find_item_from_any_db(query):
    item = search_local_db(query)
    if item is not None:
        if DEBUG:
            print("Found item from the local database: " + str(item))
        return {"name": query, "email": item}

    lookup_table = get_lookup_table()
    for address, values in lookup_table.items():
        if query in values:
            if DEBUG:
                print(f"Item found in lookup table at {address}")
            item = grpc_client_SAND.run(query, address)
            if item and item.data:
                collection.insert_one({"name": query, "email": item.data})
                print("Added " + str(item) + " to the local database")
                # Update the lookup table on the local node
                update_lookup_table(
                    # Construct a key with the hostname and port
                    {f"{socket.gethostname()}:{PORT}": [query]},
                    message_type="A",
                    received_from_message=False,
                    kafka_producer_port=KAFKA_PROD_PORT,
                    topic=NODE_UPDATES,
                )
                return {"name": query, "email": item.data}

    if DEBUG:
        print("Item not found in lookup table, sending request to the main server")
    item = grpc_client_SAND.run(query, MAIN_SERVER_ADDRESS)
    if item and item.data:
        collection.insert_one({"name": query, "email": item.data})
        print("Added " + str(item) + " to the local database")
        # Update the lookup table on the local node only
        update_lookup_table(
            {f"{socket.gethostname()}:{PORT}": [query]},
            "A",
            received_from_message=False,
            kafka_producer_port=KAFKA_PROD_PORT,
            topic=NODE_UPDATES,
        )
        return {"name": query, "email": item.data}

    return None


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
    print("Shutting down gracefully...")
    send_message(
        NODE_UPDATES,
        {"data": [f"{socket.gethostname()}:{PORT}"], "type": "D"},
        KAFKA_PROD_PORT,
    )
    time.sleep(2)
    stop_event.set()

    # Remove process termination code
    kafka_thread.join(timeout=5)
    grpc_thread.join(timeout=5)
    http_thread.join(timeout=5)

    print("Shutdown complete.")
    os._exit(0)


# Use the correct MongoDB service name
MONGO_URL = os.getenv("MONGO_URL", "mongodb://root:example@mongodb-service:27017")


def main(port):
    global PORT, collection, KAFKA_PROD_PORT, kafka_thread, grpc_thread, http_thread
    PORT = port
    HTTP_PORT = port + 1
    KAFKA_CON_PORT = port + 2
    KAFKA_PROD_PORT = port + 3

    client = MongoClient(MONGO_URL)
    db_name = f"SAND{port}"
    db = client[db_name]
    collection = db["users"]
    collection.drop()

    test_server_connection()

    print("Initializing lookup table")
    init_lookup_table(KAFKA_CON_PORT, LOOKUP_TABLE_TOPIC)
    print("Lookup table initialized")

    time.sleep(5)

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
        {"data": [f"{socket.gethostname()}:{PORT}"], "type": "I"},
        KAFKA_PROD_PORT,
    )

    print("Lookuptable: ", get_lookup_table())

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        shutdown_gracefully()
    except Exception as e:
        print(f"Error in main: {e}")
        shutdown_gracefully()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python main.py <port>")
        sys.exit(1)
    port = int(sys.argv[1])
    main(port)
