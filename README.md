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

1. start minikube
2. Another terminal, go to root dir of the git project
3. follow this: <https://strimzi.io/quickstarts/> , this is the last command that is needed: kubectl wait kafka/my-cluster --for=condition=Ready --timeout=300s -n kafka
4. kubectl apply -f deployments/zookeeper.yaml, wait for this to start before next step
5. kubectl apply -f deployments/kafka-broker.yaml
6. kubectl apply -f deployments/server-deployment.yaml
7. kubectl apply -f deployments/mongodb-configmap.yaml
8. kubectl apply -f deployments/mongodb-deployment.yaml
9. wait for both kafkas to start
10. kubectl apply -f deployments/lookup.yaml
11. kubectl apply -f node_manager/templates/rbac.yaml
12. kubectl apply -f deployments/node-manager.yaml, starts 2 nodes
13. To send http request to node, new terminal. run "minikube service proxy-node-{id}-external"
14. This opens browser, add "/resource/Jane Doe" after the port.
15. Should return the data
