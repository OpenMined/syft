from fastapi.testclient import TestClient


def test_register(client: TestClient):
    data = {"email": "test@example.com"}
    response = client.post("/register", json=data)
    assert response.status_code == 200
    assert "token" in response.json()
