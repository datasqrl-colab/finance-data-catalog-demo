"""Credit cards and consumer loans: 244 card accounts, 165 personal loans and 130 auto loans with their history."""
import datetime as dt

from common import (AS_OF, AS_OF_DATE, LAST12_START, WINDOW_START_DATE, add_months, amortized_balance,
                    amortized_payment, at, business_time, days_in_month, due_dates, ds, ident, lognormal_cents,
                    months_between, rand_date, rng_for, stamp_bronze, weighted)

CARD_PRODUCTS = {"BASIC_CARD": ("Everyday Card", (200000, 800000), 0.2199, 0, None, "STANDARD"),
                 "REWARDS_PLUS": ("Rewards Plus Card", (800000, 2500000), 0.1899, 0, "CASHBACK", "GOLD"),
                 "PLATINUM_ELITE": ("Platinum Elite Card", (2000000, 6000000), 0.1599, 45000, "TRAVEL_MILES", "PLATINUM")}
BINS = {"VISA": "4532", "MASTERCARD": "5425"}
VEHICLES = [("Toyota", "Camry", "SE"), ("Honda", "CR-V", "EX"), ("Ford", "F-150", "XLT"), ("Chevrolet", "Silverado", "LT"),
            ("Tesla", "Model 3", "Long Range"), ("Hyundai", "Tucson", "SEL"), ("Subaru", "Outback", "Premium"),
            ("BMW", "X3", "xDrive30i"), ("Kia", "Telluride", "EX"), ("Jeep", "Grand Cherokee", "Limited")]
VIN_CHARS = "ABCDEFGHJKLMNPRSTUVWXYZ0123456789"
CARD_ACCOUNTS, PERSONAL_LOANS, AUTO_LOANS, UNFUNDED_APPLICATIONS = 244, 165, 130, 80


def build(tables, world):
    rng = rng_for("cards_loans")
    individuals = [c for c in world["customers"] if c["type"] == "INDIVIDUAL" and (c["age"] or 0) >= 21]
    world["checking_by_customer"] = {}
    for a in world["accounts"]:
        if a["type"] == "CHECKING":
            world["checking_by_customer"].setdefault(a["customer"]["id"], a["id"])
    cards = _plan_card_accounts(rng, individuals)
    world["card_accounts"] = cards
    for card in cards:
        _statements(tables, rng, card)
    _card_account_rows(tables, rng, cards)
    _card_rows(tables, rng, world, cards, individuals)
    _limit_rows(tables, rng, cards)
    _card_delinquency_rows(tables, rng, cards)
    loans = _plan_loans(rng, individuals)
    world["loans"] = loans
    _application_rows(tables, rng, world, loans, individuals)
    _loan_rows(tables, rng, world, loans)
    _loan_payment_rows(tables, rng, loans)
    _loan_delinquency_rows(tables, rng, loans)


# ---------------------------------------------------------------------------
# Credit cards
# ---------------------------------------------------------------------------

def _plan_card_accounts(rng, individuals):
    owners = sorted(rng.sample(individuals, CARD_ACCOUNTS), key=lambda c: (c["start"], c["id"]))
    cards = []
    for i, c in enumerate(owners):
        earliest = max(c["start"], dt.date(2012, 1, 1))
        latest = (c["end"] - dt.timedelta(days=60)) if c["end"] else AS_OF_DATE - dt.timedelta(days=45)
        opened = earliest if earliest >= latest else rand_date(rng, earliest, latest)
        product = weighted(rng, [("BASIC_CARD", 35), ("REWARDS_PLUS", 45), ("PLATINUM_ELITE", 20)])
        status, closed, reason = "OPEN", None, None
        if c["status"] in ("CLOSED", "DECEASED"):
            status, closed = "CLOSED", max(c["end"], opened + dt.timedelta(days=1))
            reason = "DECEASED" if c["status"] == "DECEASED" else "CUSTOMER_REQUEST"
        else:
            status = weighted(rng, [("OPEN", 85), ("CLOSED", 6), ("SUSPENDED", 4), ("CHARGED_OFF", 5)])
            if status == "CLOSED":
                lo = max(opened + dt.timedelta(days=180), WINDOW_START_DATE)
                if lo < AS_OF_DATE - dt.timedelta(days=10):
                    closed, reason = rand_date(rng, lo, AS_OF_DATE - dt.timedelta(days=10)), rng.choice(["CUSTOMER_REQUEST", "INACTIVITY", "BANK_DECISION"])
                else:
                    status = "OPEN"
            elif status == "CHARGED_OFF":
                lo = max(opened + dt.timedelta(days=365), WINDOW_START_DATE + dt.timedelta(days=200))
                if lo < AS_OF_DATE - dt.timedelta(days=30):
                    closed = rand_date(rng, lo, AS_OF_DATE - dt.timedelta(days=30))
                else:
                    status = "OPEN"
        if status in ("CHARGED_OFF", "SUSPENDED"):
            behavior = "DELINQUENT"
        else:
            behavior = weighted(rng, [("TRANSACTOR", 36), ("REVOLVER", 36), ("MINIMUM_PAYER", 14), ("DELINQUENT", 6), ("INACTIVE", 8)])
        low, high = CARD_PRODUCTS[product][1]
        limit = rng.randint(low // 50000, high // 50000) * 50000
        changes = [("INITIAL", opened, None, limit, "NEW_ACCOUNT", "SYSTEM")]
        end = min(closed or AS_OF_DATE, AS_OF_DATE) - dt.timedelta(days=10)
        cursor = max(opened + dt.timedelta(days=180), WINDOW_START_DATE)
        for kind, p in (("INCREASE", 0.55), ("INCREASE", 0.18), ("DECREASE", 0.6 if behavior == "DELINQUENT" else 0.03)):
            if cursor >= end or rng.random() >= p:
                continue
            effective = rand_date(rng, cursor, end)
            new = limit + rng.choice([100000, 250000, 500000]) if kind == "INCREASE" else max(100000, limit // 2 // 50000 * 50000)
            if new == limit:
                continue
            changes.append((kind, effective, limit, new,
                            rng.choice(["PROACTIVE", "CUSTOMER_REQUEST"]) if kind == "INCREASE" else "RISK_REVIEW",
                            "CUSTOMER" if kind == "INCREASE" and rng.random() < 0.4 else "BANK"))
            limit, cursor = new, effective + dt.timedelta(days=60)
        network = weighted(rng, [("VISA", 65), ("MASTERCARD", 35)])
        cards.append({"id": ident("CCA", 7 + i), "customer": c, "product": product, "status": status, "closed": closed,
                      "reason": reason, "opened": opened, "behavior": behavior, "limit": limit, "changes": changes,
                      "network": network, "last_four": f"{rng.randint(0, 9999):04d}",
                      "cycle_day": rng.choice([5, 10, 12, 15, 20, 25]), "autopay": rng.random() < 0.6,
                      "statements": [], "apr": CARD_PRODUCTS[product][2] + rng.choice([-0.02, 0, 0.02, 0.04])})
    return cards


def _statements(tables, rng, card):
    start = max(LAST12_START, card["opened"] + dt.timedelta(days=30))
    end = min(card["closed"] or AS_OF_DATE, AS_OF_DATE)
    dates = []
    for m in months_between(start - dt.timedelta(days=31), end):
        day = dt.date(m.year, m.month, min(card["cycle_day"], days_in_month(m.year, m.month)))
        if start <= day <= end:
            dates.append(day)
    behavior, limit, apr = card["behavior"], card["limit"], card["apr"]
    spend_median = {"TRANSACTOR": 150000, "REVOLVER": 90000, "MINIMUM_PAYER": 60000, "DELINQUENT": 40000, "INACTIVE": 2000}[behavior]
    prev = {"TRANSACTOR": lognormal_cents(rng, 120000, 0.6, 0, limit), "INACTIVE": 0}.get(
        behavior, min(limit, int(limit * rng.uniform(0.15, 0.6))))
    prev_min, prev_date = max(0, min(prev, 2500 + prev // 50)), None
    for day in dates:
        period_start = (prev_date + dt.timedelta(days=1)) if prev_date else add_months(day, -1) + dt.timedelta(days=1)
        if behavior == "TRANSACTOR" or behavior == "INACTIVE":
            paid = prev
        elif behavior == "REVOLVER":
            paid = max(prev_min, int(prev * rng.uniform(0.05, 0.4)))
        elif behavior == "MINIMUM_PAYER":
            paid = prev_min
        else:
            paid = prev_min if rng.random() < 0.5 else 0
        paid = min(paid, prev)
        late_fee = 3500 if paid < prev_min else 0
        revolving = prev - paid
        interest = int(revolving * apr / 12) if revolving > 0 else 0
        purchases = lognormal_cents(rng, spend_median, 0.6, 0, limit)
        cash = rng.randint(5, 50) * 1000 if rng.random() < 0.03 else 0
        credits = rng.randint(1, 20) * 500 if rng.random() < 0.1 else 0
        annual = CARD_PRODUCTS[card["product"]][3] if day.month == card["opened"].month else 0
        new_balance = max(0, revolving - credits + purchases + cash + interest + late_fee + annual)
        if new_balance > limit:
            purchases = max(0, purchases - (new_balance - limit))
            new_balance = max(0, revolving - credits + purchases + cash + interest + late_fee + annual)
            new_balance = min(new_balance, limit)
        minimum = 0 if new_balance == 0 else min(new_balance, max(2500, new_balance // 50 + interest))
        card["statements"].append({"date": day, "period_start": period_start, "prev": prev, "paid": paid,
                                   "credits": credits, "purchases": purchases, "cash": cash, "fees": late_fee + annual,
                                   "interest": interest, "new": new_balance, "min": minimum,
                                   "due": day + dt.timedelta(days=25)})
        prev, prev_min, prev_date = new_balance, minimum, day


def _card_account_rows(tables, rng, cards):
    stmt_n, pay_n = 6, 6
    for card in cards:
        product = CARD_PRODUCTS[card["product"]]
        for s in card["statements"]:
            limit = card["limit"]
            row = tables.add("credit_cards-credit_card_statement",
                             statement_id=ident("STMT", stmt_n), credit_card_account_id=card["id"],
                             statement_date=ds(s["date"]), period_start_date=ds(s["period_start"]),
                             period_end_date=ds(s["date"]), previous_balance_cents=s["prev"], payments_cents=s["paid"],
                             credits_cents=s["credits"], purchases_cents=s["purchases"], cash_advances_cents=s["cash"],
                             balance_transfers_cents=0, fees_cents=s["fees"], interest_cents=s["interest"],
                             new_balance_cents=s["new"], minimum_payment_cents=s["min"], payment_due_date=ds(s["due"]),
                             credit_limit_cents=limit, available_credit_cents=limit - s["new"],
                             transaction_count=max(0, s["purchases"] // 4500), days_in_cycle=(s["date"] - s["period_start"]).days + 1,
                             avg_daily_balance_cents=(s["prev"] + s["new"]) // 2,
                             rewards_earned=s["purchases"] // 100 if product[4] else 0,
                             rewards_redeemed=rng.choice([0, 0, 0, 2500]) if product[4] else 0, source_system="CARD_PLATFORM")
            stamp_bronze(rng, row, at(s["date"], 23, 59))
            s["id"] = ident("STMT", stmt_n)
            stmt_n += 1
            behavior = card["behavior"]
            amount = s["new"] if behavior in ("TRANSACTOR", "INACTIVE") else (
                s["min"] if behavior == "MINIMUM_PAYER" else (max(s["min"], int(s["new"] * rng.uniform(0.05, 0.4)))
                                                                if behavior == "REVOLVER" else (s["min"] if rng.random() < 0.5 else 0)))
            late = behavior == "DELINQUENT" and rng.random() < 0.4
            received = s["due"] + dt.timedelta(days=rng.randint(3, 35)) if late else s["due"] - dt.timedelta(days=rng.randint(0, 12))
            if amount <= 0 or received > AS_OF_DATE - dt.timedelta(days=1):
                continue
            returned = rng.random() < 0.01
            row = tables.add("credit_cards-credit_card_payment", payment_id=ident("CPMT", pay_n),
                             credit_card_account_id=card["id"], statement_id=s["id"], payment_amount_cents=amount,
                             payment_type="AUTOPAY" if card["autopay"] else "REGULAR",
                             payment_status="RETURNED" if returned else "POSTED",
                             payment_method="ACH" if card["autopay"] or rng.random() < 0.6 else "DEBIT_CARD",
                             source_account=f"****{rng.randint(0, 9999):04d}", source_routing=f"****{rng.randint(0, 9999):04d}",
                             received_date=ds(received), posted_date=ds(received), due_date=ds(s["due"]),
                             days_from_due=(received - s["due"]).days, balance_after_cents=max(0, s["new"] - amount),
                             confirmation_number=f"{'AP' if card['autopay'] else 'ONL'}-{received:%Y%m%d}-{pay_n:05d}",
                             return_reason_code="R01" if returned else None,
                             return_reason="Insufficient funds" if returned else None, source_system="CARD_PLATFORM")
            stamp_bronze(rng, row, business_time(rng, received))
            pay_n += 1
        last = card["statements"][-1] if card["statements"] else None
        closed = card["status"] in ("CLOSED", "CHARGED_OFF")
        statement_balance = 0 if card["status"] == "CLOSED" else (last["new"] if last else 0)
        current = 0 if card["status"] == "CLOSED" else min(card["limit"], statement_balance + (0 if closed else rng.randint(0, 40) * 1000))
        intro = card["opened"] >= add_months(AS_OF_DATE, -15)
        last_activity = card["closed"] if closed else AS_OF_DATE - dt.timedelta(days=rng.randint(0, 20))
        row = tables.add("credit_cards-credit_card_account", credit_card_account_id=card["id"],
                         account_number=f"{BINS[card['network']]}-XXXX-XXXX-{card['last_four']}",
                         primary_customer_id=card["customer"]["id"], product_code=card["product"], product_name=product[0],
                         account_status=card["status"], credit_limit_cents=card["limit"],
                         available_credit_cents=0 if closed else card["limit"] - current, current_balance_cents=current,
                         statement_balance_cents=statement_balance,
                         minimum_payment_due_cents=0 if closed or not last else last["min"],
                         payment_due_date=None if closed or not last else ds(last["due"]), purchase_apr=round(card["apr"], 4),
                         cash_advance_apr=round(card["apr"] + 0.06, 4), balance_transfer_apr=round(card["apr"], 4),
                         penalty_apr=0.2999, penalty_apr_active=card["behavior"] == "DELINQUENT" and card["status"] != "CLOSED",
                         intro_apr=0.0 if intro else None, intro_apr_end_date=ds(add_months(card["opened"], 15)) if intro else None,
                         annual_fee_cents=product[3], opened_date=ds(card["opened"]), closed_date=ds(card["closed"]),
                         closure_reason=card["reason"], last_activity_date=ds(last_activity),
                         statement_cycle_day=card["cycle_day"], autopay_enrolled=card["autopay"],
                         autopay_type=weighted(rng, [("STATEMENT_BALANCE", 50), ("MINIMUM", 25), ("FULL_BALANCE", 25)]) if card["autopay"] else None,
                         rewards_program=product[4], rewards_balance=rng.randint(0, 200) * 250 if product[4] else 0,
                         source_system="CARD_PLATFORM")
        card["current_balance"], card["available"] = current, 0 if closed else card["limit"] - current
        latest = max([card["opened"]] + [s["date"] for s in card["statements"]] + ([card["closed"]] if card["closed"] else []))
        stamp_bronze(rng, row, business_time(rng, latest))


def _card_rows(tables, rng, world, cards, individuals):
    stem = "credit_cards-credit_card"
    number = 9
    for card in cards:
        c = card["customer"]
        tier = CARD_PRODUCTS[card["product"]][5]
        current_issue = card["opened"]
        while add_months(current_issue, 48) < AS_OF_DATE and (not card["closed"] or add_months(current_issue, 48) < card["closed"]):
            current_issue = add_months(current_issue, 48)
        plan = []
        if rng.random() < 0.12 and current_issue < AS_OF_DATE - dt.timedelta(days=200):
            lost_day = rand_date(rng, max(current_issue, WINDOW_START_DATE), AS_OF_DATE - dt.timedelta(days=30))
            plan.append(("PRIMARY", c, weighted(rng, [("LOST", 45), ("STOLEN", 35), ("REPLACED", 20)]), current_issue, lost_day))
            current_issue = lost_day + dt.timedelta(days=3)
        elif current_issue > card["opened"] and rng.random() < 0.06:
            plan.append(("PRIMARY", c, "EXPIRED", add_months(current_issue, -48), current_issue))
        status = {"OPEN": "ACTIVE", "CLOSED": "CLOSED", "SUSPENDED": "INACTIVE", "CHARGED_OFF": "INACTIVE"}[card["status"]]
        plan.append(("PRIMARY", c, status, current_issue, card["closed"] if card["closed"] else None))
        if rng.random() < 0.12:
            holder = world["customer_by_id"].get(c["spouse"]) if c["spouse"] else rng.choice(individuals)
            if holder["id"] != c["id"]:
                plan.append(("AUTHORIZED_USER", holder, status, max(current_issue, holder["start"]), card["closed"]))
        if rng.random() < 0.08 and card["status"] == "OPEN":
            plan.append(("VIRTUAL", c, "ACTIVE", rand_date(rng, max(current_issue, WINDOW_START_DATE), AS_OF_DATE - dt.timedelta(days=5)), None))
        for kind, holder, card_status, issued, changed in plan:
            virtual = kind == "VIRTUAL"
            expiration = add_months(issued, 48).replace(day=1)
            expiration = dt.date(expiration.year, expiration.month, days_in_month(expiration.year, expiration.month))
            if card_status == "EXPIRED":
                expiration = min(expiration, changed - dt.timedelta(days=1))
            activated = min(issued + dt.timedelta(days=rng.randint(1, 10)), AS_OF_DATE - dt.timedelta(days=1))
            status_day = changed or activated
            first = holder["first"].split()[0].upper()
            row = tables.add(stem, card_id=ident("CARD", number), credit_card_account_id=card["id"],
                             cardholder_customer_id=holder["id"],
                             card_last_four=card["last_four"] if kind == "PRIMARY" else f"{rng.randint(0, 9999):04d}",
                             card_type=kind, card_status=card_status,
                             embossed_name=None if virtual else f"{first} {holder['last'].upper()}",
                             expiration_date=ds(expiration), issued_date=ds(issued), activated_date=ds(activated),
                             status_changed_date=ds(status_day), network=card["network"], card_tier=tier,
                             contactless_enabled=not virtual and rng.random() < 0.9, is_virtual=virtual,
                             has_chip=not virtual, pin_status="NOT_SET" if virtual or rng.random() < 0.1 else "SET",
                             spending_limit_cents=rng.choice([50000, 100000, 250000]) if kind == "AUTHORIZED_USER" else None,
                             source_system="CARD_PLATFORM")
            stamp_bronze(rng, row, business_time(rng, status_day))
            number += 1


def _limit_rows(tables, rng, cards):
    stem = "credit_cards-credit_limit_history"
    number = 9
    for card in cards:
        for kind, effective, previous, new, reason, by in card["changes"]:
            row = tables.add(stem, limit_change_id=ident("CLH", number), credit_card_account_id=card["id"],
                             change_type=kind, previous_limit_cents=previous, new_limit_cents=new,
                             change_amount_cents=new - (previous or 0), change_reason=reason, initiated_by=by,
                             effective_date=ds(effective), credit_score_at_change=rng.randint(560, 830),
                             customer_notified=True, notification_date=ds(effective),
                             adverse_action_required=kind == "DECREASE", source_system="CARD_PLATFORM")
            stamp_bronze(rng, row, business_time(rng, effective))
            number += 1


def _card_delinquency_rows(tables, rng, cards):
    stem = "credit_cards-card_delinquency_event"
    events = []
    for card in cards:
        balance = max(card["current_balance"], card["statements"][-1]["new"] if card["statements"] else 50000) or 50000
        if card["status"] == "CHARGED_OFF":
            charge_off = card["closed"]
            ladder = [("DELINQUENCY_START", "30_DAY", 35, 150), ("DELINQUENCY_ROLL", "90_DAY", 95, 90),
                      ("DELINQUENCY_ROLL", "150_DAY", 155, 30), ("CHARGE_OFF", "180_PLUS", 185, 0)]
            for kind, bucket, dpd, days_before in ladder:
                events.append((card, kind, bucket, dpd, charge_off - dt.timedelta(days=days_before), None, balance))
        elif card["behavior"] == "DELINQUENT":
            start = max(card["opened"] + dt.timedelta(days=90), WINDOW_START_DATE)
            if start >= AS_OF_DATE - dt.timedelta(days=60):
                continue
            day = rand_date(rng, start, AS_OF_DATE - dt.timedelta(days=60))
            cured = day + dt.timedelta(days=rng.randint(2, 40))
            events.append((card, "MISSED_PAYMENT", "CURRENT", rng.randint(5, 25), day, cured if rng.random() < 0.6 else None, balance))
            if rng.random() < 0.5:
                roll = day + dt.timedelta(days=30)
                bucket = weighted(rng, [("30_DAY", 60), ("60_DAY", 30), ("120_DAY", 10)])
                events.append((card, "DELINQUENCY_START", bucket, {"30_DAY": 34, "60_DAY": 64, "120_DAY": 125}[bucket], roll,
                               roll + dt.timedelta(days=rng.randint(5, 25)) if rng.random() < 0.5 else None, balance))
    events.sort(key=lambda e: e[4])
    for i, (card, kind, bucket, dpd, day, cured, balance) in enumerate(events):
        cured = min(cured, AS_OF_DATE - dt.timedelta(days=1)) if cured else None
        charge = kind == "CHARGE_OFF"
        row = tables.add(stem, delinquency_event_id=ident("CDE", 6 + i), credit_card_account_id=card["id"],
                         customer_id=card["customer"]["id"], event_type=kind, days_past_due=dpd, delinquency_bucket=bucket,
                         amount_past_due_cents=balance if charge else max(2500, balance // 30),
                         total_balance_cents=balance, event_date=ds(day), cured_date=ds(cured),
                         collection_action="COLLECTION_ASSIGNED" if dpd > 90 else ("COLLECTION_LETTER" if dpd > 30 else "REMINDER_CALL"),
                         collection_agency="Meridian Recovery Group" if dpd > 90 else None,
                         charge_off_date=ds(day) if charge else None, charge_off_amount_cents=balance if charge else None,
                         recovery_amount_cents=0 if charge else None, net_charge_off_cents=balance if charge else None,
                         source_system="CARD_PLATFORM")
        stamp_bronze(rng, row, business_time(rng, cured or day))


# ---------------------------------------------------------------------------
# Consumer loans
# ---------------------------------------------------------------------------

def _plan_loans(rng, individuals):
    loans = []
    for kind, count in (("PERSONAL", PERSONAL_LOANS), ("AUTO", AUTO_LOANS)):
        planned = []
        while len(planned) < count:
            c = rng.choice(individuals)
            earliest = max(c["start"], dt.date(2019, 1, 1))
            latest = (c["end"] - dt.timedelta(days=60)) if c["end"] else AS_OF_DATE - dt.timedelta(days=20)
            if earliest >= latest:
                continue
            if rng.random() < 0.5 and latest > WINDOW_START_DATE:
                funding = rand_date(rng, max(earliest, WINDOW_START_DATE), latest)
            else:
                funding = rand_date(rng, earliest, latest)
            planned.append((funding, c))
        planned.sort(key=lambda p: (p[0], p[1]["id"]))
        for i, (funding, c) in enumerate(planned):
            term = rng.choice([24, 36, 48, 60]) if kind == "PERSONAL" else rng.choice([36, 48, 60, 72])
            score = max(580, min(840, int(rng.gauss(725, 55))))
            base_rate = (0.075 if kind == "PERSONAL" else 0.039) + (0.02 if funding.year >= 2023 else 0)
            rate = round(base_rate + max(0, 780 - score) * (0.0006 if kind == "PERSONAL" else 0.0004), 4)
            amount = lognormal_cents(rng, 1200000 if kind == "PERSONAL" else 3200000, 0.5,
                                     300000 if kind == "PERSONAL" else 800000, 5000000 if kind == "PERSONAL" else 9000000, 10000)
            payment = amortized_payment(amount, rate, term)
            first_payment = add_months(funding, 1)
            maturity = add_months(funding, term)
            status, event_day = "ACTIVE", None
            if maturity < AS_OF_DATE:
                status, event_day = "PAID_OFF", maturity - dt.timedelta(days=rng.randint(0, 60))
            else:
                bad = ("CHARGED_OFF", "SETTLED") if kind == "PERSONAL" else ("CHARGED_OFF", "REPOSSESSED")
                status = weighted(rng, [("ACTIVE", 85), ("PAID_OFF", 8), (bad[0], 4), (bad[1], 3)])
                lo = max(funding + dt.timedelta(days=240), WINDOW_START_DATE + dt.timedelta(days=60))
                if status != "ACTIVE" and lo < AS_OF_DATE - dt.timedelta(days=30):
                    event_day = rand_date(rng, lo, AS_OF_DATE - dt.timedelta(days=30))
                else:
                    status = "ACTIVE"
            last_paid_day = event_day if status == "PAID_OFF" else (event_day - dt.timedelta(days=90) if event_day else AS_OF_DATE)
            made = len(due_dates(first_payment, min(last_paid_day, maturity)))
            balance = 0 if status == "PAID_OFF" else amortized_balance(amount, rate, payment, made)
            loans.append({"kind": kind, "id": ident("PL" if kind == "PERSONAL" else "AL", 6 + i), "customer": c,
                          "funding": funding, "term": term, "score": score, "rate": rate, "amount": amount,
                          "payment": payment, "first_payment": first_payment, "maturity": maturity, "status": status,
                          "event_day": event_day, "made": made, "balance": min(balance, amount),
                          "last_paid_day": last_paid_day, "delinquent": status in ("CHARGED_OFF", "SETTLED", "REPOSSESSED") or
                          (status == "ACTIVE" and rng.random() < 0.07)})
    return loans


def _application_rows(tables, rng, world, loans, individuals):
    stem = "consumer_loans-loan_application"
    apps = []
    for loan in loans:
        submitted = business_time(rng, loan["funding"] - dt.timedelta(days=rng.randint(3, 20)))
        apps.append({"loan": loan, "customer": loan["customer"], "kind": loan["kind"], "submitted": submitted,
                     "status": "FUNDED", "amount": loan["amount"], "term": loan["term"], "score": loan["score"],
                     "rate": loan["rate"]})
    for _ in range(UNFUNDED_APPLICATIONS):
        c = rng.choice(individuals)
        status = weighted(rng, [("DENIED", 45), ("WITHDRAWN", 18), ("IN_REVIEW", 8), ("SUBMITTED", 7), ("APPROVED", 9), ("COUNTER_OFFER", 13)])
        if status in ("IN_REVIEW", "SUBMITTED", "APPROVED"):
            day = rand_date(rng, AS_OF_DATE - dt.timedelta(days=12), AS_OF_DATE - dt.timedelta(days=1))
        else:
            day = rand_date(rng, max(c["start"], WINDOW_START_DATE), AS_OF_DATE - dt.timedelta(days=15))
        kind = weighted(rng, [("PERSONAL", 55), ("AUTO", 45)])
        score = max(540, min(820, int(rng.gauss(680 if status == "DENIED" else 720, 50))))
        apps.append({"loan": None, "customer": c, "kind": kind, "submitted": business_time(rng, day), "status": status,
                     "amount": lognormal_cents(rng, 1500000 if kind == "PERSONAL" else 3000000, 0.5, 300000, 9000000, 10000),
                     "term": rng.choice([36, 48, 60]), "score": score, "rate": round(0.08 + max(0, 780 - score) * 0.0006, 4)})
    apps.sort(key=lambda a: (a["submitted"], a["customer"]["id"]))
    for i, app in enumerate(apps):
        c, loan, status = app["customer"], app["loan"], app["status"]
        app_id = ident("LAPP", 8 + i)
        if loan:
            loan["application_id"] = app_id
        decided = status not in ("SUBMITTED", "IN_REVIEW")
        decision_day = min(app["submitted"].date() + dt.timedelta(days=rng.randint(0, 4)), loan["funding"] if loan else AS_OF_DATE - dt.timedelta(days=1))
        approved = status in ("FUNDED", "APPROVED", "COUNTER_OFFER", "WITHDRAWN")
        approved_amount = app["amount"] if status != "COUNTER_OFFER" else app["amount"] * 3 // 4 // 10000 * 10000
        income = c["income"] or 5000000
        debt = rng.randint(5, 40) * 10000
        spouse = world["customer_by_id"].get(c["spouse"]) if c["spouse"] else None
        job = c.get("employment")
        row = tables.add(stem, application_id=app_id, primary_applicant_customer_id=c["id"],
                         co_applicant_customer_id=spouse["id"] if spouse and rng.random() < 0.3 else None,
                         loan_type=app["kind"],
                         loan_purpose="VEHICLE_PURCHASE" if app["kind"] == "AUTO" else rng.choice(
                             ["HOME_IMPROVEMENT", "DEBT_CONSOLIDATION", "MAJOR_PURCHASE", "MEDICAL", "OTHER"]),
                         requested_amount_cents=app["amount"], requested_term_months=app["term"], application_status=status,
                         submitted_at=app["submitted"].strftime("%Y-%m-%dT%H:%M:%SZ"),
                         decision_date=ds(decision_day) if decided else None,
                         decision_type=("APPROVED" if approved else "DENIED") if decided else None,
                         approved_amount_cents=approved_amount if approved and decided else None,
                         approved_rate=app["rate"] if approved and decided else None,
                         approved_term_months=app["term"] if approved and decided else None,
                         denial_reasons=rng.choice(["INSUFFICIENT_INCOME,EXCESSIVE_DTI", "LOW_CREDIT_SCORE", "LIMITED_CREDIT_HISTORY"]) if status == "DENIED" else None,
                         credit_score=app["score"], annual_income_cents=income, monthly_debt_cents=debt,
                         dti_ratio=round(debt * 1200 / income, 2), employment_status=("RETIRED" if job and job["retired"] else (
                             "SELF_EMPLOYED" if job and job["type"] == "SELF_EMPLOYED" else "EMPLOYED")),
                         employer_name=job["employer"] if job and not job["retired"] else None,
                         years_employed=rng.randint(1, 25) if job and not job["retired"] else None,
                         origination_channel="DEALER" if app["kind"] == "AUTO" and rng.random() < 0.7 else rng.choice(["ONLINE", "BRANCH"]),
                         promo_code=rng.choice(["NEWYR25", "SPRING24", "AUTO26"]) if rng.random() < 0.05 else None,
                         funded_date=ds(loan["funding"]) if loan else None, source_system="CONSUMER_LENDING")
        latest = at(loan["funding"], 11) if loan else (at(decision_day, 15) if decided else app["submitted"])
        stamp_bronze(rng, row, latest)


def _vin(rng):
    return "".join(rng.choice(VIN_CHARS) for _ in range(17))


def _loan_rows(tables, rng, world, loans):
    for loan in loans:
        c = loan["customer"]
        remaining = max(0, loan["term"] - loan["made"]) if loan["status"] == "ACTIVE" else 0
        next_due = None
        if loan["status"] == "ACTIVE":
            upcoming = [d for d in due_dates(loan["first_payment"], loan["maturity"]) if d > AS_OF_DATE]
            next_due = upcoming[0] if upcoming else None
        paid_off = loan["event_day"] if loan["status"] == "PAID_OFF" else None
        account = world["checking_by_customer"].get(c["id"])
        shared = dict(loan_id=loan["id"], application_id=loan["application_id"], primary_borrower_customer_id=c["id"],
                      loan_number=f"{loan['id'][:2]}-{loan['funding'].year}-{rng.randint(10000, 99999)}",
                      loan_status=loan["status"], original_amount_cents=loan["amount"], current_balance_cents=loan["balance"],
                      interest_rate=loan["rate"], rate_type="FIXED" if rng.random() < 0.9 else "VARIABLE",
                      original_term_months=loan["term"], remaining_term_months=remaining,
                      monthly_payment_cents=loan["payment"], funding_date=ds(loan["funding"]),
                      first_payment_date=ds(loan["first_payment"]), maturity_date=ds(loan["maturity"]),
                      next_payment_due_date=ds(next_due), paid_off_date=ds(paid_off),
                      credit_score_at_origination=loan["score"], dti_at_origination=round(rng.uniform(8, 42), 2),
                      autopay_enrolled=rng.random() < 0.7, source_system="CONSUMER_LENDING")
        if loan["kind"] == "PERSONAL":
            row = tables.add("consumer_loans-personal_loan", **shared,
                             loan_purpose=rng.choice(["HOME_IMPROVEMENT", "DEBT_CONSOLIDATION", "MAJOR_PURCHASE", "MEDICAL"]),
                             origination_fee_cents=int(loan["amount"] * rng.choice([0.0, 0.02, 0.03])),
                             disbursement_account_id=account, payment_account_id=account,
                             origination_channel=rng.choice(["ONLINE", "BRANCH"]))
        else:
            make, model, trim = rng.choice(VEHICLES)
            new = rng.random() < 0.55
            value = int(loan["amount"] / rng.uniform(0.8, 0.95)) // 10000 * 10000
            age = (AS_OF_DATE - loan["funding"]).days / 365
            current_value = 0 if loan["status"] in ("PAID_OFF", "REPOSSESSED") else int(value * max(0.35, 1 - 0.15 * age)) // 10000 * 10000
            row = tables.add("consumer_loans-auto_loan", **shared, loan_type="NEW_VEHICLE" if new else "USED_VEHICLE",
                             vehicle_vin=_vin(rng), vehicle_year=loan["funding"].year + (1 if new else -rng.randint(1, 6)),
                             vehicle_make=make, vehicle_model=model, vehicle_trim=trim,
                             mileage_at_origination=rng.randint(3, 40) if new else rng.randint(8000, 70000),
                             vehicle_condition="NEW" if new else rng.choice(["USED", "CERTIFIED"]),
                             vehicle_value_at_origination_cents=value, current_vehicle_value_cents=current_value,
                             ltv_at_origination=round(loan["amount"] * 100 / value, 2),
                             current_ltv=round(loan["balance"] * 100 / current_value, 2) if current_value else 0.0,
                             dealer_name=f"{c['city'][0]} {make}", dealer_id=f"DLR-{make[:3].upper()}-{rng.randint(1, 40):03d}",
                             gap_insurance=rng.random() < 0.4, extended_warranty=rng.random() < 0.3,
                             title_status="RELEASED" if loan["status"] == "PAID_OFF" else "HELD", lien_state=c["city"][1])
        latest = loan["event_day"] or min(loan["last_paid_day"], AS_OF_DATE - dt.timedelta(days=1))
        stamp_bronze(rng, row, business_time(rng, max(latest, loan["funding"])))


def _loan_payment_rows(tables, rng, loans):
    stem = "consumer_loans-loan_payment"
    payments = []
    for loan in loans:
        last = min(loan["last_paid_day"], loan["maturity"], AS_OF_DATE - dt.timedelta(days=1))
        all_dues = due_dates(loan["first_payment"], last)
        for k, due in enumerate(all_dues):
            if due < LAST12_START:
                continue
            payments.append((due, loan, k))
    payments.sort(key=lambda p: (p[0], p[1]["id"]))
    number = 8
    for due, loan, k in payments:
        late = loan["delinquent"] and rng.random() < 0.35
        received = due + dt.timedelta(days=rng.randint(10, 40)) if late else due - dt.timedelta(days=rng.randint(0, 5))
        if received > AS_OF_DATE - dt.timedelta(days=1):
            continue
        balance_before = amortized_balance(loan["amount"], loan["rate"], loan["payment"], k)
        interest = int(balance_before * loan["rate"] / 12)
        principal = max(0, min(balance_before, loan["payment"] - interest))
        payoff = loan["status"] == "PAID_OFF" and due == max(d for d in due_dates(loan["first_payment"], loan["last_paid_day"])) and loan["event_day"] < loan["maturity"]
        amount = (balance_before + interest) if payoff else loan["payment"]
        late_fee = 2500 if late else 0
        returned = rng.random() < 0.01
        row = tables.add(stem, payment_id=ident("LPMT", number), loan_id=loan["id"], loan_type=loan["kind"],
                         payment_amount_cents=amount + late_fee, principal_cents=balance_before if payoff else principal,
                         interest_cents=interest, late_fee_cents=late_fee, other_fees_cents=0,
                         payment_type="PAYOFF" if payoff else "REGULAR", payment_status="RETURNED" if returned else "APPLIED",
                         due_date=ds(due), received_date=ds(received), applied_date=ds(received),
                         payment_method=weighted(rng, [("ACH", 65), ("ONLINE", 30), ("CHECK", 5)]),
                         principal_balance_after_cents=0 if payoff else max(0, balance_before - principal),
                         days_past_due_at_payment=max(0, (received - due).days),
                         confirmation_number=f"ACH-{received:%Y%m%d}-{number:05d}",
                         return_reason_code="R01" if returned else None, source_system="CONSUMER_LENDING")
        stamp_bronze(rng, row, business_time(rng, received))
        number += 1


def _loan_delinquency_rows(tables, rng, loans):
    stem = "consumer_loans-consumer_loan_delinquency_event"
    events = []
    for loan in loans:
        if not loan["delinquent"]:
            continue
        balance = loan["balance"] or loan["payment"] * 6
        if loan["event_day"] and loan["status"] != "PAID_OFF":
            end = loan["event_day"]
            events.append((loan, "DELINQUENCY_START", "30_DAY", 34, end - dt.timedelta(days=150), None, {}))
            events.append((loan, "DELINQUENCY_ROLL", "90_DAY", 95, end - dt.timedelta(days=90), None, {}))
            final = {"CHARGED_OFF": "CHARGE_OFF", "SETTLED": "SETTLEMENT", "REPOSSESSED": "REPOSSESSION"}[loan["status"]]
            extra = {}
            if final == "CHARGE_OFF":
                extra = dict(charge_off_date=ds(end), charge_off_amount_cents=balance, recovery_amount_cents=0)
            elif final == "REPOSSESSION":
                sale = min(end + dt.timedelta(days=rng.randint(20, 60)), AS_OF_DATE - dt.timedelta(days=1))
                sale_amount = balance * rng.randint(40, 70) // 100
                extra = dict(repossession_date=ds(end), repossession_agency="Midwest Recovery Services", sale_date=ds(sale),
                             sale_amount_cents=sale_amount, deficiency_balance_cents=balance - sale_amount)
            else:
                extra = dict(recovery_amount_cents=balance * rng.randint(40, 70) // 100)
            events.append((loan, final, "120_PLUS", 125, end, None, extra))
        else:
            start = max(loan["first_payment"] + dt.timedelta(days=60), WINDOW_START_DATE)
            if start >= AS_OF_DATE - dt.timedelta(days=40):
                continue
            day = rand_date(rng, start, AS_OF_DATE - dt.timedelta(days=40))
            cured = day + dt.timedelta(days=rng.randint(3, 30))
            events.append((loan, "MISSED_PAYMENT", "CURRENT", rng.randint(5, 25), day, cured, {}))
            if rng.random() < 0.4:
                events.append((loan, "DELINQUENCY_START", weighted(rng, [("30_DAY", 70), ("60_DAY", 30)]), 38, day + dt.timedelta(days=30), None, {}))
                events.append((loan, "DELINQUENCY_CURED", "CURRENT", 0, day + dt.timedelta(days=rng.randint(40, 70)), None, {}))
    events = [e for e in events if WINDOW_START_DATE <= e[4] <= AS_OF_DATE - dt.timedelta(days=1)]
    events.sort(key=lambda e: e[4])
    for i, (loan, kind, bucket, dpd, day, cured, extra) in enumerate(events):
        balance = loan["balance"] or loan["payment"] * 6
        fields = dict(repossession_date=None, repossession_agency=None, sale_date=None, sale_amount_cents=None,
                      deficiency_balance_cents=None, charge_off_date=None, charge_off_amount_cents=None,
                      recovery_amount_cents=None)
        fields.update(extra)
        row = tables.add(stem, delinquency_event_id=ident("CLDE", 6 + i), loan_id=loan["id"], loan_type=loan["kind"],
                         customer_id=loan["customer"]["id"], event_type=kind, days_past_due=dpd, delinquency_bucket=bucket,
                         amount_past_due_cents=0 if kind == "DELINQUENCY_CURED" else loan["payment"] * max(1, dpd // 30),
                         total_balance_cents=balance, event_date=ds(day),
                         cured_date=ds(min(cured, AS_OF_DATE - dt.timedelta(days=1))) if cured else None,
                         collection_action="COLLECTION_ASSIGNED" if dpd > 90 else "REMINDER_CALL",
                         collection_agency="Midwest Recovery Services" if dpd > 90 else None, **fields,
                         source_system="CONSUMER_LENDING")
        loan.setdefault("events", []).append((day, bucket))
        stamp_bronze(rng, row, business_time(rng, cured or day))
