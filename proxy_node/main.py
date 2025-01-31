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
                update_lookup_table(
                    {port: values},
                    received_from_message=False,
                    kafka_producer_port=KAFKA_PROD_PORT,
                )
                # Update the lookup table on the requester node
                update_lookup_table(
                    {PORT: [query]},
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
        update_lookup_table(
            {PORT: [query]},
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

    # Dynamically name the database based on the port
    client = MongoClient()
    db_name = f"SAND{port}"
    db = client[db_name]
    collection = db["users"]

    # Start the Kafka consumer service for this node
    kafka_consumer_process = start_kafka_consumer_service(
        "lookup_table", KAFKA_CON_PORT
    )

    # Start the Kafka producer service for this node
    kafka_producer_process = start_kafka_producer_service(KAFKA_PROD_PORT)

    # Add a delay to give the Kafka consumer service time to start
    time.sleep(3)

    # Initialize the lookup table with the latest message
    init_lookup_table(KAFKA_CON_PORT)

    print("Lookuptable", get_lookup_table())

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
        kafka_consumer_process.terminate()
        kafka_producer_process.terminate()
        kafka_consumer_process.wait()
        kafka_producer_process.wait()
        kafka_thread.join()  # Ensure the Kafka listener thread is properly terminated
        grpc_thread.join()  # Ensure the gRPC server thread is properly terminated
        http_thread.join()  # Ensure the HTTP server thread is properly terminated
        print("Shutdown complete.")
    finally:
        # Ensure subprocesses are terminated
        if kafka_consumer_process.poll() is None:
            kafka_consumer_process.terminate()
        if kafka_producer_process.poll() is None:
            kafka_producer_process.terminate()
        kafka_consumer_process.wait()
        kafka_producer_process.wait()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python main.py <port>")
        sys.exit(1)
    port = int(sys.argv[1])
    main(port)
