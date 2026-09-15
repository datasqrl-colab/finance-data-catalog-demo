#!/usr/bin/env python3
"""Generate the catalog's synthetic test data.

The original hand-authored records live unchanged in scripts/testdata_gen/seed/ and are copied
verbatim into every output file; the generator adds synthetic customers, accounts, transactions,
cards, loans and mortgages around them, with activity from February 2023 up to the committed
as-of instant (scripts/testdata_gen/common.py). Output is deterministic: running it twice
produces identical files.

Usage:
    python3 scripts/generate_testdata.py           # rewrite every */testdata/*.jsonl file
    python3 scripts/generate_testdata.py --check   # verify the files on disk
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "testdata_gen"))

import accounts  # noqa: E402
import balances  # noqa: E402
import cards_loans  # noqa: E402
import common  # noqa: E402
import customers  # noqa: E402
import deposit_rows  # noqa: E402
import ledger  # noqa: E402
import mortgages  # noqa: E402

MODULES = [customers, accounts, ledger, deposit_rows, balances, cards_loans, mortgages]


def generate():
    tables = common.Tables()
    world = {}
    for module in MODULES:
        module.build(tables, world)
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
        sys.exit(check.run())
    generate()


if __name__ == "__main__":
    main()
