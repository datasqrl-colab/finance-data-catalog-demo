"""Quality gates on the generated fixtures, beyond what the SQRL assertions can express.

`generate_testdata.py --check` answers "do the files on disk match the generator". These checks
answer "is what the generator produces fit to consume": that the declared rowtime tracks business
time closely enough for the documented watermark offsets, that verification-result columns carry a
realistic distribution rather than a single value, and that coded columns hold real codes.

Run with `generate_testdata.py --verify`.
"""
import datetime as dt
import json
import os
import re

from common import PROJECT_ROOT, parse_ts

# An append-only table's business timestamp: the column naming the single event the row records.
# Every other bronze table is a CDC snapshot of something with a lifecycle — a wire moves from
# initiated to completed, an application from submitted to decided — and the row arrives when it
# last changed, so `source_updated_at` is its business timestamp and the lifecycle-start column is
# a plain attribute. `check_source_updated_tracks_event` is what holds those tables honest.
BUSINESS_TS = {
    "card_transactions-card_authorization": "authorized_at",
    "card_transactions-card_settlement": "settled_at",
    "card_transactions-card_chargeback": "initiated_at",
    "wire_ach_transactions-wire_transfer": "initiated_at",
    "wire_ach_transactions-ach_transaction": "processed_at",
    "wire_ach_transactions-payment_return": "processed_at",
    "core_transactions-account_transaction": "transaction_at",
    "core_transactions-transaction_reversal": "reversed_at",
    "deposit_accounts-account_status_history": "status_changed_at",
}
# For a CDC row, source_updated_at must sit at or just after the latest business event on the row.
# Columns naming something scheduled rather than something that happened are excluded.
FUTURE_DATED = {"expires_at", "scheduled_release_at"}
SOURCE_UPDATED_SLACK_SECONDS = 1800
# Feeds that arrive as a stream: ingestion is seconds behind the event, not minutes.
STREAMING = {
    "card_transactions-card_authorization", "card_transactions-card_settlement",
    "card_transactions-card_chargeback", "wire_ach_transactions-ach_transaction",
    "wire_ach_transactions-wire_transfer", "wire_ach_transactions-payment_return",
    "core_transactions-account_transaction", "core_transactions-transaction_reversal",
}
STREAMING_P95_SECONDS = 60
BRONZE_P95_SECONDS = 300
BRONZE_MAX_SECONDS = 900

CARD_NOT_PRESENT = ("ECOMMERCE", "MANUAL")
CVV_CODES = {"M", "N", "P", "U", "S"}


def load(root):
    tables = {}
    for lob in sorted(os.listdir(root)):
        lob_path = os.path.join(root, lob)
        if not os.path.isdir(lob_path):
            continue
        for team in sorted(os.listdir(lob_path)):
            testdata = os.path.join(lob_path, team, "testdata")
            if not os.path.isdir(testdata):
                continue
            for name in sorted(os.listdir(testdata)):
                if name.endswith(".jsonl"):
                    with open(os.path.join(testdata, name)) as handle:
                        tables[name[:-6]] = [json.loads(line) for line in handle if line.strip()]
    return tables


def percentile(values, fraction):
    if not values:
        return 0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(len(ordered) * fraction))]


def check_ingestion_lag(tables):
    """ingested_at must sit just behind the business timestamp, not hours or years behind it."""
    failures = []
    for stem, rows in sorted(tables.items()):
        if not rows or "ingested_at" not in rows[0]:
            continue
        column = BUSINESS_TS.get(stem, "source_updated_at")
        lags, negative = [], 0
        for row in rows:
            if row.get(column) is None:
                continue
            delta = (parse_ts(row["ingested_at"]) - parse_ts(row[column])).total_seconds()
            if delta < 0:
                negative += 1
            lags.append(abs(delta))
        if not lags:
            continue
        limit = STREAMING_P95_SECONDS if stem in STREAMING else BRONZE_P95_SECONDS
        p95, worst = percentile(lags, 0.95), max(lags)
        if p95 > limit:
            failures.append(f"{stem}: p95 ingest lag {p95 / 3600:.1f}h behind {column} (limit {limit}s)")
        elif worst > BRONZE_MAX_SECONDS:
            failures.append(f"{stem}: max ingest lag {worst / 3600:.1f}h behind {column} (limit {BRONZE_MAX_SECONDS}s)")
        if negative:
            failures.append(f"{stem}: {negative} rows ingested before {column}")
    return failures


def check_source_updated_tracks_event(tables):
    """On a CDC row, source_updated_at must sit at or just after the latest event it records.

    Without this, a lifecycle table could pass the lag check while its rowtime still ran far ahead
    of, or behind, the business timestamps a consumer reads.
    """
    failures = []
    for stem, rows in sorted(tables.items()):
        if not rows or "ingested_at" not in rows[0] or stem in BUSINESS_TS:
            continue
        behind = 0
        for row in rows:
            updated = parse_ts(row["source_updated_at"])
            events = [parse_ts(v) for k, v in row.items()
                      if k.endswith("_at") and k not in FUTURE_DATED
                      and k not in ("ingested_at", "source_updated_at")
                      and isinstance(v, str) and len(v) == 20 and v.endswith("Z")]
            latest = max(events, default=None)
            if latest is not None and (latest - updated).total_seconds() > SOURCE_UPDATED_SLACK_SECONDS:
                behind += 1
        if behind:
            failures.append(f"{stem}: {behind} rows where source_updated_at precedes the latest event on the row")
    return failures


def check_cvv_result(tables):
    """The network always returns a CVV result card-not-present, and it is not always a match."""
    rows = tables.get("card_transactions-card_authorization", [])
    failures = []
    cnp = [r for r in rows if r.get("entry_mode") in CARD_NOT_PRESENT]
    missing = [r for r in cnp if r.get("cvv_result") is None]
    if missing:
        failures.append(f"card_authorization: {len(missing)} of {len(cnp)} card-not-present rows have null cvv_result")
    present = {r["cvv_result"] for r in rows if r.get("cvv_result") is not None}
    unknown = present - CVV_CODES
    if unknown:
        failures.append(f"card_authorization: cvv_result holds non-standard codes {sorted(unknown)}")
    if "N" not in present:
        failures.append("card_authorization: cvv_result never takes the no-match value 'N'")
    mismatches = [r for r in rows if r.get("cvv_result") == "N"]
    if mismatches:
        declined = sum(1 for r in mismatches if r.get("authorization_status") == "DECLINED")
        matched = [r for r in rows if r.get("cvv_result") == "M"]
        match_declined = sum(1 for r in matched if r.get("authorization_status") == "DECLINED") / max(1, len(matched))
        if declined / len(mismatches) <= match_declined:
            failures.append("card_authorization: cvv_result='N' is not more likely to decline than 'M'")
    return failures


# Every return type's coded vocabulary: NACHA R-codes for ACH returns, NACHA C-codes for
# notifications of change, and ISO 20022 external return reason codes for the wire rails, which
# are not NACHA and have no R-code of their own.
RETURN_CODE_PATTERN = {"ACH_RETURN": r"^R[0-9]{2}$", "ACH_NOC": r"^C[0-9]{2}$",
                       "WIRE_RETURN": r"^[A-Z]{2}[0-9]{2}$", "WIRE_REJECT": r"^[A-Z]{2}[0-9]{2}$"}
# The unauthorized-return family: a consumer building fraud labels reads exactly these.
UNAUTHORIZED_ACH = {"R05", "R07", "R10", "R11", "R29", "R51"}


def check_return_reason_codes(tables):
    """Every return reason is a code from its rail's vocabulary, with the wording alongside it."""
    rows = tables.get("wire_ach_transactions-payment_return", [])
    failures = []
    for row in rows:
        pattern = RETURN_CODE_PATTERN.get(row.get("return_type"))
        code = row.get("return_reason_code")
        if pattern and (code is None or not re.match(pattern, code)):
            failures.append(f"payment_return {row.get('return_id')}: {row.get('return_type')} carries return_reason_code={code!r}")
    missing_description = [r for r in rows if not r.get("return_reason_description")]
    if missing_description:
        failures.append(f"payment_return: {len(missing_description)} rows have no return_reason_description")
    seen = {r.get("return_reason_code") for r in rows if r.get("return_type") == "ACH_RETURN"}
    if not seen & UNAUTHORIZED_ACH:
        failures.append(f"payment_return: no ACH_RETURN carries an unauthorized-return code {sorted(UNAUTHORIZED_ACH)}")
    return failures[:8]


CHECKS = [("ingestion lag", check_ingestion_lag),
          ("source_updated_at tracks event", check_source_updated_tracks_event),
          ("cvv_result distribution", check_cvv_result),
          ("NACHA return codes", check_return_reason_codes)]


def run(root=PROJECT_ROOT):
    tables = load(root)
    total = 0
    for label, check in CHECKS:
        failures = check(tables)
        total += len(failures)
        if failures:
            print(f"FAIL  {label}")
            for line in failures:
                print(f"        {line}")
        else:
            print(f"ok    {label}")
    if total:
        print(f"\n{total} fixture check failures.")
        return 1
    print("\nAll fixture checks pass.")
    return 0
