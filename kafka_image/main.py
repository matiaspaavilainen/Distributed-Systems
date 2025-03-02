import os
import socket
import sys
import threading
import signal
import time

from consumer import consumer_service
from producer import producer_service

# Global variables for shutdown coordination
stop_event = threading.Event()
consumer_thread = None
producer_thread = None


def start_consumer(port, kafka_broker):
    consumer_service.serve(port, stop_event, kafka_broker)


def start_producer(port, kafka_broker):
    producer_service.serve(port, stop_event, kafka_broker)


def wait_for_kafka_broker(broker):
    port = 9092
    max_attempts = 10
    print(f"Waiting for Kafka broker at {broker}:{port}...")

    for attempt in range(max_attempts):
        try:
            # Simple socket connection test
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            sock.connect((broker, port))
            sock.close()
            print(f"Successfully connected to Kafka broker after {attempt+1} attempts")
            # Add 5 second buffer for full initialization
            time.sleep(5)
            return True
        except Exception as e:
            print(f"Attempt {attempt+1}/{max_attempts}: {str(e)}")
            time.sleep(2)

    print("Failed to connect to Kafka broker after maximum attempts")
    return False


def shutdown_gracefully(*args):
    print("Kafka services received termination signal...")
    stop_event.set()

    # Give time for proxy node to send its deletion message
    time.sleep(3)

    if consumer_thread and consumer_thread.is_alive():
        consumer_thread.join(timeout=5)
    if producer_thread and producer_thread.is_alive():
        producer_thread.join(timeout=5)

    print("Kafka services shutdown complete")
    os._exit(0)


def main(base_port, broker):
    global consumer_thread, producer_thread

    signal.signal(signal.SIGTERM, shutdown_gracefully)

    kafka_broker = f"{broker}:9092"

    consumer_port = base_port + 2
    producer_port = base_port + 3

    if not wait_for_kafka_broker(broker):
        print("Exiting due to Kafka connectivity failure")
        sys.exit(1)

    print(f"Started consumer on port: {consumer_port}")
    print(f"Started producer on port: {producer_port}")
    print(f"Using broker: {kafka_broker}")

    consumer_thread = threading.Thread(
        target=start_consumer, args=(consumer_port, kafka_broker)
    )
    producer_thread = threading.Thread(
        target=start_producer, args=(producer_port, kafka_broker)
    )

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
    broker = os.getenv("POD_IP", "localhost")
    if not port:
        raise ValueError("PORT environment variable not set")
    main(port, broker)
