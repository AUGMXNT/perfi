CREATE TABLE IF NOT EXISTS "cache" (
	"key"	TEXT,
	"value_lzma"	BLOB,
	"saved"	INTEGER,
	"expire"	INTEGER,
	PRIMARY KEY("key")
);
