"""
state_tracker.py
----------------
Lightweight JSON-based persistence to track:
  - Which LinkedIn posts have already been processed
  - Which jobs are pending approval (sent to Saurabh, awaiting "ok")
  - Which jobs have already had applications sent
"""

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_STATE_FILE = Path("data/state.json")


def _load_state(state_file: Path) -> dict:
    if state_file.exists():
        try:
            with open(state_file, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"Failed to load state file: {e}. Starting fresh.")
    return {
        "seen_post_ids": [],          # All post IDs we've looked at
        "pending_approvals": {},      # post_id -> job_data (waiting for "ok")
        "applied_jobs": {},           # post_id -> {role, company, recruiter_email, applied_at}
        "skipped_jobs": [],           # post_ids we won't apply to
        "last_scan_time": None,
    }


def _save_state(state: dict, state_file: Path) -> None:
    state_file.parent.mkdir(parents=True, exist_ok=True)
    with open(state_file, "w") as f:
        json.dump(state, f, indent=2, default=str)


class StateTracker:
    def __init__(self, state_file: Path = DEFAULT_STATE_FILE):
        self.state_file = state_file
        self.state = _load_state(state_file)

    def _save(self):
        _save_state(self.state, self.state_file)

    # ── Seen posts ────────────────────────────────────────────────────────────

    def is_seen(self, post_id: str) -> bool:
        return post_id in self.state["seen_post_ids"]

    def mark_seen(self, post_id: str) -> None:
        if post_id not in self.state["seen_post_ids"]:
            self.state["seen_post_ids"].append(post_id)
            self._save()

    # ── Pending approvals ─────────────────────────────────────────────────────

    def add_pending_approval(self, post_id: str, job_data: dict) -> None:
        self.state["pending_approvals"][post_id] = {
            **job_data,
            "approval_sent_at": datetime.now(timezone.utc).isoformat(),
        }
        self._save()
        logger.info(f"Added pending approval: {post_id}")

    def get_pending_approvals(self) -> dict:
        return self.state["pending_approvals"]

    def remove_pending_approval(self, post_id: str) -> None:
        if post_id in self.state["pending_approvals"]:
            del self.state["pending_approvals"][post_id]
            self._save()

    def is_pending(self, post_id: str) -> bool:
        return post_id in self.state["pending_approvals"]

    # ── Applied jobs ──────────────────────────────────────────────────────────

    def mark_applied(self, post_id: str, role: str, company: str, recruiter_email: str) -> None:
        self.state["applied_jobs"][post_id] = {
            "role": role,
            "company": company,
            "recruiter_email": recruiter_email,
            "applied_at": datetime.now(timezone.utc).isoformat(),
        }
        self.remove_pending_approval(post_id)
        self._save()
        logger.info(f"Marked as applied: {role} @ {company} -> {recruiter_email}")

    def has_applied(self, post_id: str) -> bool:
        return post_id in self.state["applied_jobs"]

    def get_applied_count(self) -> int:
        return len(self.state["applied_jobs"])

    # ── Skipped jobs ──────────────────────────────────────────────────────────

    def mark_skipped(self, post_id: str) -> None:
        if post_id not in self.state["skipped_jobs"]:
            self.state["skipped_jobs"].append(post_id)
        self.remove_pending_approval(post_id)
        self._save()

    def is_skipped(self, post_id: str) -> bool:
        return post_id in self.state["skipped_jobs"]

    # ── Scan time ─────────────────────────────────────────────────────────────

    def update_last_scan(self) -> None:
        self.state["last_scan_time"] = datetime.now(timezone.utc).isoformat()
        self._save()

    def get_last_scan_time(self) -> Optional[str]:
        return self.state.get("last_scan_time")

    # ── Stats ─────────────────────────────────────────────────────────────────

    def get_stats(self) -> dict:
        return {
            "total_posts_seen": len(self.state["seen_post_ids"]),
            "pending_approvals": len(self.state["pending_approvals"]),
            "total_applied": len(self.state["applied_jobs"]),
            "total_skipped": len(self.state["skipped_jobs"]),
            "last_scan": self.state.get("last_scan_time"),
        }

    def print_stats(self) -> None:
        stats = self.get_stats()
        print("\n📊 LinkedIn Automator Stats")
        print(f"   Posts scanned  : {stats['total_posts_seen']}")
        print(f"   Pending review : {stats['pending_approvals']}")
        print(f"   Applications   : {stats['total_applied']}")
        print(f"   Skipped        : {stats['total_skipped']}")
        print(f"   Last scan      : {stats['last_scan'] or 'Never'}\n")
