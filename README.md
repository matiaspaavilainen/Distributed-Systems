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

KUBEADM

Doesn't need strimzi for some reason?

1. Install kubeadm on ubuntu VM:
<https://kubernetes.io/docs/setup/production-environment/tools/kubeadm/create-cluster-kubeadm/>

2. sudo kubeadm init --pod-network-cidr=10.244.0.0/16

3. mkdir -p $HOME/.kube
    sudo cp -i /etc/kubernetes/admin.conf $HOME/.kube/config
    sudo chown $(id -u):$(id -g) $HOME/.kube/config

4. kubectl apply -f <https://raw.githubusercontent.com/flannel-io/flannel/master/Documentation/kube-flannel.yml>

5. kubectl taint nodes --all node-role.kubernetes.io/control-plane-

6. Start things like in the previous one starting from  4

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
