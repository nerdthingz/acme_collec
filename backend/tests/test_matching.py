import json
from pathlib import Path
import pytest
from app.matching.engine import match_statement, parse_statement

DATA = Path(__file__).resolve().parents[2] / "data"
CUSTOMERS = json.loads((DATA / "customers.json").read_text(encoding="utf-8"))
INVOICES = json.loads((DATA / "invoices.json").read_text(encoding="utf-8"))
SAMPLE = (DATA / "bank_statement_sample.csv").read_text(encoding="utf-8")

EXPECTED = [
    (["INV-1004"], "full"),
    (["INV-1013"], "leave_open"),
    (["INV-1007"], "close_tds"),
    (["INV-1024"], "full"),
    (["INV-1021"], "full"),
    (["INV-1002"], "full"),
    (["INV-1016"], "full"),
    None,
    (["INV-1026"], "full"),
    (["INV-1010", "INV-1011", "INV-1012"], "split"),
    None,
    (["INV-1017"], "full"),
    None,
    None,
]


@pytest.fixture(scope="module")
def results():
    return match_statement(SAMPLE, CUSTOMERS, INVOICES)


@pytest.mark.parametrize("index", range(len(EXPECTED)))
def test_sample_rows(results, index):
    result = results[index]
    expected = EXPECTED[index]
    if expected is None:
        assert result["invoices"] == []
        return
    assert [i["invoice_number"] for i in result["invoices"]] == expected[0]
    assert result["suggested_action"] == expected[1]


def test_confidence_levels(results):
    assert results[0]["level"] == "high"
    assert results[11]["level"] == "low"
    assert results[1]["level"] == "medium"


def test_same_amount_is_ambiguous():
    csv_text = "txn_date,narration,reference,credit,debit,currency\n2026-10-25,NEFT CR-KESTREL FOODS,X1,59000,,INR\n"
    result = match_statement(csv_text, CUSTOMERS, INVOICES)[0]
    assert result["confidence"] < 80
    assert "also fits" in result["reason"]


def test_second_payment_cannot_reuse_invoice():
    csv_text = (
        "txn_date,narration,reference,credit,debit,currency\n"
        "2026-09-05,IMPS/KESTREL FOODS/INV 1004,A,59000,,INR\n"
        "2026-09-06,IMPS/KESTREL FOODS/INV 1004,B,59000,,INR\n"
    )
    first, second = match_statement(csv_text, CUSTOMERS, INVOICES)
    assert first["status"] == "suggested"
    assert second["status"] == "no_match"


def test_bad_csv_is_rejected():
    with pytest.raises(ValueError):
        parse_statement("a,b\n1,2\n")
    with pytest.raises(ValueError):
        parse_statement("txn_date,narration,reference,credit,debit,currency\nnot-a-date,x,y,1,,INR\n")