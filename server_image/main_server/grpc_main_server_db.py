# Copyright 2015 gRPC authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Common resources used in the gRPC route guide example."""
import os
from pymongo import MongoClient

MONGO_URL = os.getenv("MONGO_URL", "mongodb://root:example@mongodb-main-service:27017")

client = MongoClient(MONGO_URL)
db = client.SAND
collection = db["users"]

import json

DEBUG = False


def read_database():
    """Reads the route guide database.

    Returns:
      The full contents of the route guide database as a sequence of
        route_guide_pb2.Features.
    """

    items = {}
    with open("database.json") as db_file:
        for item in json.load(db_file):
            items[item["name"]] = item["email"]

    if DEBUG:
        print(items)
    return items


def mongo_read_database():
    items = {}
    if DEBUG:
        print("Querying MongoDB...")

    cursor = collection.find()
    for item in cursor:
        if DEBUG:
            print(f"Found item: {item}")
        items[item["name"]] = {
            "name": item["name"],
            "email": item["email"],
            "age": item["age"],
            "address": {
                "street": item["address"]["street"],
                "city": item["address"]["city"],
                "state": item["address"]["state"],
                "zipCode": item["address"]["zipCode"],
            },
            "created_at": item["created_at"],
            "orders": item["orders"],
            "status": item["status"],
            "premium": item["premium"],
        }

    if DEBUG:
        print(f"Final items dict: {items}")
    return items
