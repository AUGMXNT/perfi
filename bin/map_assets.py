"""
# TODO: we should run the an update anytime we can't find a mapping
# This script We need to run this to get the latest assets; depends on looking at the asset referenced by the ledger_tx's and mapping; requires updates if there are new unrecognized tokens
echo 'Updating Asset TX'
## TEMP disable
time poetry run python asset_tx_updatedb.py
# TODO: we should integrate the sql for manual overrides
## TEMP disable
time sqlite3 core.db < asset-tx-type-override.sql


echo 'Update Constants for wrapped and costbasis mappings'
time poetry run python asset-constants-generate.py
"""
