"""Deposit account master data: products, 992 generated accounts (ACCT-009 … ACCT-1000), holders and status history."""
import datetime as dt

from common import (AS_OF, AS_OF_DATE, WINDOW_START, WINDOW_START_DATE, add_months, at, business_time, ds,
                    ident, lognormal_cents, rand_date, rand_dt, rng_for, stamp_bronze, weighted)

FIRST_ACCOUNT, LAST_ACCOUNT = 9, 1000

# code: (template product, name, category, active, opening min, min balance, fee, waiver, rate, tiers, max tx,
#        interest bearing, effective_from)
NEW_PRODUCTS = {
    "PROD-CHK-PREM": ("PROD-CHK-BASIC", "Premium Checking", "CHECKING", True, 10000, 150000, 1500, True, 0.001, None, None, True, dt.date(2016, 1, 1)),
    "PROD-CHK-BUS": ("PROD-CHK-BASIC", "Business Checking", "CHECKING", True, 50000, 500000, 2500, True, 0.0, None, None, False, dt.date(2012, 1, 1)),
    "PROD-SAV-HY": ("PROD-SAV-STD", "High-Yield Savings", "SAVINGS", True, 10000, 0, 0, False, 0.041, None, 6, True, dt.date(2023, 3, 1)),
    "PROD-MMA-PREM": ("PROD-MMA-TIER", "Premier Money Market", "MONEY_MARKET", True, 1000000, 1000000, 2000, True, 0.035, "{\"tier1\":0.030,\"tier2\":0.035}", 6, True, dt.date(2018, 1, 1)),
    "PROD-CD-6M": ("PROD-CD-12M", "6-Month Certificate of Deposit", "CD", True, 100000, 100000, 0, False, 0.045, None, 0, True, dt.date(2019, 1, 1)),
    "PROD-CD-24M": ("PROD-CD-12M", "24-Month Certificate of Deposit", "CD", True, 100000, 100000, 0, False, 0.040, None, 0, True, dt.date(2019, 1, 1)),
    "PROD-IRA-ROTH": ("PROD-IRA-TRAD", "Roth IRA Savings", "IRA", True, 50000, 0, 0, False, 0.030, None, None, True, dt.date(2014, 1, 1)),
}
TYPE_NAME = {"CHECKING": "Checking", "SAVINGS": "Savings", "MONEY_MARKET": "Money Market",
             "CD": "Certificate of Deposit", "IRA": "IRA"}
CD_TERMS = {"PROD-CD-6M": 6, "PROD-CD-12M": 12, "PROD-CD-24M": 24}
CLOSURE_REASONS = ["Customer requested closure", "Moved to another bank", "Account consolidated",
                   "Closed by bank - low balance"]
UPDATE_REASONS = ["Updated overdraft preference", "Statement preference changed to e-statements",
                  "Tier upgrade", "Nickname updated", "Paper statements reinstated", "Business information update"]


def build(tables, world):
    rng = rng_for("accounts")
    _products(tables, rng)
    accounts = _plan_accounts(rng, world)
    world["accounts"] = accounts
    world["account_by_id"] = {a["id"]: a for a in accounts}
    for a in accounts:
        _assign_status(rng, a)
    # Guarantee a handful of the rarer statuses.
    for status, minimum in (("ESCHEAT", 5), ("FROZEN", 6), ("DORMANT", 10)):
        count = sum(1 for a in accounts if a["status"] == status)
        candidates = [a for a in accounts if a["status"] == "OPEN" and a["type"] != "CD"
                      and a["customer"]["status"] == "ACTIVE" and a["opened"] < dt.date(2020, 1, 1)]
        for a in rng.sample(candidates, max(0, minimum - count)):
            a["status_changes"] = []
            _assign_status(rng, a, forced=status)
    _holders(tables, rng, world, accounts)
    _account_rows(tables, rng, accounts)
    _status_history(tables, rng, accounts)


def _products(tables, rng):
    stem = "deposit_accounts-account_product"
    templates = {r["product_code"]: r for _, r in tables.anchors[stem]}
    for code, (tmpl, name, category, active, opening, minimum, fee, waiver, rate, tiers, max_tx, bearing, eff) in NEW_PRODUCTS.items():
        row = tables.add(stem, templates[tmpl], product_code=code, product_name=name, product_category=category,
                         is_active=active, minimum_opening_deposit_cents=opening, minimum_balance_cents=minimum,
                         monthly_fee_cents=fee, fee_waiver_eligible=waiver,
                         fee_waiver_conditions="Maintain minimum daily balance" if waiver else None,
                         base_interest_rate=rate, rate_tiers=tiers, max_monthly_transactions=max_tx,
                         interest_bearing=bearing, fdic_insured=True, effective_from=ds(eff), effective_to=None,
                         source_system="CORE_BANKING")
        stamp_bronze(rng, row, at(eff, 9))


def _wanted_types(rng, c):
    if c["type"] == "BUSINESS":
        return ["CHECKING"] + (["MONEY_MARKET"] if rng.random() < 0.5 else [])
    if c["type"] == "TRUST":
        return [rng.choice(["MONEY_MARKET", "SAVINGS"])] + (["CD"] if rng.random() < 0.4 else [])
    types = ["CHECKING"] if rng.random() < 0.9 else ["SAVINGS"]
    if "SAVINGS" not in types and rng.random() < 0.55:
        types.append("SAVINGS")
    for kind, p in (("CD", 0.12), ("MONEY_MARKET", 0.08), ("IRA", 0.09 if (c["age"] or 0) >= 25 else 0)):
        if rng.random() < p:
            types.append(kind)
    return types


def _plan_accounts(rng, world):
    planned = []
    for c in world["customers"]:
        for kind in _wanted_types(rng, c):
            planned.append((c, kind))
    target = LAST_ACCOUNT - FIRST_ACCOUNT + 1
    extras = ["SAVINGS", "CD", "MONEY_MARKET", "CHECKING"]
    individuals = [c for c in world["customers"] if c["type"] in ("INDIVIDUAL", "JOINT")]
    while len(planned) < target:
        planned.append((rng.choice(individuals), rng.choice(extras)))
    rng.shuffle(planned)
    planned = planned[:target]
    planned.sort(key=lambda p: (p[0]["start"], p[0]["id"]))
    accounts = []
    for i, (c, kind) in enumerate(planned):
        number = FIRST_ACCOUNT + i
        latest_open = (c["end"] - dt.timedelta(days=45)) if c["end"] else AS_OF_DATE - dt.timedelta(days=3)
        if c["start"] < WINDOW_START_DATE and rng.random() < 0.75:
            opened = rand_date(rng, c["start"], min(latest_open, WINDOW_START_DATE - dt.timedelta(days=1)))
        else:
            opened = rand_date(rng, max(c["start"], WINDOW_START_DATE) if c["start"] < latest_open else c["start"],
                               latest_open)
        opened = min(opened, latest_open)
        if opened < c["start"]:
            opened = c["start"]
        if kind == "CHECKING":
            product = "PROD-CHK-BUS" if c["type"] == "BUSINESS" else weighted(rng, [("PROD-CHK-BASIC", 70), ("PROD-CHK-PREM", 30)])
        elif kind == "SAVINGS":
            product = "PROD-SAV-HY" if opened >= dt.date(2023, 3, 1) and rng.random() < 0.5 else "PROD-SAV-STD"
        elif kind == "MONEY_MARKET":
            product = weighted(rng, [("PROD-MMA-TIER", 60), ("PROD-MMA-PREM", 40)])
        elif kind == "CD":
            choices = [("PROD-CD-6M", 30), ("PROD-CD-24M", 30)] + ([("PROD-CD-12M", 40)] if opened < dt.date(2024, 1, 1) else [])
            product = weighted(rng, choices)
        else:
            product = weighted(rng, [("PROD-IRA-TRAD", 60), ("PROD-IRA-ROTH", 40)])
        median = {"CHECKING": 4500000 if c["type"] == "BUSINESS" else 350000, "SAVINGS": 1200000,
                  "MONEY_MARKET": 5500000, "CD": 2500000, "IRA": 3800000}[kind]
        accounts.append({"id": ident("ACCT", number), "n": number, "customer": c, "type": kind, "product": product,
                         "opened": opened, "closed": None, "closure_reason": None, "status": "OPEN",
                         "number": f"40001{number:05d}", "branch": f"BR-{rng.randint(100, 104)}",
                         "source_system": "COMMERCIAL_BANKING" if c["type"] in ("BUSINESS", "TRUST") else "CORE_BANKING",
                         "initial_balance": lognormal_cents(rng, median, 0.8, 5000, 90000000),
                         "dormant_since": None, "frozen_at": None, "status_changes": [], "holders": []})
    return accounts


def _assign_status(rng, a, forced=None):
    c, opened = a["customer"], a["opened"]
    kind = a["type"]
    rate = {"PROD-CHK-BASIC": None, "PROD-CHK-PREM": 0.001, "PROD-CHK-BUS": None, "PROD-SAV-STD": 0.015,
            "PROD-SAV-HY": 0.041, "PROD-MMA-TIER": 0.025, "PROD-MMA-PREM": 0.035, "PROD-CD-6M": 0.045,
            "PROD-CD-12M": 0.050, "PROD-CD-24M": 0.040, "PROD-IRA-TRAD": 0.030, "PROD-IRA-ROTH": 0.030}[a["product"]]
    a["rate"] = rate
    a["compounding"] = {"CHECKING": "MONTHLY" if rate else None, "SAVINGS": "MONTHLY", "MONEY_MARKET": "DAILY",
                        "CD": "DAILY", "IRA": rng.choice(["MONTHLY", "QUARTERLY", "ANNUALLY"])}[kind]
    a["pay_freq"] = {"CHECKING": "MONTHLY" if rate else None, "SAVINGS": "MONTHLY", "MONEY_MARKET": "MONTHLY",
                     "CD": "AT_MATURITY" if a["product"] != "PROD-CD-24M" else "QUARTERLY", "IRA": "ANNUALLY"}[kind]
    a["interest_bearing"] = rate is not None and rate > 0
    a["maturity"], a["term"] = None, None
    if c["status"] in ("CLOSED", "DECEASED") or (c["status"] == "INACTIVE" and rng.random() < 0.5):
        a["status"] = "CLOSED"
        a["closed"] = max(c["end"], opened + dt.timedelta(days=30))
        a["closure_reason"] = "Deceased - estate settled" if c["status"] == "DECEASED" else "Customer requested closure"
    elif c["status"] == "INACTIVE" and opened < AS_OF_DATE - dt.timedelta(days=800):
        a["status"] = "DORMANT"
    else:
        a["status"] = forced or weighted(rng, [("OPEN", 88), ("CLOSED", 6), ("DORMANT", 3), ("FROZEN", 2), ("ESCHEAT", 1)])
    if a["status"] == "DORMANT" and opened >= AS_OF_DATE - dt.timedelta(days=800):
        a["status"] = "OPEN"
    if a["status"] == "ESCHEAT" and opened >= dt.date(2021, 6, 1):
        a["status"] = "OPEN"
    if a["status"] == "CLOSED" and a["closed"] is None:
        earliest = max(opened + dt.timedelta(days=60), WINDOW_START_DATE)
        if earliest >= AS_OF_DATE - dt.timedelta(days=5):
            a["status"] = "OPEN"
        else:
            a["closed"] = rand_date(rng, earliest, AS_OF_DATE - dt.timedelta(days=5))
            a["closure_reason"] = rng.choice(CLOSURE_REASONS)
    if kind == "CD":
        term = CD_TERMS[a["product"]]
        a["term"] = term
        maturity = add_months(opened, term)
        while maturity < WINDOW_START_DATE:
            maturity = add_months(maturity, term)
        if a["status"] == "CLOSED":
            a["closed"] = min(a["closed"], maturity) if maturity < a["closed"] else a["closed"]
        elif maturity < AS_OF_DATE and rng.random() < 0.55:
            a["status"], a["closed"], a["closure_reason"] = "CLOSED", maturity, "Matured - funds transferred"
        while a["status"] != "CLOSED" and maturity < AS_OF_DATE:
            maturity = add_months(maturity, term)
        a["maturity"] = maturity
    if a["status"] == "DORMANT":
        a["dormant_since"] = rand_date(rng, max(opened, dt.date(2020, 1, 1)), AS_OF_DATE - dt.timedelta(days=400))
        a["status_changes"].append(("OPEN", "DORMANT", a["dormant_since"] + dt.timedelta(days=365),
                                    "No activity for 12 months", "SYSTEM_BATCH", "SYSTEM"))
    elif a["status"] == "ESCHEAT":
        a["dormant_since"] = rand_date(rng, opened, min(dt.date(2022, 6, 1), AS_OF_DATE))
        a["status_changes"].append(("OPEN", "DORMANT", a["dormant_since"] + dt.timedelta(days=365),
                                    "No activity for 12 months", "SYSTEM_BATCH", "SYSTEM"))
        a["status_changes"].append(("DORMANT", "ESCHEAT", a["dormant_since"] + dt.timedelta(days=365 * 3 + 30),
                                    "Escheat period elapsed; funds reported to state", "SYSTEM_BATCH", "SYSTEM"))
    elif a["status"] == "FROZEN":
        a["frozen_at"] = rand_date(rng, max(opened, AS_OF_DATE - dt.timedelta(days=120)), AS_OF_DATE - dt.timedelta(days=2))
        a["status_changes"].append(("OPEN", "FROZEN", a["frozen_at"], rng.choice(["Court order garnishment",
                                    "Suspected account takeover"]), rng.choice(["LEGAL_OPS", "FRAUD_OPS"]),
                                    rng.choice(["SYSTEM", "BRANCH"])))
    elif a["status"] == "CLOSED":
        channel = weighted(rng, [("BRANCH", 40), ("ONLINE", 30), ("PHONE", 20), ("SYSTEM", 10)])
        by = {"BRANCH": f"TELLER-{rng.randint(10, 99):03d}", "ONLINE": c["id"], "PHONE": f"RM-{rng.randint(1, 30):03d}",
              "SYSTEM": "SYSTEM_BATCH"}[channel]
        a["status_changes"].append(("OPEN", "CLOSED", a["closed"], a["closure_reason"], by, channel))
    if rng.random() < 0.15:
        start = max(opened, WINDOW_START_DATE)
        end = a["closed"] or AS_OF_DATE - dt.timedelta(days=1)
        if start < end:
            channel = weighted(rng, [("ONLINE", 50), ("PHONE", 25), ("BRANCH", 25)])
            by = {"BRANCH": f"TELLER-{rng.randint(10, 99):03d}", "ONLINE": c["id"], "PHONE": f"RM-{rng.randint(1, 30):03d}"}[channel]
            a["status_changes"].append(("OPEN", "OPEN", rand_date(rng, start, end), rng.choice(UPDATE_REASONS), by, channel))
    a["status_changes"].sort(key=lambda s: s[2])
    a["overdraft"] = kind == "CHECKING" and rng.random() < 0.5
    a["linked"] = None


def _holders(tables, rng, world, accounts):
    customers = world["customers"]
    individuals = [c for c in customers if c["type"] == "INDIVIDUAL" and c["status"] == "ACTIVE"]
    by_customer = {}
    for a in accounts:
        by_customer.setdefault(a["customer"]["id"], []).append(a)
    for a in accounts:
        # Overdraft link to another open savings or money market account of the same customer.
        if a["overdraft"]:
            options = [b for b in by_customer[a["customer"]["id"]] if b["type"] in ("SAVINGS", "MONEY_MARKET")
                       and b["id"] != a["id"] and b["status"] == "OPEN"]
            a["linked"] = options[0]["id"] if options and rng.random() < 0.7 else None
    stem = "deposit_accounts-account_holder"
    for a in accounts:
        c = a["customer"]
        end = a["closed"] or AS_OF_DATE
        extra = []
        spouse = world["customer_by_id"].get(c["spouse"]) if c["spouse"] else None
        if a["type"] in ("CHECKING", "SAVINGS") and c["type"] == "INDIVIDUAL":
            if spouse and rng.random() < 0.6:
                extra.append(("JOINT", spouse))
            elif rng.random() < 0.08:
                extra.append(("JOINT", rng.choice(individuals)))
        if (a["type"] == "IRA" and rng.random() < 0.7) or (a["type"] == "SAVINGS" and rng.random() < 0.05):
            extra.append(("BENEFICIARY", spouse or rng.choice(individuals)))
        if c["type"] == "TRUST":
            extra.append(("TRUSTEE", rng.choice(individuals)))
        if (c["age"] or 0) >= 70 and rng.random() < 0.15:
            extra.append(("POA", rng.choice(individuals)))
        if c["type"] == "INDIVIDUAL" and (c["age"] or 99) < 26 and rng.random() < 0.35:
            extra.append(("CUSTODIAN", rng.choice(individuals)))
        extra = [(kind, h) for kind, h in extra if h["id"] != c["id"] and max(a["opened"], h["start"]) <= end]
        seen = {c["id"]}
        joint = any(kind == "JOINT" for kind, _ in extra)
        a["holders"].append(c["id"])
        row = tables.add(stem, account_id=a["id"], customer_id=c["id"], holder_type="PRIMARY",
                         ownership_percentage=50.0 if joint else 100.0, has_signing_authority=True,
                         added_date=ds(a["opened"]), removed_date=None, is_active=True,
                         tax_reporting_percentage=50.0 if joint else 100.0, source_system=a["source_system"])
        stamp_bronze(rng, row, business_time(rng, a["opened"]))
        for kind, h in extra:
            if h["id"] in seen:
                continue
            seen.add(h["id"])
            added = max(a["opened"], h["start"])
            removed = None
            if kind == "BENEFICIARY" and rng.random() < 0.15 and added < end - dt.timedelta(days=30):
                removed = rand_date(rng, added + dt.timedelta(days=1), end)
            a["holders"].append(h["id"])
            row = tables.add(stem, account_id=a["id"], customer_id=h["id"], holder_type=kind,
                             ownership_percentage=50.0 if kind == "JOINT" else None,
                             has_signing_authority=kind in ("JOINT", "TRUSTEE", "POA", "CUSTODIAN"), added_date=ds(added),
                             removed_date=ds(removed), is_active=removed is None,
                             tax_reporting_percentage=50.0 if kind == "JOINT" else None,
                             source_system=a["source_system"])
            stamp_bronze(rng, row, business_time(rng, removed or added))


def _account_rows(tables, rng, accounts):
    stem = "deposit_accounts-account"
    templates = {r["account_type"]: r for _, r in tables.anchors[stem]}
    for a in accounts:
        c = a["customer"]
        owner = c["full_name"] if c["type"] in ("BUSINESS", "TRUST") else f"{c['first'].split()[0]} {c['last']}"
        row = tables.add(stem, templates[a["type"]], account_id=a["id"], account_number=a["number"],
                         account_type=a["type"], product_code=a["product"],
                         account_title=f"{owner} {TYPE_NAME[a['type']]}", account_status=a["status"],
                         opened_date=ds(a["opened"]), closed_date=ds(a["closed"]), closure_reason=a["closure_reason"],
                         opening_branch_id=a["branch"], servicing_branch_id=a["branch"], currency_code="USD",
                         interest_rate=a["rate"], compounding_frequency=a["compounding"],
                         interest_payment_frequency=a["pay_freq"], maturity_date=ds(a["maturity"]),
                         original_term_months=a["term"], overdraft_protection_enabled=a["overdraft"],
                         overdraft_linked_account_id=a["linked"], source_system=a["source_system"])
        changes = [s[2] for s in a["status_changes"] if s[2] <= AS_OF_DATE]
        latest = max(changes + [a["opened"]])
        if latest < WINDOW_START_DATE and rng.random() < 0.5:
            event = rand_dt(rng, WINDOW_START, AS_OF - dt.timedelta(days=1))
        else:
            event = business_time(rng, latest)
        stamp_bronze(rng, row, event)


def _status_history(tables, rng, accounts):
    stem = "deposit_accounts-account_status_history"
    for a in accounts:
        for previous, new, day, reason, by, channel in a["status_changes"]:
            if day > AS_OF_DATE - dt.timedelta(days=1):
                continue
            when = business_time(rng, day) if channel != "SYSTEM" else at(day, 2, rng.randint(0, 59))
            row = tables.add(stem, account_id=a["id"], previous_status=previous, new_status=new,
                             change_reason=reason, status_changed_at=when.strftime("%Y-%m-%dT%H:%M:%SZ"),
                             changed_by=by, change_channel=channel,
                             notes="Customer requested via phone banking" if channel == "PHONE" else None,
                             source_system=a["source_system"])
            stamp_bronze(rng, row, when)
