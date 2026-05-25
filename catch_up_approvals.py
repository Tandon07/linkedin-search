
import sys
import os
import logging
import email
import imaplib
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from dotenv import load_dotenv

# Add current directory to path so we can import our modules
sys.path.append(os.getcwd())

from email_handler import (
    poll_for_approvals, 
    send_job_application, 
    GMAIL_IMAP, 
    GMAIL_SMTP,
    _decode_header_value
)
from main import (
    APPROVAL_SENDER_EMAIL, 
    APPROVAL_SENDER_PASSWORD,
    APPLICATION_SENDER_EMAIL,
    APPLICATION_SENDER_PASSWORD,
    RESUME_PDF_PATH,
    tracker
)

# Set up logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("catch_up_poller")

def run_catch_up(after_time_str="2026-05-13 16:00:00"):
    """
    Polls for 'ok' replies sent AFTER a specific time (in local IST).
    """
    # Parse the target time (assumed IST +05:30)
    target_dt = datetime.strptime(after_time_str, "%Y-%m-%d %H:%M:%S")
    target_dt = target_dt.replace(tzinfo=timezone(timedelta(hours=5, minutes=30)))
    
    logger.info(f"Checking for approvals sent after: {target_dt}")

    pending = tracker.get_pending_approvals()
    if not pending:
        logger.info("No pending approvals in state.json")
        return

    pending_jobs_map = {pending[pid].get("message_id"): pending[pid] for pid in pending if pending[pid].get("message_id")}
    
    approved_jobs = []
    
    mail = None
    try:
        mail = imaplib.IMAP4_SSL(GMAIL_IMAP, timeout=30)
        mail.login(APPROVAL_SENDER_EMAIL, APPROVAL_SENDER_PASSWORD)
        mail.select("inbox")

        # Search for ALL messages so we don't miss ones you already opened
        _, msg_nums = mail.search(None, 'ALL')
        msg_list = msg_nums[0].split()
        msg_list.reverse()
        
        # Limit to 200 messages to be sure we find today's emails
        msg_list = msg_list[:200]

        for num in msg_list:
            _, data = mail.fetch(num, "(RFC822)")
            if not data or not data[0]:
                continue
            raw = data[0][1]
            msg = email.message_from_bytes(raw)

            # Check the date
            date_str = msg.get("Date")
            try:
                msg_dt = email.utils.parsedate_to_datetime(date_str)
            except:
                continue
            
            # Ensure msg_dt is aware
            if msg_dt.tzinfo is None:
                msg_dt = msg_dt.replace(tzinfo=timezone.utc)

            if msg_dt < target_dt:
                logger.info(f"Skipping old email from {msg_dt}")
                continue

            subject = _decode_header_value(msg.get("Subject", ""))
            logger.info(f"Found email from today: '{subject}' ({msg_dt})")
            
            if "[JOB APPROVAL NEEDED]" not in subject.upper():
                logger.info(f"  -> Skipping: Subject doesn't contain [JOB APPROVAL NEEDED]")
                continue

            # Standard matching logic from email_handler
            # (Re-implementing a simplified version here for the filter)
            body = ""
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == "text/plain":
                        body += part.get_payload(decode=True).decode("utf-8", errors="replace")
            else:
                body = msg.get_payload(decode=True).decode("utf-8", errors="replace")

            if not re.search(r'\b(ok|okay|yes|approve|send)\b', body.lower()):
                continue

            # Identify job
            job_data = None
            in_reply_to = msg.get("In-Reply-To", "").strip().strip("<>")
            
            if in_reply_to:
                for mid in pending_jobs_map:
                    if in_reply_to in mid or mid in in_reply_to:
                        job_data = pending_jobs_map[mid]
                        break
            
            if not job_data:
                id_match = re.search(r"\[ID:(.*?)\]", subject)
                if id_match:
                    target_id = id_match.group(1)
                    for mid in pending_jobs_map:
                        if pending_jobs_map[mid].get("post_id") == target_id:
                            job_data = pending_jobs_map[mid]
                            break

            if job_data:
                logger.info(f"Found approval for: {job_data.get('role_title')}")
                approved_jobs.append(job_data)
                mail.store(num, "+FLAGS", "\\Seen")

    except Exception as e:
        logger.error(f"Error: {e}")
    finally:
        if mail:
            mail.logout()

    if not approved_jobs:
        logger.info("No approvals found after 4 PM.")
        return

    # Now apply
    for job_meta in approved_jobs:
        post_id = job_meta.get("post_id", "")
        role = job_meta.get("role_title")
        company = job_meta.get("company_name")
        recruiter_email = job_meta.get("recruiter_email")

        if tracker.has_applied(post_id):
            continue

        logger.info(f"[SENDING] Application: {role} @ {company} -> {recruiter_email}")
        success = send_job_application(
            app_sender_email=APPLICATION_SENDER_EMAIL,
            app_sender_password=APPLICATION_SENDER_PASSWORD,
            recruiter_email=recruiter_email,
            role_title=role,
            recruiter_name=job_meta.get("recruiter_name", "Hiring Manager"),
            resume_pdf_path=RESUME_PDF_PATH
        )
        if success:
            tracker.mark_applied(post_id, role, company, recruiter_email)

if __name__ == "__main__":
    run_catch_up("2026-05-13 16:00:00")
