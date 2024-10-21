from threading import Event

from loguru import logger

stop_event = Event()


def register(client_config):
    response = client_config.server_client.post(
        "/register",
        json={"email": client_config.email},
    )

    j = response.json()
    if "token" in j:
        client_config.token = j["token"]
        client_config.save()

    return response.status_code == 200


def run(shared_state):
    if not stop_event.is_set():
        if not shared_state.client_config.token:
            register(shared_state.client_config)
            logger.info("> Register Complete")
