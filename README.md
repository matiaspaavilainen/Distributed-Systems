# Distributed-Systems

## Secure Application Network Data Fabric (SAND)

### How to use

DOCKER from main branch

1. "run docker-compose up --build" in the directory where compose.yaml is
2. wait for the thigns to start, nodes, gateway and lookup should wait for kafka to start
3. If starting takes long, 30 seconds or something do 4-7
4. In a new terminal window, run: "docker exec --workdir /opt/kafka/bin/ -it broker sh"
5. run: "./kafka-topics.sh --bootstrap-server localhost:9094 --create --topic node-updates"
6. run: "./kafka-topics.sh --bootstrap-server localhost:9094 --create --topic lookup-updates"
7. run: "./kafka-topics.sh --bootstrap-server localhost:9094 --create --topic lookup-table"
8. Should now work, in browser or postman: "localhost:40404/query/John%20Doe"

KUBERNETES

minikube

1. start minikube and "minikube addons enable ingress"
2. Another terminal, go to root dir of the git project
3. - kubectl create namespace kafka
   - kubectl create -f '<https://strimzi.io/install/latest?namespace=kafka>' -n kafka
   - kubectl apply -f <https://strimzi.io/examples/latest/kafka/kraft/kafka-single-node.yaml> -n kafka
   - kubectl wait kafka/my-cluster --for=condition=Ready --timeout=300s -n kafka
4. kubectl apply -f deployments/zookeeper.yaml, wait for this to start before next step
5. kubectl apply -f deployments/kafka-broker.yaml
6. kubectl apply -f deployments/server-deployment.yaml
7. kubectl apply -f deployments/mongodb-configmap.yaml
8. kubectl apply -f deployments/mongodb-deployment.yaml
9. wait for kafka-broker to start
10. kubectl apply -f deployments/lookup.yaml
11. kubectl apply -f deployments/gateway.yaml
12. kubectl apply -f node_manager/templates/rbac.yaml
13. kubectl apply -f deployments/node-manager.yaml, starts 2 nodes
14. In a new terminal window "minikube tunnel"
15. Use postman or browser, <http://localhost/resource/John%20Williams>
16. Should return the data

To delete the nodes, simply delete the node-manager deployment. This will delete all the services and deployments related to the nodes.

## KUBEADM

### Prerequisites

1. Ubuntu 22.04 VM
2. sudo privileges

### Clone Repository

```bash
git clone https://github.com/matiaspaavilainen/Distributed-Systems.git
cd Distributed-Systems
git checkout containerization
```

### Install Stern (for log viewing)

```bash
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
    ```

5. **Initialize Kubernetes Cluster**

    ```bash
    sudo kubeadm init --pod-network-cidr=10.244.0.0/16

    mkdir -p $HOME/.kube
    sudo cp -i /etc/kubernetes/admin.conf $HOME/.kube/config
    sudo chown $(id -u):$(id -g) $HOME/.kube/config

    # important to run, nothign works without this 
    kubectl taint nodes --all node-role.kubernetes.io/control-plane-
    ```

6. **Install CNI (Flannel)**

    ```bash
    kubectl apply -f https://raw.githubusercontent.com/flannel-io/flannel/master/Documentation/kube-flannel.yml
    ```

### Deploy Application Components

1. **Deploy Kafka**

   ```bash
   kubectl apply -f deployments/zookeeper.yaml

   # wait for zookeeper before starting kafka
   kubectl get pods # to check if done
   kubectl apply -f deployments/kafka-broker.yaml
   ```

2. **Deploy Database**

   ```bash
   kubectl apply -f deployments/mongodb-configmap.yaml
   kubectl apply -f deployments/mongodb-deployment.yaml
   ```

3. **Deploy Core Services**

   ```bash
   kubectl apply -f deployments/server-deployment.yaml
   kubectl apply -f deployments/lookup.yaml
   kubectl apply -f deployments/gateway.yaml
   ```

4. **Deploy Node Manager**

   ```bash
   kubectl apply -f node_manager/templates/rbac.yaml
   kubectl apply -f deployments/node-manager.yaml
   ```

5. **Verify Deployment**

   ```bash
   kubectl get pods -A
   curl http://<VM_IP>:30404/resource/John%20Williams
   ```

### PROMETHEUS-GRAFANA

Install the prometheus-grafana stack using this tutorial
<https://medium.com/@akilblanchard09/monitoring-a-kubernetes-cluster-using-prometheus-and-grafana-8e0f21805ea9>
Create a service

1. minikube service grafana-ext --url -n monitoring

    Get the name of the kubernetes pod to port forward it

2. kubectl get pods -n monitoring

3. kubectl --namespace monitoring port-forward <Name of the grafana pod> 3000

You can now access the grafana dashboard in

4. <http://localhost:3000>

look up the ip address of the prometheus-server and add it as a data source for grafana
