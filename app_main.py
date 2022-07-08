import os
from time import sleep

from uvicorn import Config

from perfi.api import Server

API_PORT = int(os.environ.get("API_PORT", 5000))
FRONTEND_PORT = int(os.environ.get("FRONTEND_PORT", 5001))
HOST = "127.0.0.1"

config = Config("perfi.api:app", host=HOST, port=API_PORT, log_level="info")
server = Server(config=config)

frontend_config = Config(
    "perfi.api:frontend_app", host=HOST, port=FRONTEND_PORT, log_level="debug"
)
frontend_server = Server(config=frontend_config)


if __name__ == "__main__":
    with server.run_in_thread():
        with frontend_server.run_in_thread():
            while True:
                sleep(1)
