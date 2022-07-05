from time import sleep

from uvicorn import Config

from perfi.api import Server

HOST = "127.0.0.1"

API_PORT = 5001
config = Config("perfi.api:app", host=HOST, port=API_PORT, log_level="info")
server = Server(config=config)

FRONTEND_PORT = 5002
frontend_config = Config(
    "perfi.api:frontend_app", host=HOST, port=FRONTEND_PORT, log_level="debug"
)
frontend_server = Server(config=frontend_config)


if __name__ == "__main__":
    with server.run_in_thread():
        with frontend_server.run_in_thread():
            while True:
                sleep(1)
            # webview.create_window(
            #     "perfi", f"http://{HOST}:{FRONTEND_PORT}", width=1400, height=1000
            # )
            # webview.start()
