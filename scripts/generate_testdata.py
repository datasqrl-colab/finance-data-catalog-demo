#!/usr/bin/env python3
"""Generate the catalog's synthetic test data.

The original hand-authored records live unchanged in scripts/testdata_gen/seed/ and are copied
verbatim into every output file; the generator adds synthetic customers, accounts, transactions,
cards, loans and mortgages around them, plus the silver profiles, segments, households and credit
risk signals derived from that book, with activity from February 2023 up to the committed as-of
instant (scripts/testdata_gen/common.py). Output is deterministic: running it twice produces
identical files.

The seed rows keep the identifiers the catalog's snapshot tests are filtered on (CUST-001, ML-001,
ACCT-001 and friends), so generated rows start above the highest seeded number in each table and
never write against a seeded key.

Usage:
    python3 scripts/generate_testdata.py           # rewrite every */testdata/*.jsonl file
    python3 scripts/generate_testdata.py --check   # verify the files on disk match the generator
    python3 scripts/generate_testdata.py --verify  # run the fixture quality gates
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "testdata_gen"))

import accounts
import balances
import cards_loans
import common
import customers
import deposit_rows
import enriched
import ledger
import mortgages

# enriched runs last: every row it writes aggregates what the bronze modules built.
MODULES = [customers, accounts, ledger, deposit_rows, balances, cards_loans, mortgages, enriched]


def build_tables():
    tables = common.Tables()
    world = {}
    for module in MODULES:
        module.build(tables, world)
    return tables


def generate():
    tables = build_tables()
    tables.write()
    total = 0
    for stem in tables.paths:
        count = len(tables.anchors[stem]) + len(tables.generated[stem])
        total += count
        print(f"{count:7d}  {stem}")
    print(f"{total:7d}  total rows")


def main():
    if "--check" in sys.argv[1:]:
        import check
        sys.exit(check.run(build_tables()))
    if "--verify" in sys.argv[1:]:
        import fixture_checks
        sys.exit(fixture_checks.run())
    generate()


if __name__ == "__main__":
    main()
