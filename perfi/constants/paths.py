import rootpath

# Paths...
ROOT = rootpath.detect()

DATA_DIR = f"{ROOT}/data"
CACHE_DIR = f"{ROOT}/cache"
LOG_DIR = f"{ROOT}/logs"

DB_PATH = f"{DATA_DIR}/perfi.db"
CACHEDB_PATH = f"{CACHE_DIR}/cache.db"

DB_SCHEMA_PATH = f"{ROOT}/perfi.schema.sql"
CACHEDB_SCHEMA_PATH = f"{ROOT}/cache.schema.sql"
