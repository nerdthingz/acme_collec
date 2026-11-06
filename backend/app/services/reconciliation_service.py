
import hashlib
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from app.core.errors import AppError
from app.matching.engine import match_rows, parse_statement
from app.matching.text_utils import squash
from app.repositories import customer_repo, invoice_repo
from app.repositories import reconciliation_repo as repo

TOLERANCE = 0.01
TDS_RATE = 0.10
MAX_ROWS = 2000
OPEN_STATES = ["pending", "unmatched"]
REVIEW_STATUS = {"suggested": "pending", "no_match": "unmatched", "ignored": "ignored", "duplicate": "duplicate"}


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def fingerprint(row):
    amount = row["credit"] or row["debit"]
    reference = row["reference"] or squash(row["narration"])
    key = f"{row['txn_date'].isoformat()}|{amount:.2f}|{row['currency']}|{reference}"
    return hashlib.sha1(key.encode()).hexdigest()


def summarize(transactions):
    counts = defaultdict(int)
    for t in transactions:
        counts[t["review_status"]] += 1
    return dict(counts)


def upload_statement(filename, text):
    try:
        rows = parse_statement(text)
    except ValueError as error:
        raise AppError(str(error)) from None
    if not rows:
        raise AppError("The statement has no rows")
    if len(rows) > MAX_ROWS:
        raise AppError(f"The statement has more than {MAX_ROWS} rows")

    repo.ensure_indexes()
    prints = [fingerprint(r) for r in rows]
    done = repo.approved_fingerprints(prints)
    results = match_rows(
        rows, customer_repo.list_all(), invoice_repo.find({}),
        skip=lambda r: "Already approved from an earlier upload" if fingerprint(r) in done else None,
    )

    batch_id = uuid.uuid4().hex[:10]
    uploaded_at = now()
    docs = []
    for number, (result, print_) in enumerate(zip(results, prints), start=1):
        doc = {k: v for k, v in result.items() if k != "status"}
        doc.update({
            "txn_id": f"{batch_id}-{number}", "batch_id": batch_id, "filename": filename, "row": number,
            "fingerprint": print_, "uploaded_at": uploaded_at,
            "match_status": result["status"], "review_status": REVIEW_STATUS[result["status"]],
        })
        docs.append(doc)
    repo.insert_transactions(docs)
    return get_batch(batch_id)


def get_batch(batch_id):
    transactions = repo.transactions_in_batch(batch_id)
    if not transactions:
        raise AppError("Batch not found", 404)
    first = transactions[0]
    return {
        "batch_id": batch_id, "filename": first["filename"], "uploaded_at": first["uploaded_at"],
        "summary": summarize(transactions), "transactions": transactions,
    }


def list_batches():
    batches = {}
    for item in repo.status_counts():
        key = item["_id"]["batch_id"]
        batch = batches.setdefault(key, {
            "batch_id": key, "filename": item["filename"], "uploaded_at": item["uploaded_at"], "summary": {},
        })
        batch["summary"][item["_id"]["status"]] = item["count"]
    return sorted(batches.values(), key=lambda b: b["uploaded_at"], reverse=True)


def list_payments():
    return repo.list_payments()


def build_plan(txn, invoice_numbers, action):
    numbers = list(dict.fromkeys(invoice_numbers or [i["invoice_number"] for i in txn["invoices"]]))
    if not numbers:
        raise AppError("Choose an invoice for this payment")
    invoices = []
    for number in numbers:
        invoice = repo.get_invoice(number)
        if not invoice:
            raise AppError(f"{number} does not exist", 404)
        if invoice["status"] != "sent" or invoice["balance_due"] <= TOLERANCE:
            raise AppError(f"{number} is not open for payment")
        if invoice["currency"] != txn["currency"]:
            raise AppError(f"{number} is in {invoice['currency']} but the payment is in {txn['currency']}")
        invoices.append(invoice)
    if len({i["customer_id"] for i in invoices}) > 1:
        raise AppError("The selected invoices belong to different customers")

    paid = txn["amount"]
    if len(invoices) > 1:
        due = round(sum(i["balance_due"] for i in invoices), 2)
        if abs(due - paid) > TOLERANCE:
            raise AppError(f"The selected invoices add up to {due:,.2f}, not {paid:,.2f}")
        return [(i, i["balance_due"], 0.0) for i in invoices], "split"

    invoice = invoices[0]
    balance = invoice["balance_due"]
    if abs(paid - balance) <= TOLERANCE:
        return [(invoice, balance, 0.0)], "full"
    if paid > balance:
        raise AppError("The payment is more than this invoice's balance; select every invoice it pays")

    chosen = action or (txn["suggested_action"] if txn["suggested_action"] in ("close_tds", "leave_open") else None)
    if chosen == "leave_open":
        return [(invoice, paid, 0.0)], "leave_open"
    if chosen == "close_tds":
        if invoice["currency"] != "INR":
            raise AppError("TDS applies only to INR invoices")
        shortfall = round(balance - paid, 2)
        limit = round(invoice["subtotal"] * TDS_RATE, 2)
        if shortfall > limit + TOLERANCE:
            raise AppError(f"The shortfall {shortfall:,.2f} is more than 10% of the subtotal ({limit:,.2f}), so it cannot be closed as TDS")
        return [(invoice, paid, shortfall)], "close_tds"
    raise AppError("The payment is less than the invoice: choose close_tds or leave_open")


def apply_plan(plan):
    applied = []
    for invoice, apply, tds in plan:
        balance = round(invoice["balance_due"] - apply - tds, 2)
        if balance < 0.005:
            balance = 0.0
        fields = {
            "amount_paid": round(invoice["amount_paid"] + apply, 2),
            "balance_due": balance,
            "status": "paid" if balance == 0.0 else "sent",
        }
        if tds:
            fields["tds_deducted"] = round(invoice.get("tds_deducted", 0.0) + tds, 2)
        if not repo.apply_to_invoice(invoice, fields):
            for done in applied:
                repo.restore_invoice(done["invoice"])
            raise AppError(f"{invoice['invoice_number']} changed while approving, please refresh and try again", 409)
        applied.append({"invoice": invoice, "apply": apply, "tds": tds, "after": fields})
    return applied


def record(txn, applied, mode):
    stamp = now()
    payments, summary = [], []
    for number, item in enumerate(applied, start=1):
        invoice = item["invoice"]
        payments.append({
            "payment_id": f"{txn['txn_id']}-{number}", "txn_id": txn["txn_id"], "batch_id": txn["batch_id"],
            "invoice_number": invoice["invoice_number"], "customer_id": invoice["customer_id"],
            "customer_name": invoice["customer_name"], "amount": item["apply"], "tds_amount": item["tds"],
            "currency": txn["currency"], "payment_date": txn["txn_date"], "reference": txn["reference"],
            "mode": mode, "approved_at": stamp,
        })
        summary.append({
            "invoice_number": invoice["invoice_number"], "amount": item["apply"], "tds_amount": item["tds"],
            "new_balance": item["after"]["balance_due"], "new_status": item["after"]["status"],
        })
    repo.insert_payments(payments)
    repo.set_fields(txn["txn_id"], {
        "review_status": "approved", "action_taken": mode, "applied": summary, "decided_at": stamp,
    })


def approve(txn_id, invoice_numbers=None, action=None):
    txn = repo.transition(txn_id, OPEN_STATES, {"review_status": "processing"})
    if not txn:
        if not repo.get_transaction(txn_id):
            raise AppError("Transaction not found", 404)
        raise AppError("This transaction has already been decided", 409)
    try:
        if repo.approved_fingerprints([txn["fingerprint"]]):
            raise AppError("This bank transaction was already approved from another upload", 409)
        plan, mode = build_plan(txn, invoice_numbers, action)
        applied = apply_plan(plan)
        try:
            record(txn, applied, mode)
        except Exception:
            for item in applied:
                repo.restore_invoice(item["invoice"])
            raise
    except Exception:
        repo.set_fields(txn_id, {"review_status": txn["review_status"]})
        raise
    return repo.get_transaction(txn_id)


def reject(txn_id, note=None):
    txn = repo.transition(txn_id, OPEN_STATES, {"review_status": "rejected", "decided_at": now(), "note": note})
    if not txn:
        if not repo.get_transaction(txn_id):
            raise AppError("Transaction not found", 404)
        raise AppError("This transaction has already been decided", 409)
    return repo.get_transaction(txn_id)