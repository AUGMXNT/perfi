import logging
import os
import pathlib
import sys
from typing import Union, List, Tuple

import rootpath

logger = logging.getLogger(__name__)
logger.setLevel(os.environ.get("LOG_LEVEL", "WARNING").upper())

IS_PYINSTALLER = getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS")


def get_user_data_dir(
    appending_paths: Union[str, List[str], Tuple[str, ...]] = None
) -> pathlib.Path:
    """
    Returns a parent directory path where persistent application data can be stored.
    Can also append additional paths to the return value automatically.

    Linux: ~/.local/share
    macOS: ~/Library/Application Support
    Windows: C:/Users/<USER>/AppData/Roaming

    :param appending_paths: Additional path (str) or paths (List[str], Tuple[str]) to append to return value
    :type appending_paths: Un

    :return: User Data Path
    :rtype: str
    """
    logger.debug(f"Getting Home Path...")
    home = pathlib.Path.home()
    logger.debug(f"Home Path: {home}")

    system_paths = {
        "win32": home / "AppData/Roaming",
        "linux": home / ".local/share",
        "darwin": home / "Library/Application Support",
    }

    logger.debug(f"Getting System Platform...")
    if sys.platform not in system_paths:
        raise SystemError(
            f'Unknown System Platform: {sys.platform}. Only supports {", ".join(list(system_paths.keys()))}'
        )
    data_path = system_paths[sys.platform]

    if appending_paths:
        if isinstance(appending_paths, str):
            appending_paths = [appending_paths]
        for path in appending_paths:
            data_path = data_path / path

    logger.debug(f"System Platform: {sys.platform}")
    logger.debug(f"User Data Directory: {system_paths[sys.platform]}")
    logger.debug(f"Return Value: {data_path}")
    return data_path


# Paths...
if IS_PYINSTALLER:
    logger.debug(
        "PyInstaller mode detected. Using user's data dir for ROOT perfi path..."
    )
    ROOT = get_user_data_dir("perfi")
else:
    ROOT = rootpath.detect()

logger.debug(f"ROOT: {ROOT}")

DATA_DIR = f"{ROOT}/data"
CACHE_DIR = f"{ROOT}/cache"
LOG_DIR = f"{ROOT}/logs"
GENERATED_FILES_DIR = f"{DATA_DIR}/generated_files"

for directory in [DATA_DIR, CACHE_DIR, LOG_DIR, GENERATED_FILES_DIR]:
    if not os.path.exists(directory):
        os.makedirs(directory)

DB_PATH = f"{DATA_DIR}/perfi.db"
CACHEDB_PATH = f"{CACHE_DIR}/cache.db"

SOURCE_ROOT = ROOT if not IS_PYINSTALLER else sys._MEIPASS  # noqa
DB_SCHEMA_PATH = f"{SOURCE_ROOT}/perfi.schema.sql"
CACHEDB_SCHEMA_PATH = f"{SOURCE_ROOT}/cache.schema.sql"

logging.debug(f"DB_PATH: {DB_PATH}")
logging.debug(f"CACHE_PATH: {DB_PATH}")
logging.debug(f"DB_SCHEMA_PATH: {DB_SCHEMA_PATH}")
logging.debug(f"CACHE_SCHEMA_PATH: {DB_SCHEMA_PATH}")
