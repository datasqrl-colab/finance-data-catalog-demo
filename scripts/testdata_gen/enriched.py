"""Silver conformed views over the generated book: customer profiles, segments, households and
lifetime value, plus the credit-risk signals derived from cards, consumer loans and mortgages.

This module runs last because every row it writes aggregates what the bronze modules already built.
It writes rows only for generated customers (CUST-009 and up), leaving the hand-authored anchor
customers to the seed rows that the catalog's snapshot tests are filtered on.
"""
import datetime as dt

from common import (AS_OF_DATE, LAST12_START, add_months, ident, month_start, months_between,
                    rand_date, rng_for, stamp_current, stamp_period, weighted)

AGE_BANDS = [(25, "18-24"), (35, "25-34"), (45, "35-44"), (55, "45-54"), (65, "55-64"), (200, "65+")]
TENURE_BANDS = [(12, "NEW"), (36, "GROWING"), (84, "ESTABLISHED"), (10000, "MATURE")]
INCOME_BANDS = [(5000000, "UNDER-50K"), (10000000, "50K-100K"), (15000000, "100K-150K"),
                (25000000, "150K-250K"), (10 ** 12, "250K+")]
LTV_TIERS = [(40, "BRONZE"), (70, "SILVER"), (90, "GOLD"), (101, "PLATINUM")]
UTILIZATION_BANDS = [(10, "VERY_LOW"), (30, "LOW"), (50, "MODERATE"), (75, "HIGH"), (1000, "VERY_HIGH")]
RISK_TIERS = [(20, "SUPER_PRIME"), (40, "PRIME"), (60, "NEAR_PRIME"), (80, "SUBPRIME"), (101, "DEEP_SUBPRIME")]
SEGMENTS = {
    "BEHAVIORAL": [("BEH-CONSERVATIVE", "Conservative Saver", "Low transaction frequency, high savings ratio"),
                   ("BEH-ACTIVE-SPENDER", "Active Spender", "High card and debit activity, low idle balances"),
                   ("BEH-DIGITAL-FIRST", "Digital First", "Almost all activity through online and mobile channels"),
                   ("BEH-BRANCH-LOYAL", "Branch Loyal", "Prefers in-branch and teller-assisted servicing")],
    "VALUE": [("VAL-MASS", "Mass Market", "Standard product holding and balance profile"),
              ("VAL-AFFLUENT", "Affluent", "High balances across deposits and investments"),
              ("VAL-EMERGING", "Emerging Affluent", "Rising income and balance trajectory"),
              ("VAL-PRIVATE", "Private Client", "Top-percentile relationship value")],
    "LIFECYCLE": [("LIFE-NEW-HOMEOWNER", "New Homeowner", "Recently originated first mortgage"),
                  ("LIFE-FAMILY-BUILDER", "Family Builder", "Household growth and rising recurring spend"),
                  ("LIFE-WEALTH-ACCUM", "Wealth Accumulator", "Peak earning years, growing investable balances"),
                  ("LIFE-RETIREMENT", "Retirement", "Drawing down balances, fixed income deposits"),
                  ("LIFE-STUDENT", "Student", "Early tenure, low balances, high digital engagement")],
}


def band(value, table):
    for ceiling, name in table:
        if value < ceiling:
            return name
    return table[-1][1]


def build(tables, world):
    rng = rng_for("enriched")
    customers = world["customers"]
    holdings = _holdings(world)
    _profile_rows(tables, rng, customers, world)
    _segment_rows(tables, rng, customers, holdings)
    _household_rows(tables, rng, customers, world, holdings)
    _lifetime_value_rows(tables, rng, customers, holdings)
    _utilization_rows(tables, rng, world)
    _exposure_rows(tables, rng, customers, holdings)
    _payment_behavior_rows(tables, rng, customers, holdings)
    _rollforward_rows(tables, rng, world)


def _holdings(world):
    """Everything one customer holds, keyed by customer id."""
    out = {c["id"]: {"deposits": [], "cards": [], "personal": [], "auto": [], "mortgages": []}
           for c in world["customers"]}
    for a in world["accounts"]:
        out[a["customer"]["id"]]["deposits"].append(a)
    for card in world["card_accounts"]:
        out[card["customer"]["id"]]["cards"].append(card)
    for loan in world["loans"]:
        out[loan["customer"]["id"]]["personal" if loan["kind"] == "PERSONAL" else "auto"].append(loan)
    for loan in world["mortgages"]:
        out[loan["customer"]["id"]]["mortgages"].append(loan)
    return out


def _tenure_months(c):
    return max(0, (AS_OF_DATE.year - c["start"].year) * 12 + AS_OF_DATE.month - c["start"].month)


# ---------------------------------------------------------------------------
# Customer profile, segments, households and lifetime value
# ---------------------------------------------------------------------------

def _profile_rows(tables, rng, customers, world):
    stem = "customer_enriched-customer_profile"
    for c in customers:
        city = c["city"]
        address = f"{c['street']}, {city[0]}, {city[1]} {c['zip']}"
        tenure = _tenure_months(c)
        row = tables.add(stem, customer_id=c["id"], full_name=c["full_name"],
                         primary_email=c["email"], primary_phone=c["phone_compact"],
                         primary_address=address, primary_city=city[0], primary_state=city[1],
                         primary_postal_code=c["zip"], age_years=c["age"],
                         age_band=band(c["age"], AGE_BANDS) if c["age"] else None,
                         tenure_months=tenure, tenure_band=band(tenure, TENURE_BANDS),
                         customer_type=c["type"], customer_status=c["status"],
                         risk_rating=c["risk_rating"], is_kyc_verified=c["status"] != "CLOSED",
                         is_pep=c["is_pep"], is_digital_enrolled=c["digital"],
                         preferred_channel=weighted(rng, [("EMAIL", 46), ("MOBILE_PUSH", 28),
                                                          ("SMS", 16), ("MAIL", 10)])
                         if c["digital"] else weighted(rng, [("MAIL", 58), ("PHONE", 42)]))
        stamp_current(rng, row)


def _segment_rows(tables, rng, customers, holdings):
    """A current segment per segment type, plus a superseded behavioral one for some customers."""
    stem = "customer_enriched-customer_segment"
    for c in customers:
        held = holdings[c["id"]]
        for segment_type in ("BEHAVIORAL", "VALUE", "LIFECYCLE"):
            code, name, description = _pick_segment(rng, segment_type, c, held)
            effective_from = max(c["start"], rand_date(rng, LAST12_START, AS_OF_DATE - dt.timedelta(days=30)))
            if segment_type == "BEHAVIORAL" and rng.random() < 0.35:
                old_code, old_name, old_description = rng.choice(SEGMENTS["BEHAVIORAL"])
                old_from = max(c["start"], effective_from - dt.timedelta(days=rng.randint(400, 900)))
                if old_from < effective_from:
                    row = tables.add(stem, customer_id=c["id"], segment_type=segment_type,
                                     segment_code=old_code, segment_name=old_name,
                                     segment_description=old_description,
                                     confidence_score=rng.randint(58, 92), model_version="seg-v1.2",
                                     effective_from=old_from.isoformat(),
                                     effective_to=(effective_from - dt.timedelta(days=1)).isoformat(),
                                     is_current=False)
                    stamp_period(rng, row, effective_from)
            row = tables.add(stem, customer_id=c["id"], segment_type=segment_type, segment_code=code,
                             segment_name=name, segment_description=description,
                             confidence_score=rng.randint(62, 98), model_version="seg-v1.3",
                             effective_from=effective_from.isoformat(), effective_to=None, is_current=True)
            stamp_current(rng, row)


def _pick_segment(rng, segment_type, c, held):
    balance = sum(a["final_balance"] for a in held["deposits"])
    if segment_type == "VALUE":
        if balance > 25000000:
            code = "VAL-PRIVATE"
        elif balance > 9000000:
            code = "VAL-AFFLUENT"
        elif balance > 3000000:
            code = "VAL-EMERGING"
        else:
            code = "VAL-MASS"
    elif segment_type == "LIFECYCLE":
        recent_mortgage = any(m["funding"] >= AS_OF_DATE - dt.timedelta(days=730) for m in held["mortgages"])
        if recent_mortgage:
            code = "LIFE-NEW-HOMEOWNER"
        elif (c["age"] or 40) >= 67:
            code = "LIFE-RETIREMENT"
        elif (c["age"] or 40) < 25:
            code = "LIFE-STUDENT"
        elif (c["age"] or 40) >= 50:
            code = "LIFE-WEALTH-ACCUM"
        else:
            code = "LIFE-FAMILY-BUILDER"
    else:
        code = "BEH-DIGITAL-FIRST" if c["digital"] and rng.random() < 0.55 else rng.choice(
            ["BEH-CONSERVATIVE", "BEH-ACTIVE-SPENDER", "BEH-BRANCH-LOYAL"])
    return next(s for s in SEGMENTS[segment_type] if s[0] == code)


def _household_rows(tables, rng, customers, world, holdings):
    """One household per married pair, plus single-member households for a share of the rest."""
    stem = "customer_enriched-customer_household"
    number, seen = 7, set()
    for c in customers:
        if c["id"] in seen or c["type"] not in ("INDIVIDUAL", "JOINT"):
            continue
        spouse = world["customer_by_id"].get(c["spouse"]) if c["spouse"] else None
        if spouse is None and rng.random() < 0.6:
            continue
        members = [c] if spouse is None else [c, spouse]
        seen.update(m["id"] for m in members)
        household_id = ident("HH", number)
        number += 1
        city = c["city"]
        address = f"{c['street']}, {city[0]}, {city[1]} {c['zip']}"
        size = len(members) + (rng.randint(0, 3) if len(members) == 2 else rng.randint(0, 1))
        income = sum(m["income"] or 0 for m in members)
        balance = sum(a["final_balance"] for m in members for a in holdings[m["id"]]["deposits"])
        products = sum(len(holdings[m["id"]][k]) for m in members
                       for k in ("deposits", "cards", "personal", "auto", "mortgages"))
        effective_from = max(m["start"] for m in members)
        for member in members:
            head = member is members[0]
            row = tables.add(stem, household_id=household_id, customer_id=member["id"],
                             household_role="HEAD" if head else "SPOUSE", is_primary=head,
                             household_size=max(size, len(members)),
                             household_income_band=band(income, INCOME_BANDS),
                             household_address=address, household_city=city[0], household_state=city[1],
                             household_postal_code=c["zip"], household_balance_cents=balance,
                             household_product_count=products,
                             match_method="RELATIONSHIP" if spouse else "ADDRESS",
                             confidence_score=rng.randint(88, 99) if spouse else rng.randint(62, 86),
                             effective_from=effective_from.isoformat(), effective_to=None, is_current=True)
            stamp_current(rng, row)


def _lifetime_value_rows(tables, rng, customers, holdings):
    """A quarterly CLV calculation over the last year."""
    stem = "customer_enriched-customer_lifetime_value"
    for c in customers:
        held = holdings[c["id"]]
        tenure = _tenure_months(c)
        deposits = sum(a["final_balance"] for a in held["deposits"])
        lending = (sum(l["balance"] for l in held["personal"] + held["auto"])
                   + sum(m["balance"] for m in held["mortgages"]))
        cards = sum(card["current_balance"] for card in held["cards"])
        for calculation_date in _quarterly_dates(c):
            deposit_revenue = int(deposits * 0.008) + rng.randint(0, 20000)
            lending_revenue = int(lending * 0.012) + int(cards * 0.09)
            fee_revenue = rng.randint(0, 45000)
            interchange = rng.randint(2000, 90000) if held["cards"] else rng.randint(0, 25000)
            historical = int((deposit_revenue + lending_revenue + fee_revenue + interchange) * max(1, tenure) / 12)
            churn = round(min(0.95, max(0.01, rng.gauss(0.12, 0.07))), 4)
            predicted_tenure = max(6, int((1 - churn) * rng.randint(90, 220)))
            predicted = int((deposit_revenue + lending_revenue + fee_revenue + interchange) * predicted_tenure / 12)
            percentile = max(1, min(99, int(rng.gauss(50, 24))))
            row = tables.add(stem, customer_id=c["id"], calculation_date=calculation_date.isoformat(),
                             historical_ltv_cents=historical, predicted_ltv_cents=predicted,
                             total_ltv_cents=historical + predicted, ltv_percentile=percentile,
                             ltv_tier=band(percentile, LTV_TIERS), deposit_revenue_cents=deposit_revenue,
                             lending_revenue_cents=lending_revenue, fee_revenue_cents=fee_revenue,
                             interchange_revenue_cents=interchange, churn_probability=churn,
                             predicted_tenure_months=predicted_tenure, model_version="clv-v2.2")
            stamp_period(rng, row, calculation_date)


def _quarterly_dates(c):
    out = []
    for month in months_between(LAST12_START, AS_OF_DATE):
        if month.month % 3 == 1 and month >= month_start(c["start"]):
            out.append(month)
    return out


# ---------------------------------------------------------------------------
# Credit risk signals
# ---------------------------------------------------------------------------

def _utilization_rows(tables, rng, world):
    """A monthly utilization snapshot per open card account over the last year."""
    stem = "credit_risk_signals-credit_utilization"
    for card in world["card_accounts"]:
        if card["status"] not in ("OPEN", "SUSPENDED"):
            continue
        limit = card["limit"]
        for month in months_between(LAST12_START, AS_OF_DATE):
            utilization_date = month.replace(day=min(24, month.day or 1))
            if utilization_date < card["opened"] or utilization_date > AS_OF_DATE:
                continue
            balance = max(0, min(limit, int(card["current_balance"] * rng.uniform(0.55, 1.25))))
            rate = round(min(999.99, balance * 100 / max(1, limit)), 2)
            prior30 = round(min(999.99, max(0.0, rate + rng.uniform(-9, 9))), 2)
            prior90 = round(min(999.99, max(0.0, rate + rng.uniform(-16, 16))), 2)
            row = tables.add(stem, credit_card_account_id=card["id"], customer_id=card["customer"]["id"],
                             utilization_date=utilization_date.isoformat(),
                             current_balance_cents=balance, credit_limit_cents=limit,
                             utilization_rate=rate, utilization_band=band(rate, UTILIZATION_BANDS),
                             avg_utilization_7d=round(min(999.99, max(0.0, rate + rng.uniform(-3, 3))), 2),
                             avg_utilization_30d=prior30, avg_utilization_90d=prior90,
                             utilization_change_30d=round(rate - prior30, 2),
                             utilization_change_90d=round(rate - prior90, 2),
                             peak_utilization_30d=round(min(999.99, rate + rng.uniform(0, 12)), 2),
                             days_over_90_pct=rng.randint(0, 12) if rate > 85 else 0,
                             available_credit_cents=max(0, limit - balance),
                             distance_to_limit_cents=max(0, limit - balance),
                             cash_advance_utilization=round(rng.uniform(0, 8), 2) if rng.random() < 0.12 else 0.0,
                             trend_direction="INCREASING" if rate > prior30 + 1 else
                                             ("DECREASING" if rate < prior30 - 1 else "STABLE"),
                             high_utilization_flag=rate >= 75)
            stamp_period(rng, row, month)


def _exposure_rows(tables, rng, customers, holdings):
    """A monthly total-credit-exposure snapshot per customer that holds any credit product."""
    stem = "credit_risk_signals-customer_credit_exposure"
    for c in customers:
        held = holdings[c["id"]]
        if not (held["cards"] or held["personal"] or held["auto"] or held["mortgages"]):
            continue
        for month in months_between(LAST12_START, AS_OF_DATE):
            snapshot_date = month.replace(day=min(25, month.day or 1))
            if snapshot_date > AS_OF_DATE:
                continue
            open_cards = [k for k in held["cards"] if k["status"] in ("OPEN", "SUSPENDED")]
            card_limit = sum(k["limit"] for k in open_cards)
            card_balance = sum(k["current_balance"] for k in open_cards)
            personal = sum(l["balance"] for l in held["personal"])
            auto = sum(l["balance"] for l in held["auto"])
            mortgage = sum(m["balance"] for m in held["mortgages"])
            exposure = card_balance + personal + auto + mortgage
            installment = personal + auto + mortgage
            past_due, worst, delinquent = _delinquency_summary(held)
            score = _current_score(rng, c, held, past_due)
            risk = _risk_score(rng, score, card_limit, card_balance, delinquent)
            row = tables.add(stem, customer_id=c["id"], snapshot_date=snapshot_date.isoformat(),
                             total_card_limit_cents=card_limit, total_card_balance_cents=card_balance,
                             total_card_available_cents=max(0, card_limit - card_balance),
                             credit_card_count=len(held["cards"]), active_card_count=len(open_cards),
                             total_personal_loan_cents=personal, personal_loan_count=len(held["personal"]),
                             total_auto_loan_cents=auto, auto_loan_count=len(held["auto"]),
                             total_mortgage_cents=mortgage, mortgage_count=len(held["mortgages"]),
                             total_exposure_cents=exposure,
                             total_available_cents=max(0, card_limit - card_balance),
                             overall_utilization=round(min(999.99, card_balance * 100 / max(1, card_limit)), 2),
                             revolving_utilization=round(min(999.99, card_balance * 100 / max(1, card_limit)), 2),
                             installment_ratio=round(min(999.99, installment * 100 / max(1, exposure)), 2),
                             current_credit_score=score, credit_score_change_90d=rng.randint(-30, 30),
                             max_delinquency_bucket=worst, delinquent_product_count=delinquent,
                             total_past_due_cents=past_due, risk_tier=band(risk, RISK_TIERS),
                             risk_score=risk)
            stamp_period(rng, row, month)


def _delinquency_summary(held):
    """Worst delinquency bucket, how many products are behind, and the total past due."""
    worst_days, past_due, delinquent = 0, 0, 0
    for card in held["cards"]:
        if card["behavior"] == "DELINQUENT" or card["status"] == "CHARGED_OFF":
            delinquent += 1
            worst_days = max(worst_days, 60 if card["status"] == "CHARGED_OFF" else 35)
            past_due += int(card["current_balance"] * 0.05)
    for loan in held["personal"] + held["auto"]:
        if loan.get("delinquent"):
            delinquent += 1
            worst_days = max(worst_days, 45)
            past_due += loan["payment"]
    for m in held["mortgages"]:
        if m["behavior"] != "CURRENT":
            delinquent += 1
            worst_days = max(worst_days, m["days_past_due"])
            past_due += m["payment"] + m["escrow_monthly"]
    buckets = [(120, "120_PLUS"), (90, "90_DAY"), (60, "60_DAY"), (30, "30_DAY"), (0, "CURRENT")]
    return past_due, next(name for floor, name in buckets if worst_days >= floor), delinquent


def _current_score(rng, c, held, past_due):
    base = {"LOW": rng.randint(700, 820), "MEDIUM": rng.randint(640, 720),
            "HIGH": rng.randint(560, 670)}[c["risk_rating"]]
    if past_due:
        base -= rng.randint(30, 90)
    return max(300, min(850, base))


def _risk_score(rng, score, card_limit, card_balance, delinquent):
    """0-100, where higher is riskier."""
    risk = int((850 - score) / 5.5) + delinquent * 9
    if card_limit:
        risk += int(card_balance * 100 / card_limit / 6)
    return max(1, min(100, risk + rng.randint(-4, 4)))


def _payment_behavior_rows(tables, rng, customers, holdings):
    """A monthly payment-behaviour summary per customer that owes on a card or loan."""
    stem = "credit_risk_signals-payment_behavior"
    for c in customers:
        held = holdings[c["id"]]
        obligations = [k for k in held["cards"] if k["status"] in ("OPEN", "SUSPENDED")] + held["personal"] + held["auto"] + held["mortgages"]
        if not obligations:
            continue
        for analysis_month in months_between(LAST12_START, AS_OF_DATE):
            statement_balance = sum(k["current_balance"] for k in held["cards"] if k["status"] in ("OPEN", "SUSPENDED"))
            minimum_due = max(2500, int(statement_balance * 0.02))
            installment_due = (sum(l["payment"] for l in held["personal"] + held["auto"])
                               + sum(m["payment"] + m["escrow_monthly"] for m in held["mortgages"]))
            behavior = _payment_style(rng, held)
            share = {"FULL_PAYER": rng.uniform(0.95, 1.0), "OVER_PAYER": rng.uniform(1.0, 1.6),
                     "PARTIAL_PAYER": rng.uniform(0.25, 0.7), "MINIMUM_PAYER": rng.uniform(0.02, 0.09),
                     "MISSED": 0.0}[behavior]
            payments = int(statement_balance * share) + installment_due
            total_due = minimum_due + installment_due
            late = rng.randint(1, 2) if behavior in ("MINIMUM_PAYER", "PARTIAL_PAYER") and rng.random() < 0.3 else 0
            missed = 1 if behavior == "MISSED" else 0
            on_time = max(0, len(obligations) - late - missed)
            row = tables.add(stem, customer_id=c["id"], analysis_month=analysis_month.isoformat(),
                             total_payments_cents=payments, total_minimum_due_cents=total_due,
                             total_statement_balance_cents=statement_balance + installment_due,
                             payment_ratio=round(min(99.9999, payments / max(1, total_due)), 4),
                             full_payment_ratio=round(min(99.9999, payments / max(1, statement_balance + installment_due)), 4),
                             payment_behavior=behavior, on_time_payment_count=on_time,
                             late_payment_count=late, missed_payment_count=missed,
                             avg_days_to_payment=round(rng.uniform(-6, 2) if not late else rng.uniform(1, 18), 2),
                             returned_payment_count=1 if rng.random() < 0.02 else 0,
                             on_time_rate_3m=round(rng.uniform(0.7, 1.0) if late or missed else 1.0, 4),
                             on_time_rate_6m=round(rng.uniform(0.7, 1.0) if late or missed else 1.0, 4),
                             on_time_rate_12m=round(rng.uniform(0.75, 1.0) if late or missed else 1.0, 4),
                             months_since_late=rng.randint(0, 11) if late else None,
                             months_since_missed=rng.randint(0, 11) if missed else None,
                             autopay_coverage=round(rng.choice([0.0, 33.33, 50.0, 66.67, 100.0]), 2),
                             primary_payment_method=weighted(rng, [("ACH", 58), ("ONLINE", 28),
                                                                   ("CHECK", 8), ("DEBIT_CARD", 6)]),
                             payment_consistency_score=max(1, min(100, rng.randint(74, 99) - late * 12 - missed * 30)))
            stamp_period(rng, row, analysis_month)


def _payment_style(rng, held):
    behaviors = [k["behavior"] for k in held["cards"]]
    if "DELINQUENT" in behaviors:
        return weighted(rng, [("MISSED", 34), ("MINIMUM_PAYER", 42), ("PARTIAL_PAYER", 24)])
    if "TRANSACTOR" in behaviors:
        return weighted(rng, [("FULL_PAYER", 74), ("OVER_PAYER", 16), ("PARTIAL_PAYER", 10)])
    return weighted(rng, [("FULL_PAYER", 38), ("PARTIAL_PAYER", 32), ("MINIMUM_PAYER", 22), ("OVER_PAYER", 8)])


ROLLFORWARD_BUCKETS = ["CURRENT", "30_DAY", "60_DAY", "90_DAY", "120_PLUS"]


def _rollforward_rows(tables, rng, world):
    """Month-over-month bucket transitions for the accounts that are actually delinquent."""
    stem = "credit_risk_signals-delinquency_rollforward"
    troubled = ([("CREDIT_CARD", k) for k in world["card_accounts"] if k["behavior"] == "DELINQUENT"]
                + [(l["kind"], l) for l in world["loans"] if l.get("delinquent")]
                + [("MORTGAGE", m) for m in world["mortgages"] if m["behavior"] != "CURRENT"])
    for loan_type, item in troubled:
        opened = item["opened"] if loan_type == "CREDIT_CARD" else item["funding"]
        balance = item["current_balance"] if loan_type == "CREDIT_CARD" else item["balance"]
        level = 0
        for from_month in months_between(LAST12_START, add_months(AS_OF_DATE, -1)):
            to_month = add_months(from_month, 1)
            if to_month > AS_OF_DATE or from_month < opened:
                continue
            move = weighted(rng, [(1, 34), (0, 44), (-level if level else 0, 22)])
            new_level = max(0, min(len(ROLLFORWARD_BUCKETS) - 1, level + move))
            if new_level > level:
                transition = "ROLL"
            elif new_level < level:
                transition = "CURE"
            else:
                transition = "STABLE"
            paid = 0 if transition == "ROLL" else int(balance * rng.uniform(0.02, 0.12))
            months_on_books = max(0, (from_month.year - opened.year) * 12 + from_month.month - opened.month)
            row = tables.add(stem, loan_id=item["id"], loan_type=loan_type,
                             from_month=from_month.isoformat(), to_month=to_month.isoformat(),
                             from_bucket=ROLLFORWARD_BUCKETS[level], to_bucket=ROLLFORWARD_BUCKETS[new_level],
                             transition_type=transition, from_balance_cents=balance,
                             to_balance_cents=max(0, balance - paid), payment_received_cents=paid,
                             from_days_past_due=level * 30, to_days_past_due=new_level * 30,
                             was_contacted=new_level > 0, arrangement_made=transition == "CURE" and rng.random() < 0.5,
                             promise_to_pay=new_level > 0 and rng.random() < 0.4,
                             credit_score=max(300, min(850, 640 - new_level * 22 + rng.randint(-20, 20))),
                             months_on_books=months_on_books)
            stamp_period(rng, row, to_month)
            balance = max(0, balance - paid)
            level = new_level
