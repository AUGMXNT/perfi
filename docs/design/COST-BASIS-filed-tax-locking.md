# 2022-05-30 Thinking about locking records for tax filing

- figure out snapshotting or archiving or adding a is_locked field to costbasis stuff, or copy stuff to a locked table for a year?
- once a costbasis is USED for submitted taxes, it's FINAL. It shouldn't be edited later.
- the way [bitcoin.tax](http://bitcoin.tax/) does it, when you start each year, it imports the closing values from the previous year.  We need to figure out some best way to handle this too.

## Thoughts
- [Bitcoin.tax](http://bitcoin.tax/) way makes a lot of sense. We should probably follow similar pattern.
- What does it mean for a CB lot to be locked? Means It was used for filing taxes. Going forward from the timestamp of being locked, the only thing that can be changed on the costbasis lot is to be further drawndown (eg. only current_amount can change). We can't allow editing total_usd or basis_usd since that basis has been established and committed to for tax purposes.
- We should export a file containing a snapshot of the closing values for each tax-filed year. Just dump each costbasis_lot row.
- When calculating tax for a year, options are either: 1) construct costbasis lots from all-time, 2) import opening costbasis values for the year (last year's closed values) and calculate the year forward from there. Perhaps eventually we even prevent the calculating for all-time and instead require a year-by-year approach, the same as [bitcoin.tax](http://bitcoin.tax/).

We currently don't allow editing anything about a costbasis_lot. You can only provide a manual price override for a given tx_ledger (which would then be used for the costbasis lot pricing during CostbasisGenerator.process). So, here is a potential timeline for locking behavior:

1. Data is imported from exchange/chain.
2. A tx_ledger's price is edited
3. Costbasis calculation is triggered to generate an 8949 for year X
4. Taxes are filed for year X and all costbasis lots involved for year X are locked with 'year X'
5. Someone decides that the price of the tx_ledger in step 2 should be different and tries to re-adjust the price again.
6. Costbasis re-calculation is triggered for year X. costbasis.regenerate_costbasis_lots deletes all from costbasis_lot, costbasis_disposal, costbasis_income.

At this point we have a problem because we will create the costbasis lot for the tx using the updated price, but we already locked that costbasis for year X to a previous price. We need a way to either a) prevent the price from being updated if the tx_ledger is associated with a locked costbasis_lot or b) overwrite the costbasis lot's total_usd/basis_usd with the locked values after the lot is created.  Approach A might be safer... So, we won't allow editing a price_usd for a tx_ledger if that tx_ledger is associated with a locked costbasis_lot.  This seems to make sense...

Currently spiking out a branch on the above to see how it feels...

Mechanics of locking:

- [x]  locking should be done by creating and applying a LOCK_COSTBASIS_LOT event so we can safely replay it on top of a re-run (since we have stable lot IDs).
- [x]  set locked_for_year column to the integer year (e.g. 2021) that was the first year we ever used this costbasis for filing for. This lets us have a little more metadata than just a boolean is_locked value, which could potentially help if we ever want to know which year was the first year that costbasis got locked for use in filing taxes.
- [x]  prevent tx_ledger price updates for tx_ledgers that are associated with a locked costbasis_lot (the lot's tx_ledger_id matches the tx_ledger's id)

# Actions

### Data

- Create `generated_reports` table, store generated 8949 as blob
    - id
    - entity
    - description text
    - year
    - file blob
    - generate timestamp
    - is_locked / final ?
- `generated_reports.id` is the `locked_id` (added field) we need to store in:
    - `costbasis_lot`
    - `costbasis_disposal`
    

`Costbasis_Lot` column updates:

LOCKED_FOR_8949_ID = NULL (points to generated_reports.id)

CURRENT_AMOUNT_AT_LOCK = NULL (copied over from CURRENT_AMOUNT)
(CURRENT_AMOUNT gets zeroed at lock after copy)
CARRIED_OVER_FROM_LOT_ID = NULL

`Costbasis_Disposal` column updates:

LOCKED_FOR_8949_ID = NULL (points to generated_reports.id)

`Costbasis_`income column updates:

LOCKED_FOR_8949_ID = NULL (points to generated_reports.id)

### Logic

- 8949 Report Generation
    - Output blob into `generated_reports`
    - If on the command line, write the generated report file to disk as well
        - We should print out the generated_reports metadata as well, just to let them know it’s in the DB
        - Command line/web api options
            - list generated reports
            - re-export individual and/or all
            - delete reports
            - edit name/description
        - API just pokes the same command line modules
- Apply lock
    - use generated_reports.id as lock_id
    - apply lock_id to all related to year
        - all disposals and income from the year
        - and all lots related to disposal and income
    - tx_ledger is not locked, but if there is a change to tx_ledgers, then do a check
        - select * from costbasis_* where tx_ledger_id = blah and locked_id is not null
            - if found reject change w/ error (??? or allow force change w/ prompt?)
        - currently, applying a manual edit event to a tx_ledger blows away costbasis but we shouldn’t blow away locked stuff moving
        - before any regens we should probably think about snapshotting…
            - think about space concerns (maybe just warn and check space before doing this)
    - Create carryovers
        - zero out locked amounts, move pre-lock current_amount to
        - add CARRIED_OVER_FROM_LOT_ID
- For safety, make sure we ignore locked lots/disposals for costbasis calculations
    - grep through our costbasis matcher queries
    - they should be zeroed so it shouldn’t matter, but… better to be safe
- Allow user to undo/remove a locked year
    - think about what happens with a carryover - if a carryover has had changes to the lot, then it’s in an inconsitent state.
        - allow you to undo the lock
            - reconcile: leave the carryover if amounts don’t match.
            - in one sense it’s an artifact, but the math is the same and it’s easily traceable since the carryover_id reference remains
    - if not, then it’s fine
        - delete carryover
        - move previous amount back to current
        - null out the locks
        - maybe save a log…

### Snapshot

- make a copy of the entire database & compress - in `/snapshots`
    - we should store metadata in a accompanying json file
        - git version (this is important so we can restore and run code w/ the same schema and matching algorithms)
        - record counts
        - earliest and latest transactions
        - generate_reports
        - last edited
        - snapshot generated
        - last_restored in setting table from snapshot (this may be zero/null)
            - the reason we might want this is if you’re running multiple scenarios and want to see when it was split from
    - we should name snapshot and json as ISO datetimestamp
- restore
    - always make a most-recent snapshot
        - could be a single “autosave” snapshot, but maybe safer to be autosave named
            - description “Autosave at timestamp before restore of snapshot xyz”
    - decompress and overwrite the db
    - give status of snapshot
    - set config to current snapshot
    - V1: no sanity checks, just a warning

## V2 Snapshot Reload Sanity Checks

- V2: after restore give a warning if there was a schema change
    - Sanity Checks
        - does sqlite dump output match schema.sql
        - if difference ok
    - Data sanity
        - regenerate 8949 and see if it matches existing blob
            - (this might be different just due to data source/pricing differences)
    - Show diffs and let the user decide
- V2 Refactor - Tracking Schema changes?
    - sanity check of snapshot vs code version? - it’s possible that there was a breaking change in versions for the db.
    - we should try to apply schema changes?
        - we need a db migration tool in that case
            - alembic?
            - do we need schema versioning?

## V2 Delta

Is there an easier way to diff?

The extra complexity is that any change can have downstream effects

but also, any code changes in between, eg to our cost basis matcher would also have potentially big effects.

- Edit a transaction before the lock period
- Make a snapshot
- Regenerate from year forward
- Snapshot, and look at new snapshot?

Note:

- Locked lots will have a locked `price_usd` and `basis_usd` but if there’s a carry-over, we need to think about how those prices are modifiable/derived from an updated price event… we shouldn’t really care but we should document what happens and think about if we give a refiling warning or not? It may not be possible to efficiently notify you of this even, we should document if so.
    - Or this may happen w a delta

# Current Notes

Once we file for taxes, we need to lock down the costbasis for every tx_ledger that contributed to an 8949 output. Locking down means:

- no editing a tx_ledger price_usd
- no changing the assigned tx_logical for a tx_ledger
- no changing any of the costbasis_disposal, costbasis_income, or costbasis_lot records associated with a tx_ledger that contributed to the 8949

Once we’re ready to lock down the records contributing to an 8949, we should perform the lock by:

- save the 8949 file
    - could store the file in a new `generated_reports` table as blob data. This might be best because it would let us reference the exact report record ID from other rows in tables that contributed to the locked report. (maybe preferred?)
    - alternately could just write to filesystem and just use the file name as a value in a new locked_to column (see below)
    - allow user to later update with a note about when this 8949 was actually submitted as part of filing
- update all associated records for the 8949 to somehow track that they’re locked for edits. options:
    - new boolean-like column `locked_to_8949_xx` where `xx` is a value that lets us link back to the specific report (either by report table ID or file name)
- show this locked status as a kind of flag (non-user-removable) in the UI as well?
    
    
    It’s important to save a copy of the actual 8949 generated, and not just track a locked status on all the contributing records, because if we have a code change that effects the output of 8949s we would still want to know exactly what we filed, even if future code changes would have generated a different file.  
    
    - If we do ever end up in a situation where code changes would generate 8949s that vary from past saved reports, we almost certainly want to flag that to the user so they’re aware.  How? Perhaps we add a feature that re-generates all locked reports with current code and compares the outputs (at least SHA of file) to detect cases where the user might want to re-generate and amend a return?

We should also have an ability to undo the lock status in case of user error or, you know, just because someone wants to mess around and doesn’t care about this level of record keeping and protection.

# Why a simple locking-year field for price is not enough:

- Let’s say you start 2021 w/ 1000 ETH costbasis
- You subtract 500 ETH, and at the end of the year, you lock for 2021
    - LOT A: 500 ETH @ $100 costbasis
- Now, in 2022
    - You will run costbasis processing, and lets say you end up using 200 ETH from that costbasis
        - At this point, we subtract 200 ETH from the $100 costbasis
    - You add a new 2022 transaction that has a +100ETH costbasis at $2000 - due to our HIFO costbasis processing, you’ll want to rerun and subtract from that instead
        - Locking means that we do not change the lots *or* disposals from that year because we would need to refile if we did
        - Because costbasis_lot has only the original and current amount, if we allow regeneration from the start, either any  additional costbasis_lot additions before the locked year, or changes to our costbasis processing, risks that we end up modifying our submitted disposals.
            - We can help protect from this by locking costbasis_disposals for the year as well, but we would need to replay those disposals as a priority to make sure that our costbasis_lot.current_amount is correct
            - this might solve our problems? but feels like it could get us in trouble
            - It may be safer to do what [bitcoin.tax](http://bitcoin.tax) does and then zero out and carry over?
                - If so we want to carry the remainder into a new costbasis_disposal lot, but maybe have a reference to the old lot as well?
                - We should have a frozen_amount field for the locked lot so that we can restore a locked lot after it’s zeroed out if necessary
                - we need to think about making sure locking is reversible, and for refiling
        
        ## Bitcoin.tax-like scenario runthrough
        
        Assume we started trading in year 2021 (no history before 2021 that needs tracking/filing).
        
        **In 2021:**
        
        - Buy 100 ETH @ $50  (LOT A)
        - Buy 10 ETH @ $75  (LOT B)
        - Sell 20 ETH @ 100  (Makes Disposals 1 and 2)
        
        **When filing for 2021 we end up with the following CB Lots and Disposals:**
        
        LOT A:  90 / 100  ETH @ $50
        
        LOT B: 0 / 10  ETH @ $75
        
        Disposal 1: 10 ETH @ $100 (-10 from LOT B @ $75)
        
        Disposal 2: 10 ETH @ $100 (-10 from LOT A @ $50)
        
        **Simple case first: locking a year**
        
        Now we generate 8949, file it, and lock 2021 based on that 8949. This does a few things:
        
        1. Puts the 8949 as a blob in to a Filed/Locked years DB table so we have a unique ID for it (along with tracking the entity and year it belongs to)
        2. Update all of the Lots and Disposals referenced from the 8949
            1. For each Lot and Disposal, update a LOCKED_FOR_8949_ID column with the lock ID from step 1 above
            2. For each Costbasis Lot as ‘locked_lot’
                1. copy its CURRENT_AMOUNT to a CURRENT_AMOUNT_AT_LOCK column (new col)
                2. set its CURRENT_AMOUNT to 0  (to prevent it from participating in any future drawdowns)
                3. create a new Lot as ‘new_lot’ with all the same attrs, except its ORIGINAL_AMOUNT = CURRENT_AMOUNT = locked_lot.current_amount_at_lock   (this allows the remainder locked_lot to participate in future drawdowns under this new lot)
                4. update new_lot.NOTE (or similar) to reflect that it was created as a carry-over from previous year locked lot (just to aid human understanding later when looking at history)
                    1. will we need an explicit carried_over_from_lot_id field?
        
        What happens if, after locking, someone tries to edit a price for a given ledger item in the year that is locked?
        
        - They should not be able to because the year has been locked. See case below for handling un-locking, edits, re-locking.
        - WHAT OTHER CASES HERE NEED TO LOOK TO SEE IF A RELATED LOT IS LOCKED?
        
        **Simple case continued: handling the following year**
        
        No code changes needed. By creating new carry-over lots, transactions in the following year will just work (creating lots/drawdowns as needed with the same data model). Nothing here needs to understand ‘locked’ records.
        
        **More complex case: Unlocking, editing, re-generating/filing**
        
        After 2021 was locked and filed, how do we handle the case where we need to update a transaction in 2021 (because we do want a new 8949 generated)? 
        
        This will, of course, *potentially* require changing *all future years* as well (assuming future years have similar asset txns to the one you changed). So if 2022 was already locked/filed as well, we’d need to unlock/re-gen it as well.
        
        Add a snapshot functionality that literally makes a backup copy of perfi.db?
        
        - **Snapshot** functionality in general
            - We should probalby do a schema and database dump and xz it, note w/ git sha (version)
                - this isn’t perfect, but it means that we can pull a snapshot of a codebase that works with it
                - will give us a little more future proofing since we can still load a snapshot as long as future schema changes don’t conflict (eg are additions)
                - a copy of the db would be more brittle
        - Snapshot viewer should display date, version, some stats
            - what’s locked
            - what reports years or generated?
            - \# of txs? records
            - size and file location
        
        1. User sees that 2021 is locked/filed (need new view to show this status for each year btw).  User clicks on ‘unlock’ for 2021.
        2. Easiest thing to do here is delete all lots/disposals from 2021 onwards, then let the user make whatever changes to transactions as they see fit, then re-generate everything from 2021 onwards for viewing/locking again.  This isn’t a great experience, because it would be helpful to see deltas between previously locked/filed 8949 and the new ones resulting from the unlock/change/re-generate steps.  So maybe it’s better to set everything aside with a soft-delete style db update instead? IDK.
            1. Remember, when doing the re-generation, there may have been other price updates as part of the previous 8949 that user still wants to persist. These are in the events table as manual price updates so we just need to make sure the re-gen logic is correctly re-applying all the manual updates (there is a test for this but good to check our code paths just in case)
        
        Ideally if we want to minimize changes for the future
        
        - list out what’s stable and not
            - chain and tx data is idempotent
            - price oracle probably stable
            - we do a event stream for edits - eg, manual price application
            - costbasis lot  and disposal ids are idempotent b/c they point to the tx ledger id
                - but the actual lots and disposals are not
                
        - keep a copy of the old stuff (invisibly, so it doesn’t interfere with new generation)
        - generate the new stuff
        - match any new stuff against old stuff that’s the same
        - we would want a delta output
        - repeat and show changes for the future years
