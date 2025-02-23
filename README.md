# Distributed-Systems

## KUBEADM

### Prerequisites

1. 4x Ubuntu 22.04 VM
2. sudo privileges

### Only do these 2 for the control VM

### Clone Repository (on the VM)

```bash
# only on control
git clone https://github.com/matiaspaavilainen/Distributed-Systems.git
cd Distributed-Systems
git checkout containerization
```

### Install Stern (for log viewing)

```bash
# only on control
# Download stern binary
STERN_VERSION=1.28.0
wget https://github.com/stern/stern/releases/download/v${STERN_VERSION}/stern_${STERN_VERSION}_linux_amd64.tar.gz

# Extract the binary
tar -xf stern_${STERN_VERSION}_linux_amd64.tar.gz

# Move to PATH
sudo mv stern /usr/local/bin/
sudo chmod +x /usr/local/bin/stern

# Verify installation
stern --version
```

### VM Setup Steps

1. **Install Base Dependencies**

   ```bash
   sudo apt update && sudo apt install -y apt-transport-https ca-certificates curl
   ```

2. **Configure System Settings**
   - Disable swap:

    ```bash
    sudo swapoff -a
    sudo sed -i '/ swap / s/^/#/' /etc/fstab  # Prevent swap from turning on after reboot
    ```

   - Load kernel modules:

    ```bash
    sudo modprobe overlay
    sudo modprobe br_netfilter
    ```

   - Persist kernel modules:

     ```bash
     sudo tee /etc/modules-load.d/k8s.conf <<EOF
     overlay
     br_netfilter
     EOF
     ```

   - Set kernel parameters:

     ```bash
     sudo tee /etc/sysctl.d/k8s.conf <<EOF
     net.bridge.bridge-nf-call-iptables  = 1
     net.bridge.bridge-nf-call-ip6tables = 1
     net.ipv4.ip_forward                 = 1
     EOF
     sudo sysctl --system
     ```

3. **Install Containerd**

    ```bash
    sudo apt install -y containerd
    sudo mkdir -p /etc/containerd
    containerd config default | sudo tee /etc/containerd/config.toml   
    sudo sed -i 's/SystemdCgroup = false/SystemdCgroup = true/' /etc/containerd/config.toml

    sudo systemctl restart containerd
    sudo systemctl enable containerd
   ```

4. **Install Kubernetes Components**

    ```bash
    curl -fsSL https://pkgs.k8s.io/core:/stable:/v1.32/deb/Release.key | sudo gpg --dearmor -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg
    echo 'deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] https://pkgs.k8s.io/core:/stable:/v1.32/deb/ /' | sudo tee /etc/apt/sources.list.d/kubernetes.list

    sudo apt-get update

    sudo apt-get install -y kubelet kubeadm kubectl
    sudo apt-mark hold kubelet kubeadm kubectl

    sudo systemctl enable --now kubelet

    # for worker nodes, stop here
    ```

5. **Initialize Kubernetes Cluster**

    ```bash

    # Get and store the IP address
    CONTROL_IP=$(ip -4 addr show | grep -oP '(?<=inet\s)\d+(\.\d+){3}' | grep -v '127.0.0.1' | head -n 1)
    echo "Control plane IP: $CONTROL_IP"

    # Initialize with captured IP
    sudo kubeadm init --pod-network-cidr=10.244.0.0/16 --apiserver-advertise-address=$CONTROL_IP

    # Setup kubeconfig
    mkdir -p $HOME/.kube
    sudo cp -i /etc/kubernetes/admin.conf $HOME/.kube/config
    sudo chown $(id -u):$(id -g) $HOME/.kube/config

    # important to run, nothing works without this 
    kubectl taint nodes --all node-role.kubernetes.io/control-plane-

    # Install flannel (CNI)
    kubectl apply -f https://raw.githubusercontent.com/flannel-io/flannel/master/Documentation/kube-flannel.yml

    # Check that the control plane is running
    kubectl get nodes
    # Status should be: Ready
    ```

6. **Join Worker Nodes**

    ```bash
    # On control plane, generate the join command
    # EXPIRES AFTER 24 HOURS
    kubeadm token create --print-join-command

    # On each worker node, run the join command with sudo
    # Example (actual command will be different):
    sudo kubeadm join <control-plane-ip>:6443 --token <token> --discovery-token-ca-cert-hash sha256:<hash>

    # After joining, verify on control plane that nodes are connected
    # Takes some time for all of them to be Ready
    kubectl get nodes
    ```

7. **Label Worker Nodes**

    ```bash
    # Get node names
    kubectl get nodes

    # Label control-plane node (replace <control-plane-name> with actual node name)

    kubectl label node <control-plane-name> kafka-ordinal=0 node-role.kubernetes.io/control-plane=true

    # Label worker nodes (replace <worker-X-name> with actual node names)

    kubectl label node <worker1-name> kafka-ordinal=1 node-role.kubernetes.io/worker=true
    kubectl label node <worker2-name> kafka-ordinal=2 node-role.kubernetes.io/worker=true
    kubectl label node <worker3-name> kafka-ordinal=3 node-role.kubernetes.io/worker=true

    # Verify labels

    kubectl get nodes --show-labels | grep -E "kafka-ordinal|kubernetes.io/role"
    ```

### Deploy Application Components

1. **Deploy Kafka Infrastructure**

    ```bash
    # Deploy Zookeeper first
    kubectl apply -f deployments/zookeeper.yaml
    kubectl wait --for=condition=ready pod -l app=zookeeper

    # Then deploy Kafka
    kubectl apply -f deployments/kafka-broker.yaml
    kubectl wait --for=condition=ready pod -l app=kafka
    ```

2. **Deploy Core Services**

    ```bash
    # Deploy MongoDB first
    kubectl apply -f deployments/mongodb-configmap.yaml
    kubectl apply -f deployments/mongodb-deployment.yaml
    kubectl wait --for=condition=ready pod -l app=mongodb-node

    # Then deploy lookup service
    kubectl apply -f deployments/lookup.yaml
    kubectl wait --for=condition=ready pod -l app=lookup

    # Deploy remaining services
    kubectl apply -f deployments/server-deployment.yaml
    kubectl apply -f deployments/proxy-nodes.yaml
    kubectl apply -f deployments/gateway.yaml
    ```

3. **Deploy Node Manager**

    ```bash
    kubectl apply -f node_manager/templates/rbac.yaml
    kubectl apply -f deployments/node-manager.yaml
    ```

4. **Verify Deployment**

    ```bash
    # Check gateway logs with stern
    stern gateway -c gateway
    # If active nodes shows 2 nodes for this VM, should be good to go

    # Get VM's IP
    ip -4 addr show | grep -oP '(?<=inet\s)\d+(\.\d+){3}' | grep -v '127.0.0.1' | head -n 1
    ```

    **Network Access Note**:
    - **Multipass**: Uses private IP, directly accessible from host
    - **VirtualBox**:
    NOT TESTED MIGHT WORK MIGHT NOT
      1. Use "Bridged Adapter" in VM network settings
      2. Or use "Host-only Adapter" with IP range 192.168.56.0/24
      3. Or use Port Forwarding with NAT:

         ```bash
         # In VirtualBox Manager:
         # Settings -> Network -> Advanced -> Port Forwarding
         # Add rule:
         # Name: Gateway
         # Protocol: TCP
         # Host Port: 30404
         # Guest Port: 30404
         ```

    **Test the service**:

    ```bash
    # From VM
    curl http://$VM_IP:30404/resource/John%20Williams

    # From host (based on your VM setup):
    # Bridged/Host-only: Use VM's IP
    curl http://<VM_IP>:30404/resource/John%20Williams
    # NAT with port forwarding: Use localhost
    curl http://localhost:30404/resource/John%20Williams

### PROMETHEUS

1. **Install helm**

    ```bash
    curl https://baltocdn.com/helm/signing.asc | gpg --dearmor | sudo tee /usr/share/keyrings/helm.gpg > /dev/null
    sudo apt-get install apt-transport-https --yes
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/helm.gpg] https://baltocdn.com/helm/stable/debian/ all main" | sudo tee /etc/apt/sources.list.d/helm-stable-debian.list
    sudo apt-get update
    sudo apt-get install helm
    ```

2. **Install prometheus**

    ```bash
    kubectl create namespace monitoring
    helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
    helm repo update

    # Create directories if not exist
    sudo mkdir -p /mnt/prometheus-server
    sudo chmod 777 /mnt/prometheus-server

    # Get node name
    NODE_NAME=$(kubectl get nodes -o jsonpath='{.items[0].metadata.name}')

    # Update node name in storage config
    sed -i "s/YOUR_NODE_NAME/$NODE_NAME/g" deployments/prometheus-storage.yaml

    # Apply new storage config
    kubectl apply -f deployments/prometheus-storage.yaml

    # Install Prometheus
    helm install prometheus prometheus-community/prometheus \
    --namespace monitoring \
    --set alertmanager.enabled=false \
    --set server.persistentVolume.storageClass=local-storage

    kubectl expose service prometheus-server --namespace monitoring \
    --type=NodePort --target-port=9090 --name=prometheus-server-ext

    # Find the port of prometheus-server-ext with
    kubectl get svc prometheus-server-ext -n monitoring -o jsonpath='{.spec.ports[0].nodePort}'

    # Prometheus dashboard should now be available at
    # http://VM_IP:prometheus-server-ext port
    ```

3. **Install grafana**

    ```bash
    helm repo add grafana https://grafana.github.io/helm-charts
    helm repo update
    helm install grafana grafana/grafana --namespace monitoring

    kubectl expose service grafana --namespace monitoring --type=NodePort --target-port=3000 --name=grafana-ext
    
    # Find the port of grafana with
    kubectl get svc grafana-ext -n monitoring -o jsonpath='{.spec.ports[0].nodePort}'

    # Grafana should now be available at
    # http://VM_IP:grafana-ext port

    # get password for user "admin"
    kubectl get secret --namespace monitoring grafana -o jsonpath="{.data.admin-password}" | base64 --decode ; echo

    # Add the datasource
    kubectl get svc prometheus-server-ext -n monitoring -o jsonpath='{.spec.ports[0].nodePort}'
    # http://VM_IP:prometheus-server-ext port
    ```

## Stopping and Restarting

### Shutdown

```bash
# Stop all Kubernetes services
sudo kubeadm reset -f

# Stop containerd
sudo systemctl stop containerd

# Cleanup (optional)
sudo rm -rf /etc/kubernetes/
sudo rm -rf $HOME/.kube/
sudo rm -rf /var/lib/etcd/
```

### Restart Later

```bash
# On Control Plane:
# Start containerd
sudo systemctl start containerd

# Start kubelet
sudo systemctl start kubelet

# Get and store the IP address
CONTROL_IP=$(ip -4 addr show | grep -oP '(?<=inet\s)\d+(\.\d+){3}' | grep -v '127.0.0.1' | head -n 1)
echo "Control plane IP: $CONTROL_IP"

# Initialize with captured IP
sudo kubeadm init --pod-network-cidr=10.244.0.0/16 --apiserver-advertise-address=$CONTROL_IP

# Setup kubeconfig
mkdir -p $HOME/.kube
sudo cp -i /etc/kubernetes/admin.conf $HOME/.kube/config
sudo chown $(id -u):$(id -g) $HOME/.kube/config

# Allow pods on control-plane
kubectl taint nodes --all node-role.kubernetes.io/control-plane-

# Reinstall CNI
kubectl apply -f https://raw.githubusercontent.com/flannel-io/flannel/master/Documentation/kube-flannel.yml

# Generate new join command for workers
kubeadm token create --print-join-command

# On Each Worker Node:
# Start services
sudo systemctl start containerd
sudo systemctl start kubelet

# Run the new join command from control plane
sudo kubeadm join <control-plane-ip>:6443 --token <token> --discovery-token-ca-cert-hash sha256:<hash>

# Back on Control Plane - Verify nodes are connected
kubectl get nodes

# Redeploy components
kubectl apply -f deployments/zookeeper.yaml

# wait
kubectl apply -f deployments/kafka-broker.yaml
kubectl apply -f deployments/mongodb-configmap.yaml
kubectl apply -f deployments/mongodb-deployment.yaml
kubectl apply -f deployments/server-deployment.yaml
kubectl apply -f deployments/lookup.yaml

# wait
kubectl apply -f deployments/gateway.yaml
kubectl apply -f deployments/proxy-nodes.yaml
kubectl apply -f node_manager/templates/rbac.yaml
kubectl apply -f deployments/node-manager.yaml

# Verify deployment
kubectl get pods -A
stern gateway -c gateway
```

### PROMETHEUS-GRAFANA

Install the prometheus-grafana stack using this tutorial
<https://medium.com/@akilblanchard09/monitoring-a-kubernetes-cluster-using-prometheus-and-grafana-8e0f21805ea9>
Create a service

1. minikube service grafana-ext --url -n monitoring

    Get the name of the kubernetes pod to port forward it

2. kubectl get pods -n monitoring

3. kubectl --namespace monitoring port-forward <name of the grafana pod> 3000

    You can now access the grafana dashboard in

4. <http://localhost:3000>

look up the ip address of the prometheus-server and add it as a data source for grafana
