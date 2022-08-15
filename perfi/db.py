import atexit
import os
import sqlite3
from decimal import Decimal, Context

import psutil

from .constants.paths import DB_PATH, DB_SCHEMA_PATH

# Decimal adapting from https://stackoverflow.com/questions/6319409/how-to-convert-python-decimal-to-sqlite-numeric
DECIMAL_QUANTIZE_PLACES = (
    Decimal(10) ** -16
)  # Would like to use 18 places but DeBank gives 16 almost always right now so we'll use 16
DECIMAL_QUANTIZE_CONTEXT = Context(prec=100)


def adapt_decimal(d):
    return str(d).encode("ascii")


def convert_decimal(s):
    # Context precision needs to accomodate 18 decimal palces PLUS whatever is to the left of the decimal point. 100 should be enough, right?
    return Decimal(s.decode("ascii")).quantize(
        DECIMAL_QUANTIZE_PLACES, context=DECIMAL_QUANTIZE_CONTEXT
    )


sqlite3.register_adapter(Decimal, adapt_decimal)

sqlite3.register_converter("decimal", convert_decimal)


class DB:
    def __init__(self, db_file=DB_PATH, same_thread=True):
        self.db_file = db_file
        self.fcon = sqlite3.connect(
            db_file, detect_types=sqlite3.PARSE_DECLTYPES, check_same_thread=same_thread
        )
        self.mcon = sqlite3.connect(
            ":memory:",
            detect_types=sqlite3.PARSE_DECLTYPES,
            check_same_thread=same_thread,
        )

        self.fcon.row_factory = sqlite3.Row
        self.mcon.row_factory = sqlite3.Row

        self.con = self.fcon
        self.cur = self.con.cursor()

        self.cur.execute("pragma journal_mode=wal")
        self.cur.execute("pragma synchronous=normal")
        self.cur.execute("pragma temp_store=memory")
        # 100 MiB just in case
        self.cur.execute("pragma cache_size=-100000")

        if db_file != ":memory:":
            free_memory = psutil.virtual_memory().free
            mmap_size = int(1.5 * os.stat(db_file).st_size)
            if free_memory - (200 * 1024 * 1024) > mmap_size:
                self.cur.execute(f"pragma mmap_size={mmap_size}")

        # improve db perf...
        atexit.register(self.optimize)

    def use_mem(self):
        # print('using memory')
        self.fcon.backup(self.mcon)
        self.con = self.mcon
        self.cur = self.mcon.cursor()
        atexit.register(self.save_mem)

    def save_mem(self):
        # print(f'saving db to disk: {self.db_file}')
        self.mcon.backup(self.fcon)

    def query(self, query, params=()):
        if type(params) == str:
            params = (params,)
        self.cur.execute(query, params)
        return self.cur.fetchall()

    def execute(self, query, params=()):
        if type(params) == str:
            params = (params,)
        try:
            self.cur.execute(query, params)
            self.con.commit()
        except:
            self.con.rollback()

    def execute_many(self, query, params=()):
        if type(params) == str:
            params = (params,)
        try:
            self.cur.executemany(query, params)
            self.con.commit()
        except:
            self.con.rollback()

    def create_db(self, schema_path):
        with open(schema_path) as f:
            schema_sql = f.read()
            self.cur.executescript(schema_sql)

    def optimize(self):
        self.cur.execute("pragma optimize")


# Singleton for perfi db
db = DB(same_thread=False)
db_is_empty = len(db.query("select * from sqlite_master")) == 0
if db_is_empty:
    db.create_db(DB_SCHEMA_PATH)
