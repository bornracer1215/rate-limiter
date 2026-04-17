from locust import HttpUser, task, between
import random

class RateLimiterUser(HttpUser):
    wait_time = between(0.1, 0.5)

    def on_start(self):
        self.user_id = f"load_test_user_{random.randint(1, 100000)}"

    @task(3)
    def check_fixed_window(self):
        self.client.post("/check", json={
            "client_id": self.user_id,
            "algorithm": "fixed_window",
            "limit": 10000,
            "window": 60
        })

    @task(2)
    def check_token_bucket(self):
        self.client.post("/check", json={
            "client_id": self.user_id,
            "algorithm": "token_bucket",
            "limit": 10000,
            "window": 60
        })

    @task(1)
    def check_sliding_window(self):
        self.client.post("/check", json={
            "client_id": self.user_id,
            "algorithm": "sliding_window",
            "limit": 10000,
            "window": 60
        })

    @task(1)
    def health_check(self):
        self.client.get("/health")