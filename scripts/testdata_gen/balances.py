"""Holds, quarter-end balances, interest accruals and account analytics derived from the ledger."""
import bisect
import datetime as dt
import statistics

from common import (AS_OF, AS_OF_DATE, WINDOW_START_DATE, at, ds, ident, month_end, quarter_ends, rand_date,
                    rand_dt, rng_for, stamp_bronze, stamp_current, stamp_period, ts, weighted)
from ledger import NOT_CUSTOMER_INITIATED

AFFECTS = ("POSTED", "REVERSED")
ACTIVITY_LABEL = {"TT-POS": "POS_PURCHASE", "TT-WDL": "WITHDRAWAL", "TT-DEP": "DEPOSIT", "TT-MOB-DEP": "DEPOSIT",
                  "TT-ATM-DEP": "DEPOSIT", "TT-XFER-IN": "TRANSFER", "TT-XFER-OUT": "TRANSFER", "TT-CHK": "CHECK",
                  "TT-ACH-DR": "ACH_DEBIT", "TT-WIRE-OUT": "WIRE"}


def build(tables, world):
    rng = rng_for("balances")
    series, txns = _series(world)
    holds = _hold_rows(tables, rng, world)
    _balance_rows(tables, rng, world, series, txns, holds)
    _accrual_rows(tables, rng, world, series, txns)
    _activity_rows(tables, rng, world, txns)
    _trend_rows(tables, rng, world, series)
    _dormancy_rows(tables, rng, world, txns)


def _series(world):
    series = {a["id"]: ([], []) for a in world["accounts"]}
    txns = {a["id"]: [] for a in world["accounts"]}
    for t in world["ledger"]:
        txns[t["account"]["id"]].append(t)
        if t["status"] in AFFECTS:
            times, values = series[t["account"]["id"]]
            times.append(t["at"])
            values.append(t["balance"])
    return series, txns


def balance_on(a, series, day):
    times, values = series[a["id"]]
    i = bisect.bisect_left(times, at(day + dt.timedelta(days=1))) - 1
    return values[i] if i >= 0 else a["start_balance"]


def _hold_rows(tables, rng, world):
    ledger = world["ledger"]
    holds = []
    deposits = [t for t in ledger if t["code"] in ("TT-DEP", "TT-MOB-DEP", "TT-ATM-DEP") and t["status"] == "POSTED" and t["amount"] >= 100000]
    for t in rng.sample(deposits, min(60, len(deposits))):
        placed = t["at"] + dt.timedelta(minutes=1)
        holds.append(dict(account=t["account"], type="DEPOSIT", amount=min(t["amount"], 500000), placed=placed,
                          scheduled=placed + dt.timedelta(days=2), txn=t, reason="Funds availability hold on large deposit",
                          by="SYSTEM_BATCH", legal=None))
    pending_pos = [t for t in ledger if t["code"] == "TT-POS" and t["status"] == "PENDING"]
    older_pos = [t for t in ledger if t["code"] == "TT-POS" and t["status"] == "POSTED" and t["at"] < AS_OF - dt.timedelta(days=30)]
    for t in pending_pos + rng.sample(older_pos, 15):
        placed = t["at"]
        holds.append(dict(account=t["account"], type="AUTHORIZATION", amount=t["amount"], placed=placed,
                          scheduled=placed + dt.timedelta(days=3), txn=t, reason="Card authorization hold",
                          by="SYSTEM_BATCH", legal=None, expire=t["status"] == "POSTED"))
    disputed = [t for t in ledger if t.get("disputed")]
    for t in rng.sample(disputed, min(20, len(disputed))):
        placed = min(t["settled_at"] + dt.timedelta(days=rng.randint(3, 20)), AS_OF - dt.timedelta(hours=2))
        holds.append(dict(account=t["account"], type="DISPUTE", amount=t["amount"], placed=placed,
                          scheduled=placed + dt.timedelta(days=30), txn=t, reason="Disputed transaction pending investigation",
                          by="DISPUTES_TEAM", legal=None))
    series_like = {a["id"]: a for a in world["accounts"]}
    for a in world["accounts"]:
        if a["status"] == "FROZEN":
            placed = at(a["frozen_at"], 10)
            holds.append(dict(account=a, type="LEGAL", amount=max(10000, abs(a["final_balance"]) or 10000), placed=placed,
                              scheduled=None, txn=None, reason="Court order garnishment", by="LEGAL_OPS",
                              legal=f"CASE-{a['frozen_at'].year}-{a['n']:04d}", active=True))
    open_accounts = [a for a in series_like.values() if a["status"] == "OPEN" and a["opened"] < AS_OF_DATE - dt.timedelta(days=120)]
    for i, a in enumerate(rng.sample(open_accounts, 26)):
        placed = rand_dt(rng, at(max(a["opened"], WINDOW_START_DATE)), AS_OF - dt.timedelta(days=1))
        kind = "LEGAL" if i < 4 else "ADMINISTRATIVE"
        holds.append(dict(account=a, type=kind, amount=rng.randint(5, 500) * 1000, placed=placed,
                          scheduled=placed + dt.timedelta(days=rng.randint(5, 60)), txn=None,
                          reason="Levy released after payment" if kind == "LEGAL" else rng.choice(
                              ["Returned mail verification", "Signature card review", "Deceased co-owner review"]),
                          by="LEGAL_OPS" if kind == "LEGAL" else "BRANCH_OPS",
                          legal=f"CASE-{placed.year}-{a['n']:04d}" if kind == "LEGAL" else None))
    holds.sort(key=lambda h: (h["placed"], h["account"]["n"]))
    stem = "account_balances-account_hold"
    for i, h in enumerate(holds):
        scheduled = h["scheduled"]
        if h.get("active") or (scheduled and scheduled > AS_OF):
            status, released = "ACTIVE", None
        elif h.get("expire") or (h["type"] == "ADMINISTRATIVE" and rng.random() < 0.3):
            status, released = "EXPIRED", scheduled
        else:
            status = "RELEASED"
            released = min(scheduled - dt.timedelta(hours=rng.randint(0, 24)), AS_OF - dt.timedelta(minutes=5))
            released = max(released, h["placed"] + dt.timedelta(minutes=5))
        h["end"] = released
        row = tables.add(stem, hold_id=ident("HOLD", 6 + i), account_id=h["account"]["id"], hold_type=h["type"],
                         hold_amount_cents=h["amount"], hold_status=status, hold_reason=h["reason"],
                         placed_at=ts(h["placed"]), scheduled_release_at=ts(scheduled) if scheduled else None,
                         released_at=ts(released) if released else None,
                         related_transaction_id=h["txn"]["id"] if h["txn"] else None, legal_reference=h["legal"],
                         placed_by=h["by"], released_by=("SYSTEM_BATCH" if h["by"] == "SYSTEM_BATCH" else h["by"]) if released else None,
                         source_system=h["account"]["source_system"])
        stamp_bronze(rng, row, released or h["placed"])
    by_account = {}
    for h in holds:
        by_account.setdefault(h["account"]["id"], []).append(h)
    return by_account


def balance_dates(a):
    if a["closed"] and a["closed"] < WINDOW_START_DATE:
        return []
    start = max(a["opened"], WINDOW_START_DATE)
    end = a["closed"] or AS_OF_DATE
    dates = quarter_ends(start, end)
    if not a["closed"]:
        dates.append(AS_OF_DATE)
    return dates


def _balance_rows(tables, rng, world, series, txns, holds):
    stem = "account_balances-account_balance_daily"
    for a in world["accounts"]:
        day_totals = {}
        for t in txns[a["id"]]:
            if t["status"] in AFFECTS:
                entry = day_totals.setdefault(t["at"].date(), [0, 0, 0])
                entry[0] += 1
                entry[1 if t["category"] == "DEBIT" else 2] += t["amount"]
        for day in balance_dates(a):
            ledger_balance = balance_on(a, series, day)
            moment = at(day, 23, 59) if day < AS_OF_DATE else AS_OF
            active = [h for h in holds.get(a["id"], []) if h["placed"] <= moment and (h["end"] is None or h["end"] > moment)]
            hold_amount = sum(h["amount"] for h in active)
            deposit_hold = sum(h["amount"] for h in active if h["type"] == "DEPOSIT")
            pending_debits = pending_credits = 0
            if day == AS_OF_DATE:
                for t in txns[a["id"]]:
                    if t["status"] == "PENDING":
                        if t["category"] == "DEBIT":
                            pending_debits += t["amount"]
                        else:
                            pending_credits += t["amount"]
            samples = [balance_on(a, series, day.replace(day=d)) for d in (1, 8, 15, 22) if d <= day.day] + [ledger_balance]
            ytd = [balance_on(a, series, month_end(day.replace(month=m, day=1))) for m in range(1, day.month)] + [ledger_balance]
            count, debits, credits = day_totals.get(day, [0, 0, 0])
            row = tables.add(stem, account_id=a["id"], balance_date=ds(day), ledger_balance_cents=ledger_balance,
                             available_balance_cents=ledger_balance - hold_amount - pending_debits,
                             collected_balance_cents=ledger_balance - deposit_hold, hold_amount_cents=hold_amount,
                             pending_credits_cents=pending_credits, pending_debits_cents=pending_debits,
                             overdraft_amount_cents=max(0, -ledger_balance),
                             interest_bearing_balance_cents=ledger_balance if a["interest_bearing"] and ledger_balance > 0 else None,
                             day_count=day.timetuple().tm_yday, mtd_average_balance_cents=int(statistics.mean(samples)),
                             ytd_average_balance_cents=int(statistics.mean(ytd)), transaction_count=count,
                             debit_amount_cents=debits, credit_amount_cents=credits, source_system=a["source_system"])
            event = at(day, 23, 30) if day < AS_OF_DATE else AS_OF - dt.timedelta(minutes=rng.randint(40, 90))
            stamp_bronze(rng, row, event, max_lag_hours=6)


def _accrual_rows(tables, rng, world, series, txns):
    stem = "account_balances-interest_accrual"
    for a in world["accounts"]:
        interest_paid = {}
        for t in txns[a["id"]]:
            if t["code"] == "TT-INT" and t["status"] in AFFECTS:
                interest_paid.setdefault(t["at"].year, []).append((t["at"].date(), t["amount"]))
        for day in balance_dates(a):
            balance = balance_on(a, series, day)
            if a["interest_bearing"] and balance > 0:
                kind, apy, base = "CREDIT", a["rate"], balance
            elif a["type"] == "CHECKING" and balance < 0:
                kind, apy, base = "DEBIT", 0.18, -balance
            else:
                continue
            daily = round(apy / 365, 10)
            accrued = int(base * daily)
            tier = None
            if a["type"] == "MONEY_MARKET":
                tier = "TIER1" if base < 5000000 else "TIER2"
            row = tables.add(stem, account_id=a["id"], accrual_date=ds(day), calculation_balance_cents=base,
                             interest_rate=daily, apy=apy, accrued_interest_cents=accrued,
                             mtd_accrued_interest_cents=accrued * day.day,
                             ytd_accrued_interest_cents=accrued * day.timetuple().tm_yday,
                             ytd_interest_paid_cents=sum(v for d, v in interest_paid.get(day.year, []) if d <= day),
                             rate_tier=tier, interest_type=kind, source_system="CORE_BANKING")
            event = at(day, 23, 45) if day < AS_OF_DATE else AS_OF - dt.timedelta(minutes=rng.randint(30, 60))
            stamp_bronze(rng, row, event, max_lag_hours=6)


def _activity_rows(tables, rng, world, txns):
    stem = "account_analytics-account_activity_summary"
    for a in world["accounts"]:
        months = {}
        for t in txns[a["id"]]:
            months.setdefault(t["at"].date().replace(day=1), []).append(t)
        for month, items in sorted(months.items()):
            posted = [t for t in items if t["status"] in AFFECTS]
            if not posted:
                continue
            debits = [t for t in posted if t["category"] == "DEBIT"]
            credits = [t for t in posted if t["category"] == "CREDIT"]
            total_debit, total_credit = sum(t["amount"] for t in debits), sum(t["amount"] for t in credits)
            fees = [t for t in posted if t["code"] in ("TT-FEE", "TT-OD-FEE")]
            negative_days = {t["at"].date() for t in posted if t["balance"] is not None and t["balance"] < 0}
            channel = lambda name: sum(1 for t in posted if t["channel"] == name)
            row = tables.add(stem, account_id=a["id"], summary_month=ds(month), total_transaction_count=len(posted),
                             debit_transaction_count=len(debits), credit_transaction_count=len(credits),
                             total_debit_cents=total_debit, total_credit_cents=total_credit,
                             net_change_cents=total_credit - total_debit,
                             avg_transaction_size_cents=(total_debit + total_credit) // len(posted),
                             atm_transaction_count=channel("ATM"), pos_transaction_count=channel("POS"),
                             ach_transaction_count=channel("ACH"), wire_transaction_count=channel("WIRE"),
                             mobile_deposit_count=sum(1 for t in posted if t["code"] == "TT-MOB-DEP"),
                             branch_transaction_count=channel("BRANCH"),
                             online_transaction_count=sum(1 for t in posted if t["channel"] in ("ONLINE", "MOBILE") and t["code"] != "TT-MOB-DEP"),
                             fee_count=len(fees), total_fees_cents=sum(t["amount"] for t in fees),
                             overdraft_count=sum(1 for t in posted if t["code"] == "TT-OD-FEE"), overdraft_days=len(negative_days),
                             nsf_count=sum(1 for t in items if t["code"] == "TT-ACH-DR" and t["status"] == "RETURNED"),
                             interest_earned_cents=sum(t["amount"] for t in posted if t["code"] == "TT-INT"),
                             last_activity_date=ds(max(t["at"].date() for t in posted)))
            stamp_period(rng, row, month_end(month))


def _trend_rows(tables, rng, world, series):
    stem = "account_analytics-account_balance_trend"
    rows = []
    for a in world["accounts"]:
        balances = [balance_on(a, series, AS_OF_DATE - dt.timedelta(days=89 - k)) for k in range(90)]
        last30 = balances[-30:]
        ma30 = int(statistics.mean(last30))
        monthly = balances[-1] - balances[-31]
        threshold = max(2000, abs(ma30) // 50)
        direction = "INCREASING" if monthly > threshold else ("DECREASING" if monthly < -threshold else "STABLE")
        strength = 0 if direction == "STABLE" else min(100, int(abs(monthly) * 100 / max(abs(ma30), 10000)))
        rows.append((a, balances, ma30, monthly, direction, strength))
    ranked = sorted(r[1][-1] for r in rows)
    for a, balances, ma30, monthly, direction, strength in rows:
        last30 = balances[-30:]
        percentile = int(100 * bisect.bisect_left(ranked, balances[-1]) / max(1, len(ranked) - 1))
        row = tables.add(stem, account_id=a["id"], trend_date=ds(AS_OF_DATE), eod_balance_cents=balances[-1],
                         ma_7d_balance_cents=int(statistics.mean(balances[-7:])), ma_30d_balance_cents=ma30,
                         ma_90d_balance_cents=int(statistics.mean(balances)), daily_change_cents=balances[-1] - balances[-2],
                         weekly_change_cents=balances[-1] - balances[-8], monthly_change_cents=monthly,
                         volatility_30d=round(statistics.pstdev(last30), 1), min_balance_30d_cents=min(last30),
                         max_balance_30d_cents=max(last30), balance_percentile=min(100, percentile),
                         trend_direction=direction, trend_strength=strength)
        stamp_current(rng, row)


def _dormancy_rows(tables, rng, world, txns):
    stem = "account_analytics-dormancy_signal"
    for a in world["accounts"]:
        c = a["customer"]
        initiated = [t for t in txns[a["id"]] if t["code"] not in NOT_CUSTOMER_INITIATED and t["channel"] != "INTERNAL"]
        if initiated:
            last, label = initiated[-1]["at"].date(), ACTIVITY_LABEL.get(initiated[-1]["code"], "DEPOSIT")
        else:
            last = a["dormant_since"] or (a["opened"] if a["opened"] >= WINDOW_START_DATE else
                                          rand_date(rng, a["opened"], WINDOW_START_DATE - dt.timedelta(days=1)))
            label = "DEPOSIT"
        days = (AS_OF_DATE - last).days
        if a["status"] == "ESCHEAT":
            status = "ESCHEAT_ELIGIBLE"
        elif a["status"] == "DORMANT":
            status = "DORMANT"
        elif a["status"] == "CLOSED":
            status = "ACTIVE"
        else:
            status = "ACTIVE" if days < 90 else "AT_RISK" if days < 180 else "PRE_DORMANT" if days < 365 else "DORMANT"
        action = {"ACTIVE": "NONE", "AT_RISK": "OUTREACH", "PRE_DORMANT": weighted(rng, [("OUTREACH", 50), ("CERTIFIED_LETTER", 50)]),
                  "DORMANT": "CERTIFIED_LETTER", "ESCHEAT_ELIGIBLE": "ESCHEAT_PREP"}[status]
        score = {"ACTIVE": rng.randint(0, 20), "AT_RISK": rng.randint(30, 50), "PRE_DORMANT": rng.randint(50, 75),
                 "DORMANT": rng.randint(75, 95), "ESCHEAT_ELIGIBLE": rng.randint(95, 100)}[status]
        if a["status"] == "CLOSED":
            score, action = 0, "NONE"
        dormantish = status in ("PRE_DORMANT", "DORMANT", "ESCHEAT_ELIGIBLE") and a["status"] != "CLOSED"
        attempts = rng.randint(1, 3) if dormantish else 0
        row = tables.add(stem, account_id=a["id"], assessment_date=ds(AS_OF_DATE), days_since_activity=days,
                         last_activity_date=ds(last), last_activity_type=label,
                         days_since_login=min(days, rng.randint(0, 45)) if c["digital"] else None,
                         dormancy_status=status, dormancy_risk_score=score, current_balance_cents=a["final_balance"],
                         has_valid_contact=rng.random() < 0.94,
                         last_contact_date=ds(rand_date(rng, min(last, AS_OF_DATE - dt.timedelta(days=1)), AS_OF_DATE - dt.timedelta(days=1))),
                         reactivation_attempt_count=attempts,
                         last_reactivation_attempt_date=ds(rand_date(rng, last, AS_OF_DATE - dt.timedelta(days=1))) if attempts else None,
                         projected_escheat_date=ds(last + dt.timedelta(days=365 * 3)) if dormantish else None,
                         escheat_state=c["city"][1] if dormantish else None, escheat_period_months=36 if dormantish else None,
                         statement_returned=dormantish and rng.random() < 0.15, recommended_action=action)
        stamp_current(rng, row)
