import sys

from PyQt6.QtCore import QUrl, QSize
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import QApplication
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
            app = QApplication(sys.argv)
            app.setApplicationName("perfi")

            view = QWebEngineView()
            view.setWindowTitle("perfi")
            view.resize(QSize(1400, 1000))
            url = QUrl(f"http://{HOST}:{FRONTEND_PORT}")
            view.setUrl(url)
            view.show()

            app.exec()
