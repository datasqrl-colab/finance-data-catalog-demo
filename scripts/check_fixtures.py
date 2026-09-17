#!/usr/bin/env python3
"""Fixture invariants for the finance data catalog.

Run from the repository root:  python3 scripts/check_fixtures.py
Prints one line per invariant and exits non-zero when any fails.
"""
import collections
import datetime as dt
import glob
import json
import re
import sys

FAILED = []


def check(ok, label, detail=""):
    print(("  PASS  " if ok else "  FAIL  ") + label + ("  -- " + detail if detail else ""))
    if not ok:
        FAILED.append(label)


def rows(path):
    with open(path) as fh:
        return [json.loads(line) for line in fh if line.strip()]


def ts(value):
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


def pct(values, q):
    values = sorted(values)
    return values[min(len(values) - 1, int(len(values) * q))]


T = "deposits_payments/transactions/testdata/"
A = "deposits_payments/accounts/testdata/"
C = "customer/customer_data/testdata/"

auth = rows(T + "card_transactions-card_authorization.jsonl")
setl = rows(T + "card_transactions-card_settlement.jsonl")
chargeback = rows(T + "card_transactions-card_chargeback.jsonl")
ach = rows(T + "wire_ach_transactions-ach_transaction.jsonl")
wire = rows(T + "wire_ach_transactions-wire_transfer.jsonl")
returns = rows(T + "wire_ach_transactions-payment_return.jsonl")
account = rows(A + "deposit_accounts-account.jsonl")
holder = rows(A + "deposit_accounts-account_holder.jsonl")
customer = rows(C + "customer_master-customer.jsonl")
contact = rows(C + "customer_master-customer_contact.jsonl")


def money_out(record):
    return record.get("direction") == "OUTBOUND" or (
        record.get("direction") == "INBOUND" and record.get("ach_type") == "DEBIT"
    )


print("1. ingested_at trails the business timestamp by seconds")
for path, business in [
    (T + "card_transactions-card_authorization.jsonl", "authorized_at"),
    (T + "card_transactions-card_settlement.jsonl", "settled_at"),
    (T + "card_transactions-card_chargeback.jsonl", "initiated_at"),
    (T + "wire_ach_transactions-ach_transaction.jsonl", "processed_at"),
    (T + "wire_ach_transactions-wire_transfer.jsonl", "initiated_at"),
    (T + "wire_ach_transactions-payment_return.jsonl", "processed_at"),
    (A + "deposit_accounts-account.jsonl", "source_updated_at"),
    (C + "customer_master-customer.jsonl", "source_updated_at"),
    (C + "customer_master-customer_contact.jsonl", "source_updated_at"),
    (C + "customer_master-customer_address.jsonl", "source_updated_at"),
]:
    name = path.rsplit("/", 1)[1].replace(".jsonl", "")
    lags = [
        (ts(r["ingested_at"]) - ts(r[business])).total_seconds()
        for r in rows(path)
        if r.get("ingested_at") and r.get(business)
    ]
    if not lags:
        check(False, name, "no ingested_at/%s pairs" % business)
        continue
    check(
        min(lags) >= 0 and pct(lags, 0.95) <= 600 and max(lags) <= 1800,
        name,
        "min=%.0fs p95=%.0fs max=%.0fs" % (min(lags), pct(lags, 0.95), max(lags)),
    )

print("2. cvv_result models a real verification outcome")
cnp = [r for r in auth if r.get("entry_mode") in ("ECOMMERCE", "MANUAL")]
populated = sum(1 for r in cnp if r.get("cvv_result"))
check(populated == len(cnp), "cvv_result populated on every CNP authorization",
      "%d of %d" % (populated, len(cnp)))
mismatches = sum(1 for r in cnp if r.get("cvv_result") == "N")
check(mismatches >= 10, "cvv_result 'N' present on CNP authorizations", "%d rows" % mismatches)

print("3. return codes agree with return_type")
bad_r = [r for r in returns if r.get("return_type") == "ACH_RETURN"
         and not re.fullmatch(r"R\d{2}", r.get("return_reason_code") or "")]
check(not bad_r, "ACH_RETURN rows carry R-codes", "%d violations" % len(bad_r))
bad_c = [r for r in returns if r.get("return_type") == "ACH_NOC"
         and not re.fullmatch(r"C\d{2}", r.get("return_reason_code") or "")]
check(not bad_c, "ACH_NOC rows carry C-codes", "%d violations" % len(bad_c))

print("4. referential integrity")
auth_ids = {r["authorization_id"] for r in auth}
setl_ids = {r["settlement_id"] for r in setl}
account_ids = {r["account_id"] for r in account}
customer_ids = {r["customer_id"] for r in customer}
ach_ids = {r["ach_transaction_id"] for r in ach}
wire_ids = {r["wire_transfer_id"] for r in wire}
check(all(r["authorization_id"] in auth_ids for r in setl), "settlement -> authorization")
check(all(r["settlement_id"] in setl_ids for r in chargeback), "chargeback -> settlement")
check(all(r["account_id"] in account_ids for r in holder), "account_holder -> account")
check(all(r["customer_id"] in customer_ids for r in holder), "account_holder -> customer")
check(all(r["account_id"] in account_ids for r in auth), "authorization -> account")
check(all(r["account_id"] in account_ids for r in ach), "ach_transaction -> account")
check(all(r["account_id"] in account_ids for r in wire), "wire_transfer -> account")
check(all(r["ach_transaction_id"] in ach_ids for r in returns if r.get("ach_transaction_id")),
      "payment_return -> ach_transaction")
check(all(r["wire_transfer_id"] in wire_ids for r in returns if r.get("wire_transfer_id")),
      "payment_return -> wire_transfer")
ledger_ids = {r["transaction_id"] for r in rows(T + "core_transactions-account_transaction.jsonl")}
check(all(r["transaction_id"] in ledger_ids for r in ach), "ach_transaction -> ledger transaction")
check(all(r["transaction_id"] in ledger_ids for r in wire), "wire_transfer -> ledger transaction")
check(all(r["transaction_id"] in ledger_ids for r in setl), "settlement -> ledger transaction")
mcc_codes = {r["mcc_code"] for r in rows(T + "card_transactions-mcc_reference.jsonl")}
check(all(r.get("mcc_code") in mcc_codes for r in auth), "authorization -> mcc_reference")
missing_reason = [r for r in auth
                  if r.get("authorization_status") == "DECLINED" and not r.get("decline_reason_code")]
check(not missing_reason, "every DECLINED authorization carries a decline_reason_code",
      "%d missing" % len(missing_reason))

print("5. fraud labels are joinable")
fraud = [r for r in chargeback if r.get("chargeback_category") == "FRAUD"]
settlement_by_id = {r["settlement_id"]: r for r in setl}
resolved = sum(1 for r in fraud
               if settlement_by_id.get(r["settlement_id"], {}).get("authorization_id") in auth_ids)
check(len(fraud) >= 15 and resolved == len(fraud),
      "FRAUD chargebacks resolve to an authorization", "%d of %d" % (resolved, len(fraud)))
ach_by_id = {r["ach_transaction_id"]: r for r in ach}
unauthorized = [r for r in returns if r.get("return_type") == "ACH_RETURN"
                and r.get("return_reason_code") in {"R05", "R07", "R10", "R11", "R29", "R51"}]
usable = sum(1 for r in unauthorized if money_out(ach_by_id.get(r.get("ach_transaction_id"), {})))
check(usable >= 3, "unauthorized ACH returns resolve to money-out entries", "%d rows" % usable)

print("6. enum coverage and hour spread")
status = collections.Counter(r.get("account_status") for r in account)
check(all(status.get(s, 0) >= 5 for s in ("OPEN", "CLOSED", "DORMANT", "FROZEN", "ESCHEAT")),
      "account_status covers all five values", str(dict(status)))
astatus = collections.Counter(r.get("authorization_status") for r in auth)
check(all(astatus.get(s, 0) >= 5
          for s in ("APPROVED", "DECLINED", "EXPIRED", "REVERSED", "PENDING")),
      "authorization_status covers all five values", str(dict(astatus)))
category = collections.Counter(r.get("chargeback_category") for r in chargeback)
check(all(category.get(c, 0) >= 3 for c in
          ("FRAUD", "CONSUMER_DISPUTE", "AUTHORIZATION", "PROCESSING_ERROR")),
      "chargeback_category covers all four values", str(dict(category)))
hours = {r["authorized_at"][11:13] for r in auth if r.get("authorized_at")}
check(len(hours) == 24, "card authorizations cover all 24 hours", "%d distinct hours" % len(hours))

print("7. identifiers pinned by ontology.sqrl snapshot tests")
blob = "".join(open(p).read() for p in glob.glob("**/testdata/*.jsonl", recursive=True))
for pinned in ("ACCT-001", "AUTH-001", "CUST-001", "TXN-001", "TXN-002", "WIRE-001"):
    check('"%s"' % pinned in blob, "snapshot-pinned id %s present" % pinned)

print("8. per-entity history is deep enough to compute a baseline")
per_card = collections.Counter(r["card_id"] for r in auth)
median_card = sorted(per_card.values())[len(per_card) // 2]
check(median_card >= 20, "median authorizations per card",
      "median=%d across %d cards" % (median_card, len(per_card)))
outflow = [r["account_id"] for r in ach if money_out(r)]
outflow += [r["account_id"] for r in wire if r.get("direction") == "OUTBOUND"]
per_account = collections.Counter(outflow)
median_account = sorted(per_account.values())[len(per_account) // 2]
check(median_account >= 10, "median money-out payments per active account",
      "median=%d across %d accounts" % (median_account, len(per_account)))

print("9. the CDC stream carries changes")
pairs = collections.defaultdict(set)
for r in contact:
    pairs[(r["customer_id"], r["contact_type"])].add(r["contact_value"])
changed = sum(1 for values in pairs.values() if len(values) > 1)
check(changed >= 20, "customer_contact pairs with more than one value",
      "%d changed pairs of %d" % (changed, len(pairs)))

print("10. engineered clusters and boundary rows")


def window_max(times, seconds):
    times = sorted(t for t in times if t)
    best = 0
    for i, start in enumerate(times):
        j = i
        while j < len(times) and (times[j] - start).total_seconds() <= seconds:
            j += 1
        best = max(best, j - i)
    return best


by_card = collections.defaultdict(list)
declines_by_card = collections.defaultdict(list)
for r in auth:
    by_card[r["card_id"]].append(ts(r.get("authorized_at")))
    if r.get("authorization_status") == "DECLINED":
        declines_by_card[r["card_id"]].append(ts(r.get("authorized_at")))

peaks = {c: window_max(v, 300) for c, v in by_card.items()}
tier1 = sum(1 for p in peaks.values() if 5 <= p <= 7)
tier2 = sum(1 for p in peaks.values() if p >= 8)
near = sum(1 for p in peaks.values() if p == 4)
check(tier1 >= 2, "cards peaking at 5-7 authorizations in 5 minutes", "%d cards" % tier1)
check(tier2 >= 1, "cards peaking at 8+ authorizations in 5 minutes", "%d cards" % tier2)
check(near >= 1, "near-miss card peaking at exactly 4 in 5 minutes", "%d cards" % near)

dpeaks = {c: window_max(v, 600) for c, v in declines_by_card.items() if v}
d3 = sum(1 for p in dpeaks.values() if p >= 3)
check(d3 >= 2, "cards with 3+ declines in 10 minutes", "%d cards" % d3)
dnear = sum(1 for p in dpeaks.values() if p == 2)
check(dnear >= 1, "near-miss card with exactly 2 declines in 10 minutes", "%d cards" % dnear)

outflow = [(r["account_id"], ts(r.get("processed_at")), r.get("amount_cents") or 0)
           for r in ach if money_out(r)]
outflow += [(r["account_id"], ts(r.get("initiated_at")), r.get("amount_cents") or 0)
            for r in wire if r.get("direction") == "OUTBOUND"]
by_account = collections.defaultdict(list)
for account_id, when, amount in outflow:
    if when:
        by_account[account_id].append((when, amount))
bursts = count_only = value_only = 0
for events in by_account.values():
    events.sort()
    for i, (start, _) in enumerate(events):
        j, total = i, 0
        while j < len(events) and (events[j][0] - start).total_seconds() <= 3600:
            total += events[j][1]
            j += 1
        n = j - i
        if n >= 3 and total >= 1000000:
            bursts += 1
        elif n >= 4 and total < 1000000:
            count_only += 1
        elif n == 2 and total >= 1000000:
            value_only += 1
check(bursts >= 2, "3+ money-out payments over $10,000 within an hour", "%d windows" % bursts)
check(count_only >= 1, "near-miss burst: enough payments, too little value",
      "%d windows" % count_only)
check(value_only >= 1, "near-miss burst: enough value, too few payments", "%d windows" % value_only)

account_by_id = {r["account_id"]: r for r in account}
scoreable = [(r["account_id"], r.get("currency_code"), r.get("authorization_amount_cents"))
             for r in auth]
scoreable += [(r["account_id"], r.get("currency_code"), r.get("amount_cents"))
              for r in ach if money_out(r)]
scoreable += [(r["account_id"], r.get("currency_code"), r.get("amount_cents"))
              for r in wire if r.get("direction") == "OUTBOUND"]
escheat = sum(1 for a, _, _ in scoreable
              if account_by_id.get(a, {}).get("account_status") == "ESCHEAT")
check(escheat >= 1, "scoreable payments on an ESCHEAT account", "%d payments" % escheat)
foreign = sum(1 for _, c, _ in scoreable if c and c != "USD")
check(foreign >= 3, "scoreable payments in a non-USD currency", "%d payments" % foreign)
null_amount = sum(1 for _, _, amount in scoreable if amount is None)
check(null_amount >= 2, "scoreable payments with a null amount", "%d payments" % null_amount)
no_key = sum(1 for r in ach if money_out(r)
             and not (r.get("company_id") or r.get("individual_id") or r.get("company_name")))
check(no_key >= 1, "money-out ACH entries with no counterparty identifier", "%d entries" % no_key)

approved = collections.Counter(r["card_id"] for r in auth
                               if r.get("authorization_status") == "APPROVED")
nine = sum(1 for v in approved.values() if v == 9)
check(nine >= 1, "card with exactly 9 approved authorizations", "%d cards" % nine)

burst_cards = {c for c, p in peaks.items() if p >= 5}
settled = {r["authorization_id"] for r in setl if r.get("settlement_status") == "SETTLED"}
precursor = sum(1 for r in auth
                if r["card_id"] in burst_cards and r["authorization_id"] in settled)
check(precursor >= 1, "burst authorization that later settles", "%d authorizations" % precursor)

asof = dt.date(2026, 6, 30)
ages = {(asof - ts(r["authorized_at"]).date()).days for r in auth if r.get("authorized_at")}
check(119 in ages and 120 in ages,
      "authorizations at exactly 119 and 120 days before 2026-06-30",
      "119=%s 120=%s" % (119 in ages, 120 in ages))

print()
if FAILED:
    print("%d invariant(s) failed:" % len(FAILED))
    for name in FAILED:
        print("  -", name)
    sys.exit(1)
print("All invariants hold.")
