import pytest
from fastapi.testclient import TestClient

from syftbox.client.api import create_api
from syftbox.client.base import SyftClientInterface


class MockClient(SyftClientInterface):
    @property
    def all_datasites(self):
        return ["datasite1", "datasite2"]


@pytest.fixture
def mock_api():
    yield TestClient(create_api({}))


def test_create_api(mock_api):
    response = mock_api.get("/")
    assert response.status_code == 200


def test_version(mock_api):
    response = mock_api.get("/version")
    assert response.status_code == 200
    assert "version" in response.json()


def test_datasites():
    app = create_api(MockClient())
    mock_api = TestClient(app)
    response = mock_api.get("/datasites")
    assert response.status_code == 200
    assert response.json() == {"datasites": ["datasite1", "datasite2"]}


def test_datasites_exception(mock_api):
    response = mock_api.get("/datasites")
    assert response.status_code == 500
