import sys

from PyQt6.QtCore import QUrl
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import QApplication
from fastapi import FastAPI
from starlette.staticfiles import StaticFiles
from uvicorn import Config

from perfi.api import Server
from perfi.constants.paths import ROOT

HOST = "127.0.0.1"

API_PORT = 5000
config = Config("perfi.api:app", host=HOST, port=API_PORT, log_level="info")
server = Server(config=config)

FRONTEND_PORT = 5001
frontend_app = FastAPI()
FRONTEND_FILES_PATH = f"{ROOT}/frontend/dist"
frontend_app.mount(
    "/",
    StaticFiles(directory=FRONTEND_FILES_PATH, html=True),
    name="frontend_files_static",
)
frontend_config = Config(
    "app_main:frontend_app", host=HOST, port=FRONTEND_PORT, log_level="debug"
)
frontend_server = Server(config=frontend_config)


if __name__ == "__main__":
    with server.run_in_thread():
        with frontend_server.run_in_thread():
            sys.argv.append(
                "--disable-web-security"
            )  # So we can load a local html file
            app = QApplication(sys.argv)

            view = QWebEngineView()
            url = QUrl(f"http://{HOST}:{FRONTEND_PORT}")
            view.setUrl(url)
            view.show()

            # Start the event loop.
            app.exec()
