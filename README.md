# Distributed-Systems

## Secure Application Network Data Fabric (SAND)

### How to use

# Distributed-Systems

## Secure Application Network Data Fabric (SAND)

### How to use

First start the main server in the directory `/main_server` by running `grpc_main_server_SAND.py`. Then, start a node from the ROOT directory with the command `python proxy_node/main.py PORT`. Additional nodes can be started with the same command in another terminal window, and with a port at least 5 larger than the previous one. So if the first node is started with port 50050, the next shoudl be 50055. HTTP requests can be sent to the nodes using for example PostMan, to `localhost:50061/resource/{name}`. This will return the databse entry if the person exists. Also needs mongodb running on the computer in the default port, and a Kafka broker, also on it's default port.
