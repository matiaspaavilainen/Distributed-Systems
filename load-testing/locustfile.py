from locust import HttpUser, task


class HelloWorldUser(HttpUser):
    @task
    def hello_world(self):
        # HOST: http://VM_IP:30404/resource/
        self.client.get("John%20Williams")
