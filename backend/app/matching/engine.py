import csv
import io
from datetime import date, datetime
from itertools import combinations
from app.matching.text_utils import extract_invoice_numbers, name_score, name_tokens, squash

REQUIRED = {"txn_date", "narration", "credit", "debit", "currency"}
TOLERANCE = 0.01
NAME_OK = 0.6
NON_CUSTOMER = ("INT.PD", "INTEREST", "CHARGES")
AMOUNT_POINTS = {"exact": 35, "tds": 33, "partial": 12, "over": 0}


def parse_date(value):
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(value.strip(), fmt).date()
        except ValueError:
            pass
    raise ValueError(f"invalid date '{value}'")


def to_amount(value):
    value = (value or "").replace(",", "").strip()
    if not value:
        return 0.0
    try:
        amount = round(float(value), 2)
    except ValueError:
        raise ValueError(f"invalid amount '{value}'") from None
    if amount < 0:
        raise ValueError(f"negative amount '{value}'")
    return amount


def parse_statement(text):
    reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff")))
    reader.fieldnames = [f.strip().lower() for f in (reader.fieldnames or [])]
    missing = REQUIRED - set(reader.fieldnames)
    if missing:
        raise ValueError(f"Missing columns: {', '.join(sorted(missing))}")
    rows = []
    for number, raw in enumerate(reader, start=2):
        try:
            rows.append({
                "txn_date": parse_date(raw["txn_date"] or ""),
                "narration": (raw["narration"] or "").strip(),
                "reference": (raw.get("reference") or "").strip(),
                "credit": to_amount(raw["credit"]),
                "debit": to_amount(raw["debit"]),
                "currency": (raw["currency"] or "").strip().upper(),
            })
        except ValueError as error:
            raise ValueError(f"Row {number}: {error}") from None
    return rows


def build_context(customers, invoices):
    return {
        "customers": {c["customer_id"]: {**c, "tokens": name_tokens(c["name"])} for c in customers},
        "invoices": invoices,
        "by_number": {i["invoice_number"]: i for i in invoices},
        "remaining": {i["invoice_number"]: i["balance_due"] for i in invoices},
    }


def level(confidence):
    return "high" if confidence >= 80 else "medium" if confidence >= 55 else "low"


def money(value):
    return f"{value:,.2f}"


def base(row):
    credit = row["credit"] > 0
    return {
        "txn_date": row["txn_date"].isoformat(),
        "narration": row["narration"],
        "reference": row["reference"],
        "amount": row["credit"] if credit else row["debit"],
        "currency": row["currency"],
        "direction": "credit" if credit else "debit",
    }


def no_match(row, reason, status="no_match"):
    return {
        **base(row), "status": status, "customer_id": None, "customer_name": None,
        "invoices": [], "suggested_action": None, "confidence": 0, "level": "none",
        "reason": reason, "alternatives": [],
    }


def suggestion(row, customer, allocations, action, confidence, reason, alternatives=()):
    confidence = max(0, min(99, round(confidence)))
    return {
        **base(row), "status": "suggested", "customer_id": customer["customer_id"],
        "customer_name": customer["name"], "invoices": allocations, "suggested_action": action,
        "confidence": confidence, "level": level(confidence), "reason": reason,
        "alternatives": list(alternatives),
    }


def amount_kind(paid, invoice):
    balance = invoice["balance_due"]
    if abs(paid - balance) <= TOLERANCE:
        return "exact", 0.0
    if invoice["currency"] == "INR" and invoice["amount_paid"] == 0:
        for base_amount in (invoice["subtotal"], invoice["subtotal"] - invoice["discount"]):
            if abs(paid - (balance - round(base_amount * 0.10, 2))) <= TOLERANCE:
                return "tds", round(balance - paid, 2)
    return ("partial" if paid < balance else "over"), 0.0


def open_invoices(ctx, row):
    pool = []
    for invoice in ctx["invoices"]:
        left = ctx["remaining"][invoice["invoice_number"]]
        if (
            invoice["status"] == "sent"
            and left > TOLERANCE
            and invoice["currency"] == row["currency"]
            and date.fromisoformat(invoice["invoice_date"]) <= row["txn_date"]
        ):
            pool.append({**invoice, "balance_due": left})
    return pool


def referenced(ctx, narration):
    numbers = [n for n in extract_invoice_numbers(narration) if n in ctx["by_number"]]
    squashed = squash(narration)
    for invoice in ctx["invoices"]:
        po = squash(invoice["po_number"] or "")
        if po and po in squashed and invoice["invoice_number"] not in numbers:
            numbers.append(invoice["invoice_number"])
    return numbers


def score_invoice(row, invoice, name_s, ref_hit):
    kind, tds = amount_kind(row["credit"], invoice)
    days = (row["txn_date"] - date.fromisoformat(invoice["invoice_date"])).days
    points = (
        (40 if ref_hit else 0)
        + (35 * name_s if name_s >= NAME_OK else 12 * name_s)
        + AMOUNT_POINTS[kind]
        + (5 if days <= 90 else 2)
    )
    return {"invoice": invoice, "kind": kind, "tds": tds, "score": points}


def find_combos(paid, pool):
    pool = sorted(pool, key=lambda i: i["due_date"])[:12]
    hits = []
    for size in range(2, min(4, len(pool)) + 1):
        for group in combinations(pool, size):
            if abs(sum(i["balance_due"] for i in group) - paid) <= TOLERANCE:
                hits.append(group)
    return hits


def match_combo(row, ctx, group, scores, ref_hit):
    customer = ctx["customers"][group[0]["customer_id"]]
    name_s = scores[customer["customer_id"]]
    points = (40 if ref_hit else 0) + (35 * name_s if name_s >= NAME_OK else 12 * name_s) + 35 + 5 + 15
    cap = 95 if ref_hit else 85
    if name_s < 0.4:
        cap = 60
    allocations = [
        {"invoice_number": i["invoice_number"], "balance_due": i["balance_due"], "apply": i["balance_due"], "tds": 0.0}
        for i in group
    ]
    reason = f"{'Invoice numbers found, ' if ref_hit else ''}payer matches {customer['name']}, {len(group)} open invoices add up to this amount exactly"
    return suggestion(row, customer, allocations, "split", min(points, cap), reason[0].upper() + reason[1:])


def match_unrecognised(row, pool, scores, ctx):
    if any(word in row["narration"].upper() for word in NON_CUSTOMER):
        return no_match(row, "Looks like a bank credit such as interest, not a customer payment")
    same = [i for i in pool if abs(i["balance_due"] - row["credit"]) <= TOLERANCE]
    if not same:
        return no_match(row, "Payer not recognised and no open invoice has this amount")
    if len(same) > 1:
        return no_match(row, f"Payer not recognised and {len(same)} invoices share this amount")
    invoice = same[0]
    customer = ctx["customers"][invoice["customer_id"]]
    resembles = scores[customer["customer_id"]] >= 0.4
    reason = f"Payer not recognised, only {invoice['invoice_number']} has this exact amount"
    if resembles:
        reason += f", narration partly resembles {customer['name']}"
    allocations = [{"invoice_number": invoice["invoice_number"], "balance_due": invoice["balance_due"], "apply": row["credit"], "tds": 0.0}]
    return suggestion(row, customer, allocations, "full", 50 if resembles else 40, reason)


def match_credit(row, ctx):
    narration, paid = row["narration"], row["credit"]
    tokens = name_tokens(narration)
    scores = {cid: name_score(tokens, c["tokens"]) for cid, c in ctx["customers"].items()}
    best_id = max(scores, key=scores.get)
    pool = open_invoices(ctx, row)
    named = referenced(ctx, narration)
    ref_hit = bool(named)

    if ref_hit:
        candidates = [i for i in pool if i["invoice_number"] in named]
        if not candidates:
            return no_match(row, f"{', '.join(named)} not open for this payment (already paid, draft, other currency or dated after payment)")
    elif scores[best_id] >= NAME_OK:
        candidates = [i for i in pool if i["customer_id"] == best_id]
        if not candidates:
            name = ctx["customers"][best_id]["name"]
            return no_match(row, f"{name} has no open {row['currency']} invoice dated on or before this payment")
    else:
        return match_unrecognised(row, pool, scores, ctx)

    ranked = sorted(
        (score_invoice(row, i, scores[i["customer_id"]], ref_hit) for i in candidates),
        key=lambda r: (-r["score"], r["invoice"]["due_date"]),
    )

    if not any(r["kind"] in ("exact", "tds") for r in ranked) and len(candidates) >= 2:
        hits = find_combos(paid, candidates)
        if len(hits) == 1:
            return match_combo(row, ctx, hits[0], scores, ref_hit)
        if len(hits) > 1:
            return no_match(row, "Several invoice combinations add up to this amount")

    top = ranked[0]
    runner = ranked[1] if len(ranked) > 1 else None
    margin = top["score"] - runner["score"] if runner else 100
    score = top["score"] + (15 if margin >= 20 else -15 if margin < 10 else 0)

    invoice, kind, tds = top["invoice"], top["kind"], top["tds"]
    customer = ctx["customers"][invoice["customer_id"]]
    name_s = scores[customer["customer_id"]]

    parts = []
    if ref_hit:
        parts.append("Invoice/PO number found")
    parts.append(f"payer matches {customer['name']}" if name_s >= NAME_OK else f"payer does not match {customer['name']}")
    parts.append({
        "exact": "exact amount",
        "tds": f"amount equals balance less TDS of {money(tds)}",
        "partial": f"part payment, {money(invoice['balance_due'] - paid)} would remain",
        "over": "amount exceeds the invoice balance",
    }[kind])
    if runner and margin < 10:
        parts.append(f"also fits {runner['invoice']['invoice_number']}")
    reason = ", ".join(parts)
    reason = reason[0].upper() + reason[1:]

    if kind == "over":
        score = min(score, 50)
    if ref_hit and name_s < 0.4:
        score = min(score, 60)

    action = {"exact": "full", "tds": "close_tds", "partial": "leave_open", "over": "review"}[kind]
    allocations = [{
        "invoice_number": invoice["invoice_number"], "balance_due": invoice["balance_due"],
        "apply": min(paid, invoice["balance_due"]), "tds": tds,
    }]
    alternatives = [
        {"invoice_number": r["invoice"]["invoice_number"], "confidence": min(99, round(r["score"]))}
        for r in ranked[1:3]
    ]
    return suggestion(row, customer, allocations, action, score, reason, alternatives)


def reserve(ctx, result):
    if result["status"] != "suggested" or result["level"] == "low" or result["suggested_action"] == "review":
        return
    for item in result["invoices"]:
        ctx["remaining"][item["invoice_number"]] -= item["apply"] + item["tds"]


def match_rows(rows, customers, invoices, skip=None):
    ctx = build_context(customers, invoices)
    results = []
    for row in rows:
        duplicate = skip(row) if skip else None
        if duplicate:
            result = no_match(row, duplicate, "duplicate")
        elif row["credit"] > 0:
            result = match_credit(row, ctx)
        elif row["debit"] > 0:
            result = no_match(row, "Money out (debit), not a customer payment", "ignored")
        else:
            result = no_match(row, "Row has no amount", "ignored")
        reserve(ctx, result)
        results.append(result)
    return results


def match_statement(text, customers, invoices):
    return match_rows(parse_statement(text), customers, invoices)