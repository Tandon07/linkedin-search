"""
reprocess_saved.py
------------------
Reads the most recent 'fetched_posts_*.json' file and re-runs the AI classifier 
on any posts that weren't previously marked as pending approval.
"""

import json
import logging
import os
import sys
from pathlib import Path
from main import (
    LINKEDIN_EMAIL, LINKEDIN_PASSWORD, GROQ_API_KEY,
    APPROVAL_SENDER_EMAIL, APPROVAL_SENDER_PASSWORD, APPROVAL_RECEIVER_EMAIL,
    tracker
)
from ai_classifier import classify_post
from email_handler import send_approval_request

# Set up basic logging to console
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

def reprocess():
    data_dir = Path("data")
    if not data_dir.exists():
        logger.error("Data directory not found.")
        return

    # Find the most recent fetched_posts file
    files = list(data_dir.glob("fetched_posts_*.json"))
    if not files:
        logger.error("No fetched_posts_*.json files found.")
        return
    
    files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
    latest_file = files[0]
    logger.info(f"Reprocessing latest file: {latest_file}")

    with open(latest_file, "r", encoding="utf-8") as f:
        posts = json.load(f)

    relevant_count = 0
    for p_dict in posts:
        post_id = p_dict.get("post_id")
        author_name = p_dict.get("author_name", "Unknown Recruiter")
        post_text = p_dict.get("post_text", "")
        post_url = p_dict.get("post_url", "")
        recruiter_email = p_dict.get("recruiter_email", "")

        # Only process if not already pending or applied
        if tracker.is_pending(post_id) or tracker.has_applied(post_id):
            logger.info(f"Skipping {post_id} - already pending or applied.")
            continue

        logger.info(f"Classifying: {post_text[:80].encode('ascii', 'ignore').decode('ascii')}...")
        result = classify_post(post_text, GROQ_API_KEY)

        if not result.is_relevant:
            logger.info(f"  [X] Still not relevant: {result.reason}")
            continue

        # Found a match with new logic!
        final_email = result.recruiter_email or recruiter_email
        apply_links = result.apply_links

        if not final_email and not apply_links:
            logger.info("  [X] No email or apply links found, skipping.")
            continue

        relevant_count += 1

        job_data = {
            "post_id": post_id,
            "role_title": result.role_title,
            "company_name": result.company_name,
            "location": result.location,
            "experience_required": result.experience_required,
            "recruiter_name": result.recruiter_name or author_name,
            "recruiter_email": final_email,
            "key_skills": result.key_skills,
            "apply_links": apply_links,
            "post_url": post_url,
        }

        from email_handler import send_manual_apply_notification
        
        if final_email:
            logger.info(f"  [OK] RELEVANT (Auto Apply): {result.role_title} @ {result.company_name} -> {final_email}")
            msg_id = send_approval_request(
                approval_sender_email=APPROVAL_SENDER_EMAIL,
                approval_sender_password=APPROVAL_SENDER_PASSWORD,
                approval_receiver_email=APPROVAL_RECEIVER_EMAIL,
                job_data=job_data,
            )
            if msg_id:
                tracker.add_pending_approval(post_id, job_data)
                logger.info(f"  [SENT] Approval request sent for {result.role_title}")
            else:
                logger.error(f"  [ERR] Failed to send approval email for {result.role_title}")
        elif apply_links:
            logger.info(f"  [OK] RELEVANT (Manual Apply): {result.role_title} @ {result.company_name} -> {apply_links[0]}")
            sent = send_manual_apply_notification(
                approval_sender_email=APPROVAL_SENDER_EMAIL,
                approval_sender_password=APPROVAL_SENDER_PASSWORD,
                approval_receiver_email=APPROVAL_RECEIVER_EMAIL,
                job_data=job_data,
            )
            if sent:
                logger.info(f"  [SENT] Manual apply notification sent for {result.role_title}")
            else:
                logger.error(f"  [ERR] Failed to send manual apply notification for {result.role_title}")

    logger.info(f"Reprocessing complete. Found {relevant_count} new relevant jobs.")

if __name__ == "__main__":
    reprocess()
