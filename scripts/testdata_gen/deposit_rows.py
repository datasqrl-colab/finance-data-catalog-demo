"""Rows derived from the ledger simulation: ledger, reversals, card, ACH, wire, returns, recurring and unified."""
import datetime as dt

from common import (AS_OF, AS_OF_DATE, at, ds, ident, parse_ts, rand_dt, rng_for, stamp_bronze, stamp_current,
                    stamp_silver, ts, weighted)

NETWORKS = [("VISA", 55), ("MASTERCARD", 35), ("DISCOVER", 7), ("AMEX", 3)]
OUR_BANK = ("First National Bank", "011000015")
BANKS = [("Commercial Banking Partners", "071000013"), ("Metro Supply Bank", "051000017"),
         ("Statewide Insurance Bank", "041000124"), ("City Power & Light Bank", "031000053"),
         ("Acme Industries Bank", "021000021"), ("Johnson Consulting Bank", "061000104"),
         ("Rocky Mountain Bank", "102000076"), ("Springfield Community Bank", "081000032")]
INTL_BANKS = [("GB", "National Westminster Bank", "NWBKGB2L", "London"), ("AE", "Emirates Trade Bank", "ETBKAEAD", "Dubai"),
              ("MX", "Banco del Norte", "BNORMXMM", "Monterrey"), ("DE", "Rhein Handelsbank", "RHBKDEFF", "Frankfurt"),
              ("JP", "Tokai Commerce Bank", "TKCBJPJT", "Nagoya")]
UNIFIED_TYPE = {"TT-POS": "POS_PURCHASE", "TT-ACH-CR": "ACH_CREDIT", "TT-ACH-DR": "ACH_DEBIT", "TT-WIRE-OUT": "WIRE_OUT",
                "TT-WIRE-IN": "WIRE_IN", "TT-DEP": "DEPOSIT", "TT-ATM-DEP": "DEPOSIT", "TT-MOB-DEP": "MOBILE_DEPOSIT",
                "TT-WDL": "WITHDRAWAL", "TT-CHK": "CHECK", "TT-XFER-IN": "TRANSFER_IN", "TT-XFER-OUT": "TRANSFER_OUT",
                "TT-FEE": "FEE", "TT-OD-FEE": "OVERDRAFT_FEE", "TT-INT": "INTEREST"}
CODE_CATEGORY = {"TT-ACH-CR": "CAT-020", "TT-INT": "CAT-021", "TT-FEE": "CAT-017", "TT-OD-FEE": "CAT-017",
                 "TT-WDL": "CAT-019", "TT-DEP": "CAT-022", "TT-ATM-DEP": "CAT-022", "TT-MOB-DEP": "CAT-022",
                 "TT-XFER-IN": "CAT-011", "TT-XFER-OUT": "CAT-011"}
RECURRING_CATEGORY = {"SUBSCRIPTION": "Entertainment", "BILL": "Utilities", "LOAN_PAYMENT": "Loan Payment",
                      "MEMBERSHIP": "Membership", "INSURANCE": "Insurance"}
ECOMMERCE_MCC = {"4899", "7997", "4511", "7011", "5732", "6051", "7995"}


def build(tables, world):
    rng = rng_for("deposit_rows")
    _assign_rail_ids(world)
    _ledger_rows(tables, rng, world)
    _reversal_rows(tables, rng, world)
    _card_rows(tables, rng, world)
    _chargeback_rows(tables, rng, world)
    _ach_rows(tables, rng, world)
    _wire_rows(tables, rng, world)
    _return_rows(tables, rng, world)
    _recurring_rows(tables, rng, world)
    _unified_rows(tables, rng, world)


def _assign_rail_ids(world):
    ach_n, wire_n, trace_n, checks = 7, 6, 2000000, {}
    for t in world["ledger"]:
        if t["code"] in ("TT-ACH-CR", "TT-ACH-DR"):
            t["ach_id"], t["trace"] = ident("ACH", ach_n), f"TRC-{trace_n}"
            ach_n, trace_n = ach_n + 1, trace_n + 1
        elif t["code"] in ("TT-WIRE-OUT", "TT-WIRE-IN"):
            t["wire_id"] = ident("WIRE", wire_n)
            wire_n += 1
        elif t["code"] == "TT-CHK":
            checks[t["account"]["id"]] = checks.get(t["account"]["id"], 1000) + 1
            t["check_no"] = str(checks[t["account"]["id"]])


def _ledger_rows(tables, rng, world):
    stem = "core_transactions-account_transaction"
    for t in world["ledger"]:
        a, channel = t["account"], t["channel"]
        terminal = None
        if channel == "POS" and t["merchant"]:
            terminal = f"POS-{int(t['merchant']['id'][6:]) * 7 + 1000}"
        elif channel == "ATM":
            terminal = f"ATM-{2200 + a['n'] % 60}"
        row = tables.add(stem, transaction_id=t["id"], account_id=a["id"], transaction_type_code=t["code"],
                         transaction_category=t["category"], amount_cents=t["amount"], currency_code="USD",
                         transaction_status=t["status"], posted_date=None if t["status"] == "PENDING" else ds(t["at"].date()),
                         transaction_at=ts(t["at"]), effective_date=ds(t["at"].date()), description=t["description"],
                         memo=None, running_balance_cents=t["balance"] if t["status"] in ("POSTED", "REVERSED") else None,
                         channel=channel, external_reference=t.get("wire_id"), trace_number=t.get("trace"),
                         check_number=t.get("check_no"), branch_id=a["branch"] if channel == "BRANCH" else None,
                         terminal_id=terminal, teller_id=f"TLR-{a['n'] % 20 + 1:02d}" if channel == "BRANCH" else None,
                         counterparty_account_id=None, counterparty_name=t["counterparty"],
                         is_reconciled=t["status"] != "PENDING" and t["at"] < AS_OF - dt.timedelta(days=3),
                         source_system=a["source_system"])
        stamp_bronze(rng, row, t["at"])
        t["row"] = row


def _reversal_rows(tables, rng, world):
    stem = "core_transactions-transaction_reversal"
    number = 6
    for t in world["ledger"]:
        original = t["reversal_of"]
        if not original:
            continue
        kind = t["reversal_type"]
        if kind == "FULL":
            code, reason = ("R015", "Fee refunded as courtesy") if original["code"] in ("TT-FEE", "TT-OD-FEE") else ("R001", "Duplicate charge reversed")
        elif kind == "PARTIAL":
            code, reason = "R010", "Merchant issued partial refund"
        else:
            code, reason = "R020", "Posting error corrected"
        row = tables.add(stem, reversal_id=ident("REV", number), original_transaction_id=original["id"],
                         reversing_transaction_id=t["id"], reversal_type=kind, reversal_amount_cents=t["amount"],
                         reason_code=code, reason_description=reason, reversed_at=ts(t["at"]),
                         posted_date=ds(t["at"].date()),
                         reversed_by="SYSTEM_BATCH" if kind == "FULL" else f"OPS-ANALYST-{rng.randint(1, 9):02d}",
                         approved_by=f"SUP-{rng.randint(10, 30):03d}" if t["amount"] >= 10000 else None,
                         channel="INTERNAL", source_system=t["account"]["source_system"])
        stamp_bronze(rng, row, t["at"])
        number += 1


def _entry_mode(rng, t_merchant, recurring):
    if recurring:
        return "RECURRING"
    if t_merchant and t_merchant["mcc"] in ECOMMERCE_MCC:
        return "ECOMMERCE"
    return weighted(rng, [("CHIP", 40), ("CONTACTLESS", 38), ("SWIPE", 12), ("MANUAL", 4), ("ECOMMERCE", 6)])


def _network(rng, a):
    if "network" not in a:
        a["network"] = weighted(rng, NETWORKS)
    return a["network"]


def _card_rows(tables, rng, world):
    pos = [t for t in world["ledger"] if t["code"] == "TT-POS"]
    auths = [{"at": t["at"] - dt.timedelta(seconds=rng.randint(1, 90)), "txn": t, "account": t["account"],
              "merchant": t["merchant"], "status": "APPROVED", "type": "PURCHASE"} for t in pos]
    checking = [a for a in world["accounts"] if a["type"] == "CHECKING" and a["status"] in ("OPEN", "FROZEN", "CLOSED")]
    merchants = [m for m in world["merchants"] if m["type"] in ("RETAIL", "RESTAURANT", "SERVICE")]
    from ledger import activity_window
    for i in range(int(len(pos) * 0.2)):
        a = rng.choice(checking)
        start, end = activity_window(a)
        if end <= start:
            continue
        status = weighted(rng, [("DECLINED", 45), ("EXPIRED", 20), ("REVERSED", 20), ("PENDING", 15)])
        if status == "PENDING":
            when = rand_dt(rng, AS_OF - dt.timedelta(hours=30), AS_OF - dt.timedelta(minutes=20))
        else:
            when = rand_dt(rng, at(start), min(at(end, 20), AS_OF - dt.timedelta(days=8)))
        auths.append({"at": when, "txn": None, "account": a, "merchant": rng.choice(merchants), "status": status,
                      "type": "PURCHASE" if i < 12 else weighted(rng, [("PURCHASE", 70), ("CASH_ADVANCE", 10), ("REFUND", 10), ("BALANCE_INQUIRY", 10)])})
    auths.sort(key=lambda x: (x["at"], x["account"]["n"]))
    rejected = set(id(t) for t in rng.sample([t for t in pos if t["status"] == "POSTED"], 4))
    settle_n = 6
    for i, auth in enumerate(auths):
        a, m, t = auth["account"], auth["merchant"], auth["txn"]
        auth_id = ident("AUTH", 9 + i)
        network = _network(rng, a)
        card_id = f"DCARD-{a['n']:04d}"
        mode = _entry_mode(rng, m, t and t["recurring"])
        present = mode not in ("ECOMMERCE", "RECURRING", "MANUAL")
        amount = t["amount"] if t else (0 if auth["type"] == "BALANCE_INQUIRY" else max(100, int(rng.lognormvariate(8.3, 0.8))))
        auth_amount = amount
        if t and m and m["mcc"] in ("5812", "5814") and not t["recurring"] and rng.random() < 0.35:
            auth_amount = max(100, int(amount / rng.uniform(1.15, 1.22)))
        status = auth["status"]
        declined = status == "DECLINED"
        expires = None if status in ("DECLINED", "REVERSED") else auth["at"] + dt.timedelta(days=7)
        row = tables.add("card_transactions-card_authorization", authorization_id=auth_id, card_id=card_id,
                         account_id=a["id"], authorization_amount_cents=auth_amount, currency_code="USD",
                         merchant_amount_cents=None, merchant_currency_code=None, exchange_rate=None,
                         authorization_status=status,
                         decline_reason_code=weighted(rng, [("INSUFFICIENT_FUNDS", 50), ("SUSPECTED_FRAUD", 20), ("LIMIT_EXCEEDED", 15),
                                                            ("INVALID_PIN", 10), ("EXPIRED_CARD", 5)]) if declined else None,
                         authorized_at=ts(auth["at"]), expires_at=ts(expires) if expires else None, merchant_name=m["name"],
                         merchant_id=m["card_id"], mcc_code=m["mcc"], merchant_city=m["city"], merchant_state=m["state"],
                         merchant_country="US", transaction_type=auth["type"], entry_mode=mode,
                         pin_used=(mode in ("CHIP", "SWIPE") and rng.random() < 0.4) if present else None,
                         card_present=present, network=network, network_reference_id=f"NRI-{100000 + i}",
                         rrn=f"RRN-{100000 + i}", authorization_code=None if declined else f"A{(i * 7919) % 100000:05d}",
                         cvv_result="M" if not present else None, avs_result=rng.choice(["Y", "N"]) if not present else None,
                         three_ds_result="Y" if mode == "ECOMMERCE" else None, source_system="CARD_PLATFORM")
        stamp_bronze(rng, row, auth["at"])
        if not t:
            continue
        t["auth_id"], t["network"], t["card_id"] = auth_id, network, card_id
        pending = t["status"] == "PENDING"
        settled_at = min(t["at"] + dt.timedelta(hours=rng.randint(4, 30)), AS_OF - dt.timedelta(minutes=1))
        status = "PENDING" if pending else ("REJECTED" if id(t) in rejected else "SETTLED")
        row = tables.add("card_transactions-card_settlement", settlement_id=ident("SETL", settle_n),
                         authorization_id=auth_id, transaction_id=t["id"], card_id=card_id, account_id=a["id"],
                         settlement_amount_cents=amount, currency_code="USD", authorization_amount_cents=auth_amount,
                         variance_cents=amount - auth_amount, settlement_status=status, settled_at=ts(settled_at),
                         network_settlement_date=None if status != "SETTLED" else ds(min(settled_at.date() + dt.timedelta(days=1), AS_OF_DATE)),
                         merchant_name=m["name"], merchant_id=m["card_id"], mcc_code=m["mcc"], network=network,
                         network_reference_id=f"NRI-{100000 + i}",
                         interchange_fee_cents=int(amount * 0.015) if status == "SETTLED" else None,
                         assessment_fee_cents=int(amount * 0.0014) if status == "SETTLED" else None,
                         source_system="CARD_PLATFORM")
        stamp_bronze(rng, row, settled_at)
        t["settlement_id"], t["settled_at"], t["settlement_status"] = ident("SETL", settle_n), settled_at, status
        settle_n += 1


def _chargeback_rows(tables, rng, world):
    stem = "card_transactions-card_chargeback"
    candidates = [t for t in world["ledger"] if t.get("settlement_status") == "SETTLED" and t["amount"] >= 1500
                  and t["at"] <= AS_OF - dt.timedelta(days=10)]
    chosen = sorted(rng.sample(candidates, 40), key=lambda t: t["at"])
    reasons = {"FRAUD": [("10.4", "Card-absent fraud"), ("4837", "No cardholder authorization")],
               "CONSUMER_DISPUTE": [("13.1", "Merchandise not received"), ("13.3", "Not as described")],
               "PROCESSING_ERROR": [("12.6", "Duplicate processing")],
               "AUTHORIZATION": [("11.3", "No authorization obtained"), ("AUTH-01", "Authorization not obtained")]}
    for i, t in enumerate(chosen):
        a = t["account"]
        initiated = min(t["settled_at"] + dt.timedelta(days=rng.randint(3, 60), hours=rng.randint(0, 20)), AS_OF - dt.timedelta(days=1))
        status = weighted(rng, [("INITIATED", 6), ("PENDING", 8), ("WON", 12), ("LOST", 8), ("EXPIRED", 6)])
        if status in ("WON", "LOST", "EXPIRED") and initiated > AS_OF - dt.timedelta(days=11):
            status = "PENDING"
        resolved = min(initiated + dt.timedelta(days=rng.randint(10, 45)), AS_OF - dt.timedelta(hours=1)) if status in ("WON", "LOST", "EXPIRED") else None
        outcome = {"WON": weighted(rng, [("CUSTOMER_WIN", 80), ("SPLIT", 20)]), "LOST": "MERCHANT_WIN", "EXPIRED": "MERCHANT_WIN"}.get(status)
        category = weighted(rng, [("FRAUD", 35), ("CONSUMER_DISPUTE", 40), ("PROCESSING_ERROR", 15), ("AUTHORIZATION", 10)])
        code, description = rng.choice(reasons[category])
        amount = t["amount"] if rng.random() < 0.8 else max(500, t["amount"] // 2)
        provisional = category in ("FRAUD", "CONSUMER_DISPUTE")
        row = tables.add(stem, chargeback_id=ident("CB", 6 + i), transaction_id=t["id"], settlement_id=t["settlement_id"],
                         card_id=t["card_id"], account_id=a["id"], customer_id=a["customer"]["id"],
                         chargeback_amount_cents=amount, currency_code="USD", chargeback_status=status, reason_code=code,
                         reason_description=description, chargeback_category=category, initiated_at=ts(initiated),
                         response_due_date=ds(initiated.date() + dt.timedelta(days=30)),
                         resolved_at=ts(resolved) if resolved else None, resolution_outcome=outcome,
                         recovery_amount_cents={"CUSTOMER_WIN": amount, "SPLIT": amount // 2, "MERCHANT_WIN": 0}.get(outcome),
                         merchant_name=t["merchant"]["name"], merchant_id=t["merchant"]["card_id"], network=t["network"],
                         network_case_number=f"CASE-{t['network'][:4]}-{6 + i:05d}", provisional_credit_issued=provisional,
                         provisional_credit_date=ds(min(initiated.date() + dt.timedelta(days=rng.randint(1, 5)), AS_OF_DATE)) if provisional else None,
                         source_system="CARD_PLATFORM")
        stamp_bronze(rng, row, resolved or initiated)
        t["disputed"] = True


def _company(name):
    initials = "".join(w[0] for w in name.replace("-", " ").split() if w[0].isalnum()).upper()[:4]
    return f"COMP-{initials}{sum(map(ord, name)) % 100:02d}"


def _ach_rows(tables, rng, world):
    stem = "wire_ach_transactions-ach_transaction"
    for t in world["ledger"]:
        if "ach_id" not in t:
            continue
        a, c, plan = t["account"], t["account"]["customer"], t["recurring"]
        if t["code"] == "TT-ACH-CR":
            direction, ach_type = "INBOUND", "CREDIT"
        elif plan or rng.random() < 0.7:
            direction, ach_type = "INBOUND", "DEBIT"
        else:
            direction, ach_type = "OUTBOUND", "CREDIT"
        business = c["type"] == "BUSINESS"
        if business:
            sec = "CCD"
        elif t["code"] == "TT-ACH-CR":
            sec = "PPD"
        else:
            sec = weighted(rng, [("PPD", 55), ("WEB", 35), ("TEL", 10)])
        if t["status"] == "POSTED":
            status = "POSTED"
        elif t["status"] == "PENDING":
            status = "ORIGINATED" if rng.random() < 0.4 else "PENDING"
        else:
            status = "REJECTED" if rng.random() < 0.2 else "RETURNED"
        t["ach_status"] = status
        other_bank = BANKS[sum(map(ord, t["counterparty"] or "x")) % len(BANKS)]
        odfi, rdfi = (other_bank, OUR_BANK) if direction == "INBOUND" else (OUR_BANK, other_bank)
        company = t["counterparty"] or c["full_name"]
        if t["code"] == "TT-ACH-CR":
            entry = "INVOICE PMT" if business else "PAYROLL"
        elif plan:
            entry = {"BILL": "UTILBILL", "INSURANCE": "INSURPREM", "LOAN_PAYMENT": "LOANPMT"}.get(plan["kind"], "SUBSCRIPT")
        else:
            entry = "VENDOR PMT" if business else "ACH PMT"
        day = t["at"].date()
        row = tables.add(stem, ach_transaction_id=t["ach_id"], transaction_id=t["id"], account_id=a["id"],
                         direction=direction, ach_type=ach_type, sec_code=sec, amount_cents=t["amount"], currency_code="USD",
                         transaction_status=status, odfi_routing_number=odfi[1], odfi_name=odfi[0],
                         rdfi_routing_number=rdfi[1], rdfi_name=rdfi[0], company_id=_company(company),
                         company_name=company[:40], entry_description=entry, individual_name=c["full_name"][:40],
                         individual_id=f"IND-{c['n']:04d}", trace_number=t["trace"], addenda=None, effective_date=ds(day),
                         settlement_date=ds(day) if status in ("POSTED", "RETURNED") else None, processed_at=ts(t["at"]),
                         is_same_day=rng.random() < 0.1, batch_number=f"BATCH-{day:%Y%m%d}", file_id=f"FILE-{day:%Y%m%d}",
                         source_system=a["source_system"])
        stamp_bronze(rng, row, t["at"])


def _wire_rows(tables, rng, world):
    stem = "wire_ach_transactions-wire_transfer"
    wires = [t for t in world["ledger"] if "wire_id" in t]
    returned = [t for t in wires if t["status"] == "RETURNED"]
    forced = {id(t): s for t, s in zip(returned, ["CANCELLED"] * 3 + ["RETURNED"] * 3)}
    pending_out = 0
    for t in wires:
        a, c = t["account"], t["account"]["customer"]
        outbound = t["code"] == "TT-WIRE-OUT"
        intl = rng.random() < 0.2
        if t["status"] == "POSTED":
            status = weighted(rng, [("COMPLETED", 80), ("SENT", 20)]) if outbound else weighted(rng, [("RECEIVED", 60), ("COMPLETED", 40)])
        elif t["status"] == "PENDING":
            status = ("INITIATED" if pending_out % 2 == 0 else "PENDING") if outbound else "PENDING"
            pending_out += outbound
        else:
            status = forced.get(id(t)) or weighted(rng, [("RETURNED", 65), ("CANCELLED", 35)])
        if status == "CANCELLED":
            ofac = "BLOCKED" if forced.get(id(t)) == "CANCELLED" or rng.random() < 0.5 else "HOLD"
        elif status == "RETURNED":
            ofac = "HOLD" if forced.get(id(t)) == "RETURNED" or rng.random() < 0.3 else "CLEAR"
        elif status in ("INITIATED", "PENDING") and intl:
            ofac = "HOLD"
        else:
            ofac = "CLEAR"
        approval = "PENDING" if status in ("INITIATED", "PENDING") else ("REJECTED" if status == "CANCELLED" else "APPROVED")
        initiated = t["at"] - dt.timedelta(minutes=rng.randint(0, 90))
        sent = None
        if status in ("SENT", "COMPLETED", "RECEIVED", "RETURNED"):
            sent = min(initiated + dt.timedelta(minutes=rng.randint(5, 60)), AS_OF - dt.timedelta(minutes=1))
        completed = min(sent + dt.timedelta(minutes=rng.randint(5, 90)), AS_OF - dt.timedelta(minutes=1)) if status == "COMPLETED" else None
        approved_at = min(initiated + dt.timedelta(minutes=rng.randint(1, 4)), sent or AS_OF) if approval == "APPROVED" and outbound else None
        fee = (4500 if intl else 2500) if outbound else 0
        bank_country, bank_name, bank_id, bank_city = rng.choice(INTL_BANKS) if intl else ("US",) + BANKS[a["n"] % len(BANKS)] + ("Denver",)
        party = t["counterparty"] or "Overseas Trading Co"
        customer_side = (c["full_name"], f"{c['street']}, {c['city'][0]} {c['city'][1]}", a["number"], OUR_BANK[0], OUR_BANK[1])
        other_account = f"{bank_country}{rng.randint(10**15, 10**16 - 1)}" if intl else str(rng.randint(100000000, 999999999))
        other_side = (party, f"{rng.randint(1, 999)} Commerce St, {bank_city}", other_account, bank_name, bank_id)
        orig, bene = (customer_side, other_side) if outbound else (other_side, customer_side)
        row = tables.add(stem, wire_transfer_id=t["wire_id"], transaction_id=t["id"], account_id=a["id"],
                         customer_id=c["id"], direction="OUTBOUND" if outbound else "INBOUND",
                         wire_type="INTERNATIONAL" if intl else "DOMESTIC", amount_cents=t["amount"], currency_code="USD",
                         fee_cents=fee, total_amount_cents=t["amount"] + fee, wire_status=status,
                         originator_name=orig[0], originator_address=orig[1], originator_account=orig[2],
                         originator_bank_name=orig[3], originator_bank_id=orig[4], beneficiary_name=bene[0],
                         beneficiary_address=bene[1], beneficiary_account=bene[2], beneficiary_bank_name=bene[3],
                         beneficiary_bank_id=bene[4], beneficiary_country="US" if not outbound else bank_country,
                         intermediary_bank_name="Intermediary Bank Ltd" if intl and rng.random() < 0.5 else None,
                         intermediary_bank_id=None, purpose=rng.choice(["Vendor payment", "Real estate closing", "Family support",
                                                                        "Import goods payment", "Investment transfer"]),
                         reference_for_beneficiary=f"REF-{t['id'][4:]}", fed_reference=None if intl or not sent else f"FED-{t['id'][4:]}",
                         swift_reference=f"SWIFT-{t['id'][4:]}" if intl and sent else None, ofac_status=ofac,
                         initiated_at=ts(initiated), sent_at=ts(sent) if sent else None,
                         completed_at=ts(completed) if completed else None,
                         initiated_by=c["id"] if outbound else "SYSTEM_BATCH", approval_status=approval,
                         approved_by=f"OPS-{rng.randint(1, 6):02d}" if approved_at else None,
                         approved_at=ts(approved_at) if approved_at else None, source_system=a["source_system"])
        if intl:
            row["intermediary_bank_id"] = "INTLGB2X" if row["intermediary_bank_name"] else None
        stamp_bronze(rng, row, completed or sent or initiated)
        t["wire_status"], t["wire_country"] = status, bank_country


def _return_rows(tables, rng, world):
    stem = "wire_ach_transactions-payment_return"
    items = []
    for t in world["ledger"]:
        if t.get("ach_status") in ("RETURNED", "REJECTED"):
            items.append(("ACH_RETURN", t))
        elif t.get("wire_status") == "RETURNED":
            items.append(("WIRE_RETURN", t))
        elif t.get("wire_status") == "CANCELLED":
            items.append(("WIRE_REJECT", t))
    notices = [t for t in world["ledger"] if t.get("ach_status") == "POSTED" and t["at"] < AS_OF - dt.timedelta(days=5)]
    items += [("ACH_NOC", t) for t in rng.sample(notices, 8)]
    items.sort(key=lambda it: it[1]["at"])
    reasons = {"ACH_RETURN": [("R01", "Insufficient funds"), ("R02", "Account closed"), ("R03", "No account/unable to locate account"),
                              ("R08", "Payment stopped"), ("R10", "Customer advises not authorized")],
               "ACH_NOC": [("C01", "Incorrect DFI account number, corrected"), ("C02", "Incorrect routing number, corrected")],
               "WIRE_RETURN": [("BENE-ACCT-CLOSED", "Beneficiary account closed"), ("INVALID-ACCT", "Beneficiary account invalid")],
               "WIRE_REJECT": [("OFAC-HOLD", "Wire rejected pending OFAC review")]}
    for i, (kind, t) in enumerate(items):
        code, description = reasons[kind][0] if kind == "ACH_RETURN" and t["balance"] is None and rng.random() < 0.6 else rng.choice(reasons[kind])
        processed = min(t["at"] + dt.timedelta(days=rng.randint(1, 3), hours=rng.randint(0, 8)), AS_OF - dt.timedelta(minutes=5))
        status = "PENDING" if processed > AS_OF - dt.timedelta(days=1) else weighted(rng, [("PROCESSED", 90), ("DISPUTED", 10)])
        is_ach = kind.startswith("ACH")
        row = tables.add(stem, return_id=ident("RET", 6 + i), ach_transaction_id=t.get("ach_id") if is_ach else None,
                         wire_transfer_id=None if is_ach else t["wire_id"], original_transaction_id=t["id"],
                         return_transaction_id=None, account_id=t["account"]["id"], return_type=kind,
                         return_amount_cents=0 if kind == "ACH_NOC" else t["amount"], currency_code="USD",
                         return_status=status, return_reason_code=code, return_reason_description=description,
                         original_effective_date=ds(t["at"].date()), return_effective_date=ds(processed.date()),
                         processed_at=ts(processed), original_trace_number=t.get("trace"),
                         return_trace_number=(t["trace"] + ("C" if kind == "ACH_NOC" else "R")) if is_ach else None,
                         addenda=None, is_dishonored=is_ach and rng.random() < 0.05, source_system="CORE_BANKING")
        stamp_bronze(rng, row, processed)


def _recurring_rows(tables, rng, world):
    stem = "enriched_transactions-recurring_payment"
    for plan in world["recurring"]:
        a, m = plan["account"], plan["merchant"]
        per_year = {"WEEKLY": 52, "BIWEEKLY": 26, "MONTHLY": 12, "QUARTERLY": 4, "ANNUAL": 1}[plan["frequency"]]
        next_expected = None
        if plan["status"] != "ENDED":
            from ledger import _step
            next_expected = _step(plan["last"], plan["frequency"])
        row = tables.add(stem, recurring_payment_id=plan["id"], account_id=a["id"], customer_id=a["customer"]["id"],
                         merchant_id=m["id"], merchant_name=m["name"], payment_type=plan["kind"],
                         typical_amount_cents=plan["amount"], amount_variance_cents=rng.choice([0, 0, 100, 200, 500]),
                         frequency=plan["frequency"],
                         typical_day=plan["last"].day if plan["frequency"] in ("MONTHLY", "QUARTERLY", "ANNUAL") else None,
                         day_variance=rng.randint(1, 5), first_occurrence_date=ds(plan["first"]),
                         last_occurrence_date=ds(plan["last"]), next_expected_date=ds(next_expected),
                         occurrence_count=plan["count"], missed_count=plan["missed"], status=plan["status"],
                         confidence_score=plan["confidence"], category_name=RECURRING_CATEGORY[plan["kind"]],
                         is_essential=plan["kind"] in ("BILL", "INSURANCE", "LOAN_PAYMENT"),
                         annual_cost_cents=plan["amount"] * per_year, detection_method=plan["detection"])
        stamp_current(rng, row)


def _unified_rows(tables, rng, world):
    stem = "enriched_transactions-unified_transaction"
    names = world["categories"]
    for t in world["ledger"]:
        a, c, m, plan = t["account"], t["account"]["customer"], t["merchant"], t["recurring"]
        code = t["code"]
        if code == "TT-POS":
            source, source_id = "CARD", t["auth_id"]
        elif "ach_id" in t:
            source, source_id = "ACH", t["ach_id"]
        elif "wire_id" in t:
            source, source_id = "WIRE", t["wire_id"]
        else:
            source, source_id = "CORE", t["id"]
        if m:
            category_id = m["category_id"]
        elif t["reversal_of"] or code in ("TT-CHK", "TT-WIRE-OUT", "TT-WIRE-IN"):
            category_id = None
        elif code == "TT-ACH-CR" and c["type"] == "BUSINESS":
            category_id = "CAT-022"
        else:
            category_id = CODE_CATEGORY.get(code)
        if plan and plan["kind"] == "LOAN_PAYMENT":
            category_id = "CAT-018"
        fraud = rng.randint(0, 12)
        if m and m["mcc"] in ("7995", "6051"):
            fraud = rng.randint(45, 97)
        elif m and m["mcc"] in ECOMMERCE_MCC:
            fraud += 5
        located = code == "TT-POS" and m
        branch = t["channel"] in ("BRANCH", "ATM")
        city = m["city"] if located else (c["city"][0] if branch else None)
        state = m["state"] if located else (c["city"][1] if branch else None)
        clean = m["name"] if m else (t["counterparty"] or t["description"])
        row = tables.add(stem, transaction_id=t["id"], account_id=a["id"], customer_id=c["id"], transaction_source=source,
                         source_transaction_id=source_id,
                         transaction_type="SUBSCRIPTION_CHARGE" if plan and plan["kind"] in ("SUBSCRIPTION", "MEMBERSHIP") else (
                             "REVERSAL" if t["reversal_of"] else UNIFIED_TYPE[code]),
                         debit_credit=t["category"], amount_cents=t["amount"], currency_code="USD",
                         transaction_status=t["status"], transaction_at=ts(t["at"]),
                         posted_date=None if t["status"] == "PENDING" else ds(t["at"].date()),
                         original_description=(f"{m['name'].upper()} #{int(m['id'][6:]) * 13 % 9000 + 1000}" if m
                                               else t["description"].upper())[:60],
                         clean_description=clean, channel="ONLINE" if t["channel"] == "INTERNAL" else t["channel"],
                         merchant_id=m["id"] if m else None, merchant_name=m["name"] if m else None,
                         mcc_code=m["mcc"] if located else None, category_id=category_id,
                         category_name=names[category_id] if category_id else None,
                         subcategory_name=world["mcc"].get(m["mcc"]) if located else None,
                         is_recurring=plan is not None, recurring_payment_id=plan["id"] if plan else None,
                         location=f"{city}, {state}" if city else None, city=city, state=state,
                         country=t.get("wire_country", "US") if source == "WIRE" and t["code"] == "TT-WIRE-OUT" else "US",
                         running_balance_cents=t["balance"] if t["status"] in ("POSTED", "REVERSED") else None,
                         is_disputed=t.get("disputed", False), is_suspicious=fraud >= 80, fraud_score=fraud)
        stamp_silver(rng, row, parse_ts(t["row"]["ingested_at"]))
