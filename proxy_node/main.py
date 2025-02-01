import sys
import os
import threading
import time
from pymongo import MongoClient
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
import uvicorn
import subprocess

# add current dir to path because python imports are annoying
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from messaging import (
    init_lookup_table,
    listen_for_new_messages,
    update_lookup_table,
    get_lookup_table,
    send_deletion_message,
)

import grpc_client_SAND
import grpc_server_SAND

DEBUG = True

MAIN_SERVER_PORT = 50053  # Static port for the main server

stop_event = threading.Event()

app = FastAPI()


@app.get("/resource/{query}")
async def get_resource(query: str):
    item = find_item_from_any_db(query)
    if item:
        return JSONResponse(content={"data": item}, status_code=200)
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
    for port, values in lookup_table.items():
        if query in values:
            if DEBUG:
                print(f"Item found in lookup table at port {port}")
            item = grpc_client_SAND.run(query, port)
            if item and item.data:
                collection.insert_one({"name": query, "email": item.data})
                print("Added " + str(item) + " to the local database")
                # Update the lookup table on the local node
                update_lookup_table(
                    {PORT: [query]},
                    "A",
                    received_from_message=False,
                    kafka_producer_port=KAFKA_PROD_PORT,
                )
                return {"name": query, "email": item.data}

    if DEBUG:
        print("Item not found in lookup table, sending request to the main server")
    item = grpc_client_SAND.run(query, MAIN_SERVER_PORT)
    if item and item.data:
        collection.insert_one({"name": query, "email": item.data})
        print("Added " + str(item) + " to the local database")
        # Update the lookup table on the local node only
        update_lookup_table(
            {PORT: [query]},
            "A",
            received_from_message=False,
            kafka_producer_port=KAFKA_PROD_PORT,
        )
        return {"name": query, "email": item.data}

    return None


def start_http_server(port):
    uvicorn.run(app, host="localhost", port=port)


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


def main(port):
    global PORT, collection, KAFKA_PROD_PORT
    PORT = port
    HTTP_PORT = port + 1
    KAFKA_CON_PORT = port + 2
    KAFKA_PROD_PORT = port + 3
    # need to have another topic to send the entire table to,
    # to avoid performance issues when the table grows
    # this consumer is removed after the initialization
    KAFKA_INIT_PORT = port + 4

    LOOKUP_UPDATES_TOPIC = "lookup-updates"
    LOOKUP_TABLE_TOPIC = "lookup-table"

    # Dynamically name the database based on the port
    client = MongoClient()
    db_name = f"SAND{port}"
    db = client[db_name]
    collection = db["users"]

    # Start the Kafka consumer service for updates
    kafka_consumer_process = start_kafka_consumer_service(
        LOOKUP_UPDATES_TOPIC, KAFKA_CON_PORT
    )

    # Start the Kafka consumer service for initialization
    kafka_init_process = start_kafka_consumer_service(
        LOOKUP_TABLE_TOPIC, KAFKA_INIT_PORT
    )

    # Start the Kafka producer service for this node
    kafka_producer_process = start_kafka_producer_service(KAFKA_PROD_PORT)

    # Add a delay to give the Kafka services time to start
    time.sleep(3)

    print("Initializing lookup table")

    # Initialize the lookup table
    init_lookup_table(KAFKA_INIT_PORT)

    print("Lookuptable initialized: ", get_lookup_table())

    kafka_init_process.kill()  # Use kill() to terminate the temporary Kafka consumer process
    kafka_init_process.wait()  # Ensure the process is properly reaped

    # Start the Kafka listener thread
    kafka_thread = threading.Thread(
        target=listen_for_new_messages, args=(KAFKA_CON_PORT,)
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

    try:
        # Keep the main thread running
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Shutting down gracefully...")
        stop_event.set()
        send_deletion_message(PORT, KAFKA_PROD_PORT)
        kafka_consumer_process.kill()  # Use kill() to forcefully terminate the Kafka consumer process
        kafka_producer_process.kill()  # Use kill() to forcefully terminate the Kafka producer process
        kafka_consumer_process.wait()
        kafka_producer_process.wait()
        kafka_thread.join()  # Ensure the Kafka listener thread is properly terminated
        grpc_thread.join()  # Ensure the gRPC server thread is properly terminated
        http_thread.join()  # Ensure the HTTP server thread is properly terminated
        print("Shutdown complete.")
    finally:
        # Ensure subprocesses are terminated
        if kafka_consumer_process.poll() is None:
            kafka_consumer_process.kill()
        if kafka_producer_process.poll() is None:
            kafka_producer_process.kill()
        kafka_consumer_process.wait()
        kafka_producer_process.wait()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python main.py <port>")
        sys.exit(1)
    port = int(sys.argv[1])
    main(port)
