import sys

from uvicorn import Config

import contextlib
import time
import threading
import uvicorn

from PyQt6.QtWidgets import QApplication, QWidget

from perfi.api import Server

config = Config("perfi.api:app", host="127.0.0.1", port=5000, log_level="info")
server = Server(config=config)

if __name__ == "__main__":
    with server.run_in_thread():
        app = QApplication(sys.argv)

        # Create a Qt widget, which will be our window.
        window = QWidget()
        window.show()  # IMPORTANT!!!!! Windows are hidden by default.

        # Start the event loop.
        app.exec()
