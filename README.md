# Distributed-Systems

## Secure Application Network Data Fabric (SAND)

### How to use

# Distributed-Systems

## Secure Application Network Data Fabric (SAND)

### How to use

First start the main server in the directory `/main_server` by running `grpc_main_server_SAND.py`. Then, start the lookup table service from the ROOT directory by running `python lookup_table_service/main.py`. Then, start a node from the ROOT directory with the command `python proxy_node/main.py PORT`. Additional nodes can be started with the same command in another terminal window, and with a port at least 6 larger than the previous one. So if the first node is started with port 50000, the next should be 50006, easier to do increments of 10. Static ports are 40000, 40001 and 40002. HTTP requests can be sent to the nodes using for example PostMan, to `localhost:PORT+1/resource/{name}`. This will return the databse entry if the person exists. Also needs mongodb running on the computer in the default port, and a Kafka broker, also on it's default port. Three kafka topics named lookup-table, lookup-updates and node-updates.
