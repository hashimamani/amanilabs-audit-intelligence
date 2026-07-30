"""
Synthetic SACCO Data Generator
==============================

Generates a believable one-year dataset for a Kenyan SACCO:
Branches, Employees, Members, Accounts, Loans, Guarantors, Loan Payments,
Transactions.

Then INJECTS 8 known fraud/anomaly scenarios into that baseline and logs
exactly which records were injected into ground_truth.json / ground_truth.csv.
The ground truth is NOT part of the "clean" export a prospect would see -
it's your answer key for building/testing rules and for narrating the demo.

Output: /mnt/user-data/outputs/synthetic_sacco_data/
"""

import random
import json
import os
import numpy as np
import pandas as pd
from datetime import datetime, timedelta

random.seed(42)
np.random.seed(42)

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "synthetic_sacco_data")
os.makedirs(OUT_DIR, exist_ok=True)

TODAY = datetime(2026, 7, 1)
YEAR_START = TODAY - timedelta(days=365)

# ---------------------------------------------------------------------------
# Reference data (Kenyan texture)
# ---------------------------------------------------------------------------

BRANCH_TOWNS = [
    "Nairobi CBD", "Kiambu", "Thika", "Nakuru", "Eldoret", "Kisumu", "Meru",
    "Nyeri", "Machakos", "Mombasa", "Kakamega", "Kericho", "Embu", "Naivasha",
    "Kitengela"
]

EMPLOYERS = [
    "Self Employed", "Teacher - TSC", "County Government", "National Police Service",
    "Boda Boda Operator", "Matatu SACCO Crew", "Small Business Owner", "KPLC",
    "Safaricom", "Kenya Ports Authority", "Ministry of Health", "Retired",
    "Kenya Revenue Authority", "Private Security Firm", "Farmer / Agribusiness"
]

FIRST_NAMES_M = ["John","Peter","James","David","Samuel","Joseph","Daniel","Paul",
    "Stephen","Francis","Patrick","Kevin","Brian","Dennis","Erick","Charles",
    "Moses","Vincent","Anthony","Michael","Julius","Geoffrey","Isaac","Martin",
    "Elijah","Kennedy","Duncan","Felix","Robert","Simon"]
FIRST_NAMES_F = ["Mary","Grace","Jane","Faith","Ann","Alice","Lucy","Esther",
    "Catherine","Margaret","Agnes","Joyce","Rose","Beatrice","Sarah","Winnie",
    "Purity","Caroline","Susan","Nancy","Judith","Everlyne","Diana","Mercy",
    "Emily","Irene","Damaris","Lilian","Consolata","Rebecca"]
LAST_NAMES = ["Mwangi","Kamau","Otieno","Odhiambo","Wanjiru","Njoroge","Kiptoo",
    "Cheruiyot","Mutua","Wafula","Barasa","Kilonzo","Maina","Nyambura","Achieng",
    "Onyango","Koech","Rotich","Muthoni","Waweru","Kariuki","Omondi","Chebet",
    "Wekesa","Mumo","Ndungu","Gitau","Langat","Wamalwa","Adhiambo"]

def random_name():
    if random.random() < 0.5:
        first = random.choice(FIRST_NAMES_M)
    else:
        first = random.choice(FIRST_NAMES_F)
    return f"{first} {random.choice(LAST_NAMES)}"

def random_phone():
    return f"07{random.randint(10000000,99999999)}"

def random_national_id():
    return str(random.randint(20000000, 39999999))

def random_date(start, end):
    if end <= start:
        end = start + timedelta(days=1)
    delta = end - start
    return start + timedelta(days=random.randint(0, delta.days),
                              seconds=random.randint(0, 86399))

# ---------------------------------------------------------------------------
# Branches & Employees
# ---------------------------------------------------------------------------

branches = []
for i, town in enumerate(BRANCH_TOWNS, start=1):
    branches.append({
        "branch_id": f"BR{i:03d}",
        "branch_name": f"{town} Branch",
        "town": town,
        "opened_date": random_date(YEAR_START - timedelta(days=1500), YEAR_START).date().isoformat(),
    })
branches_df = pd.DataFrame(branches)

employees = []
emp_counter = 1
for b in branches:
    n_staff = random.randint(2, 4)
    for _ in range(n_staff):
        role = random.choice(["Loan Officer", "Loan Officer", "Teller", "Branch Manager"])
        employees.append({
            "employee_id": f"EMP{emp_counter:04d}",
            "name": random_name(),
            "role": role,
            "branch_id": b["branch_id"],
            "hire_date": random_date(YEAR_START - timedelta(days=2000), YEAR_START).date().isoformat(),
        })
        emp_counter += 1
employees_df = pd.DataFrame(employees)
loan_officers = employees_df[employees_df.role == "Loan Officer"]["employee_id"].tolist()

# ---------------------------------------------------------------------------
# Members
# ---------------------------------------------------------------------------

N_MEMBERS = 1500
members = []
for i in range(1, N_MEMBERS + 1):
    branch = random.choice(branches)
    join_date = random_date(YEAR_START - timedelta(days=365 * 6), TODAY - timedelta(days=30))
    members.append({
        "member_id": f"M{i:05d}",
        "name": random_name(),
        "national_id": random_national_id(),
        "phone": random_phone(),
        "branch_id": branch["branch_id"],
        "employer": random.choice(EMPLOYERS),
        "join_date": join_date.date().isoformat(),
        "risk_rating": "Normal",  # will be overwritten for injected cases downstream
    })
members_df = pd.DataFrame(members)

# ---------------------------------------------------------------------------
# Accounts (one savings account per member)
# ---------------------------------------------------------------------------

accounts = []
for m in members:
    accounts.append({
        "account_id": f"ACC{m['member_id'][1:]}",
        "member_id": m["member_id"],
        "account_type": "Savings",
        "opened_date": m["join_date"],
    })
accounts_df = pd.DataFrame(accounts)
member_account = {a["member_id"]: a["account_id"] for a in accounts}

# ---------------------------------------------------------------------------
# Baseline transactions (deposits / withdrawals / transfers over 1 year)
# ---------------------------------------------------------------------------
# Each member gets a "profile": typical deposit size, typical withdrawal size,
# activity frequency. This lets fraud rules like "withdrawal > 10x average"
# be meaningful rather than arbitrary.

transactions = []
txn_counter = 1

member_profiles = {}
for m in members:
    monthly_income_band = random.choice([8000, 15000, 25000, 40000, 60000, 100000])
    member_profiles[m["member_id"]] = {
        "typical_deposit": monthly_income_band * random.uniform(0.15, 0.4),
        "typical_withdrawal": monthly_income_band * random.uniform(0.1, 0.3),
        "activity_level": random.choice(["low", "medium", "high"]),
        "join_date": datetime.fromisoformat(m["join_date"]),
    }

ACTIVITY_TXNS_PER_MONTH = {"low": 1, "medium": 3, "high": 6}

def make_txn(member_id, txn_type, amount, dt, recipient=None, channel="Branch"):
    global txn_counter
    t = {
        "transaction_id": f"T{txn_counter:07d}",
        "account_id": member_account[member_id],
        "member_id": member_id,
        "transaction_type": txn_type,
        "amount": round(amount, 2),
        "timestamp": dt.isoformat(),
        "recipient": recipient if recipient else "",
        "channel": channel,
    }
    txn_counter += 1
    transactions.append(t)
    return t

for m in members:
    prof = member_profiles[m["member_id"]]
    start = max(YEAR_START, prof["join_date"])
    if start >= TODAY:
        continue
    n_months = max(1, int((TODAY - start).days / 30))
    txns_per_month = ACTIVITY_TXNS_PER_MONTH[prof["activity_level"]]
    for month in range(n_months):
        month_start = start + timedelta(days=30 * month)
        for _ in range(txns_per_month):
            dt = random_date(month_start, min(month_start + timedelta(days=30), TODAY))
            if random.random() < 0.55:
                amt = max(200, np.random.normal(prof["typical_deposit"], prof["typical_deposit"] * 0.25))
                make_txn(m["member_id"], "Deposit", amt, dt)
            else:
                amt = max(200, np.random.normal(prof["typical_withdrawal"], prof["typical_withdrawal"] * 0.25))
                make_txn(m["member_id"], "Withdrawal", amt, dt)

# ---------------------------------------------------------------------------
# Loans, Guarantors, Loan Payments (baseline)
# ---------------------------------------------------------------------------

loans = []
guarantors = []
loan_payments = []
loan_counter = 1
payment_counter = 1

# ~40% of members take at least one loan
loan_members = random.sample(members, int(N_MEMBERS * 0.4))

def create_loan(member_id, approved_by, approval_dt, amount=None, status="Active",
                 guarantor_ids=None, force_business_hours=True):
    global loan_counter
    if force_business_hours:
        # Keep approval within normal business hours (8am-5pm) unless the
        # caller explicitly wants an off-hours timestamp (see scenario 7,
        # which passes force_business_hours=False). Without this, "normal"
        # injected loans get random hours 0-23 and accidentally trip the
        # off-hours rule, polluting that rule's signal with noise that has
        # nothing to do with the scenario being tested.
        approval_dt = approval_dt.replace(hour=random.randint(8, 16),
                                           minute=random.randint(0, 59))
    prof = member_profiles[member_id]
    if amount is None:
        amount = round(random.uniform(10000, 300000), -2)
    term_months = random.choice([6, 12, 18, 24, 36])
    disbursement_dt = approval_dt + timedelta(days=random.randint(0, 3))
    loan_id = f"L{loan_counter:05d}"
    loan_counter += 1
    loans.append({
        "loan_id": loan_id,
        "member_id": member_id,
        "amount": amount,
        "term_months": term_months,
        "interest_rate": 12.0,
        "approved_by": approved_by,
        "approval_timestamp": approval_dt.isoformat(),
        "disbursement_timestamp": disbursement_dt.isoformat(),
        "status": status,
    })
    if guarantor_ids is None:
        candidates = [mm["member_id"] for mm in members if mm["member_id"] != member_id]
        guarantor_ids = random.sample(candidates, 2)
    for g in guarantor_ids:
        guarantors.append({"loan_id": loan_id, "guarantor_member_id": g})

    # Monthly repayments, with some randomly missed
    installment = round(amount * 1.12 / term_months, 2)
    for month in range(term_months):
        due_dt = disbursement_dt + timedelta(days=30 * (month + 1))
        if due_dt > TODAY:
            break
        if random.random() < 0.08:
            continue  # missed payment
        global payment_counter
        loan_payments.append({
            "payment_id": f"LP{payment_counter:06d}",
            "loan_id": loan_id,
            "amount": installment,
            "payment_timestamp": (due_dt + timedelta(days=random.randint(-3, 5))).isoformat(),
        })
        payment_counter += 1
    return loan_id

for m in loan_members:
    branch_id = m["branch_id"]
    branch_officers = employees_df[(employees_df.branch_id == branch_id) &
                                    (employees_df.role == "Loan Officer")]["employee_id"].tolist()
    if not branch_officers:
        branch_officers = loan_officers
    officer = random.choice(branch_officers)
    approval_dt = random_date(max(YEAR_START, member_profiles[m["member_id"]]["join_date"]), TODAY - timedelta(days=40))
    # keep approvals to normal business hours/weekdays for baseline
    while approval_dt.weekday() >= 5 or not (8 <= approval_dt.hour <= 17):
        approval_dt = random_date(max(YEAR_START, member_profiles[m["member_id"]]["join_date"]), TODAY - timedelta(days=40))
    create_loan(m["member_id"], officer, approval_dt)

# ---------------------------------------------------------------------------
# FRAUD SCENARIO INJECTION
# ---------------------------------------------------------------------------

ground_truth = []

def log_scenario(scenario, description, ids):
    ground_truth.append({
        "scenario": scenario,
        "description": description,
        "record_ids": ids,
    })

all_member_ids = [m["member_id"] for m in members]

# 1. LARGE WITHDRAWAL: withdrawal > 10x member's average
targets = random.sample(all_member_ids, 15)
for mid in targets:
    prof = member_profiles[mid]
    dt = random_date(TODAY - timedelta(days=90), TODAY - timedelta(days=2))
    amt = prof["typical_withdrawal"] * random.uniform(11, 22)
    t = make_txn(mid, "Withdrawal", amt, dt)
    log_scenario("large_withdrawal",
                 f"{mid} withdrew {amt:,.0f} vs typical {prof['typical_withdrawal']:,.0f}",
                 [t["transaction_id"]])

# 2. DORMANT ACCOUNT RAID: no activity >180 days, then a large withdrawal
targets = random.sample([mid for mid in all_member_ids if mid not in
                          [x for s in ground_truth for x in s["record_ids"]]], 10)
for mid in targets:
    prof = member_profiles[mid]
    # remove recent transactions for this member to simulate dormancy
    cutoff = TODAY - timedelta(days=200)
    global_idx_to_remove = [i for i, t in enumerate(transactions)
                             if t["member_id"] == mid and datetime.fromisoformat(t["timestamp"]) > cutoff]
    for i in sorted(global_idx_to_remove, reverse=True):
        del transactions[i]
    dt = random_date(TODAY - timedelta(days=15), TODAY - timedelta(days=1))
    amt = prof["typical_withdrawal"] * random.uniform(8, 15)
    t = make_txn(mid, "Withdrawal", amt, dt)
    log_scenario("dormant_account_raid",
                 f"{mid} dormant 200+ days, then withdrew {amt:,.0f}",
                 [t["transaction_id"]])

# 3. DUPLICATE TRANSACTION: same amount, same recipient, same day
targets = random.sample(all_member_ids, 10)
for mid in targets:
    dt = random_date(TODAY - timedelta(days=120), TODAY - timedelta(days=2))
    amt = round(random.uniform(5000, 60000), -2)
    recipient = random_name()
    t1 = make_txn(mid, "Transfer", amt, dt, recipient=recipient, channel="Mobile")
    t2 = make_txn(mid, "Transfer", amt, dt + timedelta(minutes=random.randint(2, 40)),
                  recipient=recipient, channel="Mobile")
    log_scenario("duplicate_transaction",
                 f"{mid} sent {amt:,.0f} to {recipient} twice same day",
                 [t1["transaction_id"], t2["transaction_id"]])

# 4. RAPID TRANSFERS: >5 outgoing transfers within a short window (structuring)
targets = random.sample(all_member_ids, 10)
for mid in targets:
    base_dt = random_date(TODAY - timedelta(days=100), TODAY - timedelta(days=3))
    ids = []
    for k in range(random.randint(6, 9)):
        dt = base_dt + timedelta(minutes=random.randint(0, 45))
        amt = round(random.uniform(9000, 9900), -1)  # just under a round threshold
        t = make_txn(mid, "Transfer", amt, dt, recipient=random_name(), channel="Mobile")
        ids.append(t["transaction_id"])
    log_scenario("rapid_transfers",
                 f"{mid} made {len(ids)} outgoing transfers within ~45 minutes",
                 ids)

# 5. EMPLOYEE LOAN-APPROVAL ANOMALY: one officer approves way more loans than peers
rogue_officer = random.choice(loan_officers)
rogue_members = random.sample([mid for mid in all_member_ids], 25)
injected_loan_ids = []
for mid in rogue_members:
    approval_dt = random_date(TODAY - timedelta(days=150), TODAY - timedelta(days=10))
    while approval_dt.weekday() >= 5:
        approval_dt = random_date(TODAY - timedelta(days=150), TODAY - timedelta(days=10))
    lid = create_loan(mid, rogue_officer, approval_dt, amount=round(random.uniform(50000, 250000), -2))
    injected_loan_ids.append(lid)
log_scenario("employee_loan_approval_anomaly",
             f"Officer {rogue_officer} approved {len(injected_loan_ids)} extra loans "
             f"(well above peer average) over 5 months",
             injected_loan_ids + [rogue_officer])

# 6. REPEATED GUARANTOR: same guarantor on many unrelated loans
serial_guarantor = random.choice(all_member_ids)
targets = random.sample([mid for mid in all_member_ids if mid != serial_guarantor], 18)
injected_loan_ids = []
for mid in targets:
    officer = random.choice(loan_officers)
    approval_dt = random_date(TODAY - timedelta(days=300), TODAY - timedelta(days=20))
    while approval_dt.weekday() >= 5:
        approval_dt = random_date(TODAY - timedelta(days=300), TODAY - timedelta(days=20))
    other_guarantor = random.choice([m for m in all_member_ids if m not in (mid, serial_guarantor)])
    lid = create_loan(mid, officer, approval_dt,
                       amount=round(random.uniform(20000, 150000), -2),
                       guarantor_ids=[serial_guarantor, other_guarantor])
    injected_loan_ids.append(lid)
log_scenario("repeated_guarantor",
             f"Member {serial_guarantor} guarantees {len(injected_loan_ids)} unrelated loans",
             injected_loan_ids + [serial_guarantor])

# 7. WEEKEND / OFF-HOURS APPROVALS
targets = random.sample(all_member_ids, 15)
injected_loan_ids = []
for mid in targets:
    officer = random.choice(loan_officers)
    # force weekend or late-night timestamp
    base = random_date(TODAY - timedelta(days=250), TODAY - timedelta(days=5))
    if random.random() < 0.5:
        while base.weekday() < 5:
            base += timedelta(days=1)
        approval_dt = base.replace(hour=random.randint(9, 16))
    else:
        approval_dt = base.replace(hour=random.choice([22, 23, 0, 1, 2]))
    lid = create_loan(mid, officer, approval_dt, amount=round(random.uniform(20000, 120000), -2),
                       force_business_hours=False)
    injected_loan_ids.append(lid)
log_scenario("weekend_offhours_approval",
             f"{len(injected_loan_ids)} loans approved on weekends or outside business hours",
             injected_loan_ids)

# 8. SAME-DAY DISBURSEMENT-THEN-WITHDRAWAL (loan cashed out immediately in full)
targets = random.sample(all_member_ids, 10)
injected = []
for mid in targets:
    officer = random.choice(loan_officers)
    approval_dt = random_date(TODAY - timedelta(days=180), TODAY - timedelta(days=10))
    while approval_dt.weekday() >= 5:
        approval_dt = random_date(TODAY - timedelta(days=180), TODAY - timedelta(days=10))
    amount = round(random.uniform(40000, 200000), -2)
    lid = create_loan(mid, officer, approval_dt, amount=amount)
    disb_dt = datetime.fromisoformat(loans[-1]["disbursement_timestamp"])
    t = make_txn(mid, "Withdrawal", amount * random.uniform(0.95, 1.0),
                 disb_dt + timedelta(hours=random.randint(1, 6)))
    injected.append({"loan_id": lid, "transaction_id": t["transaction_id"]})
log_scenario("same_day_disbursement_withdrawal",
             f"{len(injected)} loans withdrawn in full within hours of disbursement",
             [f"{x['loan_id']}/{x['transaction_id']}" for x in injected])

# 9. FRAUD RING (R009 - see app/rules/fraud_ring.py for the detection
# side). Two independent sub-scenarios: a closed-loop guarantee chain
# (9a) and shared contact info across "different" member records (9b).
already_used = {x for s in ground_truth for x in s["record_ids"]}
ring_pool = [mid for mid in all_member_ids if mid not in already_used]

# 9a. CIRCULAR GUARANTEE RING: each member guarantees the next member's
# loan, looping back to the first - a closed loop where nobody in the
# chain has independent financial backing. Approvals clustered within a
# few days (with a small forward-shift to dodge weekends, so this doesn't
# also masquerade as an R007 off-hours flag) so the "synchronized window"
# signal fires too.
for ring_size in (4, 5):
    ring_members = random.sample(ring_pool, ring_size)
    ring_pool = [mid for mid in ring_pool if mid not in ring_members]
    officer = random.choice(loan_officers)
    base_dt = random_date(TODAY - timedelta(days=200), TODAY - timedelta(days=30))
    ring_loan_ids = []
    for i, mid in enumerate(ring_members):
        guarantor = ring_members[i - 1]  # previous member in the ring guarantees this one
        approval_dt = base_dt + timedelta(days=random.randint(0, 4))
        while approval_dt.weekday() >= 5:
            approval_dt += timedelta(days=1)
        lid = create_loan(mid, officer, approval_dt,
                           amount=round(random.uniform(50000, 200000), -2),
                           guarantor_ids=[guarantor])
        ring_loan_ids.append(lid)
    log_scenario("circular_guarantee_ring",
                 f"{ring_size}-member circular guarantee chain "
                 f"({' -> '.join(ring_members)} -> {ring_members[0]}), "
                 f"loans approved within days of each other",
                 ring_loan_ids + ring_members)

# 9b. SHARED IDENTITY: "different" member records that actually share a
# phone number or national ID - either duplicate registrations for the
# same person, or coordinated accounts. Mutates members_df directly
# (already snapshotted from `members` by this point in the script) since
# that's what actually gets written to members.csv.
shared_id_targets = random.sample(ring_pool, 6)
ring_pool = [mid for mid in ring_pool if mid not in shared_id_targets]

for pair in (shared_id_targets[0:2], shared_id_targets[2:4]):
    shared_phone = random_phone()
    members_df.loc[members_df.member_id.isin(pair), "phone"] = shared_phone
    log_scenario("shared_identity_ring",
                 f"Members {pair[0]} and {pair[1]} share phone number {shared_phone}",
                 list(pair))

national_id_pair = shared_id_targets[4:6]
shared_nid = random_national_id()
members_df.loc[members_df.member_id.isin(national_id_pair), "national_id"] = shared_nid
log_scenario("shared_identity_ring",
             f"Members {national_id_pair[0]} and {national_id_pair[1]} share national ID {shared_nid}",
             list(national_id_pair))

# ---------------------------------------------------------------------------
# Mark risk_rating for injected members (light touch, still "Normal" by default
# in the clean export - this field simulates what a SACCO's own system might
# already show, which is usually... nothing useful yet)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Write outputs
# ---------------------------------------------------------------------------

transactions_df = pd.DataFrame(transactions).sort_values("timestamp")
loans_df = pd.DataFrame(loans)
guarantors_df = pd.DataFrame(guarantors)
loan_payments_df = pd.DataFrame(loan_payments)

branches_df.to_csv(f"{OUT_DIR}/branches.csv", index=False)
employees_df.to_csv(f"{OUT_DIR}/employees.csv", index=False)
members_df.to_csv(f"{OUT_DIR}/members.csv", index=False)
accounts_df.to_csv(f"{OUT_DIR}/accounts.csv", index=False)
transactions_df.to_csv(f"{OUT_DIR}/transactions.csv", index=False)
loans_df.to_csv(f"{OUT_DIR}/loans.csv", index=False)
guarantors_df.to_csv(f"{OUT_DIR}/guarantors.csv", index=False)
loan_payments_df.to_csv(f"{OUT_DIR}/loan_payments.csv", index=False)

with open(f"{OUT_DIR}/ground_truth.json", "w") as f:
    json.dump(ground_truth, f, indent=2)

# Flat CSV version of ground truth for quick scanning
gt_rows = []
for s in ground_truth:
    gt_rows.append({
        "scenario": s["scenario"],
        "description": s["description"],
        "n_records": len(s["record_ids"]),
        "record_ids": ";".join(s["record_ids"]),
    })
pd.DataFrame(gt_rows).to_csv(f"{OUT_DIR}/ground_truth.csv", index=False)

print("=== Generation complete ===")
print(f"Branches: {len(branches_df)}")
print(f"Employees: {len(employees_df)}")
print(f"Members: {len(members_df)}")
print(f"Transactions: {len(transactions_df)}")
print(f"Loans: {len(loans_df)}")
print(f"Guarantors: {len(guarantors_df)}")
print(f"Loan payments: {len(loan_payments_df)}")
print()
print("=== Injected fraud scenarios ===")
for s in ground_truth[:8] if len(ground_truth) <= 8 else ground_truth:
    pass
for s in ground_truth:
    print(f"- {s['scenario']}: {s['description']}")
