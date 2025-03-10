import os
import signal
import threading
import time
from kubernetes import client, config
from prometheus_api_client import PrometheusConnect
import yaml
import copy


def fill_template(template, node_id, ports, worker_num, pod_ip, service_name):
    """Fill template with node ID and port values"""
    filled = copy.deepcopy(template)

    def replace_values(obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                if isinstance(v, (dict, list)):
                    replace_values(v)
                elif isinstance(v, str):
                    # Create a mapping of replacements
                    replacements = {
                        "id": str(node_id),
                        "worker_num": worker_num,
                        "pod_ip": pod_ip,
                        "service_name": service_name,
                    }

                    # Add port replacements
                    replacements.update(ports)

                    try:
                        # Replace all placeholders using string formatting
                        new_value = v.format(**replacements)

                        # Convert to proper type for port values
                        if k in ["containerPort", "port", "targetPort", "nodePort"]:
                            if any(port_key in v for port_key in ports.keys()):
                                new_value = int(new_value)

                        obj[k] = new_value
                    except KeyError:
                        # Skip if the placeholder doesn't need to be replaced
                        pass

        elif isinstance(obj, list):
            for item in obj:
                replace_values(item)

    replace_values(filled)
    # Return the filled template
    return filled


def create_node(k8s_apps, k8s_core, template, node_id, worker_num, pod_ip):
    base_port = 50060

    port_offset = node_id * 10

    # Generate service name for Kubernetes DNS
    service_name = f"proxy-node-{worker_num}-{node_id}-grpc"

    ports = {
        "base_port": int(base_port + port_offset),
        "http_port": int(base_port + port_offset + 1),
        "grpc_port": int(base_port + port_offset),
    }

    print(f"Creating node {node_id} with ports: {ports} on worker-{worker_num}")
    print(
        f"Service DNS name: {service_name}.default.svc.cluster.local:{ports['grpc_port']}"
    )

    # Create deployment and services using filled templates
    deployment = fill_template(
        template[0], node_id, ports, worker_num, pod_ip, service_name
    )
    k8s_apps.create_namespaced_deployment(body=deployment, namespace="default")

    grpc_service = fill_template(
        template[1], node_id, ports, worker_num, pod_ip, service_name
    )
    k8s_core.create_namespaced_service(body=grpc_service, namespace="default")

    http_service = fill_template(
        template[2], node_id, ports, worker_num, pod_ip, service_name
    )
    k8s_core.create_namespaced_service(body=http_service, namespace="default")


def delete_node(k8s_apps, k8s_core, node_id, worker_num):
    """Delete a node and its services"""
    print(f"Deleting node {node_id} from worker {worker_num}...")
    try:
        # Delete deployment with worker-specific name
        k8s_apps.delete_namespaced_deployment(
            name=f"proxy-node-{worker_num}-{node_id}", namespace="default"
        )
        # Delete services with worker-specific names
        k8s_core.delete_namespaced_service(
            name=f"proxy-node-{worker_num}-{node_id}-grpc", namespace="default"
        )
        k8s_core.delete_namespaced_service(
            name=f"proxy-node-{worker_num}-{node_id}-http", namespace="default"
        )
    except Exception as e:
        print(f"Error deleting node {node_id} from worker {worker_num}: {e}")


# This is feels so dumb, but it works I guess
def create_node_template(template_base, worker_num):
    """Create worker-specific template with hardcoded worker number"""
    template = copy.deepcopy(template_base)

    # Directly modify the nested affinity section
    path = template[0]["spec"]["template"]["spec"]["affinity"]["podAffinity"][
        "requiredDuringSchedulingIgnoredDuringExecution"
    ][0]["labelSelector"]["matchLabels"]

    # Set the correct label for worker pod matching
    path.update(
        {"app": "worker", "statefulset.kubernetes.io/pod-name": f"worker-{worker_num}"}
    )

    return template


def initialize_k8s():
    try:
        config.load_incluster_config()
    except config.ConfigException:
        config.load_kube_config()
    return client.AppsV1Api(), client.CoreV1Api(), client.NetworkingV1Api()


def setup_environment():
    """Set up the environment variables and return configuration values."""
    WORKER_NAME = os.getenv("WORKER_NAME")
    POD_IP = os.getenv("POD_IP")

    if not WORKER_NAME or not POD_IP:
        raise ValueError("WORKER_NAME or POD_IP environment variable not set")

    worker_num = int(WORKER_NAME.split("-")[1])

    return POD_IP, worker_num


def load_template(template_path):
    """Load the template file and validate it exists."""
    if not os.path.exists(template_path):
        raise FileNotFoundError(f"Template file not found: {template_path}")

    with open(template_path, "r") as f:
        return list(yaml.safe_load_all(f))


def cleanup_existing_nodes(k8s_apps, k8s_core, worker_num):
    """
    Clean up any existing nodes for this worker.
    Needed in case the node manager crashes, restarts and tries to create nodes that already exist.
    """
    print(f"Cleaning up all existing nodes for worker-{worker_num}...")

    try:
        # Get all deployments in the default namespace
        deployments = k8s_apps.list_namespaced_deployment(namespace="default")

        # Filter deployments that belong to our worker
        worker_deployments = [
            dep
            for dep in deployments.items
            if dep.metadata.name.startswith(f"proxy-node-{worker_num}-")
        ]

        if not worker_deployments:
            print(f"No existing nodes found for worker-{worker_num}")
            return

        print(f"Found {len(worker_deployments)} existing nodes to clean up")

        # Extract node IDs from deployment names
        for deployment in worker_deployments:
            try:
                # Extract node ID from the name (format: proxy-node-{worker_num}-{node_id})
                parts = deployment.metadata.name.split("-")
                if len(parts) >= 4:
                    node_id = int(parts[3])  # The node ID should be the 4th part
                    delete_node(
                        k8s_apps, k8s_core, node_id=node_id, worker_num=worker_num
                    )
                    print(f"Cleaned up existing node {node_id} on worker {worker_num}")
            except ValueError:
                # In case the node ID isn't a valid integer
                print(
                    f"Could not determine node ID from deployment {deployment.metadata.name}, skipping cleanup"
                )
            except Exception as e:
                print(f"Error cleaning up deployment {deployment.metadata.name}: {e}")

        time.sleep(5)  # Wait for deletions to complete
    except Exception as e:
        print(f"Error during cleanup: {e}")


def create_initial_nodes(
    k8s_apps, k8s_core, base_template, worker_num, pod_ip, node_count
):
    """Create the initial set of nodes."""
    print(f"Starting node manager, creating initial {node_count} nodes...")

    for i in range(node_count):
        current_template = create_node_template(base_template, worker_num)
        create_node(
            k8s_apps,
            k8s_core,
            current_template,
            node_id=i,
            worker_num=worker_num,
            pod_ip=pod_ip,
        )
        print(f"Created node {i} on worker-{worker_num}")

    print("Initial nodes created. Node ports:")
    for i in range(node_count):
        print(f"Node {i}:")
        print(f"  HTTP: {50060 + i * 10 + 1}")
        print(f"  gRPC: {50060 + i * 10}")


def monitor_and_scale(
    stop_event,
    prom,
    k8s_apps,
    k8s_core,
    base_template,
    worker_num,
    pod_ip,
    current_nodes,
    min_nodes,
    max_nodes,
):
    """Monitor metrics and scale nodes up or down as needed."""
    last_scale_time = 0  # Initialize to 0 to allow immediate first scaling if needed

    try:
        while not stop_event.is_set():
            # Query Prometheus for RPS
            result = prom.custom_query(
                query="sum(rate(nginx_ingress_controller_nginx_process_requests_total[1m]))"
            )

            if result:
                rps = float(result[0]["value"][1])
                print(f"Current RPS: {rps:.2f}, Nodes: {current_nodes}")

                current_nodes, last_scale_time = scale_based_on_metrics(
                    rps,
                    current_nodes,
                    min_nodes,
                    max_nodes,
                    k8s_apps,
                    k8s_core,
                    base_template,
                    worker_num,
                    pod_ip,
                    last_scale_time,
                )

            time.sleep(15)  # Check every 15 seconds
    except Exception as e:
        print(f"Error in monitoring loop: {e}")

    return current_nodes


def scale_based_on_metrics(
    rps,
    current_nodes,
    min_nodes,
    max_nodes,
    k8s_apps,
    k8s_core,
    base_template,
    worker_num,
    pod_ip,
    last_scale_time,
):
    # Don't scale again too soon after previous scaling operation
    current_time = time.time()
    if current_time - last_scale_time < 30:
        print(
            f"Skipping scaling - in cooldown period ({int(30-(current_time-last_scale_time))}s remaining)"
        )
        return current_nodes, last_scale_time

    RPS_PER_NODE = 16
    total_capacity = 2 * current_nodes * RPS_PER_NODE

    if float(rps) > 0.8 * total_capacity and current_nodes < max_nodes:
        try:
            print(
                f"Scaling up due to high load: {rps:.1f} RPS > {0.8 * total_capacity:.1f} RPS threshold"
            )
            current_template = create_node_template(base_template, worker_num)
            create_node(
                k8s_apps,
                k8s_core,
                current_template,
                node_id=current_nodes,
                worker_num=worker_num,
                pod_ip=pod_ip,
            )
            current_nodes += 1
            print(f"Scaled up to {current_nodes} nodes")
            return current_nodes, current_time  # Return updated last_scale_time

        except Exception as e:
            print(f"Failed to scale up: {e}")
            # Don't update last_scale_time on error to allow retry
            return current_nodes, last_scale_time

    # Scale down if we're using <40% of capacity
    elif float(rps) < 0.5 * total_capacity and current_nodes > min_nodes:
        try:
            print(
                f"Scaling down due to low load: {rps:.1f} RPS < {0.4 * total_capacity:.1f} RPS threshold"
            )
            node_to_remove = current_nodes - 1
            delete_node(k8s_apps, k8s_core, node_to_remove, worker_num)
            current_nodes -= 1
            print(f"Scaled down to {current_nodes} nodes")
            return current_nodes, current_time  # Return updated last_scale_time

        except Exception as e:
            print(f"Failed to scale down: {e}")
            return current_nodes, last_scale_time

    return current_nodes, last_scale_time


def main():
    MIN_NODES = 2
    MAX_NODES = 18
    DEFAULT_NODE_QUANTITY = 2
    current_nodes = DEFAULT_NODE_QUANTITY
    template_path = "templates/proxy-node-template.yaml"

    try:
        # Setup
        POD_IP, worker_num = setup_environment()
        base_template = load_template(template_path)
        k8s_apps, k8s_core, k8s_networking = initialize_k8s()

        prom = PrometheusConnect(
            url="http://prometheus-kube-prometheus-prometheus.monitoring.svc.cluster.local:9090"
        )

        # Create stop event for graceful shutdown
        stop_event = threading.Event()

        # Register signal handler
        def shutdown_gracefully(*args):
            print("Received termination signal, shutting down node manager...")
            stop_event.set()
            # Clean up nodes - make sure to clean up all nodes including delayed ones
            for i in range(current_nodes):
                delete_node(k8s_apps, k8s_core, node_id=i, worker_num=worker_num)
            print("All nodes deleted")

        signal.signal(signal.SIGTERM, shutdown_gracefully)

        # Cleanup and initialization with default number of nodes
        cleanup_existing_nodes(k8s_apps, k8s_core, worker_num)
        create_initial_nodes(
            k8s_apps, k8s_core, base_template, worker_num, POD_IP, DEFAULT_NODE_QUANTITY
        )

        # Main scaling loop
        current_nodes = monitor_and_scale(
            stop_event,
            prom,
            k8s_apps,
            k8s_core,
            base_template,
            worker_num,
            POD_IP,
            current_nodes,
            MIN_NODES,
            MAX_NODES,
        )

    except Exception as e:
        print(f"Error in main function: {e}")
    finally:
        print("Node manager shutdown complete")


if __name__ == "__main__":
    main()
