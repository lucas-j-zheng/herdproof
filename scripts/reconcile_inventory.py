"""Constrained CSV reconciliation. Synthetic records are never ownership proof."""
from __future__ import annotations
import csv
import io
from datetime import date


def read_records(text):
    reader = csv.DictReader(io.StringIO(text))
    required = {"document_id", "date", "event", "pen", "quantity"}
    if set(reader.fieldnames or []) != required: raise ValueError("Unsupported CSV columns")
    output, seen = [], set()
    for line, row in enumerate(reader, 2):
        if any(row[k] is None or not row[k].strip() for k in required): raise ValueError(f"Missing field at line {line}")
        if row["document_id"] in seen: raise ValueError("Duplicate document ID")
        seen.add(row["document_id"])
        if row["event"] not in {"inventory", "purchase", "sale"}: raise ValueError("Unsupported event")
        amount = int(row["quantity"])
        if amount < 0: raise ValueError("Negative quantity")
        output.append({**row, "quantity": amount, "date": date.fromisoformat(row["date"]), "source_line": line})
    if not output: raise ValueError("Empty records")
    return output


def reconcile(records, observations, as_of):
    as_of = date.fromisoformat(as_of)
    pens = sorted({r["pen"] for r in records if r["event"] == "inventory"})
    if not pens: raise ValueError("Inventory baseline required")
    if any(r["pen"] not in pens for r in records): raise ValueError("Transaction references an unknown pen")
    output = []
    for pen in pens:
        inventory = [r for r in records if r["pen"] == pen and r["event"] == "inventory"]
        if len(inventory) != 1: raise ValueError("Exactly one baseline per pen required")
        base = inventory[0]
        if base["date"] > as_of: raise ValueError("Baseline is after inspection")
        transactions = [r for r in records if r["pen"] == pen and r["event"] != "inventory"]
        if any(r["date"] <= base["date"] for r in transactions):
            raise ValueError("Transactions must follow baseline date; same-day ordering needs timestamps")
        applicable = [r for r in transactions if r["date"] <= as_of]
        expected = base["quantity"] + sum(r["quantity"] * (1 if r["event"] == "purchase" else -1) for r in applicable)
        if expected < 0: raise ValueError("Transactions produce negative inventory")
        evidence = observations.get(pen)
        status, observed, reason = "incomplete", None, "Capture and review this pen"
        if evidence is not None:
            if not isinstance(evidence.get("count"), int) or isinstance(evidence["count"], bool) or evidence["count"] < 0:
                raise ValueError("Observed count must be a nonnegative integer")
            observed = evidence["count"]
            if evidence.get("as_of") != as_of.isoformat(): reason = "Observation date differs from inspection date"
            elif evidence.get("coverage") != "complete": reason = "Required area is not completely observable"
            elif not evidence.get("reviewed"): reason = "Review detection proposals"
            else:
                status = "matches_records" if observed == expected else "unexplained_difference"
                reason = "Count reconciles under the scenario assumptions" if observed == expected else "Resolve count difference with additional evidence"
        output.append({"pen": pen, "expected": expected, "observed": observed,
                       "difference": observed-expected if status != "incomplete" else None,
                       "status": status, "next_action": reason,
                       "source_lines": [base["source_line"]] + [r["source_line"] for r in applicable],
                       "ignored_future_documents": [r["document_id"] for r in transactions if r["date"] > as_of]})
    return {"as_of": as_of.isoformat(), "pens": output,
            "status": "incomplete" if any(r["status"] == "incomplete" for r in output) else "reviewed",
            "expected_total": sum(r["expected"] for r in output),
            "observed_total": sum(r["observed"] for r in output) if all(r["status"] != "incomplete" for r in output) else None,
            "scope": "Observed inventory reconciliation only; ownership, loan eligibility, and capture authenticity not established"}
