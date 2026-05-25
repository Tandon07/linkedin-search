"""
main.py
-------
Main orchestrator for the LinkedIn Job Application Automator.

Workflow:
  1. [Every SCAN_INTERVAL_HOURS] Scrape LinkedIn feed → AI classify → send approval emails
  2. [Every 15 min]              Poll inbox for "ok" replies → send application emails

Run:  python main.py
"""

import logging
import os
import sys
import time
import json
from pathlib import Path

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger
from dotenv import load_dotenv

from linkedin_scraper import scrape_linkedin_feed
from ai_classifier import classify_post
from email_handler import send_approval_request, poll_for_approvals, send_job_application, send_manual_apply_notification
from state_tracker import StateTracker

# ── Logging setup ─────────────────────────────────────────────────────────────
os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("logs/automator.log"),
    ],
)
logger = logging.getLogger(__name__)

# ── Load env ──────────────────────────────────────────────────────────────────
load_dotenv()

LINKEDIN_EMAIL              = os.getenv("LINKEDIN_EMAIL", "")
LINKEDIN_PASSWORD           = os.getenv("LINKEDIN_PASSWORD", "")
GROQ_API_KEY                = os.getenv("GROQ_API_KEY", "")
APPROVAL_SENDER_EMAIL       = os.getenv("APPROVAL_SENDER_EMAIL", "")
APPROVAL_SENDER_PASSWORD    = os.getenv("APPROVAL_SENDER_PASSWORD", "")
APPROVAL_RECEIVER_EMAIL     = os.getenv("APPROVAL_RECEIVER_EMAIL", "")
APPLICATION_SENDER_EMAIL    = os.getenv("APPLICATION_SENDER_EMAIL", "")
APPLICATION_SENDER_PASSWORD = os.getenv("APPLICATION_SENDER_PASSWORD", "")
RESUME_PDF_PATH             = Path(os.getenv("RESUME_PDF_PATH", "resume/Saurabh_Tandon_Resume.pdf"))
SCAN_INTERVAL_HOURS         = int(os.getenv("SCAN_INTERVAL_HOURS", "3"))
MAX_POSTS_TO_SCAN           = int(os.getenv("MAX_POSTS_TO_SCAN", "5"))
HEADLESS                    = os.getenv("HEADLESS", "True").lower() in ("true", "1", "yes")

# ── State tracker (shared across jobs) ───────────────────────────────────────
tracker = StateTracker(Path("data/state.json"))


def _validate_env():
    required = {
        "LINKEDIN_EMAIL": LINKEDIN_EMAIL,
        "LINKEDIN_PASSWORD": LINKEDIN_PASSWORD,
        "GROQ_API_KEY": GROQ_API_KEY,
        "APPROVAL_SENDER_EMAIL": APPROVAL_SENDER_EMAIL,
        "APPROVAL_SENDER_PASSWORD": APPROVAL_SENDER_PASSWORD,
        "APPROVAL_RECEIVER_EMAIL": APPROVAL_RECEIVER_EMAIL,
        "APPLICATION_SENDER_EMAIL": APPLICATION_SENDER_EMAIL,
        "APPLICATION_SENDER_PASSWORD": APPLICATION_SENDER_PASSWORD,
    }
    missing = [k for k, v in required.items() if not v]
    if missing:
        logger.error(f"Missing required environment variables: {missing}")
        logger.error("Please fill in your .env file. See .env.example for reference.")
        sys.exit(1)

    if not RESUME_PDF_PATH.exists():
        logger.warning(
            f"Resume PDF not found at: {RESUME_PDF_PATH}\n"
            "Applications will be sent without attachment. "
            "Place your PDF at that path to include it."
        )


def cleanup_old_data_files(data_dir: Path = Path("data"), max_age_days: int = 4):
    """
    Delete JSON files in the data folder that are older than max_age_days.
    Only targets files starting with 'fetched_posts_' and 'classified_posts_'.
    """
    logger.info(f"[CLEANUP] Checking for data files older than {max_age_days} days in '{data_dir}'...")
    if not data_dir.exists():
        return

    now = time.time()
    cutoff_sec = max_age_days * 24 * 60 * 60
    deleted_count = 0

    from datetime import datetime

    for file_path in data_dir.glob("*.json"):
        # We only delete timestamped fetched/classified posts
        if not (file_path.name.startswith("fetched_posts_") or file_path.name.startswith("classified_posts_")):
            continue
        # Skip standard backup and active files
        if file_path.name in ("fetched_posts_backup.json", "fetched_posts.json"):
            continue

        try:
            # Check 1: File modification time
            mtime = file_path.stat().st_mtime
            age_sec = now - mtime
            
            # Check 2: Parse date from filename: fetched_posts_YYYYMMDD_HHMMSS.json
            parts = file_path.stem.split("_")
            is_old = False
            if len(parts) >= 3:
                date_str = parts[-2]  # YYYYMMDD
                if len(date_str) == 8 and date_str.isdigit():
                    file_date = datetime.strptime(date_str, "%Y%m%d")
                    days_diff = (datetime.now() - file_date).days
                    if days_diff > max_age_days:
                        is_old = True

            if age_sec > cutoff_sec or is_old:
                file_path.unlink()
                logger.info(f"[CLEANUP] Deleted old data file: {file_path.name}")
                deleted_count += 1
        except Exception as e:
            logger.error(f"[CLEANUP] Failed to check/delete file {file_path.name}: {e}")

    logger.info(f"[CLEANUP] Cleanup complete. Deleted {deleted_count} file(s).")


# ─────────────────────────────────────────────────────────────────────────────
# JOB 1: Scrape LinkedIn + classify + send approval emails
# ─────────────────────────────────────────────────────────────────────────────

def run_linkedin_scan():
    logger.info("=" * 60)
    logger.info("--- Starting LinkedIn feed scan ---")
    logger.info("=" * 60)

    posts = scrape_linkedin_feed(
        email=LINKEDIN_EMAIL,
        password=LINKEDIN_PASSWORD,
        max_posts=MAX_POSTS_TO_SCAN,
        headless=HEADLESS,
    )

    if not posts:
        logger.info("No posts with emails found this scan.")
        tracker.update_last_scan()
        return

    # Save fetched posts to local JSON with timestamp
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    fetched_posts_path = Path(f"data/fetched_posts_{timestamp}.json")
    fetched_posts_path.parent.mkdir(parents=True, exist_ok=True)
    with open(fetched_posts_path, "w", encoding="utf-8") as f:
        json.dump([vars(p) for p in posts], f, indent=4, ensure_ascii=False)
    logger.info(f"Saved {len(posts)} raw fetched posts to {fetched_posts_path}")

    new_count = 0
    relevant_count = 0
    classified_jobs = []

    for post in posts:
        post_id = post.post_id

        # Skip already processed posts
        if tracker.is_seen(post_id) or tracker.is_pending(post_id) or tracker.has_applied(post_id):
            continue

        tracker.mark_seen(post_id)
        new_count += 1

        safe_text = post.post_text[:80].encode('ascii', 'ignore').decode('ascii')
        logger.info(f"Classifying post by {post.author_name}: {safe_text}...")
        result = classify_post(post.post_text, GROQ_API_KEY)

        if not result.is_relevant:
            logger.info(f"  [X] Not relevant: {result.reason}")
            continue

        # Use email from classifier (more accurate) or fall back to scraper
        recruiter_email = result.recruiter_email or post.recruiter_email
        apply_links = result.apply_links

        if not recruiter_email and not apply_links:
            logger.info("  [X] No recruiter email or apply links found, skipping.")
            continue

        relevant_count += 1
        
        job_data = {
            "post_id": post_id,
            "role_title": result.role_title,
            "company_name": result.company_name,
            "location": result.location,
            "experience_required": result.experience_required,
            "recruiter_name": result.recruiter_name or post.author_name,
            "recruiter_email": recruiter_email,
            "key_skills": result.key_skills,
            "apply_links": apply_links,
            "post_url": post.post_url,
        }
        classified_jobs.append(job_data)

        if recruiter_email:
            logger.info(f"  [OK] RELEVANT (Auto Apply): {result.role_title} @ {result.company_name} -> {recruiter_email}")
            msg_id = send_approval_request(
                approval_sender_email=APPROVAL_SENDER_EMAIL,
                approval_sender_password=APPROVAL_SENDER_PASSWORD,
                approval_receiver_email=APPROVAL_RECEIVER_EMAIL,
                job_data=job_data,
            )
            if msg_id:
                job_data["message_id"] = msg_id
                tracker.add_pending_approval(post_id, job_data)
            else:
                logger.error(f"Failed to send approval email for {result.role_title}")
        elif apply_links:
            logger.info(f"  [OK] RELEVANT (Manual Apply): {result.role_title} @ {result.company_name} -> {apply_links[0]}")
            sent = send_manual_apply_notification(
                approval_sender_email=APPROVAL_SENDER_EMAIL,
                approval_sender_password=APPROVAL_SENDER_PASSWORD,
                approval_receiver_email=APPROVAL_RECEIVER_EMAIL,
                job_data=job_data,
            )
            if sent:
                # Mark as seen but don't add to pending since it's manual
                pass
            else:
                logger.error(f"Failed to send manual apply notification for {result.role_title}")

    # Save classified jobs to local JSON with timestamp
    if classified_jobs:
        classified_path = Path(f"data/classified_posts_{timestamp}.json")
        with open(classified_path, "w", encoding="utf-8") as f:
            json.dump(classified_jobs, f, indent=4, ensure_ascii=False)
        logger.info(f"Saved {len(classified_jobs)} newly classified relevant posts to {classified_path}")

    logger.info(
        f"Scan complete. New posts: {new_count}, Relevant: {relevant_count}"
    )

    try:
        cleanup_old_data_files()
    except Exception as e:
        logger.error(f"Error during data cleanup: {e}")

    tracker.update_last_scan()
    tracker.print_stats()


# ─────────────────────────────────────────────────────────────────────────────
# JOB 2: Poll for "ok" replies → send applications
# ─────────────────────────────────────────────────────────────────────────────

def run_approval_poller():
    logger.info("[POLL] Polling inbox for approval replies...")

    pending = tracker.get_pending_approvals()
    if not pending:
        logger.info("No pending approvals to check.")
        return

    pending_ids = set(pending.keys())

    # Create a map of message_id -> job_data for the poller
    pending_jobs_map = {pending[pid].get("message_id"): pending[pid] for pid in pending if pending[pid].get("message_id")}

    approved_jobs = poll_for_approvals(
        approval_receiver_email=APPROVAL_SENDER_EMAIL,
        approval_receiver_password=APPROVAL_SENDER_PASSWORD,
        pending_jobs=pending_jobs_map,
    )

    if not approved_jobs:
        logger.info("No approvals found this poll.")
        return

    for job_meta in approved_jobs:
        post_id = job_meta.get("post_id", "")
        role = job_meta.get("role_title", "Unknown Role")
        company = job_meta.get("company_name", "")
        recruiter_name = job_meta.get("recruiter_name", "Hiring Manager")
        recruiter_email = job_meta.get("recruiter_email", "")

        if not recruiter_email:
            logger.error(f"No recruiter email in approved job meta: {job_meta}")
            continue

        if tracker.has_applied(post_id):
            logger.info(f"Already applied to {role} @ {company}, skipping.")
            continue

        logger.info(f"[SENDING] Application: {role} @ {company} -> {recruiter_email}")

        success = send_job_application(
            app_sender_email=APPLICATION_SENDER_EMAIL,
            app_sender_password=APPLICATION_SENDER_PASSWORD,
            recruiter_email=recruiter_email,
            role_title=role,
            recruiter_name=recruiter_name,
            resume_pdf_path=RESUME_PDF_PATH,
        )

        if success:
            tracker.mark_applied(post_id, role, company, recruiter_email)
            logger.info(f"  [SUCCESS] Application sent successfully!")
        else:
            logger.error(f"  [ERROR] Failed to send application for {role}")

    tracker.print_stats()


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

def main():
    _validate_env()

    Path("logs").mkdir(exist_ok=True)
    Path("data").mkdir(exist_ok=True)

    logger.info("--- LinkedIn Job Application Automator starting ---")
    logger.info(f"   Scan interval  : every {SCAN_INTERVAL_HOURS} hour(s)")
    logger.info(f"   Approval poll  : every 15 minutes")
    logger.info(f"   Resume         : {RESUME_PDF_PATH}")
    tracker.print_stats()

    # Run once immediately on startup
    run_linkedin_scan()
    run_approval_poller()

    # Then schedule
    scheduler = BlockingScheduler(timezone="Asia/Kolkata")

    # We add a jitter of 1800 seconds (30 mins).
    # If SCAN_INTERVAL_HOURS is 2, it will run between 1.5 and 2.5 hours.
    scheduler.add_job(
        run_linkedin_scan,
        trigger=IntervalTrigger(hours=SCAN_INTERVAL_HOURS, jitter=1800),
        id="linkedin_scan",
        name="LinkedIn Feed Scanner",
        max_instances=1,
        coalesce=True,
    )

    scheduler.add_job(
        run_approval_poller,
        trigger=IntervalTrigger(minutes=15),
        id="approval_poller",
        name="Approval Reply Poller",
        max_instances=1,
        coalesce=True,
    )

    logger.info("[WAITING] Scheduler started. Press Ctrl+C to stop.")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Automator stopped by user.")


if __name__ == "__main__":
    main()
