


import grpc_client_SAND


from pymongo import MongoClient

# Placeholder for the HTTP query to the node
input = input("Give your query: ")

#Initialization of the nodes database #TODO: Parametrizise the database and collection addresses for easier node initialization
client = MongoClient()
db = client.SAND2
collection = db["test_collection"]
DEBUG = True
def read_database():
    item = collection.find_one({"name": input})
    if item is not None:
        item = item["email"]
        if DEBUG:
            print("Found item from the local database: " + str(item))
    else:
        if DEBUG:
            print("Item not found from the local database, sending request to the other node")
        item = grpc_client_SAND.run(input)
        collection.insert_one({"name": input, "email": item.data})
        print("Added " + str(item) + " to the local database")
    return item
def main():
    data = read_database()
    print("Found: " + str(data))
if __name__ == "__main__":
    main()

