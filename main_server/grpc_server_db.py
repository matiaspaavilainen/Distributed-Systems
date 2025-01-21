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
from pymongo import MongoClient

client = MongoClient()
db = client.SAND
collection = db["test_collection"]

import json

import data_pb2

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

    for item in collection.find():

        items[item["name"]] = item["email"]
    if DEBUG:
        print(items)
    return items
