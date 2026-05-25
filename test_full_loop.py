"""
test_full_loop.py
-----------------
A debug script to test the entire approval -> application flow in one go.
1. Picks the latest job from classified_posts_*.json.
2. Sends you an approval email.
3. Polls your inbox every 10 seconds for an "ok" reply.
4. Once you reply, sends the final application to the recruiter.
"""

import time
import logging
import sys
from pathlib import Path
import json

from main import (
    APPROVAL_SENDER_EMAIL, APPROVAL_SENDER_PASSWORD, APPROVAL_RECEIVER_EMAIL,
    APPLICATION_SENDER_EMAIL, APPLICATION_SENDER_PASSWORD, RESUME_PDF_PATH,
    GROQ_API_KEY
)
from email_handler import send_approval_request, poll_for_approvals, send_job_application
from ai_classifier import classify_post

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

def test_loop():
    # 1. Get latest RAW fetched job
    data_dir = Path("data")
    files = list(data_dir.glob("fetched_posts_*.json"))
    if not files:
        logger.error("No fetched_posts_*.json files found. Run main.py once first.")
        return
    
    files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
    latest_file = files[0]
    with open(latest_file, "r", encoding="utf-8") as f:
        raw_posts = json.load(f)
    
    if not raw_posts:
        logger.error("Latest fetched file is empty.")
        return
    
    # Run the classifier on the first post
    raw_post = raw_posts[0]
    safe_text = raw_post['post_text'][:60].encode('ascii', 'ignore').decode('ascii')
    logger.info(f"Classifying raw post: {safe_text}...")
    
    result = classify_post(raw_post['post_text'], GROQ_API_KEY)
    
    if not result.is_relevant:
        logger.warning(f"AI rejected this post: {result.reason}")
        # Let's try to find the first relevant one instead
        found = False
        for p in raw_posts:
            result = classify_post(p['post_text'], GROQ_API_KEY)
            if result.is_relevant:
                raw_post = p
                found = True
                break
        if not found:
            logger.error("Could not find any relevant posts in the latest file to test with.")
            return

    job = {
        "post_id": raw_post["post_id"],
        "role_title": result.role_title,
        "company_name": result.company_name,
        "location": result.location,
        "experience_required": result.experience_required,
        "recruiter_name": result.recruiter_name or raw_post.get("author_name", "Hiring Manager"),
        "recruiter_email": result.recruiter_email or raw_post["recruiter_email"],
        "key_skills": result.key_skills,
        "post_url": raw_post["post_url"],
    }
    
    logger.info(f"AI Approved! Testing with: {job['role_title']} @ {job['company_name']}")

    # 2. Send approval request
    msg_id = send_approval_request(
        approval_sender_email=APPROVAL_SENDER_EMAIL,
        approval_sender_password=APPROVAL_SENDER_PASSWORD,
        approval_receiver_email=APPROVAL_RECEIVER_EMAIL,
        job_data=job
    )
    
    if not msg_id:
        logger.error("Failed to send approval request.")
        return

    logger.info("---------------------------------------------------------")
    logger.info("STEP 1 COMPLETE: Approval email sent to you.")
    logger.info("ACTION REQUIRED: Go to your inbox, reply 'ok' to that email.")
    logger.info("---------------------------------------------------------")

    # 3. Poll for reply
    logger.info("Waiting for your 'ok' reply (polling every 10s)...")
    approved_job_meta = None
    
    while not approved_job_meta:
        # We check the SENDER's inbox (where the reply lands)
        results = poll_for_approvals(
            approval_receiver_email=APPROVAL_SENDER_EMAIL,
            approval_receiver_password=APPROVAL_SENDER_PASSWORD,
            pending_jobs={msg_id: job}
        )
        
        if results:
            approved_job_meta = results[0]
            break
        
        time.sleep(10)

    logger.info("---------------------------------------------------------")
    logger.info("STEP 2 COMPLETE: Approval received!")
    logger.info("STEP 3: Sending final application to recruiter...")
    logger.info("---------------------------------------------------------")

    # 4. Send application to recruiter
    success = send_job_application(
        app_sender_email=APPLICATION_SENDER_EMAIL,
        app_sender_password=APPLICATION_SENDER_PASSWORD,
        recruiter_email=job["recruiter_email"],
        role_title=job["role_title"],
        recruiter_name=job["recruiter_name"],
        resume_pdf_path=RESUME_PDF_PATH
    )

    if success:
        logger.info("SUCCESS! The application email has been sent to the recruiter.")
    else:
        logger.error("FAILED to send the application email.")

if __name__ == "__main__":
    test_loop()
