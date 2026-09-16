"""Mortgage originations, servicing and performance: 170 funded loans with their servicing history."""
import datetime as dt

from common import (AS_OF_DATE, LAST12_START, add_months, amortized_balance, amortized_payment,
                    business_time, days_in_month, ds, due_dates, ident, lognormal_cents, month_end,
                    month_start, months_between, rand_date, rng_for, stamp_bronze, stamp_period, ts,
                    weighted)

FUNDED_LOANS, UNFUNDED_APPLICATIONS = 170, 70
# Earliest funding date: the catalog's mortgage book starts well before the activity window.
FIRST_FUNDING = dt.date(2012, 3, 1)
# Note rate by funding year, as (low, high) in annual decimal terms.
RATE_ENVIRONMENT = {2012: (0.0330, 0.0410), 2013: (0.0335, 0.0450), 2014: (0.0390, 0.0450),
                    2015: (0.0360, 0.0430), 2016: (0.0340, 0.0425), 2017: (0.0385, 0.0445),
                    2018: (0.0425, 0.0495), 2019: (0.0360, 0.0450), 2020: (0.0270, 0.0350),
                    2021: (0.0265, 0.0335), 2022: (0.0330, 0.0640), 2023: (0.0605, 0.0779),
                    2024: (0.0610, 0.0729), 2025: (0.0620, 0.0705), 2026: (0.0575, 0.0670)}
# The market rate a prepayment signal compares a loan's note rate against.
MARKET_RATE = 0.0605
# Conforming loan limit; above it a conventional loan is priced as JUMBO.
CONFORMING_LIMIT_CENTS = 80650000
STATE_FIPS = {"IL": "17", "TX": "48", "CO": "08", "WA": "53", "CA": "06", "OH": "39", "AZ": "04",
              "GA": "13", "OR": "41"}
# Median home value by metro, in cents; the generator draws around it.
CITY_VALUE = {"Springfield": 21000000, "Chicago": 37000000, "Evanston": 48000000, "Austin": 55000000,
              "Dallas": 40000000, "Houston": 34000000, "Denver": 62000000, "Boulder": 78000000,
              "Seattle": 82000000, "Tacoma": 52000000, "San Francisco": 132000000,
              "San Diego": 91000000, "Columbus": 29000000, "Phoenix": 45000000, "Atlanta": 41000000,
              "Portland": 57000000}
LOAN_OFFICERS = [("LO-002", "Sandra Ellis"), ("LO-003", "Marcus Webb"), ("LO-004", "Priya Raman"),
                 ("LO-005", "Daniel Okafor"), ("LO-006", "Helen Vasquez"), ("LO-007", "Tom Bridger"),
                 ("LO-008", "Renee Caldwell"), ("LO-009", "Victor Hsu")]
APPRAISERS = ["ABC Appraisals", "Cornerstone Valuation", "Summit Appraisal Group", "Keystone Valuations",
              "Meridian Property Services"]
AVM_PROVIDERS = ["CoreLogic AVM", "HouseCanary", "Clear Capital AVM"]
DENIAL_REASONS = ["DTI_TOO_HIGH", "INSUFFICIENT_INCOME", "CREDIT_HISTORY", "COLLATERAL_VALUE",
                  "INCOMPLETE_DOCUMENTATION", "EMPLOYMENT_HISTORY"]
SERVICERS = ["SVC-001", "SVC-002"]
INVESTORS = ["FNMA", "FHLMC", "GNMA", "PORTFOLIO"]
# Delinquency buckets keyed by the lowest days-past-due that reaches them.
BUCKETS = [(120, "120_PLUS"), (90, "90_DAY"), (60, "60_DAY"), (30, "30_DAY"), (0, "CURRENT")]


def bucket_for(days):
    for floor, name in BUCKETS:
        if days >= floor:
            return name
    return "CURRENT"


def build(tables, world):
    rng = rng_for("mortgages")
    borrowers = [c for c in world["customers"]
                 if c["type"] in ("INDIVIDUAL", "JOINT") and (c["age"] or 0) >= 25 and c["income"]]
    loans = _plan_loans(rng, borrowers, world)
    world["mortgages"] = loans
    _application_rows(tables, rng, loans, borrowers)
    _loan_rows(tables, rng, loans)
    _property_rows(tables, rng, loans)
    _borrower_rows(tables, rng, world, loans)
    _payment_rows(tables, rng, loans)
    _escrow_rows(tables, rng, loans)
    _delinquency_rows(tables, rng, loans)
    _modification_rows(tables, rng, loans)
    _valuation_rows(tables, rng, loans)
    _performance_rows(tables, rng, loans)
    _prepayment_rows(tables, rng, loans)
    _vintage_rows(tables, rng, loans)


# ---------------------------------------------------------------------------
# Loan planning
# ---------------------------------------------------------------------------

def _note_rate(rng, year):
    low, high = RATE_ENVIRONMENT[min(max(year, 2012), 2026)]
    return round(rng.uniform(low, high), 4)


def _plan_loans(rng, borrowers, world):
    owners = sorted(rng.sample(borrowers, FUNDED_LOANS), key=lambda c: (c["start"], c["id"]))
    loans = []
    for i, c in enumerate(owners):
        earliest = max(c["start"], FIRST_FUNDING)
        latest = (c["end"] - dt.timedelta(days=90)) if c["end"] else AS_OF_DATE - dt.timedelta(days=200)
        if earliest >= latest:
            earliest = max(FIRST_FUNDING, latest - dt.timedelta(days=365))
        funding = rand_date(rng, earliest, latest)
        city = c["city"]
        value = lognormal_cents(rng, CITY_VALUE[city[0]], 0.28, 9000000, 240000000, step=100000)
        occupancy = weighted(rng, [("PRIMARY", 84), ("SECOND_HOME", 6), ("INVESTMENT", 10)])
        property_type = weighted(rng, [("SINGLE_FAMILY", 68), ("CONDO", 16), ("TOWNHOUSE", 11),
                                       ("MULTI_FAMILY", 4), ("MANUFACTURED", 1)])
        units = {"MULTI_FAMILY": rng.randint(2, 4)}.get(property_type, 1)
        purpose = weighted(rng, [("PURCHASE", 62), ("REFINANCE", 26), ("CASH_OUT", 12)])
        ltv = weighted(rng, [(rng.randint(60, 74), 18), (rng.randint(75, 80), 40),
                             (rng.randint(81, 90), 26), (rng.randint(91, 97), 16)])
        principal = max(4000000, int(value * ltv / 100) // 100 * 100)
        program = _program(rng, principal, ltv, occupancy)
        term = weighted(rng, [(360, 78), (180, 14), (240, 8)])
        rate = _note_rate(rng, funding.year)
        rate_type = "ARM" if rng.random() < 0.12 else "FIXED"
        if rate_type == "ARM":
            rate = round(rate - rng.uniform(0.002, 0.006), 4)
        payment = amortized_payment(principal, rate, term)
        first_payment = month_start(add_months(funding, 2))
        maturity = add_months(first_payment, term - 1)
        behavior = weighted(rng, [("CURRENT", 87), ("LATE", 9), ("SERIOUS", 4)])
        escrow_waived = occupancy == "INVESTMENT" and ltv <= 80 and rng.random() < 0.5
        annual_tax = int(value * rng.uniform(0.008, 0.022)) // 100 * 100
        annual_hazard = rng.randint(90000, 320000) // 100 * 100
        flood_zone = weighted(rng, [("X", 86), ("AE", 10), ("A", 3), ("VE", 1)])
        annual_flood = rng.randint(60000, 240000) // 100 * 100 if flood_zone in ("AE", "A", "VE") else 0
        annual_pmi = (int(principal * rng.uniform(0.004, 0.011)) // 100 * 100
                      if ltv > 80 and program in ("CONVENTIONAL", "JUMBO") else 0)
        annual_hoa = rng.randint(120000, 660000) // 100 * 100 if property_type == "CONDO" else 0
        escrow_monthly = 0 if escrow_waived else (annual_tax + annual_hazard + annual_flood + annual_pmi + annual_hoa) // 12
        loan = {"id": ident("ML", 6 + i), "app_id": ident("MAPP", 6 + i), "prop_id": ident("PROP", 6 + i),
                "escrow_id": ident("ESC", 6 + i), "customer": c, "city": city, "funding": funding,
                "first_payment": first_payment, "maturity": maturity, "term": term, "rate": rate,
                "rate_type": rate_type, "program": program, "principal": principal, "payment": payment,
                "escrow_monthly": escrow_monthly, "escrow_waived": escrow_waived, "value": value, "ltv": ltv,
                "occupancy": occupancy, "purpose": purpose, "property_type": property_type, "units": units,
                "behavior": behavior, "flood_zone": flood_zone, "annual_tax": annual_tax,
                "annual_hazard": annual_hazard, "annual_flood": annual_flood, "annual_pmi": annual_pmi,
                "annual_hoa": annual_hoa, "servicer": rng.choice(SERVICERS),
                "officer": rng.choice(LOAN_OFFICERS), "credit_score": _origination_score(rng, ltv, behavior),
                "channel": weighted(rng, [("RETAIL", 52), ("ONLINE", 22), ("CORRESPONDENT", 14), ("WHOLESALE", 12)])}
        _settle_status(rng, loan)
        loans.append(loan)
    return loans


def _program(rng, principal, ltv, occupancy):
    if principal > CONFORMING_LIMIT_CENTS:
        return "JUMBO"
    if occupancy != "PRIMARY":
        return "CONVENTIONAL"
    if ltv > 90:
        return weighted(rng, [("FHA", 58), ("VA", 22), ("CONVENTIONAL", 16), ("USDA", 4)])
    return weighted(rng, [("CONVENTIONAL", 78), ("FHA", 12), ("VA", 8), ("USDA", 2)])


def _origination_score(rng, ltv, behavior):
    base = rng.randint(690, 812) if ltv <= 80 else rng.randint(640, 760)
    if behavior == "LATE":
        base -= rng.randint(20, 60)
    elif behavior == "SERIOUS":
        base -= rng.randint(60, 110)
    return max(300, min(850, base))


def _settle_status(rng, loan):
    """Resolve the loan's status, its last paid month and its running balance as of today."""
    scheduled = due_dates(loan["first_payment"], min(loan["maturity"], AS_OF_DATE))
    matured = loan["maturity"] <= AS_OF_DATE
    status, paid_off = "ACTIVE", None
    if matured:
        status, paid_off = "PAID_OFF", loan["maturity"]
    elif loan["behavior"] == "SERIOUS" and rng.random() < 0.35:
        status = weighted(rng, [("FORECLOSURE", 60), ("CHARGED_OFF", 25), ("REO", 15)])
    elif rng.random() < 0.14 and len(scheduled) >= 18:
        # An early payoff: refinanced or the property sold.
        status, paid_off = "PAID_OFF", scheduled[rng.randint(12, len(scheduled) - 1)]
    elif rng.random() < 0.04:
        status = "TRANSFERRED"
    if paid_off:
        scheduled = [d for d in scheduled if d <= paid_off]
    made = len(scheduled)
    if loan["behavior"] == "LATE" and status == "ACTIVE":
        made = max(0, made - rng.randint(0, 1))
    elif loan["behavior"] == "SERIOUS" and status in ("ACTIVE", "FORECLOSURE", "CHARGED_OFF", "REO"):
        made = max(0, made - rng.randint(2, 5))
    loan["status"], loan["paid_off"] = status, paid_off
    loan["scheduled"] = scheduled
    loan["payments_made"] = made
    loan["balance"] = 0 if status == "PAID_OFF" else amortized_balance(loan["principal"], loan["rate"], loan["payment"], made)
    loan["days_past_due"] = max(0, (len(scheduled) - made)) * 30
    loan["remaining_term"] = max(0, loan["term"] - made)
    loan["next_due"] = None if paid_off else month_start(add_months(loan["first_payment"], made))
    # Current value: home-price appreciation since origination, ~4.2%/yr with noise.
    years = max(0.0, (AS_OF_DATE - loan["funding"]).days / 365.25)
    loan["current_value"] = int(loan["value"] * (1.042 ** years) * rng.uniform(0.94, 1.09)) // 100 * 100
    loan["current_ltv"] = round(min(999.99, loan["balance"] * 100 / max(1, loan["current_value"])), 2)


# ---------------------------------------------------------------------------
# Originations
# ---------------------------------------------------------------------------

def _application_type(loan):
    return {"PURCHASE": "PURCHASE", "REFINANCE": "REFINANCE", "CASH_OUT": "CASH_OUT_REFINANCE"}[loan["purpose"]]


def _application_rows(tables, rng, loans, borrowers):
    stem = "mortgage_originations-mortgage_application"
    for loan in loans:
        received = loan["funding"] - dt.timedelta(days=rng.randint(24, 62))
        decision = received + dt.timedelta(days=rng.randint(9, 26))
        row = tables.add(stem, application_id=loan["app_id"],
                         primary_borrower_customer_id=loan["customer"]["id"],
                         application_type=_application_type(loan),
                         loan_purpose={"PRIMARY": "PRIMARY_RESIDENCE", "SECOND_HOME": "SECOND_HOME",
                                       "INVESTMENT": "INVESTMENT"}[loan["occupancy"]],
                         property_type=loan["property_type"], number_of_units=loan["units"],
                         requested_loan_amount_cents=loan["principal"],
                         estimated_property_value_cents=loan["value"],
                         ltv_ratio=float(loan["ltv"]), cltv_ratio=float(loan["ltv"]),
                         requested_term_months=loan["term"], requested_rate_type=loan["rate_type"],
                         loan_program=loan["program"], application_status="FUNDED",
                         submitted_at=ts(business_time(rng, received)), received_date=ds(received),
                         decision_date=ds(decision), decision_type="APPROVED", denial_reasons=None,
                         funded_date=ds(loan["funding"]), loan_officer_id=loan["officer"][0],
                         loan_officer_name=loan["officer"][1],
                         branch_id=f"BR-{loan['city'][1]}-{rng.randint(1, 4):03d}",
                         origination_channel=loan["channel"], hmda_action_taken="1",
                         hmda_preapproval=rng.choice(["1", "2"]), source_system="MORTGAGE_ORIGINATION")
        stamp_bronze(rng, row, business_time(rng, loan["funding"]))
    _unfunded_applications(tables, rng, borrowers, len(loans))


def _unfunded_applications(tables, rng, borrowers, offset):
    """Applications that never became loans: denied, withdrawn or still in flight."""
    stem = "mortgage_originations-mortgage_application"
    for i in range(UNFUNDED_APPLICATIONS):
        c = rng.choice(borrowers)
        received = rand_date(rng, max(c["start"], LAST12_START), AS_OF_DATE - dt.timedelta(days=3))
        status = weighted(rng, [("DENIED", 42), ("WITHDRAWN", 24), ("IN_REVIEW", 14),
                                ("SUBMITTED", 10), ("CONDITIONALLY_APPROVED", 6), ("APPROVED", 4)])
        city = c["city"]
        value = lognormal_cents(rng, CITY_VALUE[city[0]], 0.28, 9000000, 240000000, step=100000)
        ltv = rng.randint(70, 97)
        pending = status in ("SUBMITTED", "IN_REVIEW")
        decision = None if pending else received + dt.timedelta(days=rng.randint(8, 30))
        if decision and decision > AS_OF_DATE:
            decision = AS_OF_DATE
        decision_type = None
        if status == "DENIED":
            decision_type = "DENIED"
        elif status in ("APPROVED", "CONDITIONALLY_APPROVED"):
            decision_type = "APPROVED"
        elif status == "WITHDRAWN":
            decision_type = rng.choice([None, "COUNTER_OFFER"])
        row = tables.add(stem, application_id=ident("MAPP", 6 + offset + i),
                         primary_borrower_customer_id=c["id"],
                         application_type=weighted(rng, [("PURCHASE", 58), ("REFINANCE", 26),
                                                         ("CASH_OUT_REFINANCE", 10), ("HOME_EQUITY", 6)]),
                         loan_purpose=weighted(rng, [("PRIMARY_RESIDENCE", 82), ("SECOND_HOME", 7),
                                                     ("INVESTMENT", 11)]),
                         property_type=weighted(rng, [("SINGLE_FAMILY", 68), ("CONDO", 16),
                                                      ("TOWNHOUSE", 11), ("MULTI_FAMILY", 4),
                                                      ("MANUFACTURED", 1)]),
                         number_of_units=1, requested_loan_amount_cents=int(value * ltv / 100) // 100 * 100,
                         estimated_property_value_cents=value, ltv_ratio=float(ltv), cltv_ratio=float(ltv),
                         requested_term_months=weighted(rng, [(360, 80), (180, 14), (240, 6)]),
                         requested_rate_type="ARM" if rng.random() < 0.1 else "FIXED",
                         loan_program=weighted(rng, [("CONVENTIONAL", 72), ("FHA", 14), ("VA", 7),
                                                     ("JUMBO", 5), ("USDA", 2)]),
                         application_status=status, submitted_at=ts(business_time(rng, received)),
                         received_date=ds(received), decision_date=ds(decision), decision_type=decision_type,
                         denial_reasons=", ".join(rng.sample(DENIAL_REASONS, rng.randint(1, 2))) if status == "DENIED" else None,
                         funded_date=None, loan_officer_id=None, loan_officer_name=None,
                         branch_id=f"BR-{city[1]}-{rng.randint(1, 4):03d}",
                         origination_channel=weighted(rng, [("RETAIL", 52), ("ONLINE", 22),
                                                            ("CORRESPONDENT", 14), ("WHOLESALE", 12)]),
                         hmda_action_taken={"DENIED": "3", "WITHDRAWN": "4"}.get(status, "5"),
                         hmda_preapproval=rng.choice(["1", "2"]), source_system="MORTGAGE_ORIGINATION")
        stamp_bronze(rng, row, business_time(rng, decision or received))


def _loan_rows(tables, rng, loans):
    stem = "mortgage_originations-mortgage_loan"
    for loan in loans:
        arm = loan["rate_type"] == "ARM"
        securitized = loan["program"] != "JUMBO" and rng.random() < 0.72
        investor = rng.choice(INVESTORS) if securitized else None
        row = tables.add(stem, loan_id=loan["id"], application_id=loan["app_id"],
                         primary_borrower_customer_id=loan["customer"]["id"],
                         loan_number=f"MTG-{loan['funding']:%Y}-{100000 + loan['customer']['n'] * 7 % 900000:06d}",
                         loan_status=loan["status"], original_principal_cents=loan["principal"],
                         current_principal_cents=loan["balance"], interest_rate=loan["rate"],
                         rate_type=loan["rate_type"], arm_index="SOFR" if arm else None,
                         arm_margin=round(rng.uniform(0.0225, 0.0300), 4) if arm else None,
                         arm_initial_period_months=rng.choice([60, 84, 120]) if arm else None,
                         arm_adjustment_frequency_months=6 if arm else None,
                         arm_periodic_cap=2.0 if arm else None, arm_lifetime_cap=5.0 if arm else None,
                         original_term_months=loan["term"], remaining_term_months=loan["remaining_term"],
                         monthly_pi_payment_cents=loan["payment"],
                         monthly_escrow_payment_cents=loan["escrow_monthly"],
                         total_monthly_payment_cents=loan["payment"] + loan["escrow_monthly"],
                         loan_program=loan["program"], lien_position="FIRST", loan_purpose=loan["purpose"],
                         occupancy_type=loan["occupancy"], funding_date=ds(loan["funding"]),
                         first_payment_date=ds(loan["first_payment"]), maturity_date=ds(loan["maturity"]),
                         next_payment_due_date=ds(loan["next_due"]), paid_off_date=ds(loan["paid_off"]),
                         property_id=loan["prop_id"],
                         escrow_account_id=None if loan["escrow_waived"] else loan["escrow_id"],
                         servicer_id=loan["servicer"], investor_id=investor,
                         pool_id=f"{investor}-{loan['funding']:%Y}-C{rng.randint(1, 4)}" if investor else None,
                         source_system="MORTGAGE_SERVICING")
        stamp_bronze(rng, row, business_time(rng, loan["paid_off"] or min(AS_OF_DATE, loan["funding"] + dt.timedelta(days=rng.randint(30, 900)))))


def _property_rows(tables, rng, loans):
    stem = "mortgage_originations-property_collateral"
    for loan in loans:
        city = loan["city"]
        appraisal_date = loan["funding"] - dt.timedelta(days=rng.randint(12, 45))
        bedrooms = weighted(rng, [(2, 16), (3, 42), (4, 30), (5, 12)])
        row = tables.add(stem, property_id=loan["prop_id"], loan_id=loan["id"],
                         property_address=loan["customer"]["street"], property_city=city[0],
                         property_state=city[1], property_zip=loan["customer"]["zip"],
                         property_county=city[3], property_type=loan["property_type"],
                         number_of_units=loan["units"], year_built=rng.randint(1925, 2024),
                         square_footage=rng.randint(900, 4200) // 10 * 10,
                         lot_size_sqft=0 if loan["property_type"] == "CONDO" else rng.randint(2500, 22000) // 100 * 100,
                         bedrooms=bedrooms, bathrooms=round(rng.choice([1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0]), 1),
                         original_appraised_value_cents=loan["value"],
                         original_appraisal_date=ds(appraisal_date),
                         current_estimated_value_cents=loan["current_value"],
                         current_value_date=ds(AS_OF_DATE.replace(day=1)), value_source="AVM",
                         parcel_number=f"{rng.randint(10, 39)}-{rng.randint(1, 35):02d}-{rng.randint(100, 499)}-{rng.randint(1, 99):03d}",
                         flood_zone=loan["flood_zone"],
                         flood_insurance_required=loan["flood_zone"] in ("AE", "A", "VE"),
                         census_tract=f"{STATE_FIPS[city[1]]}{rng.randint(1, 199):03d}{rng.randint(1, 9999):06d}",
                         msa_code=city[4], source_system="MORTGAGE_ORIGINATION")
        stamp_bronze(rng, row, business_time(rng, loan["funding"]))


def _borrower_rows(tables, rng, world, loans):
    """The primary borrower, plus the spouse as co-borrower where the household has one."""
    for loan in loans:
        c = loan["customer"]
        spouse = world["customer_by_id"].get(c["spouse"]) if c["spouse"] else None
        co = spouse if spouse and spouse["income"] and rng.random() < 0.8 else None
        loan["co_borrower"] = co
        housing = loan["payment"] + loan["escrow_monthly"]
        combined = (c["income"] + (co["income"] if co else 0)) // 12
        other_debt = int(combined * rng.uniform(0.04, 0.16)) // 100 * 100
        _borrower_row(tables, rng, loan, c, "PRIMARY", 50.0 if co else 100.0, combined, other_debt, housing)
        if co:
            _borrower_row(tables, rng, loan, co, "CO_BORROWER", 50.0, combined, other_debt, housing)


def _borrower_row(tables, rng, loan, c, kind, share, monthly_income, other_debt, housing):
    stem = "mortgage_originations-mortgage_borrower"
    employment = c["employment"] or {}
    dti = round(min(999.99, (housing + other_debt) * 100 / max(1, monthly_income)), 2)
    front = round(min(999.99, housing * 100 / max(1, monthly_income)), 2)
    if employment.get("retired"):
        status = "RETIRED"
    elif employment.get("type") == "SELF_EMPLOYED":
        status = "SELF_EMPLOYED"
    elif employment:
        status = "EMPLOYED"
    else:
        status = "OTHER"
    row = tables.add(stem, loan_id=loan["id"], customer_id=c["id"], borrower_type=kind,
                     ownership_percentage=share, credit_score_at_origination=loan["credit_score"],
                     credit_score_source="FICO", monthly_income_cents=monthly_income,
                     monthly_debt_cents=other_debt, dti_ratio=dti, front_end_dti=front,
                     employment_status=status, employer_name=employment.get("employer"),
                     years_employed=rng.randint(1, 22),
                     first_time_homebuyer=loan["purpose"] == "PURCHASE" and rng.random() < 0.34,
                     citizenship_status=weighted(rng, [("US_CITIZEN", 91), ("PERMANENT_RESIDENT", 8),
                                                       ("NON_RESIDENT", 1)]),
                     source_system="MORTGAGE_ORIGINATION")
    stamp_bronze(rng, row, business_time(rng, loan["funding"]))


# ---------------------------------------------------------------------------
# Servicing
# ---------------------------------------------------------------------------

def _payment_rows(tables, rng, loans):
    stem = "mortgage_servicing-mortgage_payment"
    number = 7
    for loan in loans:
        due_list = [d for d in loan["scheduled"][:loan["payments_made"]] if d >= LAST12_START]
        for due in due_list:
            k = loan["scheduled"].index(due)
            balance_before = amortized_balance(loan["principal"], loan["rate"], loan["payment"], k)
            if balance_before <= 0:
                continue
            interest = int(balance_before * loan["rate"] / 12)
            principal = max(0, min(balance_before, loan["payment"] - interest))
            late_days = 0
            if loan["behavior"] == "LATE" and rng.random() < 0.25:
                late_days = rng.randint(3, 28)
            elif loan["behavior"] == "SERIOUS" and rng.random() < 0.45:
                late_days = rng.randint(16, 75)
            received = due + dt.timedelta(days=late_days - rng.randint(0, 4))
            if received > AS_OF_DATE - dt.timedelta(days=1):
                continue
            payoff = loan["paid_off"] == due
            late_fee = int(loan["payment"] * 0.05) // 100 * 100 if late_days >= 16 else 0
            amount = (balance_before + interest) if payoff else loan["payment"] + loan["escrow_monthly"]
            row = tables.add(stem, payment_id=ident("MPMT", number), loan_id=loan["id"],
                             payment_amount_cents=amount + late_fee,
                             principal_cents=balance_before if payoff else principal,
                             interest_cents=interest,
                             escrow_cents=0 if payoff else loan["escrow_monthly"],
                             late_fee_cents=late_fee, other_fees_cents=0,
                             payment_type="PAYOFF" if payoff else "REGULAR",
                             payment_status="APPLIED",
                             due_date=ds(due), received_date=ds(received), applied_date=ds(received),
                             payment_channel=weighted(rng, [("ACH", 62), ("ONLINE", 28), ("CHECK", 7),
                                                            ("PHONE", 3)]),
                             principal_balance_after_cents=0 if payoff else max(0, balance_before - principal),
                             payment_period=f"{due:%Y-%m}",
                             days_past_due_at_payment=max(0, (received - due).days),
                             suspense_amount_cents=0, unapplied_amount_cents=0,
                             source_system="MORTGAGE_SERVICING")
            stamp_bronze(rng, row, business_time(rng, received))
            number += 1


def _escrow_rows(tables, rng, loans):
    stem = "mortgage_servicing-escrow_account"
    for loan in loans:
        if loan["escrow_waived"] or loan["status"] == "PAID_OFF":
            continue
        annual = loan["annual_tax"] + loan["annual_hazard"] + loan["annual_flood"] + loan["annual_pmi"] + loan["annual_hoa"]
        for as_of in _escrow_dates(rng, loan):
            target = annual // 12 * rng.randint(2, 3)
            balance = max(0, target + rng.randint(-annual // 12, annual // 8) // 100 * 100)
            last_analysis = as_of - dt.timedelta(days=rng.randint(30, 300))
            row = tables.add(stem, escrow_account_id=loan["escrow_id"], loan_id=loan["id"],
                             as_of_date=ds(as_of), escrow_balance_cents=balance,
                             target_balance_cents=target, shortage_surplus_cents=balance - target,
                             monthly_payment_cents=loan["escrow_monthly"],
                             annual_tax_cents=loan["annual_tax"],
                             next_tax_due_date=ds(_next_anniversary(as_of, rng, 6)),
                             annual_hazard_insurance_cents=loan["annual_hazard"],
                             next_insurance_due_date=ds(_next_anniversary(as_of, rng, 3)),
                             annual_flood_insurance_cents=loan["annual_flood"],
                             annual_pmi_cents=loan["annual_pmi"], annual_hoa_cents=loan["annual_hoa"],
                             escrow_waived=False, last_analysis_date=ds(last_analysis),
                             next_analysis_date=ds(add_months(last_analysis, 12)),
                             source_system="MORTGAGE_SERVICING")
            stamp_bronze(rng, row, business_time(rng, as_of))


def _escrow_dates(rng, loan):
    """Annual escrow analysis snapshots over the last three years of the loan's life."""
    out = []
    for year in range(AS_OF_DATE.year - 2, AS_OF_DATE.year + 1):
        day = dt.date(year, rng.randint(1, 12), 1)
        if loan["funding"] < day <= AS_OF_DATE:
            out.append(day)
    return out


def _next_anniversary(as_of, rng, month):
    year = as_of.year if month >= as_of.month else as_of.year + 1
    return dt.date(year, month, min(15, days_in_month(year, month)))


def _delinquency_rows(tables, rng, loans):
    stem = "mortgage_servicing-delinquency_event"
    number = 6
    for loan in loans:
        if loan["behavior"] == "CURRENT":
            continue
        count = rng.randint(1, 3) if loan["behavior"] == "LATE" else rng.randint(3, 6)
        window = [d for d in loan["scheduled"] if d >= max(LAST12_START, loan["funding"])]
        if not window:
            continue
        for event_date in sorted(rng.sample(window, min(count, len(window)))):
            serious = loan["behavior"] == "SERIOUS"
            days = rng.randint(31, 119) if serious else rng.randint(5, 45)
            cured = None
            if not serious or rng.random() < 0.4:
                cure = event_date + dt.timedelta(days=rng.randint(4, 40))
                cured = cure if cure <= AS_OF_DATE else None
            amount_due = (loan["payment"] + loan["escrow_monthly"]) * max(1, days // 30)
            foreclosure = serious and loan["status"] in ("FORECLOSURE", "REO") and days >= 90
            attorney = event_date + dt.timedelta(days=rng.randint(30, 90)) if foreclosure else None
            sale = attorney + dt.timedelta(days=rng.randint(60, 180)) if foreclosure and rng.random() < 0.5 else None
            row = tables.add(stem, delinquency_event_id=ident("MDE", number), loan_id=loan["id"],
                             customer_id=loan["customer"]["id"],
                             event_type=weighted(rng, [("LATE_PAYMENT", 46), ("MISSED_PAYMENT", 34),
                                                       ("FORBEARANCE_START", 10), ("CURE", 10)]),
                             days_past_due=days, delinquency_bucket=bucket_for(days),
                             amount_past_due_cents=amount_due, total_amount_due_cents=amount_due,
                             event_date=ds(event_date), cured_date=ds(cured),
                             collection_action=weighted(rng, [("REMINDER_CALL", 44), ("COLLECTION_LETTER", 32),
                                                              ("OUTBOUND_CALL", 16), ("FIELD_VISIT", 8)]),
                             loss_mitigation_status=weighted(rng, [("NONE", 58), ("IN_REVIEW", 20),
                                                                   ("APPROVED", 14), ("DENIED", 8)]),
                             loss_mitigation_option=weighted(rng, [("FORBEARANCE", 44), ("REPAYMENT_PLAN", 30),
                                                                   ("MODIFICATION", 26)]) if serious else None,
                             attorney_referral_date=ds(attorney if attorney and attorney <= AS_OF_DATE else None),
                             foreclosure_sale_date=ds(sale if sale and sale <= AS_OF_DATE else None),
                             reo_date=ds(sale + dt.timedelta(days=30)) if sale and loan["status"] == "REO" and sale + dt.timedelta(days=30) <= AS_OF_DATE else None,
                             estimated_loss_cents=int(loan["balance"] * rng.uniform(0.08, 0.3)) // 100 * 100 if foreclosure else None,
                             actual_loss_cents=None, source_system="MORTGAGE_SERVICING")
            stamp_bronze(rng, row, business_time(rng, event_date))
            number += 1


# A loan's chance of entering loss mitigation at all, by how it has been paying.
MODIFICATION_CHANCE = {"SERIOUS": 0.9, "LATE": 0.4}


def _modification_rows(tables, rng, loans):
    """Loss-mitigation modifications, on the loans that are actually behind.

    A trial that fails or is withdrawn is usually followed by a second attempt a few months later,
    so one loan contributes more than one row.
    """
    number = 6
    for loan in loans:
        if rng.random() >= MODIFICATION_CHANCE.get(loan["behavior"], 0.0):
            continue
        opens = max(LAST12_START, loan["funding"] + dt.timedelta(days=400))
        closes = AS_OF_DATE - dt.timedelta(days=45)
        if opens >= closes:
            continue
        request = rand_date(rng, opens, closes)
        for _ in range(2):
            status = _modification_row(tables, rng, loan, number, request)
            number += 1
            if status not in ("FAILED", "CANCELLED"):
                break
            request += dt.timedelta(days=rng.randint(90, 210))
            if request > closes:
                break


def _modification_row(tables, rng, loan, number, request):
    """Write one modification attempt and return the status it landed in."""
    stem = "mortgage_servicing-loan_modification"
    status = weighted(rng, [("PERMANENT", 46), ("TRIAL", 22), ("FAILED", 18), ("CANCELLED", 14)])
    approval = request + dt.timedelta(days=rng.randint(12, 45))
    trial_start = month_start(add_months(approval, 1))
    required = 3
    made = required if status == "PERMANENT" else (rng.randint(1, 2) if status == "TRIAL" else rng.randint(0, 2))
    permanent = add_months(trial_start, required) if status == "PERMANENT" else None
    mod_type = weighted(rng, [("RATE_REDUCTION", 40), ("TERM_EXTENSION", 26),
                              ("CAPITALIZATION", 20), ("PRINCIPAL_FORBEARANCE", 14)])
    post_rate = round(max(0.02, loan["rate"] - rng.uniform(0.005, 0.02)), 4) if mod_type == "RATE_REDUCTION" else loan["rate"]
    pre_term = loan["remaining_term"]
    post_term = pre_term + rng.choice([60, 120]) if mod_type == "TERM_EXTENSION" else pre_term
    arrears = (loan["payment"] + loan["escrow_monthly"]) * rng.randint(2, 6) if mod_type == "CAPITALIZATION" else 0
    deferred = int(loan["balance"] * rng.uniform(0.04, 0.12)) // 100 * 100 if mod_type == "PRINCIPAL_FORBEARANCE" else 0
    post_principal = loan["balance"] + arrears
    post_payment = amortized_payment(max(1, post_principal - deferred), post_rate, max(1, post_term))
    row = tables.add(stem, modification_id=ident("LMOD", number), loan_id=loan["id"],
                     customer_id=loan["customer"]["id"], modification_type=mod_type,
                     modification_status=status,
                     modification_program=weighted(rng, [("PROPRIETARY", 56), ("GSE_FLEX", 32), ("HAMP", 12)]),
                     request_date=ds(request), approval_date=ds(approval if status != "CANCELLED" else None),
                     trial_start_date=ds(trial_start if status != "CANCELLED" else None),
                     permanent_date=ds(permanent), trial_payments_required=required,
                     trial_payments_made=made, pre_mod_rate=loan["rate"], post_mod_rate=post_rate,
                     pre_mod_payment_cents=loan["payment"], post_mod_payment_cents=post_payment,
                     pre_mod_principal_cents=loan["balance"], post_mod_principal_cents=post_principal,
                     principal_deferred_cents=deferred, principal_forgiven_cents=0,
                     arrears_capitalized_cents=arrears, pre_mod_term_months=pre_term,
                     post_mod_term_months=post_term,
                     new_maturity_date=ds(add_months(loan["maturity"], post_term - pre_term)),
                     source_system="MORTGAGE_SERVICING")
    stamp_bronze(rng, row, business_time(rng, permanent or approval))
    return status


def _valuation_rows(tables, rng, loans):
    stem = "mortgage_servicing-property_valuation"
    number = 7
    for loan in loans:
        events = [(loan["funding"] - dt.timedelta(days=rng.randint(12, 45)), "APPRAISAL", "ORIGINATION",
                   loan["value"], "MORTGAGE_ORIGINATION")]
        for _ in range(rng.randint(1, 3)):
            when = rand_date(rng, max(loan["funding"] + dt.timedelta(days=200), LAST12_START),
                             AS_OF_DATE - dt.timedelta(days=5))
            years = max(0.0, (when - loan["funding"]).days / 365.25)
            amount = int(loan["value"] * (1.042 ** years) * rng.uniform(0.93, 1.1)) // 100 * 100
            events.append((when, weighted(rng, [("AVM", 72), ("BPO", 18), ("APPRAISAL", 10)]),
                           weighted(rng, [("MONITORING", 70), ("PMI_REMOVAL", 16), ("MODIFICATION", 14)]),
                           amount, "MORTGAGE_SERVICING"))
        for when, kind, purpose, amount, system in sorted(events):
            k = loan["scheduled"].index(max([d for d in loan["scheduled"] if d <= when], default=loan["scheduled"][0])) if loan["scheduled"] else 0
            balance = amortized_balance(loan["principal"], loan["rate"], loan["payment"], k) if purpose != "ORIGINATION" else loan["principal"]
            avm = kind == "AVM"
            row = tables.add(stem, valuation_id=ident("PVAL", number), property_id=loan["prop_id"],
                             loan_id=loan["id"], valuation_type=kind, valuation_purpose=purpose,
                             valuation_amount_cents=amount, valuation_date=ds(when),
                             confidence_score=rng.randint(72, 97) if avm else None,
                             fsd=round(rng.uniform(4.0, 13.0), 2) if avm else None,
                             valuation_provider=rng.choice(AVM_PROVIDERS if avm else APPRAISERS),
                             provider_reference=f"{'AVM' if avm else 'APR'}-{when:%Y}-{10000 + number:05d}",
                             current_ltv=round(min(999.99, balance * 100 / max(1, amount)), 2),
                             source_system=system)
            stamp_bronze(rng, row, business_time(rng, when))
            number += 1


# ---------------------------------------------------------------------------
# Performance (silver)
# ---------------------------------------------------------------------------

def _performance_status(loan, month_index, months_paid):
    behind = max(0, month_index - months_paid)
    if loan["status"] in ("FORECLOSURE", "REO") and behind >= 3:
        return "FORECLOSURE", behind * 30
    if behind == 0:
        return "CURRENT", 0
    return f"DQ_{min(behind, 4) * 30}", behind * 30


def _performance_rows(tables, rng, loans):
    stem = "mortgage_performance-loan_performance_monthly"
    for loan in loans:
        for month in months_between(LAST12_START, AS_OF_DATE):
            due_through = [d for d in loan["scheduled"] if d <= month]
            if not due_through or (loan["paid_off"] and month > loan["paid_off"]):
                continue
            k = len(due_through)
            paid = min(k, loan["payments_made"])
            balance = amortized_balance(loan["principal"], loan["rate"], loan["payment"], paid)
            scheduled_balance = amortized_balance(loan["principal"], loan["rate"], loan["payment"], k)
            prev = amortized_balance(loan["principal"], loan["rate"], loan["payment"], max(0, paid - 1))
            status, dpd = _performance_status(loan, k, paid)
            age = max(0, (month.year - loan["funding"].year) * 12 + month.month - loan["funding"].month)
            years = max(0.0, (month - loan["funding"]).days / 365.25)
            value = int(loan["value"] * (1.042 ** years)) // 100 * 100
            row = tables.add(stem, loan_id=loan["id"], reporting_month=ds(month), loan_status=status,
                             days_past_due=dpd, current_upb_cents=balance,
                             scheduled_upb_cents=scheduled_balance,
                             principal_paid_cents=max(0, prev - balance),
                             interest_paid_cents=int(prev * loan["rate"] / 12) if paid > 0 else 0,
                             prepaid_principal_cents=0, curtailment_cents=0, current_rate=loan["rate"],
                             current_payment_cents=loan["payment"] + loan["escrow_monthly"],
                             payments_made=1 if paid > 0 and dpd == 0 else 0,
                             lifetime_payments_made=paid, lifetime_payments_due=k,
                             current_credit_score=max(300, min(850, loan["credit_score"] + rng.randint(-25, 30))),
                             current_ltv=round(min(999.99, balance * 100 / max(1, value)), 2),
                             current_property_value_cents=value, is_modified=False, modification_date=None,
                             in_forbearance=False,
                             in_foreclosure=loan["status"] in ("FORECLOSURE", "REO") and status == "FORECLOSURE",
                             loan_age_months=age, remaining_term_months=max(0, loan["term"] - k),
                             months_to_maturity=max(0, loan["term"] - k), servicer_id=loan["servicer"],
                             investor_id=None, pool_id=None)
            stamp_period(rng, row, month_end(month))


def _prepayment_rows(tables, rng, loans):
    stem = "mortgage_performance-prepayment_signal"
    for loan in loans:
        if loan["status"] not in ("ACTIVE", "TRANSFERRED"):
            continue
        for month in months_between(LAST12_START, AS_OF_DATE):
            if month.month % 3 != 0:
                continue
            signal_date = month.replace(day=15)
            if signal_date > AS_OF_DATE or signal_date < loan["funding"]:
                continue
            paid = len([d for d in loan["scheduled"] if d <= signal_date])
            balance = amortized_balance(loan["principal"], loan["rate"], loan["payment"], paid)
            years = max(0.0, (signal_date - loan["funding"]).days / 365.25)
            value = int(loan["value"] * (1.042 ** years)) // 100 * 100
            incentive = int(round((loan["rate"] - MARKET_RATE) * 10000))
            seasoning = max(0, (signal_date.year - loan["funding"].year) * 12 + signal_date.month - loan["funding"].month)
            probability = min(0.95, max(0.01, 0.05 + max(0, incentive) / 900 + (0.06 if years > 3 else 0.0)))
            probability = round(probability * rng.uniform(0.75, 1.25), 4)
            if probability >= 0.5:
                tier = "VERY_HIGH"
            elif probability >= 0.28:
                tier = "HIGH"
            elif probability >= 0.12:
                tier = "MEDIUM"
            else:
                tier = "LOW"
            row = tables.add(stem, loan_id=loan["id"], signal_date=ds(signal_date),
                             prepayment_probability=probability, prepayment_risk_tier=tier,
                             rate_incentive_bps=incentive, market_rate=MARKET_RATE,
                             loan_rate=loan["rate"], burnout_factor=round(min(1.0, seasoning / 120), 4),
                             seasoning_months=seasoning,
                             current_ltv=round(min(999.99, balance * 100 / max(1, value)), 2),
                             hpa_since_origination=round(min(9999.99, (value - loan["value"]) * 100 / max(1, loan["value"])), 2),
                             local_unemployment_rate=round(rng.uniform(3.0, 6.4), 2),
                             credit_score_change=rng.randint(-25, 30), months_since_refi=None,
                             is_assumable=loan["program"] in ("FHA", "VA", "USDA"),
                             has_prepay_penalty=False, penalty_months_remaining=None,
                             primary_driver="RATE" if incentive > 25 else ("EQUITY" if balance * 100 / max(1, value) < 70 else "SEASONING"),
                             model_version="prepay-v1.4")
            stamp_period(rng, row, month_end(month))


SEED_VINTAGE_KEYS = {(dt.date(2020, 3, 1), "CONVENTIONAL", "IL"), (dt.date(2019, 9, 1), "CONVENTIONAL", "CO"),
                     (dt.date(2022, 6, 1), "CONVENTIONAL", "WA"), (dt.date(2020, 3, 1), "FHA", "TX"),
                     (dt.date(2019, 9, 1), "JUMBO", "CA")}


def _vintage_rows(tables, rng, loans):
    """One row per origination quarter, program and state, aggregated over the generated book."""
    stem = "mortgage_performance-vintage_performance"
    cohorts = {}
    for loan in loans:
        quarter_month = dt.date(loan["funding"].year, (loan["funding"].month - 1) // 3 * 3 + 1, 1)
        cohorts.setdefault((quarter_month, loan["program"], loan["city"][1]), []).append(loan)
    for key in sorted(cohorts):
        vintage_month, program, state = key
        if key in SEED_VINTAGE_KEYS:
            continue
        members = cohorts[key]
        original = sum(l["principal"] for l in members)
        current = sum(l["balance"] for l in members)
        paid_off = [l for l in members if l["status"] == "PAID_OFF"]
        defaulted = [l for l in members if l["status"] in ("FORECLOSURE", "REO", "CHARGED_OFF")]
        age = max(1, (AS_OF_DATE.year - vintage_month.year) * 12 + AS_OF_DATE.month - vintage_month.month)
        # The scaling factor turns this small synthetic cohort into a plausible book-level one.
        scale = rng.randint(9, 34)
        prepay_rate = round(min(0.9999, len(paid_off) / len(members)), 4)
        default_rate = round(min(0.9999, len(defaulted) / len(members)), 4)
        smm = round(min(0.9999, prepay_rate / age), 4)
        row = tables.add(stem, vintage_month=ds(vintage_month), age_months=age, loan_program=program,
                         property_state=state, loan_count=len(members) * scale,
                         original_upb_cents=original * scale, current_upb_cents=current * scale,
                         upb_remaining_pct=round(min(99.9999, current * 100 / max(1, original)), 4),
                         cumulative_default_rate=default_rate, cumulative_prepay_rate=prepay_rate,
                         current_dq_30_rate=round(min(0.9999, len([l for l in members if l["behavior"] == "LATE"]) / len(members)), 4),
                         current_dq_60_rate=round(min(0.9999, len([l for l in members if l["behavior"] == "SERIOUS"]) / len(members) * 0.6), 4),
                         current_dq_90_rate=round(min(0.9999, len([l for l in members if l["behavior"] == "SERIOUS"]) / len(members) * 0.3), 4),
                         smm=smm, cpr=round(min(0.9999, 1 - (1 - smm) ** 12), 4),
                         cdr=round(min(0.9999, default_rate / age * 12), 4),
                         loss_severity=round(rng.uniform(0.12, 0.38), 4),
                         cumulative_loss_cents=sum(int(l["balance"] * 0.22) for l in defaulted) * scale,
                         avg_original_credit_score=sum(l["credit_score"] for l in members) // len(members),
                         avg_original_ltv=round(sum(l["ltv"] for l in members) / len(members), 2),
                         avg_original_dti=round(rng.uniform(26.0, 39.0), 2),
                         avg_note_rate=round(sum(l["rate"] for l in members) / len(members), 4),
                         first_time_buyer_pct=round(rng.uniform(12.0, 44.0), 2))
        stamp_period(rng, row, AS_OF_DATE)
