from pathlib import Path
from app.core.config import settings
from app.matching.engine import match_statement
from app.repositories import customer_repo, invoice_repo

if __name__ == "__main__":
    text = (Path(settings.data_dir) / "bank_statement_sample.csv").read_text(encoding="utf-8")
    for r in match_statement(text, customer_repo.list_all(), invoice_repo.find({})):
        nums = ",".join(i["invoice_number"] for i in r["invoices"]) or "-"
        print(f"{r['txn_date']} {r['amount']:>10} {r['currency']} | {r['status']:<9} {nums:<24} {r['confidence']:>3} {r['level']:<6} {r['suggested_action'] or '-':<10} | {r['reason']}")