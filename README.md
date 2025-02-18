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
