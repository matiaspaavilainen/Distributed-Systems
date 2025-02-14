import sys
import os
import threading
import signal
import time

from consumer import consumer_service
from producer import producer_service

# Global variables for shutdown coordination
stop_event = threading.Event()
consumer_thread = None
producer_thread = None


def shutdown_gracefully(*args):
    print("Kafka services received termination signal...")
    stop_event.set()

    # Give time for proxy node to send its deletion message
    time.sleep(5)

    if consumer_thread and consumer_thread.is_alive():
        consumer_thread.join(timeout=5)
    if producer_thread and producer_thread.is_alive():
        producer_thread.join(timeout=5)

    print("Kafka services shutdown complete")
    os._exit(0)


def start_consumer(port):
    consumer_service.serve(port, stop_event)


def start_producer(port):
    producer_service.serve(port, stop_event)


def main(base_port):
    global consumer_thread, producer_thread

    signal.signal(signal.SIGTERM, shutdown_gracefully)

    consumer_port = base_port + 2
    producer_port = base_port + 3

    print(f"Started consumer on port: {consumer_port}")
    print(f"Started producer on port: {producer_port}")

    consumer_thread = threading.Thread(target=start_consumer, args=(consumer_port,))
    producer_thread = threading.Thread(target=start_producer, args=(producer_port,))

    consumer_thread.start()
    producer_thread.start()

    try:
        while not stop_event.is_set():
            time.sleep(1)
    except Exception as e:
        print(f"Error in kafka services: {e}")
        shutdown_gracefully()


if __name__ == "__main__":
    port = int(os.getenv("PORT_BASE"))
    main(port)
