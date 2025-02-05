import signal
import sys
import os
import threading
import time
import subprocess
import socket
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
MAIN_SERVER_PORT = 40002  # Static port for the main server

# Topics
LOOKUP_UPDATES_TOPIC = "lookup-updates"
LOOKUP_TABLE_TOPIC = "lookup-table"
NODE_UPDATES = "node-updates"

# Global variables
stop_event = threading.Event()
app = FastAPI()
PORT = None
collection = None
KAFKA_PROD_PORT = None
kafka_consumer_process = None
kafka_producer_process = None
kafka_thread = None
grpc_thread = None
http_thread = None


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
    item = grpc_client_SAND.run(query, f"main_server:{MAIN_SERVER_PORT}")
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


def start_http_server(port):
    uvicorn.run(app, host="0.0.0.0", port=port)


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


def shutdown_gracefully(*args):
    print("Shutting down gracefully...")
    send_message(
        NODE_UPDATES,
        {"data": [f"{socket.gethostname()}:{PORT}"], "type": "D"},
        KAFKA_PROD_PORT,
    )
    time.sleep(2)  # Add a small delay to ensure the message is sent
    stop_event.set()

    try:
        kafka_consumer_process.terminate()
        kafka_consumer_process.wait(timeout=5)
        kafka_producer_process.terminate()
        kafka_producer_process.wait(timeout=5)
    except Exception as e:
        print(f"Error terminating Kafka process: {e}")

    if kafka_consumer_process.poll() is None:
        kafka_consumer_process.kill()
    if kafka_producer_process.poll() is None:
        kafka_producer_process.kill()

    kafka_thread.join(timeout=5)
    grpc_thread.join(timeout=5)
    http_thread.join(timeout=5)

    print("Shutdown complete.")
    os._exit(
        0
    )  # Forcefully exit the process to ensure the terminal returns to a usable state


# Use the correct MongoDB service name
MONGO_URL = os.getenv("MONGO_URL", "mongodb://root:example@mongodb-service:27017")


def main(port):
    global PORT, collection, KAFKA_PROD_PORT, kafka_consumer_process, kafka_producer_process, kafka_thread, grpc_thread, http_thread
    PORT = port
    HTTP_PORT = port + 1
    KAFKA_CON_PORT = port + 2
    KAFKA_PROD_PORT = port + 3

    # Dynamically name the database based on the port
    client = MongoClient(MONGO_URL)
    db_name = f"SAND{port}"
    db = client[db_name]
    collection = db["users"]
    collection.drop()

    # Start the Kafka consumer service
    kafka_consumer_process = start_kafka_consumer_service(KAFKA_CON_PORT)

    # Start the Kafka producer service for this node
    kafka_producer_process = start_kafka_producer_service(KAFKA_PROD_PORT)

    # Add a delay to give the Kafka services time to start
    time.sleep(3)

    # Register signal handlers for SIGINT and SIGTERM
    signal.signal(signal.SIGINT, shutdown_gracefully)
    signal.signal(signal.SIGTERM, shutdown_gracefully)

    print("Initializing lookup table")

    # Initialize the lookup table
    init_lookup_table(KAFKA_CON_PORT, LOOKUP_TABLE_TOPIC)

    # Start the Kafka listener thread
    kafka_thread = threading.Thread(
        target=listen_for_new_messages, args=(KAFKA_CON_PORT, LOOKUP_UPDATES_TOPIC)
    )
    kafka_thread.start()

    # Start the gRPC server thread
    grpc_thread = threading.Thread(
        target=grpc_server_SAND.serve, args=(collection, PORT)
    )
    grpc_thread.start()

    # Start the HTTP server thread
    http_thread = threading.Thread(target=start_http_server, args=(HTTP_PORT,))
    http_thread.start()

    send_message(
        NODE_UPDATES,
        {"data": [f"{socket.gethostname()}:{PORT}"], "type": "I"},
        KAFKA_PROD_PORT,
    )

    print("Lookuptable initialized: ", get_lookup_table())

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
    if len(sys.argv) != 2:
        print("Usage: python main.py <port>")
        sys.exit(1)
    port = int(sys.argv[1])
    main(port)
