"""Transaction reference data and the per-account ledger simulation (~5,000 ledger transactions)."""
import datetime as dt
import heapq

from common import (AS_OF, AS_OF_DATE, WINDOW_START, WINDOW_START_DATE, add_months, at, business_time, ds,
                    ident, lognormal_cents, rand_date, rand_dt, rng_for, stamp_bronze, stamp_current, ts, weighted)

BASE_EVENT_BUDGET = 2700

# code: (category, default channel, name, description, subcategory, customer initiated, fee, interest, template)
NEW_TYPES = {
    "TT-WIRE-IN": ("CREDIT", "WIRE", "Wire Transfer In", "Incoming wire transfer", "WIRE", False, False, False, "TT-DEP"),
    "TT-CHK": ("DEBIT", "CHECK", "Check Paid", "Check drawn on account and paid", "CHECK", True, False, False, "TT-WDL"),
    "TT-XFER-IN": ("CREDIT", "ONLINE", "Transfer In", "Online or mobile transfer into account", "TRANSFER", True, False, False, "TT-DEP"),
    "TT-XFER-OUT": ("DEBIT", "ONLINE", "Transfer Out", "Online or mobile transfer out of account", "TRANSFER", True, False, False, "TT-WDL"),
    "TT-MOB-DEP": ("CREDIT", "MOBILE", "Mobile Check Deposit", "Check deposited through the mobile app", "CHECK_DEPOSIT", True, False, False, "TT-DEP"),
    "TT-OD-FEE": ("DEBIT", "INTERNAL", "Overdraft Fee", "Fee charged when a debit overdraws the account", "FEE", False, True, False, "TT-FEE"),
    "TT-ATM-DEP": ("CREDIT", "ATM", "ATM Deposit", "Cash or check deposited at an ATM", "CASH_DEPOSIT", True, False, False, "TT-DEP"),
}
CATEGORY = {"TT-DEP": "CREDIT", "TT-WDL": "DEBIT", "TT-POS": "DEBIT", "TT-ACH-CR": "CREDIT", "TT-ACH-DR": "DEBIT",
            "TT-WIRE-OUT": "DEBIT", "TT-FEE": "DEBIT", "TT-INT": "CREDIT"}
CATEGORY.update({code: spec[0] for code, spec in NEW_TYPES.items()})
CHANNEL = {"TT-DEP": "BRANCH", "TT-WDL": "ATM", "TT-POS": "POS", "TT-ACH-CR": "ACH", "TT-ACH-DR": "ACH",
           "TT-WIRE-OUT": "WIRE", "TT-FEE": "INTERNAL", "TT-INT": "INTERNAL"}
CHANNEL.update({code: spec[1] for code, spec in NEW_TYPES.items()})
NOT_CUSTOMER_INITIATED = {"TT-FEE", "TT-OD-FEE", "TT-INT", "TT-ACH-CR", "TT-WIRE-IN"}

# mcc: (description, category, subcategory, high risk, cash equivalent, restricted, tax category)
NEW_MCC = {
    "5311": ("Department Stores", "RETAIL", "DEPARTMENT", False, False, False, "GENERAL"),
    "5912": ("Drug Stores and Pharmacies", "RETAIL", "PHARMACY", False, False, False, "EXEMPT"),
    "5814": ("Fast Food Restaurants", "SERVICES", "DINING", False, False, False, "GENERAL"),
    "4121": ("Taxicabs and Rideshare", "SERVICES", "TRANSPORT", False, False, False, "GENERAL"),
    "4111": ("Local Commuter Transport", "SERVICES", "TRANSPORT", False, False, False, "EXEMPT"),
    "4899": ("Cable and Streaming Services", "SERVICES", "STREAMING", False, False, False, "GENERAL"),
    "5942": ("Book Stores", "RETAIL", "BOOKS", False, False, False, "GENERAL"),
    "5732": ("Electronics Stores", "RETAIL", "ELECTRONICS", False, False, False, "GENERAL"),
    "5651": ("Family Clothing Stores", "RETAIL", "APPAREL", False, False, False, "GENERAL"),
    "7832": ("Motion Picture Theaters", "SERVICES", "ENTERTAINMENT", False, False, False, "GENERAL"),
    "7997": ("Membership Clubs and Fitness", "SERVICES", "FITNESS", False, False, False, "GENERAL"),
    "6300": ("Insurance Sales and Premiums", "FINANCIAL", "INSURANCE", False, False, False, "EXEMPT"),
    "8011": ("Doctors and Physicians", "SERVICES", "HEALTHCARE", False, False, False, "EXEMPT"),
    "8062": ("Hospitals", "SERVICES", "HEALTHCARE", False, False, False, "EXEMPT"),
    "4814": ("Telecommunication Services", "SERVICES", "TELECOM", False, False, False, "GENERAL"),
    "5999": ("Miscellaneous Retail", "RETAIL", "GENERAL", False, False, False, "GENERAL"),
    "7011": ("Hotels and Lodging", "SERVICES", "TRAVEL", False, False, False, "GENERAL"),
    "4511": ("Airlines", "SERVICES", "TRAVEL", False, False, False, "GENERAL"),
    "5993": ("Cigar Stores", "RETAIL", "TOBACCO", False, False, True, "GENERAL"),
    "7995": ("Gambling Transactions", "SERVICES", "GAMBLING", True, False, True, "GENERAL"),
    "6051": ("Quasi Cash Merchants", "FINANCIAL", "QUASI_CASH", True, True, False, "EXEMPT"),
    "9311": ("Tax Payments", "FINANCIAL", "TAX", False, False, False, "EXEMPT"),
    "5300": ("Wholesale Clubs", "RETAIL", "WAREHOUSE", False, False, False, "GENERAL"),
    "5200": ("Home Supply Warehouse", "RETAIL", "HOME", False, False, False, "GENERAL"),
    "7299": ("Miscellaneous Personal Services", "SERVICES", "PERSONAL", False, False, False, "GENERAL"),
}
# category id: (name, parent, description, icon)
NEW_CATEGORIES = {
    "CAT-006": ("Transportation", None, "Fuel, rideshare, transit and travel", "car"),
    "CAT-007": ("Entertainment", None, "Streaming, subscriptions and events", "film"),
    "CAT-008": ("Financial", None, "Bank fees, loan payments, taxes and cash", "bank"),
    "CAT-009": ("Income", None, "Payroll, interest and deposits", "wallet"),
    "CAT-010": ("Health & Insurance", None, "Medical costs and insurance premiums", "heart"),
    "CAT-011": ("Transfers", None, "Money moved between accounts", "arrows"),
    "CAT-012": ("Gas & Fuel", "CAT-006", "Gas stations and EV charging", "fuel"),
    "CAT-013": ("Rideshare & Transit", "CAT-006", "Taxis, rideshare and public transit", "bus"),
    "CAT-014": ("Travel", "CAT-006", "Airlines and lodging", "plane"),
    "CAT-015": ("Streaming & Subscriptions", "CAT-007", "Recurring digital subscriptions and memberships", "play"),
    "CAT-016": ("Movies & Events", "CAT-007", "Cinemas, concerts and events", "ticket"),
    "CAT-017": ("Bank Fees", "CAT-008", "Maintenance and overdraft fees", "receipt"),
    "CAT-018": ("Loan Payments", "CAT-008", "Loan and card payments to lenders", "credit-card"),
    "CAT-019": ("Cash Withdrawal", "CAT-008", "ATM and teller cash withdrawals", "cash"),
    "CAT-020": ("Payroll", "CAT-009", "Salary and wage deposits", "briefcase"),
    "CAT-021": ("Interest", "CAT-009", "Interest earned", "percent"),
    "CAT-022": ("Deposits", "CAT-009", "Cash and check deposits", "download"),
    "CAT-023": ("Insurance", "CAT-010", "Insurance premiums", "shield"),
    "CAT-024": ("Medical & Pharmacy", "CAT-010", "Doctors, hospitals and pharmacies", "pill"),
    "CAT-025": ("Shopping", "CAT-001", "General retail purchases", "tag"),
}
MCC_CATEGORY = {"5411": "CAT-004", "5300": "CAT-004", "5812": "CAT-003", "5814": "CAT-003", "5541": "CAT-012",
                "4900": "CAT-005", "4814": "CAT-005", "6011": "CAT-018", "4121": "CAT-013", "4111": "CAT-013",
                "7011": "CAT-014", "4511": "CAT-014", "4899": "CAT-015", "7997": "CAT-015", "7832": "CAT-016",
                "6300": "CAT-023", "8011": "CAT-024", "8062": "CAT-024", "5912": "CAT-024", "9311": "CAT-008",
                "7995": "CAT-008", "6051": "CAT-008"}
# merchant type: [(mcc, count, name stems)]
MERCHANT_PLAN = {
    "RETAIL": [("5411", 14, ["Fresh Market", "Green Basket", "Harvest Foods", "Corner Grocer"]),
               ("5541", 9, ["QuickFuel", "Speedway Gas", "Prairie Fuel"]),
               ("5311", 6, ["Main Street Department Store", "Hudson & Co"]), ("5912", 6, ["CarePlus Pharmacy", "WellRx"]),
               ("5732", 5, ["Circuit Hub", "Pixel Electronics"]), ("5651", 6, ["Urban Threads", "Family Outfitters"]),
               ("5999", 6, ["Odds & Ends", "Gift Nook"]), ("5300", 4, ["BulkWise Club"]), ("5200", 5, ["HomeCraft Supply"]),
               ("5942", 3, ["Chapter One Books"]), ("5993", 2, ["Leaf & Ash Cigars"])],
    "RESTAURANT": [("5812", 26, ["Blue Plate Diner", "Trattoria Roma", "Golden Wok", "Harbor Grill", "Taqueria Sol"]),
                   ("5814", 19, ["Burger Barn", "Taco Express", "Bagel Stop", "Chicken Coop"])],
    "SERVICE": [("4121", 5, ["RideNow", "CityCab"]), ("4111", 3, ["Metro Transit"]), ("7832", 4, ["Starlight Cinemas"]),
                ("8011", 4, ["Family Health Clinic"]), ("8062", 2, ["St. Mary Hospital"]), ("7011", 4, ["Lakeside Inn"]),
                ("4511", 3, ["SkyBridge Airlines"]), ("7299", 3, ["Shine Salon"]), ("7995", 2, ["Lucky Star Casino"]),
                ("6051", 2, ["CoinVault Exchange"]), ("6300", 8, ["Guardian Mutual Insurance", "Shield Auto Insurance"]),
                ("6011", 8, ["Summit Lending", "Heritage Credit Union", "Prairie Auto Finance"])],
    "UTILITY": [("4900", 9, ["Metro Water", "Prairie Electric", "Citywide Gas"]), ("4814", 7, ["Nexus Wireless", "FiberLink"])],
    "SUBSCRIPTION": [("4899", 15, ["StreamWave", "TuneBox", "CloudPix", "NewsDaily Digital"]),
                     ("7997", 9, ["FitLife Gym", "Wholesale Membership", "Yoga Loft"])],
    "GOVERNMENT": [("9311", 10, ["State Tax Board", "County Treasurer", "City Parking Authority"])],
}
CITIES = [("Springfield", "IL"), ("Chicago", "IL"), ("Austin", "TX"), ("Denver", "CO"), ("Seattle", "WA"),
          ("Columbus", "OH"), ("Phoenix", "AZ"), ("Atlanta", "GA"), ("Portland", "OR"), ("San Diego", "CA")]
PERIOD_DAYS = {"WEEKLY": 7, "BIWEEKLY": 14, "MONTHLY": 30, "QUARTERLY": 91, "ANNUAL": 365}
ANCHOR_SUBCATEGORY = {"5411": "GROCERY", "5812": "DINING", "5541": "FUEL", "4900": "UTILITY", "6011": "BANKING"}


def build(tables, world):
    rng = rng_for("ledger")
    _transaction_types(tables, rng)
    world["mcc"] = _mcc(tables, rng)
    world["merchants"] = _merchants(tables, rng)
    world["categories"] = _categories(tables, rng)
    world["recurring"] = _plan_recurring(rng, world)
    world["ledger"] = _simulate(rng, world)


def _transaction_types(tables, rng):
    stem = "core_transactions-transaction_type"
    templates = {r["transaction_type_code"]: r for _, r in tables.anchors[stem]}
    for i, (code, (cat, _, name, desc, sub, initiated, fee, interest, tmpl)) in enumerate(NEW_TYPES.items()):
        row = tables.add(stem, templates[tmpl], transaction_type_code=code, transaction_type_name=name,
                         description=desc, category=cat, subcategory=sub, is_customer_initiated=initiated,
                         affects_available_balance=True, is_fee=fee, is_interest=interest,
                         gl_account_code=f"GL-10{20 + i}", is_active=True, source_system="CORE_BANKING")
        stamp_bronze(rng, row, at(dt.date(2016, 1, 4), 9 + i))


def _mcc(tables, rng):
    stem = "card_transactions-mcc_reference"
    known = {r["mcc_code"]: r for _, r in tables.anchors[stem]}
    for code, (desc, cat, sub, risky, cash, restricted, tax) in NEW_MCC.items():
        row = tables.add(stem, mcc_code=code, mcc_description=desc, category=cat, subcategory=sub,
                         is_high_risk=risky, is_cash_equivalent=cash, is_restricted=restricted, tax_category=tax,
                         source_system="CARD_PLATFORM")
        stamp_bronze(rng, row, at(dt.date(2015, 6, 1), 3))
    return {**{c: r["mcc_description"] for c, r in known.items()}, **{c: v[0] for c, v in NEW_MCC.items()}}


def _merchants(tables, rng):
    stem = "enriched_transactions-merchant_enrichment"
    merchants, number = [], 6
    sources = ["PLAID", "YODLEE", "MX", "INTERNAL"]
    primary_category = {"RETAIL": "RETAIL", "RESTAURANT": "DINING", "SERVICE": "SERVICES", "UTILITY": "UTILITIES",
                        "SUBSCRIPTION": "ENTERTAINMENT", "GOVERNMENT": "GOVERNMENT"}
    for mtype, groups in MERCHANT_PLAN.items():
        for mcc, count, stems in groups:
            for k in range(count):
                city, state = rng.choice(CITIES)
                base = stems[k % len(stems)]
                clean = base if k < len(stems) else f"{base} {city}"
                financial = mcc == "6011"
                m = {"id": ident("MERCH", number), "card_id": ident("MER-CARD", number), "name": clean, "mcc": mcc,
                     "type": mtype, "city": city, "state": state, "category_id": MCC_CATEGORY.get(mcc, "CAT-025"),
                     "financial": financial, "insurance": mcc == "6300"}
                merchants.append(m)
                slug = "".join(ch for ch in clean.lower() if ch.isalnum())
                row = tables.add(stem, merchant_id=m["id"], raw_merchant_name=f"{clean.upper()} {rng.randint(100, 9999)}",
                                 clean_merchant_name=clean, parent_company=f"{base} Holdings" if k >= len(stems) else None,
                                 logo_url=f"https://cdn.example.com/logos/{slug}.png" if rng.random() < 0.7 else None,
                                 website=f"https://{slug}.example.com", primary_mcc=mcc,
                                 primary_category="FINANCIAL" if financial or mcc == "6300" else primary_category[mtype],
                                 primary_subcategory=NEW_MCC[mcc][2] if mcc in NEW_MCC else ANCHOR_SUBCATEGORY[mcc],
                                 merchant_type=mtype, is_subscription=mtype == "SUBSCRIPTION",
                                 is_utility=mtype == "UTILITY", is_financial_institution=financial,
                                 enrichment_source=sources[number % 4], confidence_score=rng.randint(60, 99),
                                 last_updated_at=ts(rand_dt(rng, WINDOW_START, AS_OF - dt.timedelta(days=1))))
                stamp_current(rng, row)
                number += 1
    return merchants


def _categories(tables, rng):
    stem = "enriched_transactions-transaction_category"
    names = {r["category_id"]: r["category_name"] for _, r in tables.anchors[stem]}
    names.update({cid: spec[0] for cid, spec in NEW_CATEGORIES.items()})
    for i, (cid, (name, parent, desc, icon)) in enumerate(NEW_CATEGORIES.items()):
        path = f"{names[parent]} > {name}" if parent else name
        created = at(dt.date(2023, 1, 1)) if i < 11 else at(dt.date(2024, 6, 1))
        row = tables.add(stem, category_id=cid, category_name=name, parent_category_id=parent,
                         category_level=2 if parent else 1, category_path=path, description=desc, icon=icon,
                         color=["#4A90D9", "#50B37D", "#E8A33D", "#D9534F", "#8E6BBF", "#3DB2C9"][i % 6],
                         is_system=True, is_active=True, sort_order=3 + i, created_at=ts(created),
                         updated_at=ts(created))
        stamp_current(rng, row)
    return names


def activity_window(a):
    """Dates during which the customer drives activity on the account."""
    start = max(a["opened"], WINDOW_START_DATE)
    end = AS_OF_DATE
    if a["closed"]:
        end = min(end, a["closed"] - dt.timedelta(days=1))
    if a["frozen_at"]:
        end = min(end, a["frozen_at"] - dt.timedelta(days=1))
    if a["dormant_since"]:
        end = min(end, a["dormant_since"])
    return start, end


def _step(day, frequency, n=1):
    if frequency in ("MONTHLY", "QUARTERLY", "ANNUAL"):
        return add_months(day, n * {"MONTHLY": 1, "QUARTERLY": 3, "ANNUAL": 12}[frequency])
    return day + dt.timedelta(days=n * PERIOD_DAYS[frequency])


def _plan_recurring(rng, world):
    by_kind = {
        "SUBSCRIPTION": [m for m in world["merchants"] if m["mcc"] == "4899"],
        "MEMBERSHIP": [m for m in world["merchants"] if m["mcc"] == "7997"],
        "BILL": [m for m in world["merchants"] if m["type"] == "UTILITY"],
        "INSURANCE": [m for m in world["merchants"] if m["insurance"]],
        "LOAN_PAYMENT": [m for m in world["merchants"] if m["financial"]],
    }
    eligible = [a for a in world["accounts"] if a["type"] == "CHECKING" and a["status"] in ("OPEN", "CLOSED", "FROZEN")]
    plans, number = [], 6
    for a in eligible:
        start, end = activity_window(a)
        if end <= start + dt.timedelta(days=45):
            continue
        for _ in range(weighted(rng, [(0, 15), (1, 45), (2, 30), (3, 10)])):
            kind = weighted(rng, [("SUBSCRIPTION", 35), ("BILL", 30), ("INSURANCE", 12), ("MEMBERSHIP", 10), ("LOAN_PAYMENT", 13)])
            frequency = {"SUBSCRIPTION": weighted(rng, [("MONTHLY", 80), ("ANNUAL", 10), ("WEEKLY", 10)]),
                         "MEMBERSHIP": weighted(rng, [("MONTHLY", 75), ("ANNUAL", 25)]),
                         "BILL": weighted(rng, [("MONTHLY", 85), ("QUARTERLY", 15)]),
                         "INSURANCE": weighted(rng, [("MONTHLY", 60), ("QUARTERLY", 20), ("ANNUAL", 20)]),
                         "LOAN_PAYMENT": weighted(rng, [("MONTHLY", 80), ("BIWEEKLY", 20)])}[kind]
            merchant = rng.choice(by_kind[kind])
            amount = {"SUBSCRIPTION": lognormal_cents(rng, 1500, 0.5, 499, 9999, 1),
                      "MEMBERSHIP": lognormal_cents(rng, 4500, 0.5, 1500, 25000, 1),
                      "BILL": lognormal_cents(rng, 11000, 0.5, 2500, 60000, 1),
                      "INSURANCE": lognormal_cents(rng, 14000, 0.5, 4000, 90000, 1),
                      "LOAN_PAYMENT": lognormal_cents(rng, 42000, 0.5, 9000, 250000, 1)}[kind]
            if frequency == "ANNUAL":
                amount *= 10
            elif frequency == "QUARTERLY":
                amount *= 3
            status = "ENDED" if a["closed"] else weighted(rng, [("ACTIVE", 72), ("ENDED", 13), ("PAUSED", 8), ("UNCERTAIN", 7)])
            period = PERIOD_DAYS[frequency]
            if status == "ACTIVE":
                last = end - dt.timedelta(days=rng.randint(0, max(1, int(period * 0.8))))
            elif status == "ENDED":
                last = rand_date(rng, start, max(start, end - dt.timedelta(days=60)))
            elif status == "PAUSED":
                last = end - dt.timedelta(days=int(period * rng.uniform(1.6, 3.0)))
            else:
                last = end - dt.timedelta(days=int(period * rng.uniform(1.1, 1.9)))
            if last < start or last > AS_OF_DATE - dt.timedelta(days=1):
                continue
            occurrences = [last]
            for back in range(1, rng.randint(1, 3)):
                prev = _step(last, frequency, -back)
                if prev < start:
                    break
                occurrences.append(prev)
            first = min(occurrences)
            history = rng.randint(0, 18)
            for _ in range(history):
                earlier = _step(first, frequency, -1)
                if earlier < a["opened"]:
                    break
                first = earlier
            count = 1
            cur = first
            while cur < last:
                cur = _step(cur, frequency)
                count += 1
            plans.append({"id": ident("REC", number), "account": a, "merchant": merchant, "kind": kind,
                          "frequency": frequency, "amount": amount, "status": status, "first": first, "last": last,
                          "occurrences": sorted(occurrences), "count": count,
                          "missed": rng.randint(0, 2) if status in ("PAUSED", "UNCERTAIN") else weighted(rng, [(0, 80), (1, 15), (2, 5)]),
                          "detection": weighted(rng, [("MERCHANT_MATCH", 50), ("AMOUNT_FREQUENCY", 35), ("DESCRIPTION_MATCH", 15)]),
                          "confidence": rng.randint(62, 99), "transactions": []})
            number += 1
    return plans


def _base_type(rng, a):
    c = a["customer"]
    if a["type"] == "CHECKING" and c["type"] == "BUSINESS":
        return weighted(rng, [("TT-POS", 15), ("TT-ACH-CR", 22), ("TT-ACH-DR", 18), ("TT-WIRE-OUT", 7), ("TT-WIRE-IN", 6),
                              ("TT-CHK", 12), ("TT-DEP", 10), ("TT-XFER-OUT", 4), ("TT-XFER-IN", 4), ("TT-FEE", 2)])
    if a["type"] == "CHECKING":
        return weighted(rng, [("TT-POS", 40), ("TT-WDL", 9), ("TT-MOB-DEP", 6), ("TT-DEP", 3), ("TT-ATM-DEP", 2),
                              ("TT-ACH-CR", 12), ("TT-ACH-DR", 5), ("TT-CHK", 5), ("TT-XFER-OUT", 6), ("TT-XFER-IN", 6),
                              ("TT-WIRE-OUT", 1.5), ("TT-WIRE-IN", 1), ("TT-FEE", 3)])
    if a["type"] == "IRA":
        return weighted(rng, [("TT-DEP", 55), ("TT-XFER-IN", 35), ("TT-WDL", 10)])
    return weighted(rng, [("TT-XFER-IN", 34), ("TT-XFER-OUT", 22), ("TT-DEP", 9), ("TT-MOB-DEP", 8), ("TT-WDL", 8),
                          ("TT-ACH-CR", 12), ("TT-WIRE-IN", 4), ("TT-WIRE-OUT", 3)])


def _amount(rng, a, code, merchant=None):
    business = a["customer"]["type"] == "BUSINESS"
    if code == "TT-POS":
        median = {"5411": 8500, "5300": 16000, "5541": 5200, "5812": 4200, "5814": 1400, "5732": 26000, "7011": 32000,
                  "4511": 45000, "8062": 60000}.get(merchant["mcc"] if merchant else "", 4500)
        return lognormal_cents(rng, median, 0.7, 150, 400000, 1)
    if code == "TT-WDL":
        return rng.choice([2000, 4000, 6000, 8000, 10000, 20000, 30000, 50000])
    if code in ("TT-MOB-DEP", "TT-ATM-DEP"):
        return lognormal_cents(rng, 40000, 0.8, 1000, 500000)
    if code == "TT-DEP":
        return lognormal_cents(rng, 300000 if business else 60000, 0.8, 2000, 5000000)
    if code == "TT-ACH-CR":
        if business:
            return lognormal_cents(rng, 250000, 0.8, 5000, 8000000)
        income = a["customer"]["income"] or 4000000
        return max(20000, income // 26 // 100 * 100 - rng.randint(0, 20) * 100)
    if code == "TT-ACH-DR":
        return lognormal_cents(rng, 180000 if business else 15000, 0.7, 1000, 6000000, 1)
    if code == "TT-CHK":
        return lognormal_cents(rng, 120000 if business else 30000, 0.8, 1000, 3000000)
    if code in ("TT-XFER-IN", "TT-XFER-OUT"):
        return lognormal_cents(rng, 50000, 0.9, 1000, 3000000)
    if code in ("TT-WIRE-OUT", "TT-WIRE-IN"):
        return lognormal_cents(rng, 2500000 if business else 800000, 0.8, 50000, 90000000)
    if code == "TT-FEE":
        return rng.choice([500, 1000, 1500, 2500])
    return 1000


def _counterparty(rng, a, code, merchant):
    if merchant:
        return merchant["name"]
    if code == "TT-ACH-CR":
        return "Payroll - " + (a["customer"]["employment"]["employer"] if a["customer"].get("employment") else "Customer payment")
    if code in ("TT-WIRE-OUT", "TT-WIRE-IN"):
        return rng.choice(["Acme Contractor LLC", "Sunrise Realty LLC", "Overseas Trading Co", "Metro Supply Co",
                           "Title Escrow Services", "Pacific Import Partners"])
    if code == "TT-ACH-DR":
        return rng.choice(["Metro Supply Co", "Statewide Insurance Co", "Northern Leasing", "Office Depot"])
    return None


def _description(code, merchant, extra):
    if extra.get("reversal"):
        return extra["reversal"]
    return {"TT-POS": f"{merchant['name']} card purchase" if merchant else "Card purchase", "TT-WDL": "ATM cash withdrawal",
            "TT-MOB-DEP": "Mobile check deposit", "TT-ATM-DEP": "ATM deposit", "TT-DEP": "Branch deposit",
            "TT-ACH-CR": "ACH credit", "TT-ACH-DR": f"{merchant['name']} ACH payment" if merchant else "ACH debit",
            "TT-CHK": "Check paid", "TT-XFER-IN": "Online transfer in", "TT-XFER-OUT": "Online transfer out",
            "TT-WIRE-OUT": "Outgoing wire transfer", "TT-WIRE-IN": "Incoming wire transfer",
            "TT-FEE": "Monthly maintenance fee", "TT-OD-FEE": "Overdraft fee", "TT-INT": "Interest credit"}[code]


def _simulate(rng, world):
    accounts = world["accounts"]
    pos_merchants = [m for m in world["merchants"] if m["type"] in ("RETAIL", "RESTAURANT")
                     or m["mcc"] in ("4121", "4111", "7832", "8011", "7011", "4511", "7299", "7995", "6051", "8062")]
    pos_weights = [(m, {"5411": 6, "5541": 4, "5812": 3, "5814": 3, "7995": 0.3, "6051": 0.3}.get(m["mcc"], 1)) for m in pos_merchants]
    rate = {"CHECKING": 1.0, "SAVINGS": 0.22, "MONEY_MARKET": 0.18, "CD": 0.0, "IRA": 0.06}
    weights = {}
    for a in accounts:
        start, end = activity_window(a)
        days = max(0, (end - start).days)
        factor = rate[a["type"]] * (1.7 if a["customer"]["type"] == "BUSINESS" else 1.0)
        weights[a["id"]] = days * factor
    total_weight = sum(weights.values()) or 1
    by_account = {}
    for plan in world["recurring"]:
        by_account.setdefault(plan["account"]["id"], []).append(plan)
    open_checking = [a for a in accounts if a["type"] == "CHECKING" and a["status"] == "OPEN"]
    today_accounts = rng.sample([a for a in open_checking if a["customer"]["type"] == "INDIVIDUAL"], 6)
    # A few wires and ACH credits still in flight, so every in-flight status has examples.
    in_flight = dict(zip([a["id"] for a in rng.sample(open_checking, 16)],
                         ["TT-WIRE-OUT"] * 8 + ["TT-WIRE-IN"] * 3 + ["TT-ACH-CR"] * 5))
    ledger = []
    for a in accounts:
        start, end = activity_window(a)
        events = []  # heap of (datetime, seq, code, amount, extra)
        seq = [0]

        def push(when, code, amount=None, **extra):
            seq[0] += 1
            heapq.heappush(events, (when, seq[0], code, amount, extra))

        balance = a["initial_balance"] if a["opened"] < WINDOW_START_DATE else 0
        escheat_day = next((s[2] for s in a["status_changes"] if s[1] == "ESCHEAT"), None)
        if (a["closed"] and a["closed"] < WINDOW_START_DATE) or (escheat_day and escheat_day < WINDOW_START_DATE):
            balance = 0
        if escheat_day and escheat_day < WINDOW_START_DATE:
            escheat_day = None
        a["start_balance"] = balance
        if a["opened"] >= WINDOW_START_DATE:
            push(business_time(rng, a["opened"], 9, 16), rng.choice(["TT-DEP", "TT-XFER-IN", "TT-MOB-DEP"]),
                 a["initial_balance"], opening=True)
        n = int(round(weights[a["id"]] / total_weight * BASE_EVENT_BUDGET + rng.uniform(-0.5, 0.5)))
        if end > start:
            for _ in range(max(0, n)):
                push(business_time(rng, rand_date(rng, start + dt.timedelta(days=1), end)), None)
        for plan in by_account.get(a["id"], []):
            for day in plan["occurrences"]:
                code = "TT-POS" if plan["kind"] in ("SUBSCRIPTION", "MEMBERSHIP") else "TT-ACH-DR"
                push(business_time(rng, day, 3, 9), code, plan["amount"], recurring=plan, merchant=plan["merchant"])
        if a in today_accounts:
            push(business_time(rng, AS_OF_DATE, 7, 15), "TT-POS")
            push(business_time(rng, AS_OF_DATE, 7, 15), "TT-ACH-DR")
        if a["id"] in in_flight:
            push(rand_dt(rng, AS_OF - dt.timedelta(hours=30), AS_OF - dt.timedelta(hours=1)), in_flight[a["id"]])
        if a["interest_bearing"]:
            for year in (2023, 2024, 2025):
                day = dt.date(year, 12, 31)
                if start <= day <= (a["closed"] or AS_OF_DATE) and rng.random() < 0.3:
                    push(at(day, 23, 50), "TT-INT", internal=True)
        close_day = a["closed"] if a["closed"] and a["closed"] >= WINDOW_START_DATE else None
        if close_day:
            cutoff = at(close_day, 23, 30)
        elif escheat_day:
            cutoff = at(escheat_day, 3, 0)
        else:
            cutoff = AS_OF - dt.timedelta(minutes=15)
        while events:
            when, _, code, amount, extra = heapq.heappop(events)
            if when >= cutoff:
                continue
            merchant = extra.get("merchant")
            if code is None:
                code = _base_type(rng, a)
                if code == "TT-POS":
                    merchant = weighted(rng, pos_weights)
                if code == "TT-FEE" and a["product"] in ("PROD-SAV-HY", "PROD-CD-6M"):
                    code = "TT-XFER-IN"
            if code == "TT-POS" and merchant is None:
                merchant = weighted(rng, pos_weights)
            if code == "TT-INT":
                amount = max(1, int(max(balance, 0) * (a["rate"] or 0) * rng.uniform(0.2, 1.0)))
            if amount is None:
                amount = _amount(rng, a, code, merchant)
            category = CATEGORY[code]
            if category == "DEBIT" and not extra.get("recurring") and code not in ("TT-FEE", "TT-OD-FEE"):
                if a["type"] != "CHECKING" and amount > balance * 0.8:
                    if balance < 2000:
                        code, category, merchant = "TT-XFER-IN", "CREDIT", None
                        amount = _amount(rng, a, code)
                    else:
                        amount = max(1000, int(balance * rng.uniform(0.1, 0.6)) // 100 * 100)
                elif a["type"] == "CHECKING" and amount > balance and rng.random() < 0.75:
                    if balance > 3000:
                        amount = max(500, int(balance * rng.uniform(0.2, 0.9)))
                    else:
                        code, category, merchant = rng.choice(["TT-MOB-DEP", "TT-XFER-IN"]), "CREDIT", None
                        amount = _amount(rng, a, code)
            channel = extra.get("channel") or CHANNEL[code]
            if code == "TT-DEP" and rng.random() < 0.2 and not extra.get("reversal"):
                channel = "ATM"
            if code == "TT-WDL" and amount >= 50000:
                channel = "BRANCH"
            if code in ("TT-XFER-IN", "TT-XFER-OUT") and rng.random() < 0.45:
                channel = "MOBILE"
            status = "POSTED"
            recent = when >= AS_OF - dt.timedelta(hours=36)
            if recent and code in ("TT-POS", "TT-ACH-DR", "TT-ACH-CR", "TT-WIRE-OUT", "TT-WIRE-IN", "TT-CHK", "TT-MOB-DEP"):
                status = "PENDING"
            elif code == "TT-ACH-DR" and not extra.get("recurring") and (balance < amount and rng.random() < 0.5 or rng.random() < 0.02):
                status = "RETURNED"
            elif code == "TT-WIRE-OUT" and rng.random() < 0.06:
                status = "RETURNED"
            txn = {"account": a, "code": code, "category": category, "amount": amount, "at": when, "status": status,
                   "channel": channel, "merchant": merchant, "recurring": extra.get("recurring"),
                   "counterparty": _counterparty(rng, a, code, merchant), "reversal_of": extra.get("reversal_of"),
                   "reversal_type": extra.get("reversal_type"), "balance": None, "opening": extra.get("opening", False)}
            txn["description"] = _description(code, merchant, extra)
            if txn["recurring"]:
                txn["recurring"]["transactions"].append(txn)
            affects = status == "POSTED"
            if affects:
                balance += amount if category == "CREDIT" else -amount
                txn["balance"] = balance
            ledger.append(txn)
            # Follow-up events: overdraft fees and reversals.
            if affects and category == "DEBIT" and a["type"] == "CHECKING" and balance < 0 and code != "TT-OD-FEE" and rng.random() < 0.6:
                push(at(when.date() + dt.timedelta(days=1), 2, rng.randint(0, 59)), "TT-OD-FEE", 3500, internal=True)
            if affects and not txn["reversal_of"] and not txn["opening"]:
                reversible = (category == "DEBIT" and code in ("TT-POS", "TT-ACH-DR", "TT-FEE", "TT-OD-FEE", "TT-CHK")) or \
                             (category == "CREDIT" and code == "TT-ACH-CR" and a["type"] == "CHECKING")
                if reversible and rng.random() < (0.05 if category == "DEBIT" else 0.02):
                    kind = "CORRECTION" if category == "CREDIT" or code in ("TT-FEE", "TT-OD-FEE") else weighted(rng, [("FULL", 55), ("PARTIAL", 45)])
                    rev_amount = amount if kind in ("FULL", "CORRECTION") and code != "TT-ACH-CR" else max(1, int(amount * rng.uniform(0.2, 0.8)))
                    rev_code = "TT-WDL" if category == "CREDIT" else "TT-DEP"
                    label = {"FULL": "Full reversal", "PARTIAL": "Partial reversal", "CORRECTION": "Correction"}[kind]
                    push(when + dt.timedelta(hours=rng.randint(1, 120)), rev_code, rev_amount, channel="INTERNAL",
                         reversal_of=txn, reversal_type=kind, reversal=f"{label} of prior {code} transaction")
            if txn["reversal_of"] and txn["reversal_type"] == "FULL":
                txn["reversal_of"]["status"] = "REVERSED"
        if close_day:
            final = at(close_day, 23, 30)
            if final <= AS_OF - dt.timedelta(minutes=15) and balance != 0:
                code = "TT-XFER-OUT" if balance > 0 else "TT-XFER-IN"
                txn = {"account": a, "code": code, "category": CATEGORY[code], "amount": abs(balance), "at": final,
                       "status": "POSTED", "channel": "INTERNAL", "merchant": None, "recurring": None,
                       "counterparty": None, "reversal_of": None, "reversal_type": None, "balance": 0,
                       "opening": False, "description": "Account closure - balance transferred" if balance > 0 else
                       "Account closure - overdraft settled"}
                ledger.append(txn)
                balance = 0
        elif escheat_day:
            final = at(escheat_day, 3, 0)
            if balance > 0:
                ledger.append({"account": a, "code": "TT-XFER-OUT", "category": "DEBIT", "amount": balance, "at": final,
                               "status": "POSTED", "channel": "INTERNAL", "merchant": None, "recurring": None,
                               "counterparty": "State Unclaimed Property Division", "reversal_of": None,
                               "reversal_type": None, "balance": 0, "opening": False,
                               "description": "Escheat remittance to state"})
                balance = 0
        a["final_balance"] = balance
    # Number transactions globally in time order.
    ledger.sort(key=lambda t: (t["at"], t["account"]["n"]))
    for i, txn in enumerate(ledger):
        txn["id"] = ident("TXN", 31 + i)
    return ledger
