from locust import HttpUser, task, constant
import random

firstName = ['John', 'Jane', 'Mike', 'Sarah', 'David', 'Emma', 'James', 'Emily']
lastName = ['Smith', 'Johnson', 'Williams', 'Brown', 'Jones', 'Garcia', 'Miller', 'Davis']
class LoadTestUser(HttpUser):
    wait_time = constant(1)
    @task(9)
    def get_user(self):
        self.client.get("/resource/" + firstName[random.randint(0,7)] + "%20" + lastName[random.randint(0,7)])

    @task(1)
    def get_nonexistant(self):
        with self.client.get("/resource/DoesNot%20Exist", catch_response=True) as response:
            if response.status_code == 404:
                response.success()
