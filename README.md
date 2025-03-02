# Distributed-Systems

## KUBEADM

### Prerequisites

4x Ubuntu 22.04 VM with 2xCPU, 2gb RAM, 10gb storage

### Only do these 2 for the control VM

### Clone Repository (on the VM)

```bash
# only on control
git clone https://github.com/matiaspaavilainen/Distributed-Systems.git
cd Distributed-Systems
git checkout multi-vm
```

### Install Stern (for log viewing)

```bash
# only on control
# Download stern binary
wget https://github.com/stern/stern/releases/download/v1.32.0/stern_1.32.0_linux_amd64.tar.gz

# Extract the binary
tar -xf stern_1.32.0_linux_amd64.tar.gz

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

    # Label worker nodes (replace <worker-X-name> with actual node names)
    # assuming worker ndoes were started with names worker-1, worker-2, worker-3
    kubectl label node worker-1 node-role.kubernetes.io/worker=true
    kubectl label node worker-2 node-role.kubernetes.io/worker=true
    kubectl label node worker-3 node-role.kubernetes.io/worker=true

    # Verify labels

    kubectl get nodes
    ```

### Deploy Application Components

1. **Deploy control stack**

    ```bash
    # Apply ingress-nginx controller
    kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/controller-v1.8.2/deploy/static/provider/cloud/deploy.yaml
    
    # Wait for the ingress controller to be fully ready
    echo "Waiting for ingress-nginx controller to be ready..."
    kubectl wait --namespace ingress-nginx \
      --for=condition=ready pod \
      --selector=app.kubernetes.io/component=controller \
      --timeout=180s
    
    # Now apply the rest of the components
    kubectl apply -f deployments/mongodb-configmap.yaml
    kubectl apply -f deployments/proxy-node-balancer.yaml
    kubectl apply -f deployments/control-stack.yaml
    ```

2. **Deploy worker stack**

    ```bash
    kubectl get pods -o wide
    # Wait for control plane to start completely
    kubectl apply -f node_manager/templates/rbac.yaml
    kubectl apply -f deployments/worker-stack.yaml
    ```

3. **Verify Deployment**

    ```bash
    # Check gateway logs with stern
    stern control -c gateway
    # When it shows 3 nodes for 3 VMs, its ready to accept requests.
    # NOTE: can take up to 2 minutes, just wait

    # Get VM's IP
    ip -4 addr show | grep -oP '(?<=inet\s)\d+(\.\d+){3}' | grep -v '127.0.0.1' | head -n 1
    ```

    **Network Access Note**:
    - **cPouta**: http://CONTROL_VM_PUBLIC_IP:30080/resource/John%20Williams
    - **Multipass**: Uses private IP, directly accessible from host
    - **VirtualBox**:

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

### PROMETHEUS & MONITORING

1. **Install helm**

    ```bash
    curl https://baltocdn.com/helm/signing.asc | gpg --dearmor | sudo tee /usr/share/keyrings/helm.gpg > /dev/null
    sudo apt-get install apt-transport-https --yes
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/helm.gpg] https://baltocdn.com/helm/stable/debian/ all main" | sudo tee /etc/apt/sources.list.d/helm-stable-debian.list
    sudo apt-get update
    sudo apt-get install helm
    ```

2. **Install kube-prometheus-stack** (includes Prometheus Operator with CRDs)

    ```bash
    # Create monitoring namespace
    kubectl create namespace monitoring

    # Add Prometheus repo
    helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
    helm repo update

    # Create local storage for Prometheus
    sudo mkdir -p /mnt/prometheus-server
    sudo chmod 777 /mnt/prometheus-server

    # Get node name for storage config
    NODE_NAME=$(kubectl get nodes -o jsonpath='{.items[0].metadata.name}')
    sed -i "s/YOUR_NODE_NAME/$NODE_NAME/g" deployments/prometheus-storage.yaml
    kubectl apply -f deployments/prometheus-storage.yaml

    # Deploy kube-prometheus-stack with values and default service monitors
    helm install prometheus prometheus-community/kube-prometheus-stack \
      --namespace monitoring \
      --set prometheus.prometheusSpec.podMonitorSelectorNilUsesHelmValues=false \
      --set prometheus.prometheusSpec.servicemonitorSelectorNilUsesHelmValues=false \
      --set prometheus.prometheusSpec.storageSpec.volumeClaimTemplate.spec.storageClassName=local-storage \
      --set prometheus.prometheusSpec.storageSpec.volumeClaimTemplate.spec.accessModes[0]=ReadWriteOnce \
      --set prometheus.prometheusSpec.storageSpec.volumeClaimTemplate.spec.resources.requests.storage=8Gi

    # Wait for CRDs to become available
    echo "Waiting for ServiceMonitor CRDs to be ready..."
    kubectl wait --for condition=established --timeout=60s \
      crd/servicemonitors.monitoring.coreos.com

    # Now create a dedicated NodePort service for external access to Prometheus
    cat <<EOF | kubectl apply -f -
    apiVersion: v1
    kind: Service
    metadata:
      name: prometheus-server-public
      namespace: monitoring
    spec:
      type: NodePort
      ports:
      - port: 9090
        targetPort: 9090
        nodePort: 30909
        name: http
      selector:
        app.kubernetes.io/name: prometheus
        prometheus: prometheus-kube-prometheus-prometheus
    EOF

    # Create ServiceMonitor for ingress and proxy nodes
    kubectl apply -f deployments/prometheus-monitoring.yaml
    ```

3. **Install Grafana**

    ```bash
    helm repo add grafana https://grafana.github.io/helm-charts
    helm repo update
    
    # Install Grafana with NodePort for easy access
    helm install grafana grafana/grafana \
      --namespace monitoring \
      --set service.type=NodePort \
      --set service.nodePort=30300
    
    # Get admin password
    kubectl get secret --namespace monitoring grafana -o jsonpath="{.data.admin-password}" | base64 --decode ; echo
    
    # Print access URL
    NODE_IP=$(ip -4 addr show | grep -oP '(?<=inet\s)\d+(\.\d+){3}' | grep -v '127.0.0.1' | head -n 1)
    echo "Grafana dashboard available at: http://$NODE_IP:30300"
    echo "Log in with username: admin and the password displayed above"
    echo "After login, add Prometheus data source: http://prometheus-kube-prometheus-prometheus.monitoring.svc:9090"
    ```

## Stopping and Restarting

### Delete everything, but cluster is not destroyed

```bash
kubectl delete -f deployments/control-stack.yaml
kubectl delete -f deployments/proxy-node-balancer.yaml
kubectl delete configmap mongodb-config

# Remove Prometheus and Grafana
helm uninstall prometheus -n monitoring
helm uninstall grafana -n monitoring
kubectl delete namespace monitoring
kubectl delete -f deployments/prometheus-storage.yaml
# Delete any leftover resources
kubectl delete pods,services,deployments,statefulsets,configmaps,ingress --all --all-namespaces

kubectl delete -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/controller-v1.8.2/deploy/static/provider/cloud/deploy.yaml
```

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

# Follow from 7. Labelling in the startup instruction
```
