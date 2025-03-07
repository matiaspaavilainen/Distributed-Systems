from prometheus_client import start_http_server, Counter, Histogram, Gauge
import time
import functools

# Define metrics
REQUEST_COUNT = Counter(
    "grpc_server_requests_total",
    "Total count of requests by method and status",
    ["method", "status"],
)

REQUEST_LATENCY = Histogram(
    "grpc_server_request_duration_seconds",
    "Histogram of request latency by method",
    ["method"],
)

# Changed from Counter to Gauge for tracking active requests
ACTIVE_REQUESTS = Gauge("grpc_server_active_requests", "Active requests", ["method"])


# Start metrics server
def start_metrics_server(port):
    start_http_server(port)
    print(f"Started Prometheus metrics server on port {port}")


# Simple decorator for instrumenting methods
def track_request(method_name):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(self, request, context):
            start = time.time()
            ACTIVE_REQUESTS.labels(method=method_name).inc()
            REQUEST_COUNT.labels(method=method_name, status="received").inc()

            try:
                response = func(self, request, context)
                REQUEST_COUNT.labels(method=method_name, status="success").inc()
                return response
            except Exception as e:
                REQUEST_COUNT.labels(method=method_name, status="error").inc()
                raise
            finally:
                REQUEST_LATENCY.labels(method=method_name).observe(time.time() - start)
                ACTIVE_REQUESTS.labels(method=method_name).dec()

        return wrapper

    return decorator
