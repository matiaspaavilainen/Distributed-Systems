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
    return client.AppsV1Api(), client.CoreV1Api()


def fill_template(template, node_id, ports):
    """Fill template with node ID and port values"""
    filled = copy.deepcopy(template)

    def replace_values(obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                if isinstance(v, (dict, list)):
                    replace_values(v)
                elif isinstance(v, str):
                    if "{id}" in v:
                        obj[k] = v.replace("{id}", str(node_id))
                    for port_key, port_value in ports.items():
                        if "{" + port_key + "}" in v:
                            # Convert to int for containerPort fields
                            if (
                                k == "containerPort"
                                or k == "port"
                                or k == "targetPort"
                                or k == "nodePort"
                            ):
                                obj[k] = int(port_value)
                            else:
                                obj[k] = str(port_value)
        elif isinstance(obj, list):
            for item in obj:
                replace_values(item)

    replace_values(filled)
    return filled


def create_node(k8s_apps, k8s_core, template, node_id, base_port=50060):
    """Create a new node with the given ID and port configuration"""
    port_offset = node_id * 10
    ports = {
        "base_port": base_port + port_offset,
        "http_port": base_port + port_offset + 1,
        "grpc_port": base_port + port_offset,
        "node_http_port": 30060 + node_id * 10 + 1,
        "node_grpc_port": 30060 + node_id * 10,
    }

    print(f"Creating node {node_id} with ports: {ports}")

    # Create deployment and services using filled templates
    deployment = fill_template(template[0], node_id, ports)
    k8s_apps.create_namespaced_deployment(body=deployment, namespace="default")

    internal_service = fill_template(template[1], node_id, ports)
    k8s_core.create_namespaced_service(body=internal_service, namespace="default")

    external_service = fill_template(template[2], node_id, ports)
    k8s_core.create_namespaced_service(body=external_service, namespace="default")


def delete_node(k8s_apps, k8s_core, node_id):
    """Delete a node and its services"""
    print(f"Deleting node {node_id}...")
    try:
        # Delete deployment (this will send SIGTERM to the pod)
        k8s_apps.delete_namespaced_deployment(
            name=f"proxy-node-{node_id}", namespace="default"
        )
        # Delete services
        k8s_core.delete_namespaced_service(
            name=f"proxy-node-{node_id}-internal", namespace="default"
        )
        k8s_core.delete_namespaced_service(
            name=f"proxy-node-{node_id}", namespace="default"
        )
    except Exception as e:
        print(f"Error deleting node {node_id}: {e}")


def main():
    template_path = "templates/proxy-node-template.yaml"
    if not os.path.exists(template_path):
        raise FileNotFoundError(f"Template file not found: {template_path}")

    stop_event = threading.Event()
    k8s_apps, k8s_core = initialize_k8s()
    NUM_NODES = 2

    with open(template_path, "r") as f:
        template = list(yaml.safe_load_all(f))

    def shutdown_gracefully(*args):
        print("Received termination signal, shutting down node manager...")
        stop_event.set()
        # Clean up nodes
        for i in range(NUM_NODES):
            delete_node(k8s_apps, k8s_core, i)
        print("All nodes deleted")

    signal.signal(signal.SIGTERM, shutdown_gracefully)
    print(f"Starting node manager, creating {NUM_NODES} nodes...")

    for i in range(NUM_NODES):
        create_node(k8s_apps, k8s_core, template, i)
        print(f"Created node {i}")

    print("All nodes created. Node ports:")
    for i in range(NUM_NODES):
        print(f"Node {i}:")
        print(f"  HTTP: {30060 + i * 10 + 1}")
        print(f"  gRPC: {30060 + i * 10}")

    try:
        while not stop_event.is_set():
            time.sleep(1)
    except Exception as e:
        print(f"Error in main loop: {e}")
    finally:
        print("Node manager shutdown complete")


if __name__ == "__main__":
    main()
