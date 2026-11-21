"""Seeded synthetic data generator with a hidden injected-issue answer key.

Run with ``python -m src.generate_data``. All generation parameters come from
``config.yaml`` so runs are reproducible. The answer key is written to a hidden
file (``data/.ground_truth.csv``) and is used only for reporting detection
quality; detection code never reads it.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .config import (
    data_file,
    get_path,
    ground_truth_file,
    load_config,
    require_path,
)
from .utils import json_dumps, short_id, to_iso, write_csv

EVENT_COLUMNS = [
    "event_id",
    "transaction_id",
    "customer_id",
    "merchant_id",
    "amount",
    "currency",
    "event_timestamp",
    "event_type",
    "status",
    "device_id",
]
STATUS_COLUMNS = ["transaction_id", "status", "status_timestamp"]
REFUND_COLUMNS = [
    "refund_id",
    "transaction_id",
    "refund_amount",
    "refund_timestamp",
    "refund_status",
]
GT_COLUMNS = [
    "issue_id",
    "issue_type",
    "record_type",
    "entity_id",
    "expected_reason_code",
    "severity",
    "description",
    "source_file",
    "details",
]


@dataclass
class GeneratedData:
    """All generated tables plus their output paths."""

    customers: pd.DataFrame
    merchants: pd.DataFrame
    transactions: pd.DataFrame
    refunds: pd.DataFrame
    payment_status: pd.DataFrame
    device_summary: pd.DataFrame
    ground_truth: pd.DataFrame
    paths: dict[str, Path]


class DataGenerator:
    """Build a realistic but deliberately imperfect payment dataset."""

    def __init__(self, config: dict[str, Any], seed: int | None = None) -> None:
        self.config = config
        self.params = require_path(config, "data.generation")
        self.rng = np.random.default_rng(
            int(seed) if seed is not None else int(self.params["seed"])
        )
        # Date-only anchor keeps the injected "future" timestamps reproducible
        # across runs while remaining in the future at validation time.
        self.now = pd.Timestamp.now().normalize()
        self.start = pd.Timestamp(str(self.params["activity_start"]))
        self.end = pd.Timestamp(str(self.params["activity_end"]))
        self.window_seconds = int((self.end - self.start).total_seconds())
        self.events: list[dict[str, Any]] = []
        self.status_history: list[dict[str, Any]] = []
        self.refunds_list: list[dict[str, Any]] = []
        self.ground_truth_rows: list[dict[str, Any]] = []
        self.customers = pd.DataFrame()
        self.merchants = pd.DataFrame()
        self.devices: list[str] = []
        self.primary_device: dict[str, str] = {}
        self.home_currency: dict[str, str] = {}
        self.event_indices: dict[str, list[int]] = {}
        self.txn_info: dict[str, dict[str, Any]] = {}
        self.event_counter = 0
        self.txn_counter = 0
        self.refund_counter = 0
        self.used_txns: set[str] = set()

    # ------------------------------------------------------------------ helpers
    def _random_time(self) -> pd.Timestamp:
        return self.start + timedelta(seconds=int(self.rng.integers(0, self.window_seconds)))

    def _issue(
        self,
        issue_type: str,
        record_type: str,
        entity_id: str,
        reason_code: str,
        severity: str,
        description: str,
        source_file: str,
        **details: Any,
    ) -> None:
        """Record one deliberately injected issue in the hidden answer key."""
        self.ground_truth_rows.append(
            {
                "issue_id": short_id("INJ", len(self.ground_truth_rows) + 1, 4),
                "issue_type": issue_type,
                "record_type": record_type,
                "entity_id": entity_id,
                "expected_reason_code": reason_code,
                "severity": severity,
                "description": description,
                "source_file": source_file,
                "details": json_dumps(details),
            }
        )

    def _add_event(
        self,
        txn_id: str,
        customer_id: str,
        merchant_id: str,
        amount: float,
        currency: str,
        timestamp: pd.Timestamp,
        event_type: str,
        status: str,
        device_id: str,
    ) -> int:
        self.event_counter += 1
        row = {
            "event_id": short_id("EV", self.event_counter, 7),
            "transaction_id": txn_id,
            "customer_id": customer_id,
            "merchant_id": merchant_id,
            "amount": round(float(amount), 2),
            "currency": currency,
            "event_timestamp": to_iso(timestamp),
            "event_type": event_type,
            "status": status,
            "device_id": device_id,
        }
        index = len(self.events)
        self.events.append(row)
        self.event_indices.setdefault(txn_id, []).append(index)
        return index

    def _add_status(self, txn_id: str, status: str, timestamp: pd.Timestamp) -> None:
        self.status_history.append(
            {
                "transaction_id": txn_id,
                "status": status,
                "status_timestamp": to_iso(timestamp),
            }
        )

    def _add_refund(
        self,
        txn_id: str,
        amount: float,
        timestamp: pd.Timestamp,
        refund_status: str = "completed",
    ) -> str:
        self.refund_counter += 1
        refund_id = short_id("RFD", self.refund_counter, 6)
        self.refunds_list.append(
            {
                "refund_id": refund_id,
                "transaction_id": txn_id,
                "refund_amount": round(float(amount), 2),
                "refund_timestamp": to_iso(timestamp),
                "refund_status": refund_status,
            }
        )
        return refund_id

    def _new_transaction(
        self,
        customer_id: str,
        merchant_id: str,
        amount: float,
        currency: str,
        timestamp: pd.Timestamp,
        outcome: str = "captured",
        device_id: str | None = None,
        n_retries: int = 0,
    ) -> str:
        """Create a normal transaction lifecycle (events + status history)."""
        self.txn_counter += 1
        txn_id = short_id("TXN", self.txn_counter, 6)
        device = device_id or self.primary_device[customer_id]
        self.txn_info[txn_id] = {
            "customer_id": customer_id,
            "merchant_id": merchant_id,
            "amount": round(float(amount), 2),
            "currency": currency,
            "device_id": device,
            "capture_time": timestamp + timedelta(seconds=45) if outcome == "captured" else None,
        }
        self._add_event(
            txn_id, customer_id, merchant_id, amount, currency, timestamp,
            "authorization", "authorized" if outcome != "failed" else "failed", device,
        )
        self._add_status(txn_id, "failed" if outcome == "failed" else "authorized", timestamp)
        for _ in range(n_retries):
            retry_time = timestamp + timedelta(seconds=int(self.rng.integers(5, 40)))
            self._add_event(
                txn_id, customer_id, merchant_id, amount, currency, retry_time,
                "retry", "authorized", device,
            )
            self._add_status(txn_id, "authorized", retry_time)
        if outcome == "captured":
            capture_time = timestamp + timedelta(seconds=45)
            self._add_event(
                txn_id, customer_id, merchant_id, amount, currency, capture_time,
                "capture", "captured", device,
            )
            self._add_status(txn_id, "captured", capture_time)
        elif outcome == "voided":
            void_time = timestamp + timedelta(minutes=int(self.rng.integers(5, 90)))
            self._add_event(
                txn_id, customer_id, merchant_id, amount, currency, void_time,
                "void", "voided", device,
            )
            self._add_status(txn_id, "voided", void_time)
        return txn_id

    def _event(self, index: int) -> dict[str, Any]:
        return self.events[index]

    def _captured_txns(self) -> list[str]:
        return [
            txn for txn, info in self.txn_info.items()
            if info.get("capture_time") is not None
        ]

    # -------------------------------------------------------------- base tables
    def _build_dimensions(self) -> None:
        countries = list(require_path(self.config, "data.generation.countries"))
        currencies = list(require_path(self.config, "data.generation.currencies"))
        categories = list(require_path(self.config, "data.generation.categories"))
        segments = list(require_path(self.config, "data.generation.risk_segments"))
        weights = list(require_path(self.config, "data.generation.risk_segment_weights"))
        n_customers = int(self.params["n_customers"])
        n_merchants = int(self.params["n_merchants"])

        self.customers = pd.DataFrame(
            {
                "customer_id": [short_id("CUST", i + 1, 4) for i in range(n_customers)],
                "signup_date": [
                    to_iso((self.start - timedelta(days=int(self.rng.integers(5, 200)))).date())
                    for _ in range(n_customers)
                ],
                "country": self.rng.choice(countries, n_customers),
                "risk_segment": self.rng.choice(segments, n_customers, p=weights),
            }
        )
        self.merchants = pd.DataFrame(
            {
                "merchant_id": [short_id("MER", i + 1, 3) for i in range(n_merchants)],
                "category": self.rng.choice(categories, n_merchants),
                "country": self.rng.choice(countries, n_merchants),
                "onboarding_date": [
                    to_iso((self.start - timedelta(days=int(self.rng.integers(10, 500)))).date())
                    for _ in range(n_merchants)
                ],
            }
        )
        self.devices = [
            short_id("DEV", i + 1, 4) for i in range(int(self.params["n_devices"]))
        ]
        chosen_devices = self.rng.choice(
            self.devices, n_customers, replace=len(self.devices) < n_customers
        )
        for customer, device in zip(self.customers["customer_id"], chosen_devices):
            self.primary_device[customer] = str(device)
            self.home_currency[customer] = str(self.rng.choice(currencies))
        # A few devices start with a legitimate second customer.
        for device in self.rng.choice(self.devices, 6, replace=False):
            other = str(self.rng.choice(self.customers["customer_id"]))
            self.primary_device[other] = str(device)

    def _build_base_activity(self) -> None:
        customer_ids = self.customers["customer_id"].tolist()
        merchant_ids = self.merchants["merchant_id"].tolist()
        outcomes = ["captured", "failed", "voided"]
        probs = [
            float(self.params["capture_probability"]),
            float(self.params["fail_probability"]),
            float(self.params["void_probability"]),
        ]
        for _ in range(int(self.params["n_transactions"])):
            customer = str(self.rng.choice(customer_ids))
            merchant = str(self.rng.choice(merchant_ids))
            amount = float(
                np.clip(
                    self.rng.lognormal(
                        float(self.params["amount_log_mean"]),
                        float(self.params["amount_log_sigma"]),
                    ),
                    float(self.params["amount_min"]),
                    float(self.params["amount_max"]),
                )
            )
            outcome = str(self.rng.choice(outcomes, p=probs))
            retries = int(self.rng.integers(1, 3)) if self.rng.random() < float(
                self.params["retry_probability"]
            ) else 0
            txn_id = self._new_transaction(
                customer, merchant, amount, self.home_currency[customer],
                self._random_time(), outcome, n_retries=retries,
            )
            if outcome == "captured" and self.rng.random() < float(
                self.params["refund_probability"]
            ):
                capture_time = self.txn_info[txn_id]["capture_time"]
                refund_time = capture_time + timedelta(
                    hours=int(self.rng.integers(1, 96))
                )
                full = self.rng.random() < float(self.params["full_refund_probability"])
                self._add_refund(
                    txn_id,
                    amount if full else amount * float(self.rng.uniform(0.15, 0.55)),
                    refund_time,
                )
                self._add_status(
                    txn_id, "refunded" if full else "partially_refunded", refund_time
                )

    # ----------------------------------------------------------------- injections
    def inject_duplicate_events(self, count: int = 30) -> None:
        candidates = list(range(len(self.events)))
        chosen = self.rng.choice(candidates, size=min(count, len(candidates)), replace=False)
        seen_txns: set[str] = set()
        for idx in chosen:
            original = dict(self.events[idx])
            txn = original["transaction_id"]
            self.events.append(original)  # exact duplicate: SAME event_id
            self.event_indices.setdefault(txn, []).append(idx)
            if txn not in seen_txns:
                seen_txns.add(txn)
                self.used_txns.add(txn)
                self._issue(
                    "duplicate_event", "transaction", txn, "DUPLICATE_EVENT", "medium",
                    "An event id was recorded more than once.", "transactions.csv",
                    event_id=original["event_id"], copies=2,
                )

    def inject_retry_storms(self, count: int = 20) -> None:
        candidates = [t for t in self._captured_txns() if t not in self.used_txns]
        for txn in self.rng.choice(candidates, size=min(count, len(candidates)), replace=False):
            info = self.txn_info[txn]
            auth_time = pd.Timestamp(self._event(self.event_indices[txn][0])["event_timestamp"])
            n_retries = int(self.rng.integers(6, 11))
            for i in range(n_retries):
                retry_time = auth_time + timedelta(seconds=2 * i + 1)
                self._add_event(
                    txn, info["customer_id"], info["merchant_id"], info["amount"],
                    info["currency"], retry_time, "retry", "authorized", info["device_id"],
                )
                self._add_status(txn, "authorized", retry_time)
            self.used_txns.add(txn)
            self._issue(
                "retry_storm", "transaction", txn, "RETRY_STORM", "high",
                "Many retry events were injected for one transaction.", "transactions.csv",
                retries=n_retries,
            )

    def inject_partial_refunds(self, count: int = 25) -> None:
        candidates = [
            t for t in self._captured_txns()
            if t not in self.used_txns and self.txn_info[t]["amount"] >= 100
            and not any(r["transaction_id"] == t for r in self.refunds_list)
        ]
        for j, txn in enumerate(self.rng.choice(candidates, size=min(count, len(candidates)), replace=False)):
            info = self.txn_info[txn]
            high = j < int(count * 0.6)
            total_fraction = float(self.rng.uniform(0.72, 0.92)) if high else float(
                self.rng.uniform(0.20, 0.55)
            )
            n_parts = int(self.rng.integers(2, 4))
            shares = self.rng.dirichlet(np.ones(n_parts))
            capture_time = info["capture_time"]
            amounts = [info["amount"] * total_fraction * s for s in shares]
            amounts[-1] = info["amount"] * total_fraction - sum(amounts[:-1])
            for i, amount in enumerate(amounts):
                self._add_refund(
                    txn, amount, capture_time + timedelta(hours=2 * (i + 1))
                )
            self._add_status(
                txn, "partially_refunded", capture_time + timedelta(hours=2 * n_parts)
            )
            self.used_txns.add(txn)
            self._issue(
                "partial_refund_high" if high else "partial_refund_benign",
                "transaction", txn, "HIGH_REFUND_RATIO" if high else "", "medium" if high else "low",
                "Several partial refunds were injected (high total ratio)" if high
                else "Several partial refunds were injected (ordinary total ratio).",
                "refunds.csv",
                refund_parts=n_parts, total_fraction=round(total_fraction, 3),
            )

    def inject_over_refunds(self, count: int = 12) -> None:
        candidates = [
            t for t in self._captured_txns()
            if t not in self.used_txns and 50 <= self.txn_info[t]["amount"] <= 1500
            and not any(r["transaction_id"] == t for r in self.refunds_list)
        ]
        for txn in self.rng.choice(candidates, size=min(count, len(candidates)), replace=False):
            info = self.txn_info[txn]
            total = info["amount"] * float(self.rng.uniform(1.08, 1.45))
            n_parts = int(self.rng.integers(2, 4))
            shares = self.rng.dirichlet(np.ones(n_parts))
            amounts = [total * s for s in shares]
            amounts[-1] = total - sum(amounts[:-1])
            for i, amount in enumerate(amounts):
                self._add_refund(
                    txn, amount, info["capture_time"] + timedelta(hours=3 * (i + 1))
                )
            self._add_status(txn, "refunded", info["capture_time"] + timedelta(days=1))
            self.used_txns.add(txn)
            self._issue(
                "over_refund", "transaction", txn, "OVER_REFUND", "high",
                "Refunds were injected that exceed the captured amount.", "refunds.csv",
                refund_total=round(total, 2), captured=info["amount"],
            )

    def inject_invalid_transitions(self, count: int = 10) -> None:
        candidates = [
            t for t in self._captured_txns() if t not in self.used_txns
        ]
        for txn in self.rng.choice(candidates, size=min(count, len(candidates)), replace=False):
            capture_time = self.txn_info[txn]["capture_time"]
            self._add_status(txn, "refunded", capture_time - timedelta(minutes=20))
            self._add_status(txn, "captured", capture_time + timedelta(seconds=1))
            # Also inject a refund row that predates capture (not just a status row).
            self._add_refund(
                txn, self.txn_info[txn]["amount"] * 0.3,
                capture_time - timedelta(minutes=15),
            )
            self.used_txns.add(txn)
            self._issue(
                "invalid_status_transition", "transaction", txn,
                "INVALID_STATUS_TRANSITION", "high",
                "A 'refunded' status was injected before 'captured'.", "payment_status.csv",
                illegal_transition="refunded -> captured",
            )

    def inject_nonpositive_amounts(self, count: int = 12) -> None:
        candidates = list(range(len(self.events)))
        chosen = self.rng.choice(candidates, size=min(count, len(candidates)), replace=False)
        seen: set[str] = set()
        for idx in chosen:
            bad_amount = float(-self.rng.uniform(5, 300)) if self.rng.random() < 0.7 else 0.0
            self.events[idx]["amount"] = bad_amount
            txn = self.events[idx]["transaction_id"]
            if txn not in seen:
                seen.add(txn)
                self.used_txns.add(txn)
                self._issue(
                    "nonpositive_amount", "transaction", txn, "INVALID_AMOUNT", "high",
                    "A non-positive event amount was injected.", "transactions.csv",
                    event_id=self.events[idx]["event_id"], amount=bad_amount,
                )

    def inject_future_timestamps(self, count: int = 10) -> None:
        candidates = [
            i for i, event in enumerate(self.events)
            if event["transaction_id"] not in self.used_txns
        ]
        chosen = self.rng.choice(candidates, size=min(count, len(candidates)), replace=False)
        seen: set[str] = set()
        future = self.now + timedelta(days=45)
        for idx in chosen:
            self.events[idx]["event_timestamp"] = to_iso(future)
            txn = self.events[idx]["transaction_id"]
            if txn not in seen:
                seen.add(txn)
                self.used_txns.add(txn)
                self._issue(
                    "future_timestamp", "transaction", txn, "FUTURE_TIMESTAMP", "high",
                    "A future event timestamp was injected.", "transactions.csv",
                    event_id=self.events[idx]["event_id"],
                )

    def inject_out_of_order_timestamps(self, count: int = 12) -> None:
        candidates = [
            t for t in self._captured_txns() if t not in self.used_txns
        ]
        for txn in self.rng.choice(candidates, size=min(count, len(candidates)), replace=False):
            indices = self.event_indices[txn]
            auth = next((i for i in indices if self.events[i]["event_type"] == "authorization"), None)
            capture = next((i for i in indices if self.events[i]["event_type"] == "capture"), None)
            if auth is None or capture is None:
                continue
            auth_time = pd.Timestamp(self.events[auth]["event_timestamp"])
            capture_time = pd.Timestamp(self.events[capture]["event_timestamp"])
            self.events[auth]["event_timestamp"] = to_iso(capture_time)
            self.events[capture]["event_timestamp"] = to_iso(auth_time - timedelta(seconds=30))
            self.used_txns.add(txn)
            self._issue(
                "out_of_order_timestamp", "transaction", txn, "OUT_OF_ORDER_TIMESTAMP",
                "medium", "Capture was injected before authorization.", "transactions.csv",
            )

    def inject_orphan_references(self) -> None:
        candidates = [t for t, _ in self.txn_info.items() if t not in self.used_txns]
        chosen = self.rng.choice(candidates, size=10, replace=False)
        for txn, bad_field, bad_value in zip(
            chosen[:4], ["customer_id"] * 4, ["CUST-UNKNOWN"] * 4
        ):
            for idx in self.event_indices[txn]:
                self.events[idx][bad_field] = bad_value
            self.txn_info[txn][bad_field] = bad_value
            self.used_txns.add(txn)
            self._issue(
                "orphan_customer", "transaction", txn, "ORPHAN_REFERENCE", "high",
                "An unknown customer id was injected.", "transactions.csv", value=bad_value,
            )
        for txn in chosen[4:7]:
            for idx in self.event_indices[txn]:
                self.events[idx]["merchant_id"] = "MER-UNKNOWN"
            self.txn_info[txn]["merchant_id"] = "MER-UNKNOWN"
            self.used_txns.add(txn)
            self._issue(
                "orphan_merchant", "transaction", txn, "ORPHAN_REFERENCE", "high",
                "An unknown merchant id was injected.", "transactions.csv",
                value="MER-UNKNOWN",
            )
        for txn in chosen[7:9]:
            for idx in self.event_indices[txn]:
                self.events[idx]["device_id"] = "DEV-UNKNOWN"
            self.txn_info[txn]["device_id"] = "DEV-UNKNOWN"
            self.used_txns.add(txn)
            self._issue(
                "orphan_device", "transaction", txn, "ORPHAN_REFERENCE", "medium",
                "An unknown device id was injected.", "transactions.csv",
                value="DEV-UNKNOWN",
            )

        # Orphan refund and orphan payment-status references get their own ids so
        # the review queue can expose them as separate transaction records.
        orphan_refund_txn = "TXN-ORPHAN-REFUND"
        self._add_refund(orphan_refund_txn, 75.0, self._random_time())
        self._issue(
            "orphan_refund_reference", "transaction", orphan_refund_txn,
            "ORPHAN_REFERENCE", "high",
            "A refund references a transaction id that does not exist.", "refunds.csv",
        )
        self._add_refund("TXN-UNKNOWN", 40.0, self._random_time())
        self._issue(
            "orphan_refund_reference", "transaction", "TXN-UNKNOWN",
            "ORPHAN_REFERENCE", "high",
            "A refund references a generic unknown transaction id.", "refunds.csv",
        )
        orphan_status_txn = "TXN-ORPHAN-STATUS"
        self._add_status(orphan_status_txn, "captured", self._random_time())
        self._issue(
            "orphan_status_reference", "transaction", orphan_status_txn,
            "ORPHAN_REFERENCE", "high",
            "A payment-status row references a transaction id that does not exist.",
            "payment_status.csv",
        )

    def inject_bursts(self, count: int = 10) -> None:
        candidates = [
            c for c in self.customers["customer_id"]
            if not any(self.txn_info[t]["customer_id"] == c for t in self.used_txns)
        ]
        customers = self.rng.choice(candidates, size=min(count, len(candidates)), replace=False)
        for customer in customers:
            start_time = self._random_time()
            n = int(self.rng.integers(11, 17))
            for i in range(n):
                self._new_transaction(
                    str(customer),
                    str(self.rng.choice(self.merchants["merchant_id"])),
                    float(self.rng.uniform(15, 400)),
                    self.home_currency[str(customer)],
                    start_time + timedelta(minutes=int(i * 1.5)),
                )
            self._issue(
                "transaction_burst", "customer", str(customer), "BURST_ACTIVITY", "high",
                "A burst of transactions within one hour was injected.", "transactions.csv",
                transactions=n, window_minutes=25,
            )

    def inject_repeated_failures(self, count: int = 12) -> None:
        candidates = [
            c for c in self.customers["customer_id"]
            if not any(self.txn_info[t]["customer_id"] == c for t in self.used_txns)
        ]
        customers = self.rng.choice(candidates, size=min(count, len(candidates)), replace=False)
        for customer in customers:
            start_time = self._random_time()
            n = int(self.rng.integers(7, 11))
            for i in range(n):
                self._new_transaction(
                    str(customer),
                    str(self.rng.choice(self.merchants["merchant_id"])),
                    float(self.rng.uniform(20, 600)),
                    self.home_currency[str(customer)],
                    start_time + timedelta(minutes=4 * i),
                    outcome="failed",
                )
            self._issue(
                "repeated_failed_attempts", "customer", str(customer),
                "REPEATED_FAILED_ATTEMPTS", "high",
                "Several consecutive failed attempts were injected.", "transactions.csv",
                failures=n,
            )

    def inject_shared_devices(self, count: int = 8) -> None:
        candidates = [d for d in self.devices if d != "DEV-UNKNOWN"]
        devices = self.rng.choice(candidates, size=min(count, len(candidates)), replace=False)
        customer_ids = self.customers["customer_id"].tolist()
        for device in devices:
            n = int(self.rng.integers(6, 11))
            new_customers = set(self.rng.choice(customer_ids, size=n, replace=False))
            for idx, event in enumerate(self.events):
                if event["customer_id"] in new_customers and self.rng.random() < 0.7:
                    self.events[idx]["device_id"] = str(device)
            for txn, info in self.txn_info.items():
                if info["customer_id"] in new_customers and self.rng.random() < 0.7:
                    info["device_id"] = str(device)
            self._issue(
                "shared_device", "device", str(device), "SHARED_DEVICE", "high",
                "A device was injected as being shared by many customers.",
                "device_summary.csv", claimed_customers=n,
            )

    def inject_round_amounts(self, count: int = 12) -> None:
        candidates = [
            c for c in self.customers["customer_id"]
            if not any(self.txn_info[t]["customer_id"] == c for t in self.used_txns)
            and not any(self.txn_info[t]["customer_id"] == c for t in self.txn_info
                        if self.txn_info[t].get("capture_time") and
                        any(r["transaction_id"] == t for r in self.refunds_list))
        ]
        customers = self.rng.choice(candidates, size=min(count, len(candidates)), replace=False)
        for customer in customers:
            own = [
                t for t, info in self.txn_info.items()
                if info["customer_id"] == customer and info.get("capture_time")
                and not any(r["transaction_id"] == t for r in self.refunds_list)
            ]
            n = int(self.rng.integers(9, 13))
            chosen = self.rng.choice(own, size=min(n, len(own)), replace=False)
            for txn in chosen:
                round_amount = float(self.rng.choice([500.0, 1000.0, 2000.0]))
                for idx in self.event_indices[txn]:
                    self.events[idx]["amount"] = round_amount
                self.txn_info[txn]["amount"] = round_amount
            self._issue(
                "round_amount_pattern", "customer", str(customer),
                "ROUND_AMOUNT_PATTERN", "low",
                "Several round-value amounts were injected for one customer.",
                "transactions.csv", round_amounts=len(chosen),
            )

    def inject_fast_refunds(self, count: int = 12) -> None:
        candidates = [
            t for t in self._captured_txns()
            if t not in self.used_txns
            and not any(r["transaction_id"] == t for r in self.refunds_list)
        ]
        for txn in self.rng.choice(candidates, size=min(count, len(candidates)), replace=False):
            info = self.txn_info[txn]
            refund_time = info["capture_time"] + timedelta(
                minutes=int(self.rng.integers(1, 6))
            )
            self._add_refund(txn, info["amount"] * float(self.rng.uniform(0.15, 0.55)), refund_time)
            self._add_status(txn, "partially_refunded", refund_time)
            self.used_txns.add(txn)
            self._issue(
                "fast_refund", "transaction", txn, "FAST_REFUND", "medium",
                "A refund was injected within minutes of capture.", "refunds.csv",
            )

    def inject_currency_mismatch(self, count: int = 8) -> None:
        currencies = [c for c in require_path(self.config, "data.generation.currencies")]
        candidates = [
            i for i, event in enumerate(self.events)
            if event["transaction_id"] not in self.used_txns
            and event["event_type"] == "capture"
        ]
        chosen = self.rng.choice(candidates, size=min(count, len(candidates)), replace=False)
        seen: set[str] = set()
        for idx in chosen:
            event = self.events[idx]
            alternatives = [c for c in currencies if c != event["currency"]]
            event["currency"] = str(self.rng.choice(alternatives))
            txn = event["transaction_id"]
            if txn not in seen:
                seen.add(txn)
                self.used_txns.add(txn)
                self._issue(
                    "currency_mismatch", "transaction", txn, "CURRENCY_MISMATCH", "high",
                    "One event's currency was changed to disagree with its transaction.",
                    "transactions.csv", event_id=event["event_id"],
                )

    # ------------------------------------------------------------------- outputs
    def _build_device_summary(self) -> pd.DataFrame:
        events = pd.DataFrame(self.events)
        # Orphan device ids must stay absent from the reference table so that
        # referential-integrity validation can detect them.
        events = events[events["device_id"].isin(self.devices)]
        events["ts"] = pd.to_datetime(events["event_timestamp"], errors="coerce")
        customer_map = events.groupby("device_id")["customer_id"].nunique()
        grouped = events.groupby("device_id").agg(
            first_seen=("ts", "min"),
            last_seen=("ts", "max"),
            failed_attempt_count=("status", lambda s: int((s == "failed").sum())),
        ).reset_index()
        grouped["customer_count"] = grouped["device_id"].map(customer_map).fillna(0).astype(int)
        grouped["first_seen"] = grouped["first_seen"].apply(to_iso)
        grouped["last_seen"] = grouped["last_seen"].apply(to_iso)
        return grouped[[
            "device_id", "customer_count", "first_seen", "last_seen", "failed_attempt_count"
        ]].sort_values("device_id").reset_index(drop=True)

    def generate(self) -> GeneratedData:
        """Generate all tables, inject issues and write CSV files."""
        self._build_dimensions()
        self._build_base_activity()
        self.inject_duplicate_events()
        self.inject_retry_storms()
        self.inject_partial_refunds()
        self.inject_over_refunds()
        self.inject_invalid_transitions()
        self.inject_nonpositive_amounts()
        self.inject_future_timestamps()
        self.inject_out_of_order_timestamps()
        self.inject_orphan_references()
        self.inject_bursts()
        self.inject_repeated_failures()
        self.inject_shared_devices()
        self.inject_round_amounts()
        self.inject_fast_refunds()
        self.inject_currency_mismatch()

        transactions = pd.DataFrame(self.events, columns=EVENT_COLUMNS)
        refunds = pd.DataFrame(self.refunds_list, columns=REFUND_COLUMNS)
        status = pd.DataFrame(self.status_history, columns=STATUS_COLUMNS)
        devices = self._build_device_summary()
        gt = pd.DataFrame(self.ground_truth_rows, columns=GT_COLUMNS)

        paths = {
            "customers": write_csv(self.customers, data_file(self.config, "customers")),
            "merchants": write_csv(self.merchants, data_file(self.config, "merchants")),
            "transactions": write_csv(transactions, data_file(self.config, "transactions")),
            "refunds": write_csv(refunds, data_file(self.config, "refunds")),
            "payment_status": write_csv(status, data_file(self.config, "payment_status")),
            "device_summary": write_csv(devices, data_file(self.config, "device_summary")),
            "ground_truth": write_csv(gt, ground_truth_file(self.config)),
        }
        return GeneratedData(
            customers=self.customers,
            merchants=self.merchants,
            transactions=transactions,
            refunds=refunds,
            payment_status=status,
            device_summary=devices,
            ground_truth=gt,
            paths=paths,
        )


def generate_data(config: dict[str, Any] | None = None, seed: int | None = None) -> GeneratedData:
    """Convenience wrapper that generates and persists one dataset."""
    return DataGenerator(config or load_config(), seed=seed).generate()


def main() -> None:
    """CLI entry point for ``python -m src.generate_data``."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=None, help="Override the configured seed")
    parser.add_argument("--config", type=str, default=None, help="Path to config.yaml")
    args = parser.parse_args()
    result = generate_data(load_config(args.config), seed=args.seed)
    print(f"Generated {len(result.transactions)} transaction events across "
          f"{result.transactions['transaction_id'].nunique()} transactions.")
    print(f"Injected {len(result.ground_truth)} issues (hidden answer key).")
    for name, path in result.paths.items():
        print(f"  {name}: {path}")


if __name__ == "__main__":
    main()
