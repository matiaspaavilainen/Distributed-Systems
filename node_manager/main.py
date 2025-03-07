import os
import signal
import threading
import time
from kubernetes import client, config
import yaml
import copy


def initialize_k8s():
    try:
        config.load_incluster_config()
    except config.ConfigException:
        config.load_kube_config()
    return client.AppsV1Api(), client.CoreV1Api(), client.NetworkingV1Api()


# USE HPA, WITH PROMETHEUS REQUEST PER SECOND
# https://kubernetes.io/docs/tasks/run-application/horizontal-pod-autoscale/

# prometheus in cluster access
# prometheus-server.monitoring.svc.cluster.local:80
# prometheus-prometheus-pushgateway.monitoring.svc.cluster.local:9091


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


# This is feels so dumb, but can't be done in any other way
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


def main():
    WORKER_NAME = os.getenv("WORKER_NAME")
    POD_IP = os.getenv("POD_IP")
    if not WORKER_NAME or not POD_IP:
        raise ValueError("WORKER_NAME or POD_IP environment variable not set")

    template_path = "templates/proxy-node-template.yaml"
    if not os.path.exists(template_path):
        raise FileNotFoundError(f"Template file not found: {template_path}")

    stop_event = threading.Event()
    k8s_apps, k8s_core, k8s_networking = initialize_k8s()
    DEFAULT_NODE_QUANTITY = 3
    worker_num = int(WORKER_NAME.split("-")[1])

    # Load base template once
    with open(template_path, "r") as f:
        base_template = list(yaml.safe_load_all(f))

    def shutdown_gracefully(*args):
        print("Received termination signal, shutting down node manager...")
        stop_event.set()
        # Clean up nodes - make sure to clean up all nodes including delayed one
        for i in range(DEFAULT_NODE_QUANTITY):
            delete_node(k8s_apps, k8s_core, node_id=i, worker_num=worker_num)
        print("All nodes deleted")

    signal.signal(signal.SIGTERM, shutdown_gracefully)
    time.sleep(2)

    # Add this cleanup section before creating new nodes
    print("Cleaning up any existing nodes before starting...")
    for i in range(DEFAULT_NODE_QUANTITY):
        try:
            # Check if deployment exists first
            try:
                k8s_apps.read_namespaced_deployment(
                    name=f"proxy-node-{worker_num}-{i}", namespace="default"
                )
                # If we get here, deployment exists - delete it
                delete_node(k8s_apps, k8s_core, node_id=i, worker_num=worker_num)
                print(f"Cleaned up existing node {i} on worker {worker_num}")
            except client.exceptions.ApiException as e:
                if e.status == 404:
                    # Node doesn't exist, nothing to clean up
                    pass
                else:
                    raise
        except Exception as e:
            print(f"Error during cleanup of node {i}: {e}")

    time.sleep(5)  # Wait for deletions to complete

    print(f"Starting node manager, creating initial {DEFAULT_NODE_QUANTITY} nodes...")

    # Create initial nodes
    for i in range(DEFAULT_NODE_QUANTITY):
        current_template = create_node_template(base_template, worker_num)
        create_node(
            k8s_apps,
            k8s_core,
            current_template,
            node_id=i,
            worker_num=worker_num,
            pod_ip=POD_IP,
        )
        print(f"Created node {i} on {WORKER_NAME}")
        current_template = None

    print("Initial nodes created. Node ports:")
    for i in range(DEFAULT_NODE_QUANTITY):
        print(f"Node {i}:")
        print(f"  HTTP: {50060 + i * 10 + 1}")
        print(f"  gRPC: {50060 + i * 10}")

    try:
        while not stop_event.is_set():
            time.sleep(1)
    except Exception as e:
        print(f"Error in main loop: {e}")
    finally:
        print("Node manager shutdown complete")


if __name__ == "__main__":
    main()
