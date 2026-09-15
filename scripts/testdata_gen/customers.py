"""Customer master and KYC/AML bronze data: 492 generated customers (CUST-009 … CUST-500)."""
import datetime as dt

from common import (AS_OF, AS_OF_DATE, WINDOW_START, WINDOW_START_DATE, add_months, at, business_time,
                    ds, ident, rand_date, rand_dt, rng_for, stamp_bronze, ts, weighted)

FIRST_MALE = ["James", "Michael", "David", "Daniel", "Carlos", "Anthony", "Kevin", "Brian", "Jason", "Ryan",
              "Eric", "Andrew", "Joshua", "Luis", "Samuel", "Thomas", "Nathan", "Aaron", "Marcus", "Omar",
              "Ethan", "Wei", "Raj", "Hiroshi", "Patrick"]
FIRST_FEMALE = ["Mary", "Jennifer", "Linda", "Patricia", "Jessica", "Ashley", "Emily", "Sophia", "Olivia",
                "Isabella", "Grace", "Hannah", "Lauren", "Megan", "Rachel", "Priya", "Mei", "Ana", "Fatima",
                "Chloe", "Natalie", "Victoria", "Yuna", "Elena", "Rosa"]
MIDDLE = ["Lee", "Marie", "Ann", "James", "Ray", "Lynn", "Grace", "Alan", "Jo", "Paul", "Rose", "Scott"]
LAST = ["Anderson", "Brooks", "Carter", "Diaz", "Edwards", "Foster", "Gonzalez", "Harris", "Iverson", "Jackson",
        "Khan", "Lopez", "Martin", "Nguyen", "Ortiz", "Patel", "Quinn", "Rivera", "Sanchez", "Turner",
        "Underwood", "Vasquez", "Walker", "Xu", "Young", "Zimmerman", "Park", "Kim", "Murphy", "Reyes",
        "Bennett", "Coleman", "Hughes", "Price", "Ross", "Sullivan", "Tanaka", "Wright", "Baker", "Morgan"]
BUSINESS_WORD = ["Summit", "Harbor", "Pioneer", "Blue Ridge", "Northwind", "Cedar", "Granite", "Riverbend",
                 "Evergreen", "Keystone", "Silverline", "Oakmont", "Brightpath", "Ironwood", "Lakeshore"]
BUSINESS_KIND = ["Industries", "Logistics", "Consulting", "Builders", "Foods", "Dental Group", "Design Studio",
                 "Auto Repair", "Holdings", "Marketing"]
STREETS = ["Oak", "Maple", "Pine", "Elm", "Cedar", "Birch", "Willow", "Lake", "Hill", "Park", "River", "Main",
           "Washington", "Lincoln", "Sunset", "Meadow", "Highland", "Forest", "Spring", "Church"]
STREET_KIND = ["Street", "Avenue", "Road", "Lane", "Drive", "Court", "Boulevard", "Way"]
# city, state, zip prefix, county, msa, area code
CITIES = [("Springfield", "IL", "627", "Sangamon", "44100", "217"), ("Chicago", "IL", "606", "Cook", "16980", "312"),
          ("Evanston", "IL", "602", "Cook", "16980", "847"), ("Austin", "TX", "787", "Travis", "12420", "512"),
          ("Dallas", "TX", "752", "Dallas", "19100", "214"), ("Houston", "TX", "770", "Harris", "26420", "713"),
          ("Denver", "CO", "802", "Denver", "19740", "720"), ("Boulder", "CO", "803", "Boulder", "14500", "303"),
          ("Seattle", "WA", "981", "King", "42660", "206"), ("Tacoma", "WA", "984", "Pierce", "42660", "253"),
          ("San Francisco", "CA", "941", "San Francisco", "41860", "415"),
          ("San Diego", "CA", "921", "San Diego", "41740", "619"), ("Columbus", "OH", "432", "Franklin", "18140", "614"),
          ("Phoenix", "AZ", "850", "Maricopa", "38060", "602"), ("Atlanta", "GA", "303", "Fulton", "12060", "404"),
          ("Portland", "OR", "972", "Multnomah", "38900", "503")]
EMPLOYERS = [("Springfield Manufacturing Co.", "Production Manager"), ("Memorial Health System", "Registered Nurse"),
             ("Lakeshore Public Schools", "Teacher"), ("Northwind Software", "Software Engineer"),
             ("Granite Construction Partners", "Project Manager"), ("City of Springfield", "Civil Engineer"),
             ("Evergreen Retail Group", "Store Manager"), ("Pioneer Logistics", "Operations Analyst"),
             ("Summit Financial Advisors", "Financial Advisor"), ("Harbor Dental Group", "Dental Hygienist"),
             ("Riverbend University", "Professor"), ("Keystone Insurance", "Claims Adjuster"),
             ("Blue Ridge Energy", "Field Technician"), ("Oakmont Law LLP", "Paralegal"),
             ("Brightpath Marketing", "Account Director")]
FIRST_CUSTOMER, LAST_CUSTOMER = 9, 500


def _new_person(rng, number, start):
    female = rng.random() < 0.5
    first = rng.choice(FIRST_FEMALE if female else FIRST_MALE)
    last = rng.choice(LAST)
    age = weighted(rng, [(rng.randint(19, 29), 18), (rng.randint(30, 44), 30), (rng.randint(45, 64), 34),
                         (rng.randint(65, 88), 18)])
    dob = rand_date(rng, dt.date(AS_OF_DATE.year - age - 1, AS_OF_DATE.month, 1),
                    dt.date(AS_OF_DATE.year - age, 8, 31))
    return {"first": first, "middle": rng.choice(MIDDLE) if rng.random() < 0.6 else None, "last": last,
            "suffix": rng.choice(["Jr.", "Sr.", "III"]) if rng.random() < 0.04 else None, "dob": dob, "age": age}


def build(tables, world):
    rng = rng_for("customers")
    customers, singles = [], []
    for number in range(FIRST_CUSTOMER, LAST_CUSTOMER + 1):
        cid = ident("CUST", number)
        ctype = weighted(rng, [("INDIVIDUAL", 88), ("JOINT", 4), ("TRUST", 3), ("BUSINESS", 5)])
        if rng.random() < 0.7:
            start = rand_date(rng, dt.date(2010, 1, 20), WINDOW_START_DATE - dt.timedelta(days=1))
        else:
            start = rand_date(rng, WINDOW_START_DATE, AS_OF_DATE - dt.timedelta(days=20))
        city = rng.choice(CITIES)
        c = {"id": cid, "n": number, "type": ctype, "start": start, "city": city, "spouse": None,
             "street": f"{rng.randint(10, 9899)} {rng.choice(STREETS)} {rng.choice(STREET_KIND)}",
             "zip": city[2] + f"{rng.randint(1, 99):02d}", "phone_suffix": f"{number % 100:02d}"}
        if ctype in ("INDIVIDUAL", "JOINT"):
            c.update(_new_person(rng, number, start))
            if ctype == "JOINT":
                c["first"] = f"{c['first']} and {rng.choice(FIRST_FEMALE + FIRST_MALE)}"
                c["middle"] = None
        elif ctype == "TRUST":
            c.update({"first": f"{rng.choice(LAST)} Family", "middle": None, "last": "Trust", "suffix": None,
                      "dob": None, "age": None})
        else:
            c.update({"first": rng.choice(BUSINESS_WORD), "middle": None, "last": rng.choice(BUSINESS_KIND),
                      "suffix": rng.choice(["LLC", "Inc.", "Corp."]), "dob": None, "age": None})
        # Marry some individuals: the spouse takes the partner's surname and address.
        if ctype == "INDIVIDUAL" and singles and rng.random() < 0.2:
            partner = singles.pop(rng.randrange(len(singles)))
            c["last"], c["city"], c["street"], c["zip"] = partner["last"], partner["city"], partner["street"], partner["zip"]
            c["spouse"], partner["spouse"] = partner["id"], cid
            c["start"] = max(c["start"], partner["start"])
        elif ctype == "INDIVIDUAL" and c["age"] >= 24:
            singles.append(c)
        status = weighted(rng, [("ACTIVE", 88), ("INACTIVE", 6), ("CLOSED", 4), ("DECEASED", 2)])
        end = None
        latest_end = AS_OF_DATE - dt.timedelta(days=30)
        earliest_end = max(c["start"] + dt.timedelta(days=180), WINDOW_START_DATE)
        if status != "ACTIVE" and earliest_end < latest_end and (status != "DECEASED" or (c["age"] or 0) > 60):
            end = rand_date(rng, earliest_end, latest_end)
        else:
            status = "ACTIVE"
        c["status"], c["end"] = status, end
        c["full_name"] = " ".join(p for p in [c["first"], c["middle"], c["last"], c["suffix"]] if p)
        handle = f"{c['first'].split()[0]}.{c['last']}".lower().replace(" ", "")
        c["email"] = f"{handle}{number}@example.com"
        c["phone"] = f"+1-{city[5]}-555-01{c['phone_suffix']}"
        c["phone_compact"] = f"+1{city[5]}55501{c['phone_suffix']}"
        c["digital"] = rng.random() < (0.85 if (c["age"] or 40) < 60 else 0.45)
        c["source_system"] = ("COMMERCIAL_BANKING" if ctype in ("BUSINESS", "TRUST")
                              else ("DIGITAL_ONBOARD" if c["digital"] and start.year >= 2019 else "CORE_BANKING"))
        c["citizenship"] = weighted(rng, [("US", 92), ("MX", 3), ("CA", 2), ("IN", 1), ("KR", 1), ("GB", 1)])
        c["language"] = "es" if c["citizenship"] == "MX" or rng.random() < 0.05 else "en"
        c["risk_rating"] = weighted(rng, [("LOW", 70), ("MEDIUM", 25), ("HIGH", 5)])
        c["is_pep"] = c["type"] == "INDIVIDUAL" and rng.random() < 0.02
        if c["is_pep"]:
            c["risk_rating"] = "HIGH"
        if c["type"] in ("INDIVIDUAL", "JOINT") and (c["age"] or 0) >= 22:
            employer, title = rng.choice(EMPLOYERS)
            retired = c["age"] >= 67
            c["employment"] = {"employer": employer, "title": title, "retired": retired,
                               "type": weighted(rng, [("FULL_TIME", 78), ("PART_TIME", 8), ("SELF_EMPLOYED", 14)])}
            c["income"] = rng.randint(35, 260) * 100000 if not retired else rng.randint(25, 90) * 100000
        else:
            c["employment"] = None
            c["income"] = rng.randint(30, 900) * 1000000 if c["type"] == "BUSINESS" else None
        customers.append(c)
    world["customers"] = customers
    world["customer_by_id"] = {c["id"]: c for c in customers}
    _customer_rows(tables, rng, customers)
    _address_rows(tables, rng, customers)
    _contact_rows(tables, rng, customers)
    _employment_rows(tables, rng, customers)
    _relationship_rows(tables, rng, customers)
    _kyc_rows(tables, rng, customers)


def last_change(rng, c):
    """The latest change to a customer record: its end date, its onboarding, or a profile update."""
    if c["end"]:
        return business_time(rng, c["end"])
    if c["start"] >= WINDOW_START_DATE or rng.random() < 0.4:
        return business_time(rng, c["start"])
    return rand_dt(rng, WINDOW_START, AS_OF - dt.timedelta(days=1))


def _customer_rows(tables, rng, customers):
    stem = "customer_master-customer"
    for c in customers:
        individual = c["type"] in ("INDIVIDUAL", "JOINT")
        row = tables.add(stem, customer_id=c["id"], first_name=c["first"], middle_name=c["middle"],
                         last_name=c["last"], name_suffix=c["suffix"], date_of_birth=ds(c["dob"]),
                         ssn=f"9{rng.randint(0, 99):02d}-{rng.randint(10, 99)}-{rng.randint(1000, 9999)}" if individual else None,
                         tin=None if individual else f"9{rng.randint(1, 9)}-{rng.randint(1000000, 9999999)}",
                         customer_type=c["type"], customer_status=c["status"],
                         relationship_start_date=ds(c["start"]), relationship_end_date=ds(c["end"]),
                         citizenship_country=c["citizenship"], residency_country="US",
                         preferred_language=c["language"], source_system=c["source_system"])
        stamp_bronze(rng, row, last_change(rng, c))


def _address_rows(tables, rng, customers):
    stem = "customer_master-customer_address"
    for c in customers:
        city = c["city"]
        current_from = c["start"]
        if rng.random() < 0.3 and (AS_OF_DATE - c["start"]).days > 400:
            current_from = rand_date(rng, c["start"] + dt.timedelta(days=200), AS_OF_DATE - dt.timedelta(days=30))
            prior_city = rng.choice([x for x in CITIES if x[1] == city[1]])
            row = tables.add(stem, customer_id=c["id"], address_type="PRIMARY",
                             address_line_1=f"{rng.randint(10, 9899)} {rng.choice(STREETS)} {rng.choice(STREET_KIND)}",
                             address_line_2=None, city=prior_city[0], state_province=prior_city[1],
                             postal_code=prior_city[2] + f"{rng.randint(1, 99):02d}", country_code="US",
                             effective_from=ds(c["start"]), effective_to=ds(current_from), is_current=False,
                             verification_status="VERIFIED", verified_at=ts(business_time(rng, c["start"])),
                             source_system=c["source_system"])
            stamp_bronze(rng, row, business_time(rng, current_from))
        verified = rng.random() < 0.95
        row = tables.add(stem, customer_id=c["id"], address_type="PRIMARY", address_line_1=c["street"],
                         address_line_2=rng.choice([None, None, None, f"Apt {rng.randint(1, 40)}{rng.choice('ABCD')}"]),
                         city=city[0], state_province=city[1], postal_code=c["zip"], country_code="US",
                         effective_from=ds(current_from), effective_to=None, is_current=True,
                         verification_status="VERIFIED" if verified else "UNVERIFIED",
                         verified_at=ts(business_time(rng, current_from + dt.timedelta(days=2))) if verified else None,
                         source_system=c["source_system"])
        stamp_bronze(rng, row, business_time(rng, current_from))
        if c["type"] in ("BUSINESS", "TRUST") or rng.random() < 0.05:
            row = tables.add(stem, customer_id=c["id"], address_type="MAILING",
                             address_line_1=f"PO Box {rng.randint(100, 9999)}", address_line_2=None, city=city[0],
                             state_province=city[1], postal_code=c["zip"], country_code="US",
                             effective_from=ds(c["start"]), effective_to=None, is_current=True,
                             verification_status="VERIFIED", verified_at=ts(business_time(rng, c["start"])),
                             source_system=c["source_system"])
            stamp_bronze(rng, row, business_time(rng, c["start"]))


def _contact_rows(tables, rng, customers):
    stem = "customer_master-customer_contact"
    for c in customers:
        verified_day = min(c["start"] + dt.timedelta(days=rng.randint(0, 20)), AS_OF_DATE - dt.timedelta(days=1))
        kinds = [("WORK_PHONE", c["phone"])] if c["type"] in ("BUSINESS", "TRUST") else [("MOBILE", c["phone"])]
        kinds.append(("EMAIL", c["email"]))
        if c["type"] in ("INDIVIDUAL", "JOINT") and rng.random() < 0.2:
            kinds.append(("HOME_PHONE", f"+1-{c['city'][5]}-555-02{c['phone_suffix']}"))
        for i, (kind, value) in enumerate(kinds):
            row = tables.add(stem, customer_id=c["id"], contact_type=kind, contact_value=value, is_primary=i == 0,
                             verification_status="VERIFIED", verified_at=ts(business_time(rng, verified_day)),
                             marketing_opt_in=rng.random() < 0.45, transactional_opt_in=rng.random() < 0.95,
                             source_system=c["source_system"])
            stamp_bronze(rng, row, business_time(rng, verified_day))


def _employment_rows(tables, rng, customers):
    stem = "customer_master-customer_employment"
    for c in customers:
        job = c["employment"]
        if not job:
            continue
        career_start = add_months(c["dob"], 12 * rng.randint(20, 26))
        if rng.random() < 0.08 and not job["retired"]:
            prev_end = rand_date(rng, career_start + dt.timedelta(days=700), AS_OF_DATE - dt.timedelta(days=400))
            prev_employer, prev_title = rng.choice(EMPLOYERS)
            row = tables.add(stem, customer_id=c["id"], employer_name=prev_employer, job_title=prev_title,
                             employment_type="FULL_TIME", employment_status="FORMER",
                             employment_start_date=ds(career_start), employment_end_date=ds(prev_end),
                             annual_income_cents=int(c["income"] * 0.8), income_currency="USD",
                             income_verification_status="STATED", income_verified_at=None,
                             source_system="CORE_BANKING")
            stamp_bronze(rng, row, business_time(rng, prev_end))
            career_start = prev_end + dt.timedelta(days=rng.randint(10, 90))
        start = min(rand_date(rng, career_start, AS_OF_DATE - dt.timedelta(days=60)), AS_OF_DATE - dt.timedelta(days=60))
        end = None
        if job["retired"]:
            end = add_months(c["dob"], 12 * rng.randint(62, 66))
            start = min(start, end - dt.timedelta(days=365))
        verified = rng.random() < 0.7
        verified_at = rand_dt(rng, max(at(start), WINDOW_START), AS_OF - dt.timedelta(days=2)) if verified else None
        row = tables.add(stem, customer_id=c["id"], employer_name=job["employer"], job_title=job["title"],
                         employment_type=job["type"], employment_status="FORMER" if end else "CURRENT",
                         employment_start_date=ds(start), employment_end_date=ds(end),
                         annual_income_cents=c["income"], income_currency="USD",
                         income_verification_status="VERIFIED" if verified else "STATED",
                         income_verified_at=ts(verified_at) if verified_at else None,
                         source_system=c["source_system"] if c["source_system"] != "COMMERCIAL_BANKING" else "CORE_BANKING")
        stamp_bronze(rng, row, verified_at or business_time(rng, max(start, c["start"])))


def _relationship_rows(tables, rng, customers):
    stem = "customer_master-customer_relationship"
    individuals = [c for c in customers if c["type"] == "INDIVIDUAL"]
    by_id = {c["id"]: c for c in customers}
    pairs = []
    for c in customers:
        if c["spouse"] and c["id"] < c["spouse"]:
            pairs.append((c, "SPOUSE", by_id[c["spouse"]]))
    for c in rng.sample(individuals, 30):
        pairs.append((c, "AUTHORIZED_USER", rng.choice(individuals)))
    for c in rng.sample(individuals, 25):
        pairs.append((c, "BENEFICIARY", rng.choice(individuals)))
    for c in rng.sample([x for x in customers if x["type"] in ("INDIVIDUAL", "TRUST", "BUSINESS")], 15):
        pairs.append((c, "POWER_OF_ATTORNEY", rng.choice(individuals)))
    for primary, kind, related in pairs:
        directions = [(primary, related), (related, primary)] if kind == "SPOUSE" else [(primary, related)]
        for a, b in directions:
            if a["id"] == b["id"]:
                continue
            since = rand_date(rng, max(a["start"], b["start"]), AS_OF_DATE - dt.timedelta(days=5))
            row = tables.add(stem, primary_customer_id=a["id"], related_customer_id=b["id"], relationship_type=kind,
                             relationship_start_date=ds(since), relationship_end_date=None, is_active=True,
                             source_system="COMMERCIAL_BANKING" if a["type"] == "BUSINESS" else "CORE_BANKING")
            stamp_bronze(rng, row, business_time(rng, since))


def _kyc_rows(tables, rng, customers):
    kyc_n, pep_n, scr_n = 11, 10, 11
    for c in customers:
        onboard = business_time(rng, c["start"], 9, 17)
        reviews = []
        if rng.random() < 0.18:
            reviews.append(rand_dt(rng, max(WINDOW_START, onboard + dt.timedelta(days=30)), AS_OF - dt.timedelta(days=3)))
        doc_type = "PASSPORT" if c["citizenship"] != "US" else rng.choice(["DRIVERS_LICENSE", "DRIVERS_LICENSE", "PASSPORT"])
        if c["type"] in ("BUSINESS", "TRUST"):
            doc_type = "UTILITY_BILL"
        checks = [("INITIAL", onboard)] + [("PERIODIC_REVIEW", r) for r in reviews]
        if c["is_pep"]:
            checks.append(("ENHANCED_DUE_DILIGENCE", onboard + dt.timedelta(days=3)))
        for kind, when in checks:
            when = min(when, AS_OF - dt.timedelta(hours=1))
            method = "ELECTRONIC" if c["digital"] else rng.choice(["DOCUMENTARY", "IN_PERSON"])
            row = tables.add("kyc_aml-kyc_verification", verification_id=ident("KYC", kyc_n), customer_id=c["id"],
                             verification_type=kind, verification_method=method, document_type=doc_type,
                             document_number=f"{doc_type[0]}{rng.randint(1000000, 99999999)}",
                             document_issuer=c["city"][1] if doc_type == "DRIVERS_LICENSE" else c["citizenship"],
                             document_expiration_date=ds(add_months(when.date(), 12 * rng.randint(2, 9))),
                             verification_result="PASS", verification_score=rng.randint(82, 99), verified_at=ts(when),
                             verification_provider="Jumio" if method == "ELECTRONIC" else "LexisNexis",
                             provider_reference_id=f"{'JM' if method == 'ELECTRONIC' else 'LN'}-{when.year}-{kyc_n:05d}",
                             verified_by=None if method == "ELECTRONIC" else f"EMP-{rng.randint(100, 140)}",
                             notes=None if kind == "INITIAL" else ("Periodic review" if kind == "PERIODIC_REVIEW" else
                                                                   "Enhanced due diligence for PEP"))
            stamp_bronze(rng, row, when)
            kyc_n += 1
        # Risk rating: current row, sometimes preceded by a superseded one.
        current_from = (reviews[0] if reviews else onboard).date()
        cycle = {"LOW": 36, "MEDIUM": 24, "HIGH": 12}
        if rng.random() < 0.12 and current_from > c["start"] + dt.timedelta(days=60):
            prior = rng.choice(["LOW", "MEDIUM"])
            row = tables.add("kyc_aml-customer_risk_rating", customer_id=c["id"], risk_rating=prior,
                             risk_score=rng.randint(10, 45), geographic_risk_score=rng.randint(5, 40),
                             product_risk_score=rng.randint(10, 40), customer_type_risk_score=rng.randint(10, 40),
                             transaction_risk_score=rng.randint(10, 50), model_version="v2.3",
                             reason_codes="DOMESTIC_RESIDENT,STANDARD_PRODUCTS", effective_from=ds(c["start"]),
                             effective_to=ds(current_from - dt.timedelta(days=1)), is_current=False, is_override=False,
                             override_approved_by=None, override_reason=None,
                             next_review_date=ds(add_months(c["start"], cycle[prior])), source_system="RISK_ENGINE")
            stamp_bronze(rng, row, at(current_from, 6))
        score = {"LOW": rng.randint(8, 34), "MEDIUM": rng.randint(35, 64), "HIGH": rng.randint(65, 92)}[c["risk_rating"]]
        reasons = ["DOMESTIC_RESIDENT" if c["citizenship"] == "US" else "FOREIGN_NATIONAL"]
        if c["is_pep"]:
            reasons.append("PEP_FAMILY_MEMBER")
        if c["type"] == "BUSINESS":
            reasons.append("CASH_INTENSIVE_BUSINESS" if c["risk_rating"] != "LOW" else "COMMERCIAL_CUSTOMER")
        if (AS_OF_DATE - c["start"]).days > 3650:
            reasons.append("LONG_TENURE")
        row = tables.add("kyc_aml-customer_risk_rating", customer_id=c["id"], risk_rating=c["risk_rating"],
                         risk_score=score, geographic_risk_score=rng.randint(5, 60),
                         product_risk_score=rng.randint(10, 50), customer_type_risk_score=rng.randint(10, 60),
                         transaction_risk_score=rng.randint(10, 70), model_version="v3.0",
                         reason_codes=",".join(reasons), effective_from=ds(current_from), effective_to=None,
                         is_current=True, is_override=False, override_approved_by=None, override_reason=None,
                         next_review_date=ds(add_months(current_from, cycle[c["risk_rating"]])),
                         source_system="RISK_ENGINE")
        stamp_bronze(rng, row, at(current_from, 6))
        # PEP screening.
        screenings = [("ONBOARDING", onboard)] + ([("PERIODIC", reviews[0])] if reviews and rng.random() < 0.15 else [])
        for kind, when in screenings:
            when = min(when + dt.timedelta(minutes=15), AS_OF - dt.timedelta(minutes=30))
            pep = c["is_pep"]
            row = tables.add("kyc_aml-pep_screening", screening_id=ident("PEP", pep_n), customer_id=c["id"],
                             screening_type=kind, is_pep=pep, pep_category="FAMILY_MEMBER" if pep else None,
                             pep_level="JUNIOR" if pep else None, pep_country=c["citizenship"] if pep else None,
                             pep_position="Relative of municipal official" if pep else None,
                             identified_at=ts(when) if pep else None, pep_ended_at=None, edd_required=pep,
                             pep_source="WorldCheck PEP Database" if pep else None,
                             provider_reference_id=f"WC-PEP-{when.year}-{pep_n:05d}", screened_at=ts(when),
                             source_system="AML_PLATFORM")
            stamp_bronze(rng, row, when)
            pep_n += 1
        # Sanctions screening.
        screenings = [("ONBOARDING", onboard)] + [("PERIODIC", r) for r in reviews]
        if rng.random() < 0.1:
            screenings.append(("PERIODIC", rand_dt(rng, max(WINDOW_START, onboard), AS_OF - dt.timedelta(days=2))))
        for kind, when in screenings:
            when = min(when + dt.timedelta(minutes=15), AS_OF - dt.timedelta(minutes=30))
            hit = rng.random() < 0.03
            reviewed = when + dt.timedelta(hours=rng.randint(2, 30)) if hit else None
            if reviewed and reviewed > AS_OF - dt.timedelta(minutes=20):
                reviewed = AS_OF - dt.timedelta(minutes=20)
            row = tables.add("kyc_aml-sanctions_screening", screening_id=ident("SCR", scr_n), customer_id=c["id"],
                             screening_type=kind,
                             lists_screened=rng.choice(["OFAC_SDN,OFAC_CONSOLIDATED,UN_SANCTIONS",
                                                        "OFAC_SDN,OFAC_CONSOLIDATED,UN_SANCTIONS,EU_SANCTIONS"]),
                             screening_result="POTENTIAL_MATCH" if hit else "CLEAR", match_count=1 if hit else 0,
                             highest_match_score=rng.randint(55, 85) if hit else None,
                             disposition="FALSE_POSITIVE" if hit else None, screened_at=ts(when),
                             screening_provider="WorldCheck", provider_reference_id=f"WC-{when.year}-{scr_n:05d}",
                             reviewed_by=f"EMP-{rng.randint(105, 120)}" if hit else None,
                             reviewed_at=ts(reviewed) if reviewed else None, source_system="AML_PLATFORM")
            stamp_bronze(rng, row, reviewed or when)
            scr_n += 1
