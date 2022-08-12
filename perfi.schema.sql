CREATE TABLE IF NOT EXISTS "entity" (
	"id"	INTEGER NOT NULL,
	"name"	TEXT NOT NULL,
	"note"	TEXT,
	PRIMARY KEY("id" AUTOINCREMENT),
	CONSTRAINT "entity_name_u" UNIQUE("name")
);
CREATE TABLE IF NOT EXISTS "wallet" (
	"id"	INTEGER,
	"entity_id"	INTEGER,
	"name"	TEXT NOT NULL,
	"protocol"	TEXT NOT NULL,
	"address"	TEXT NOT NULL,
	"type"	TEXT,
	"hdpath"	TEXT,
	"location"	TEXT,
	PRIMARY KEY("id" AUTOINCREMENT)
);
CREATE TABLE IF NOT EXISTS "setting" (
	"key"	TEXT,
	"value"	TEXT,
	PRIMARY KEY("key")
);
CREATE TABLE IF NOT EXISTS "address" (
	"id"	INTEGER,
	"label"	TEXT,
	"chain"	TEXT,
	"address"	TEXT,
	"type"	TEXT,
	"source"	TEXT,
	"entity_id"	INTEGER,
	"ord"	INTEGER,
	UNIQUE("label","chain","address"),
	PRIMARY KEY("id")
);
CREATE TABLE IF NOT EXISTS "prices" (
	"coin_id"	text,
	"symbol"	TEXT,
	"source"	text,
	"epoch"	integer,
	"price"	real,
	CONSTRAINT "prices_pk" UNIQUE("coin_id","source","epoch")
);
CREATE TABLE IF NOT EXISTS "claim_cost" (
	"chain"	TEXT,
	"protocol"	TEXT,
	"gas_required"	INTEGER
, "extra"	TEXT);
CREATE TABLE IF NOT EXISTS "balance_current" (
	"id"	INTEGER,
	"source"	TEXT,
	"address"	TEXT,
	"chain"	TEXT,
	"symbol"	TEXT,
	"exposure_symbol"	TEXT,
	"protocol"	TEXT,
	"label"	TEXT,
	"price"	DECIMAL,
	"amount"	DECIMAL,
	"usd_value"	DECIMAL,
	"updated"	INTEGER,
	"type"	TEXT,
	"locked"	INTEGER,
	"proxy"	TEXT,
	"extra"	TEXT,
	"stable"	INTEGER,
	PRIMARY KEY("id" AUTOINCREMENT)
);

CREATE TABLE IF NOT EXISTS "balance_history" (
     "id"	INTEGER,
     "source"	TEXT,
     "address"	TEXT,
     "chain"	TEXT,
     "symbol"	TEXT,
     "exposure_symbol"	TEXT,
     "protocol"	TEXT,
     "label"	TEXT,
     "price"	DECIMAL,
     "amount"	DECIMAL,
     "usd_value"	DECIMAL,
     "updated"	INTEGER,
     "type"	TEXT,
     "locked"	INTEGER,
     "proxy"	TEXT,
     "extra"	TEXT,
     "stable"	INTEGER,
     PRIMARY KEY("id" AUTOINCREMENT)
);

CREATE TABLE IF NOT EXISTS "cache" (
	"key"	TEXT,
	"value"	BLOB,
	"saved"	INTEGER,
	"expire"	INTEGER,
	PRIMARY KEY("key")
);
CREATE TABLE IF NOT EXISTS "tx_chain" (
"chain"TEXT,
"address"TEXT,
"hash"TEXT,
"timestamp"INTEGER,
raw_data_lzma BLOB,
UNIQUE("chain","address","hash")
);
CREATE TABLE IF NOT EXISTS "asset_tx" (
	"chain"	TEXT,
	"id"	TEXT,
	"symbol"	TEXT,
	"name"	TEXT,
	"type"	TEXT,
	"tag"	TEXT,
	"asset_price_id"	TEXT,
	"raw_data"	TEXT,
	PRIMARY KEY("chain","id")
);
CREATE TABLE IF NOT EXISTS "tx_rel_ledger_logical" (
"tx_ledger_id"TEXT,
"tx_logical_id"TEXT NOT NULL,
"ord"INTEGER,
UNIQUE("tx_ledger_id")
);
CREATE TABLE IF NOT EXISTS "costbasis_mapped_asset" (
    asset_tx_id        text,
    costbasis_asset_id text,
    chain              text
);
CREATE TABLE IF NOT EXISTS "tx_ledger" (
	"id"	TEXT,
	"chain"	TEXT,
	"address"	TEXT,
	"hash"	TEXT,
	"from_address"	TEXT,
	"to_address"	TEXT,
	"asset_tx_id"	TEXT,
	"isfee"	INTEGER,
	"amount"	DECIMAL,
	"timestamp"	INTEGER,
	"direction"	TEXT,
	"tx_ledger_type"	TEXT,
	"asset_price_id"	TEXT,
	"symbol"	TEXT,
	"price_usd"	DECIMAL,
	"to_address_name"	text,
	"from_address_name"	text,
    "price_source"	text,
	PRIMARY KEY("id")
);
CREATE TABLE IF NOT EXISTS "tx_logical" (
	"id"	TEXT,
	"count"	INTEGER NOT NULL,
	"description"	TEXT,
	"note"	TEXT,
	"timestamp"	INTEGER,
	"address"	text NOT NULL,
	"tx_logical_type"	text,
	"flags"	TEXT,
	PRIMARY KEY("id")
);
CREATE TABLE IF NOT EXISTS "costbasis_income" (
"id" INTEGER,
"entity" TEXT,
"address" TEXT,
"net_usd" DECIMAL,
"symbol" TEXT,
"timestamp" INTEGER,
"tx_ledger_id" INTEGER,
"price" DECIMAL,
"amount" DECIMAL,
"lots"TEXT,
PRIMARY KEY("id" AUTOINCREMENT)
);
CREATE TABLE IF NOT EXISTS "costbasis_disposal" (
"id"INTEGER,
"entity"TEXT,
"address"TEXT,
"asset_price_id"TEXT,
"symbol"TEXT,
"amount"DECIMAL,
"timestamp"INTEGER,
"duration_held"INTEGER,
"basis_timestamp" INTEGER,
"basis_tx_ledger_id" TEXT,
"basis_usd" DECIMAL,
"total_usd" DECIMAL,
"tx_ledger_id" INTEGER,
"price_source" TEXT,
PRIMARY KEY("id" AUTOINCREMENT)
);
CREATE TABLE IF NOT EXISTS "costbasis_lot" (
	"tx_ledger_id"	TEXT,
	"entity"	TEXT,
	"address"	TEXT,
	"asset_price_id"	TEXT,
	"symbol"	TEXT,
    "chain"	text,
	"asset_tx_id"	text,
	"original_amount"	DECIMAL,
	"current_amount"	DECIMAL,
	"price_usd"	DECIMAL,
	"basis_usd"	DECIMAL,
	"timestamp"	INTEGER,
	"history"	text,
	"flags"	text,
	"receipt"	INTEGER,
	"price_source" TEXT,
	"locked_for_year" INTEGER,
	PRIMARY KEY("tx_ledger_id")
);
CREATE TABLE IF NOT EXISTS "asset_price" (
	"id"	TEXT,
	"source"	TEXT,
	"symbol"	TEXT,
	"name"	TEXT,
	"raw_data"	TEXT,
	"market_cap"	NUMERIC,
	PRIMARY KEY("id")
);
CREATE TABLE IF NOT EXISTS "event"
(
    id        TEXT    not null,
    source    TEXT    not null,
    action    TEXT    not null,
    data      TEXT    not null,
    timestamp INTEGER not null
);
CREATE INDEX IF NOT EXISTS "idx_rel_tx_logical" ON "tx_rel_ledger_logical" (
	"tx_logical_id"
);
CREATE INDEX IF NOT EXISTS "idx_address_address" ON "address" (
	"address"
);
CREATE INDEX IF NOT EXISTS "idx_address_entity_id" ON "address" (
	"entity_id"
);
CREATE INDEX IF NOT EXISTS "idx_lotmatcher" ON "costbasis_lot" (
	"asset_price_id",
    "chain",
	"asset_tx_id",
	"timestamp",
	"address",
	"price_usd"
);

CREATE TABLE IF NOT EXISTS flag
(
    id          integer not null    constraint flag_pk  primary key     autoincrement,
    target_id   text    not null,
    target_type integer not null,
    name        text    not null,
    description text,
    created_at  integer not null,
    source      text    not null
);

CREATE UNIQUE INDEX IF NOT EXISTS flag_id_uindex
    on "flag" (id);

CREATE INDEX IF NOT EXISTS flag_target_id_and_type_index
    on "flag" (target_id, target_type);
