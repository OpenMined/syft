from threading import Event

from loguru import logger

stop_event = Event()


def register(client):
    response = client.server_client.post(
        "/register",
        json={"email": client.email},
    )

    j = response.json()
    if "token" in j:
        client.token = j["token"]
        client.save_yaml_config(client.default_config_path)

    return response.status_code == 200


def run(shared_state):
    if not stop_event.is_set():
        if not shared_state.client.token:
            register(shared_state.client)
            logger.info("> Register Complete")
