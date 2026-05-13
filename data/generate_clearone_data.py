"""Generate synthetic ClearOne Advantage operational data for Quick Suite demo.

Produces CSVs covering:
- clients: enrolled debtors, state, enrollment date, enrolled debt
- enrollments: monthly draft schedule and collection status
- negotiations: creditor settlement outcomes
- agent_performance: daily agent KPIs
- call_activity: call-center operational metrics

Output: ./output/*.csv
"""
from __future__ import annotations

import csv
import os
import random
from datetime import date, datetime, timedelta
from pathlib import Path

random.seed(42)

OUT = Path(__file__).parent / "output"
OUT.mkdir(exist_ok=True)

STATES = [
    "TX", "FL", "CA", "NY", "PA", "OH", "IL", "GA", "NC", "MI",
    "NJ", "VA", "WA", "AZ", "MA", "TN", "IN", "MO", "MD", "WI",
    "CO", "MN", "SC", "AL", "LA", "KY", "OR", "OK", "CT", "IA",
]
STATE_WEIGHTS = [max(1, 30 - i) for i in range(len(STATES))]

CREDITORS = [
    "Capital One", "Chase", "Citi", "Discover", "Bank of America", "Synchrony",
    "American Express", "Wells Fargo", "Barclays", "US Bank", "PNC", "TD Bank",
    "Comenity", "Credit One", "First Premier",
]

AGENTS = [
    ("A-1001", "Emily Chen", "Debt Specialist", "Baltimore"),
    ("A-1002", "Marcus Johnson", "Debt Specialist", "Baltimore"),
    ("A-1003", "Priya Patel", "Debt Specialist", "Baltimore"),
    ("A-1004", "Jordan Rivera", "Debt Specialist", "Tempe"),
    ("A-1005", "Sofia Alvarez", "Debt Specialist", "Tempe"),
    ("A-1006", "Ethan Kim", "Debt Specialist", "Tempe"),
    ("A-2001", "Rachel Nguyen", "Negotiator", "Baltimore"),
    ("A-2002", "Daniel Okafor", "Negotiator", "Baltimore"),
    ("A-2003", "Hannah Park", "Negotiator", "Tempe"),
    ("A-2004", "Samuel Reyes", "Negotiator", "Tempe"),
    ("A-3001", "Olivia Brooks", "Client Success", "Baltimore"),
    ("A-3002", "William Tran", "Client Success", "Baltimore"),
    ("A-3003", "Ava Martinez", "Client Success", "Tempe"),
    ("A-3004", "Noah Williams", "Client Success", "Tempe"),
]

TEAMS = {
    "Debt Specialist": ["Sales Team Alpha", "Sales Team Bravo"],
    "Negotiator": ["Negotiations East", "Negotiations West"],
    "Client Success": ["CS Team North", "CS Team South"],
}

TODAY = date(2026, 5, 13)
CLIENT_COUNT = 2800
MONTHS_HISTORY = 18


def _rand_date(start: date, end: date) -> date:
    delta = (end - start).days
    return start + timedelta(days=random.randint(0, max(0, delta)))


def gen_clients() -> list[dict]:
    """Each client has one enrollment record."""
    rows = []
    for i in range(1, CLIENT_COUNT + 1):
        enrollment_date = _rand_date(TODAY - timedelta(days=MONTHS_HISTORY * 30), TODAY - timedelta(days=7))
        total_debt = round(random.triangular(5000, 95000, 22000), 2)
        monthly_deposit = round(total_debt / random.randint(24, 54), 2)
        status_roll = random.random()
        if status_roll < 0.05:
            status = "Cancelled"
        elif status_roll < 0.10:
            status = "Graduated"
        elif status_roll < 0.17:
            status = "On Hold"
        else:
            status = "Active"
        enrolled_accounts = random.randint(2, 11)
        rows.append({
            "client_id": f"C{100000 + i}",
            "first_name": random.choice(["James", "Mary", "John", "Patricia", "Robert", "Jennifer", "Michael", "Linda",
                                          "David", "Elizabeth", "Chris", "Maria", "Anthony", "Susan", "Ken", "Angela"]),
            "last_name": random.choice(["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis",
                                         "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez", "Wilson", "Anderson"]),
            "state": random.choices(STATES, weights=STATE_WEIGHTS, k=1)[0],
            "enrollment_date": enrollment_date.isoformat(),
            "total_enrolled_debt": total_debt,
            "monthly_deposit": monthly_deposit,
            "enrolled_accounts": enrolled_accounts,
            "status": status,
            "enrollment_source": random.choices(
                ["Organic", "Affiliate", "Referral", "Direct Mail", "Paid Search"],
                weights=[20, 35, 10, 15, 20],
            )[0],
            "assigned_specialist": random.choice([a for a in AGENTS if a[2] == "Debt Specialist"])[0],
            "assigned_negotiator": random.choice([a for a in AGENTS if a[2] == "Negotiator"])[0],
            "assigned_cs": random.choice([a for a in AGENTS if a[2] == "Client Success"])[0],
        })
    return rows


def gen_negotiations(clients: list[dict]) -> list[dict]:
    """Multiple settlement attempts per client."""
    rows = []
    neg_id = 500000
    for c in clients:
        if c["status"] == "Cancelled":
            settlement_count = random.randint(0, 2)
        elif c["status"] == "Graduated":
            settlement_count = c["enrolled_accounts"]
        else:
            settlement_count = random.randint(0, min(c["enrolled_accounts"], 6))
        for _ in range(settlement_count):
            original_balance = round(random.uniform(1200, 18000), 2)
            settlement_pct = random.triangular(0.30, 0.70, 0.45)
            settlement_amount = round(original_balance * settlement_pct, 2)
            savings = round(original_balance - settlement_amount, 2)
            outcome_roll = random.random()
            if outcome_roll < 0.78:
                outcome = "Accepted"
            elif outcome_roll < 0.92:
                outcome = "Pending"
            else:
                outcome = "Rejected"
            neg_date = _rand_date(date.fromisoformat(c["enrollment_date"]) + timedelta(days=90), TODAY)
            rows.append({
                "negotiation_id": f"N{neg_id}",
                "client_id": c["client_id"],
                "creditor": random.choice(CREDITORS),
                "original_balance": original_balance,
                "settlement_amount": settlement_amount,
                "settlement_percentage": round(settlement_pct * 100, 1),
                "savings": savings,
                "outcome": outcome,
                "negotiation_date": neg_date.isoformat(),
                "negotiator_id": c["assigned_negotiator"],
            })
            neg_id += 1
    return rows


def gen_payments(clients: list[dict]) -> list[dict]:
    """Monthly draft payments per active client."""
    rows = []
    pay_id = 900000
    for c in clients:
        start = date.fromisoformat(c["enrollment_date"])
        months_elapsed = max(0, (TODAY.year - start.year) * 12 + (TODAY.month - start.month))
        if c["status"] == "Cancelled":
            months_elapsed = random.randint(1, max(1, months_elapsed))
        for m in range(months_elapsed):
            draft_date = start + timedelta(days=30 * m)
            if draft_date > TODAY:
                break
            failure_roll = random.random()
            if c["status"] == "Cancelled" and m == months_elapsed - 1:
                status = "Failed"
            elif failure_roll < 0.06:
                status = "Failed"
            elif failure_roll < 0.09:
                status = "Rescheduled"
            else:
                status = "Collected"
            rows.append({
                "payment_id": f"P{pay_id}",
                "client_id": c["client_id"],
                "draft_date": draft_date.isoformat(),
                "amount": c["monthly_deposit"],
                "status": status,
                "failure_reason": "NSF" if status == "Failed" and random.random() < 0.7 else (
                    "Account Closed" if status == "Failed" else ""),
            })
            pay_id += 1
    return rows


def gen_agent_performance() -> list[dict]:
    """Daily rollup of agent metrics for past 90 days."""
    rows = []
    start = TODAY - timedelta(days=90)
    for day_offset in range(91):
        d = start + timedelta(days=day_offset)
        if d.weekday() >= 5:
            continue
        for agent_id, name, role, office in AGENTS:
            if role == "Debt Specialist":
                calls = max(0, int(random.gauss(58, 10)))
                enrollments = max(0, int(random.gauss(3.2, 1.4)))
                talk_minutes = calls * random.uniform(5.5, 9.0)
                rows.append({
                    "date": d.isoformat(),
                    "agent_id": agent_id,
                    "agent_name": name,
                    "role": role,
                    "office": office,
                    "team": random.choice(TEAMS[role]),
                    "calls_handled": calls,
                    "talk_time_minutes": round(talk_minutes, 1),
                    "enrollments_signed": enrollments,
                    "enrolled_debt_total": round(enrollments * random.uniform(18000, 32000), 2),
                    "settlements_closed": 0,
                    "settlement_savings_total": 0,
                    "client_contacts": 0,
                    "csat_score": round(random.uniform(3.9, 4.9), 2),
                })
            elif role == "Negotiator":
                settlements = max(0, int(random.gauss(4.5, 1.8)))
                savings = settlements * random.uniform(4500, 11000)
                rows.append({
                    "date": d.isoformat(),
                    "agent_id": agent_id,
                    "agent_name": name,
                    "role": role,
                    "office": office,
                    "team": random.choice(TEAMS[role]),
                    "calls_handled": max(0, int(random.gauss(22, 6))),
                    "talk_time_minutes": round(random.uniform(180, 360), 1),
                    "enrollments_signed": 0,
                    "enrolled_debt_total": 0,
                    "settlements_closed": settlements,
                    "settlement_savings_total": round(savings, 2),
                    "client_contacts": 0,
                    "csat_score": round(random.uniform(4.1, 4.9), 2),
                })
            else:
                rows.append({
                    "date": d.isoformat(),
                    "agent_id": agent_id,
                    "agent_name": name,
                    "role": role,
                    "office": office,
                    "team": random.choice(TEAMS[role]),
                    "calls_handled": max(0, int(random.gauss(45, 9))),
                    "talk_time_minutes": round(random.uniform(240, 420), 1),
                    "enrollments_signed": 0,
                    "enrolled_debt_total": 0,
                    "settlements_closed": 0,
                    "settlement_savings_total": 0,
                    "client_contacts": max(0, int(random.gauss(62, 11))),
                    "csat_score": round(random.uniform(4.0, 4.9), 2),
                })
    return rows


def gen_call_activity() -> list[dict]:
    """Hourly call-center volume for past 30 days."""
    rows = []
    start = TODAY - timedelta(days=30)
    for day_offset in range(31):
        d = start + timedelta(days=day_offset)
        if d.weekday() >= 5:
            continue
        for hour in range(8, 20):
            inbound_base = 95 if 9 <= hour <= 17 else 35
            offered = max(0, int(random.gauss(inbound_base, 18)))
            abandoned = max(0, int(offered * random.uniform(0.04, 0.12)))
            answered = offered - abandoned
            avg_wait = random.uniform(12, 60)
            avg_handle = random.uniform(280, 520)
            rows.append({
                "date": d.isoformat(),
                "hour": hour,
                "queue": random.choice(["Sales", "Client Care", "Retention", "Negotiations"]),
                "calls_offered": offered,
                "calls_answered": answered,
                "calls_abandoned": abandoned,
                "service_level_pct": round(random.uniform(72, 94), 1),
                "avg_wait_seconds": round(avg_wait, 1),
                "avg_handle_seconds": round(avg_handle, 1),
            })
    return rows


def write_csv(name: str, rows: list[dict]) -> None:
    if not rows:
        return
    path = OUT / name
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {path}  rows={len(rows)}")


def write_agents() -> None:
    rows = [
        {"agent_id": a[0], "agent_name": a[1], "role": a[2], "office": a[3],
         "team": TEAMS[a[2]][i % 2]}
        for i, a in enumerate(AGENTS)
    ]
    write_csv("agents.csv", rows)


def main() -> None:
    print(f"Generating ClearOne synthetic data (today={TODAY.isoformat()}, clients={CLIENT_COUNT})")
    clients = gen_clients()
    negotiations = gen_negotiations(clients)
    payments = gen_payments(clients)
    agent_perf = gen_agent_performance()
    calls = gen_call_activity()

    write_csv("clients.csv", clients)
    write_csv("negotiations.csv", negotiations)
    write_csv("payments.csv", payments)
    write_csv("agent_performance.csv", agent_perf)
    write_csv("call_activity.csv", calls)
    write_agents()
    print("done")


if __name__ == "__main__":
    main()
