import sys
import os
import threading

sys.path.append(os.path.join(os.path.dirname(__file__), "../consumer"))
sys.path.append(os.path.join(os.path.dirname(__file__), "../producer"))

from consumer import consumer_service
from producer import producer_service


def start_consumer(port):
    consumer_service.serve(port)


def start_producer(port):
    producer_service.serve(port)


def main(base_port):
    consumer_port = base_port + 2
    producer_port = base_port + 3

    print(f"Starting Kafka services with base port: {base_port}")
    print(f"Consumer port: {consumer_port}")
    print(f"Producer port: {producer_port}")

    consumer_thread = threading.Thread(target=start_consumer, args=(consumer_port,))
    producer_thread = threading.Thread(target=start_producer, args=(producer_port,))

    consumer_thread.start()
    producer_thread.start()

    try:
        consumer_thread.join()
        producer_thread.join()
    except KeyboardInterrupt:
        print("Shutting down Kafka services...")
        sys.exit(0)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python kafka_services.py <base_port>")
        sys.exit(1)
    base_port = int(sys.argv[1])
    main(base_port)
