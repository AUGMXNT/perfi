#!/usr/bin/env bash
set -e
set -x

pr="poetry run python"

# This is an example script that you can modify to do your initial setup

# Clear any existing DB atm (entity create and add_address are not idempotent)
# We leave the cache.db alone
rm data/perfi.db

# Add your entity
$pr bin/cli.py entity create peepo

# Add your address(es)
$pr bin/cli.py entity add_address peepo 'degen wallet' 'ethereum' '0x000...'

# Update Coingecko token list
$pr bin/update_coingecko_pricelist.py

# Get blockchain txs
$pr bin/import_chain_txs.py peepo

# Find and map tx assets
$pr bin/map_assets.py

# Create logical/ledger txs from chain txs
$pr bin/group_transactions.py peepo

# Calculate costbasis lots and disposals
$pr bin/calculate_costbasis.py peepo

# Output a spreadsheet of the results
$pr bin/generate_8949.py peepo
