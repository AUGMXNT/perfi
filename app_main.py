import argparse
from time import sleep

from uvicorn import Config

from perfi.api import Server

parser = argparse.ArgumentParser()
parser.add_argument("--apiPort", default="5001")
parser.add_argument("--frontendPort", default="5002")
args = parser.parse_args()

HOST = "127.0.0.1"
API_PORT = int(args.apiPort)
config = Config("perfi.api:app", host=HOST, port=API_PORT, log_level="info")
server = Server(config=config)

FRONTEND_PORT = int(args.frontendPort)
frontend_config = Config(
    "perfi.api:frontend_app", host=HOST, port=FRONTEND_PORT, log_level="debug"
)
frontend_server = Server(config=frontend_config)


if __name__ == "__main__":
    with server.run_in_thread():
        with frontend_server.run_in_thread():
            while True:
                sleep(1)
