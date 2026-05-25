"""
email_handler.py
----------------
Handles two types of email operations:

1. APPROVAL EMAIL  — sent from rahul.raj787807@gmail.com
                     to saurabhtandon787807@gmail.com
                     asking "ok to apply?" for each job match

2. REPLY POLLER   — checks saurabhtandon787807@gmail.com inbox
                     for "ok" replies to pending approval emails

3. APPLICATION    — sent from tandonsaurabh07@gmail.com
                     to the recruiter, with resume PDF attached
"""

import imaplib
import smtplib
import email
import json
import logging
import os
import re
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from email.header import decode_header
from datetime import datetime, timezone
from typing import Optional
from pathlib import Path

logger = logging.getLogger(__name__)

GMAIL_SMTP = ("smtp.gmail.com", 587)
GMAIL_IMAP = "imap.gmail.com"

# Subject prefix used to match approval threads
APPROVAL_SUBJECT_PREFIX = "[JOB APPROVAL NEEDED]"
APPROVAL_SUBJECT_REPLY_PREFIX = "re:"


# ─────────────────────────────────────────────────────────────────────────────
# SMTP helpers
# ─────────────────────────────────────────────────────────────────────────────

def _send_email(
    sender_email: str,
    sender_password: str,
    recipient: str,
    subject: str,
    html_body: str,
    text_body: str = "",
    attachments: Optional[list[Path]] = None,
    reply_to_message_id: Optional[str] = None,
) -> bool:
    """Generic SMTP send. Returns True on success."""
    if attachments:
        msg = MIMEMultipart("mixed")
        body_container = MIMEMultipart("alternative")
        msg.attach(body_container)
    else:
        msg = MIMEMultipart("alternative")
        body_container = msg

    msg["From"] = sender_email
    msg["To"] = recipient
    msg["Subject"] = subject
    msg["Date"] = email.utils.formatdate(localtime=True)
    msg_id = email.utils.make_msgid()
    msg["Message-ID"] = msg_id

    if reply_to_message_id:
        msg["In-Reply-To"] = reply_to_message_id
        msg["References"] = reply_to_message_id

    # Attach bodies to the alternative container
    if text_body:
        body_container.attach(MIMEText(text_body, "plain"))
    body_container.attach(MIMEText(html_body, "html"))

    # Attachments go to the main mixed container
    if attachments:
        for path in attachments:
            if not path.exists():
                logger.warning(f"Attachment not found: {path}")
                continue
            with open(path, "rb") as f:
                part = MIMEBase("application", "octet-stream")
                part.set_payload(f.read())
            encoders.encode_base64(part)
            part.add_header(
                "Content-Disposition",
                f"attachment; filename={path.name}",
            )
            msg.attach(part)

    try:
        with smtplib.SMTP(GMAIL_SMTP[0], GMAIL_SMTP[1], timeout=30) as server:
            server.ehlo()
            server.starttls()
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, recipient, msg.as_string())
        logger.info(f"Email sent to {recipient}: {subject}")
        return True
    except smtplib.SMTPAuthenticationError:
        logger.error(
            f"SMTP auth failed for {sender_email}. "
            "Make sure you're using a Gmail App Password, not your real password."
        )
        return False
    except Exception as e:
        logger.error(f"Failed to send email: {e}")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# 1. Send approval request
# ─────────────────────────────────────────────────────────────────────────────

def send_approval_request(
    approval_sender_email: str,
    approval_sender_password: str,
    approval_receiver_email: str,
    job_data: dict,
) -> Optional[str]:
    """
    Send an approval email for a single job.
    job_data keys: role_title, company_name, location, experience_required,
                   recruiter_name, recruiter_email, key_skills, post_url, post_id
    Returns the Message-ID of the sent email (used to match replies).
    """
    role = job_data.get("role_title", "Unknown Role")
    company = job_data.get("company_name", "Unknown Company")
    location = job_data.get("location", "")
    exp = job_data.get("experience_required", "")
    recruiter = job_data.get("recruiter_name", "Hiring Manager")
    rec_email = job_data.get("recruiter_email", "")
    skills = ", ".join(job_data.get("key_skills", []))
    post_url = job_data.get("post_url", "")
    post_id = job_data.get("post_id", "")

    # Include the ID in the subject because email clients often strip the quoted body text.
    # We will use this ID in the subject to identify which job is being approved.
    subject = f"{APPROVAL_SUBJECT_PREFIX} {role} @ {company} [ID:{post_id}]"

    # Embed post_id in the body so we can recover it from the reply
    hidden_meta = json.dumps({
        "post_id": post_id,
        "role_title": role,
        "company_name": company,
        "recruiter_name": recruiter,
        "recruiter_email": rec_email,
    })

    html_body = f"""
<html><body style="font-family: Arial, sans-serif; color: #222;">
<h2 style="color:#0077b5;">🔔 New Job Match Found</h2>
<table cellpadding="8" cellspacing="0" border="1" style="border-collapse:collapse; width:100%;">
  <tr><td><b>Role</b></td><td>{role}</td></tr>
  <tr><td><b>Company</b></td><td>{company}</td></tr>
  <tr><td><b>Location</b></td><td>{location}</td></tr>
  <tr><td><b>Experience</b></td><td>{exp}</td></tr>
  <tr><td><b>Recruiter</b></td><td>{recruiter}</td></tr>
  <tr><td><b>Recruiter Email</b></td><td>{rec_email}</td></tr>
  <tr><td><b>Key Skills</b></td><td>{skills}</td></tr>
</table>
<br>
<a href="{post_url}" style="color:#0077b5;">View LinkedIn Post</a>
<br><br>
<div style="background:#f0f8ff; padding:15px; border-radius:8px; border-left:4px solid #0077b5;">
  <b>👉 Reply with just <span style="color:green;">ok</span> to send the application.</b><br>
  Reply with <span style="color:red;">skip</span> to ignore this job.
</div>
<br>
<!-- META:{hidden_meta}:META -->
</body></html>"""

    text_body = f"""New Job Match: {role} @ {company}
Location: {location} | Exp: {exp}
Recruiter: {recruiter} <{rec_email}>
Post: {post_url}

Reply with: ok  (to send application)  OR  skip  (to ignore)

META:{hidden_meta}:META"""

    msg = MIMEMultipart("mixed")
    msg["From"] = approval_sender_email
    msg["To"] = approval_receiver_email
    msg["Subject"] = subject
    msg["Date"] = email.utils.formatdate(localtime=True)
    msg_id = email.utils.make_msgid()
    msg["Message-ID"] = msg_id

    msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP(GMAIL_SMTP[0], GMAIL_SMTP[1], timeout=30) as server:
            server.ehlo()
            server.starttls()
            server.login(approval_sender_email, approval_sender_password)
            server.sendmail(approval_sender_email, approval_receiver_email, msg.as_string())
        logger.info(f"Approval request sent for: {role} @ {company}")
        return msg_id
    except smtplib.SMTPAuthenticationError:
        logger.error(
            f"SMTP auth failed for {approval_sender_email}. "
            "Use a Gmail App Password."
        )
        return None
    except Exception as e:
        logger.error(f"Failed to send approval email: {e}")
        return None


def send_manual_apply_notification(
    approval_sender_email: str,
    approval_sender_password: str,
    approval_receiver_email: str,
    job_data: dict,
) -> bool:
    """
    Sends an email to the user with the application links when no recruiter email is found.
    This does not require a reply to trigger an automated application.
    """
    role = job_data.get("role_title", "Unknown Role")
    company = job_data.get("company_name", "Unknown Company")
    links = job_data.get("apply_links", [])

    subject = f"[MANUAL APPLY] {role} @ {company}"

    links_text = "\n".join([f"- {link}" for link in links])
    
    text_body = f"""New highly relevant job found!
However, this job requires a manual application via links (no email found).

Role: {role}
Company: {company}
Experience Required: {job_data.get("experience_required", "Not specified")}
Location: {job_data.get("location", "Not specified")}

Application Links:
{links_text}

Original Post:
{job_data.get("post_url", "")}

Note: Do not reply to this email. Please apply using the links above.
"""

    msg = MIMEMultipart()
    msg["From"] = approval_sender_email
    msg["To"] = approval_receiver_email
    msg["Subject"] = subject
    msg.attach(MIMEText(text_body, "plain", "utf-8"))

    try:
        with smtplib.SMTP(GMAIL_SMTP[0], GMAIL_SMTP[1], timeout=30) as server:
            server.ehlo()
            server.starttls()
            server.login(approval_sender_email, approval_sender_password)
            server.sendmail(approval_sender_email, approval_receiver_email, msg.as_string())
        logger.info(f"Manual apply notification sent for: {role} @ {company}")
        return True
    except Exception as e:
        logger.error(f"Failed to send manual apply notification: {e}")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# 2. Poll inbox for "ok" replies
# ─────────────────────────────────────────────────────────────────────────────

def _decode_header_value(value: str) -> str:
    parts = decode_header(value)
    decoded = []
    for part, enc in parts:
        if isinstance(part, bytes):
            decoded.append(part.decode(enc or "utf-8", errors="replace"))
        else:
            decoded.append(part)
    return "".join(decoded)


def _extract_email_body(msg) -> str:
    """Extract plain text body from email message."""
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                try:
                    body += part.get_payload(decode=True).decode("utf-8", errors="replace")
                except Exception:
                    pass
    else:
        try:
            body = msg.get_payload(decode=True).decode("utf-8", errors="replace")
        except Exception:
            pass
    return body


def _extract_meta_from_body(body: str) -> Optional[dict]:
    """Extract the JSON meta block embedded in approval emails."""
    match = re.search(r"META:(\{.*?\}):META", body, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    return None


def poll_for_approvals(
    approval_receiver_email: str,
    approval_receiver_password: str,
    pending_jobs: dict[str, dict],  # message_id -> job_data
) -> list[dict]:
    """
    Check the approval inbox for replies containing "ok".
    Returns list of job_data dicts that were approved.
    pending_jobs: dict of Message-ID -> job_data (to match In-Reply-To headers).
    """
    approved_jobs = []

    mail = None
    try:
        mail = imaplib.IMAP4_SSL(GMAIL_IMAP, timeout=30)
        mail.login(approval_receiver_email, approval_receiver_password)
        mail.select("inbox")

        # Search for recent unread emails
        _, msg_nums = mail.search(None, 'UNSEEN')
        
        # Reverse to process newest first
        msg_list = msg_nums[0].split()
        msg_list.reverse()
        
        # Limit to 50 unread messages to avoid hangs on large inboxes
        msg_list = msg_list[:50]

        for num in msg_list:
            _, data = mail.fetch(num, "(RFC822)")
            raw = data[0][1]
            msg = email.message_from_bytes(raw)

            subject = _decode_header_value(msg.get("Subject", ""))
            logger.info(f"Checking unread email: {subject}")
            
            # Filter subjects manually since IMAP search can be flaky with Re: prefixes
            if "[JOB APPROVAL NEEDED]" not in subject.upper():
                continue
                
            in_reply_to = msg.get("In-Reply-To", "").strip().strip("<>")
            body = _extract_email_body(msg)

            # Check if this is an "ok" reply (more flexible search)
            clean_body = body.strip().lower()
            if not re.search(r'\b(ok|okay|yes|approve|send)\b', clean_body):
                logger.info(f"Ignoring reply (not an approval): '{body[:50].strip()}'")
                # Mark as read so we don't re-process
                mail.store(num, "+FLAGS", "\\Seen")
                continue

            # IDENTIFY THE JOB (3 Methods)
            job_data = None
            
            # Method 1: Header Matching (Most reliable)
            if in_reply_to:
                for mid in pending_jobs:
                    if in_reply_to in mid or mid in in_reply_to:
                        job_data = pending_jobs[mid]
                        break
            
            # Method 2: Subject ID Fallback
            if not job_data:
                id_match = re.search(r"\[ID:(.*?)\]", subject)
                if id_match:
                    target_id = id_match.group(1)
                    for mid in pending_jobs:
                        if pending_jobs[mid].get("post_id") == target_id:
                            job_data = pending_jobs[mid]
                            break
            
            # Method 3: Body Metadata Fallback
            if not job_data:
                job_data = _extract_meta_from_body(body)

            if job_data:
                logger.info(f"Approval received for: {job_data.get('role_title')} @ {job_data.get('company_name')}")
                approved_jobs.append(job_data)
                mail.store(num, "+FLAGS", "\\Seen")
            else:
                logger.warning(f"Could not identify job for approval reply. Subject: {subject}")

    except imaplib.IMAP4.error as e:
        logger.error(f"IMAP error while polling approvals: {e}")
    except Exception as e:
        logger.error(f"Unexpected error polling approvals: {e}")
    finally:
        if mail:
            try:
                mail.logout()
            except:
                pass

    return approved_jobs


# ─────────────────────────────────────────────────────────────────────────────
# 3. Send application email to recruiter
# ─────────────────────────────────────────────────────────────────────────────

APPLICATION_TEMPLATE = """\
Hi,

I'm reaching out to apply for the {role_title} role. I am an AI Specialist with 4.4 years of \
experience and a Master's in AI/ML from BITS Pilani, specializing in Traditional ML, Generative AI \
and multi-agent architectures.

I build and deploy scalable end-to-end AI systems. My current focus is on agentic frameworks and \
fine-tuning, utilizing a stack that includes:

GenAI & Agentic Systems: LLMs, NLP, Transformers, Fine-Tuning, LangChain, LangGraph, CrewAI, MCP, A2A.

Deep Learning & Core ML: PyTorch, TensorFlow, Keras, XGBoost, Scikit-learn, Pandas, NumPy.

Engineering & MLOps: Python, PostgreSQL, CUDA/GPU Acceleration, Docker, AWS EC2, Flask.

I'd love to bring my expertise in building scalable, autonomous AI solutions to the team. Please \
find my resume attached for a deeper dive into my work.

Portfolio: https://tandon07.github.io/
Resume: https://saurabh.tiecv.com/  (also attached)

Thanks & Regards,
Saurabh Tandon
Phone: 8789499866
"""

APPLICATION_TEMPLATE_HTML = """\
<html><body style="font-family: Arial, sans-serif; color: #222; line-height:1.6;">
<p>Hi,</p>

<p>I'm reaching out to apply for the <strong>{role_title}</strong> role. I am an AI Specialist with
<strong>4.4 years of experience</strong> and a <strong>Master's in AI/ML from BITS Pilani</strong>,
specializing in Traditional ML, Generative AI and multi-agent architectures.</p>

<p>I build and deploy scalable end-to-end AI systems. My current focus is on agentic frameworks and
fine-tuning, utilizing a stack that includes:</p>

<p><strong>GenAI &amp; Agentic Systems:</strong> LLMs, NLP, Transformers, Fine-Tuning, LangChain,
LangGraph, CrewAI, MCP, A2A.</p>

<p><strong>Deep Learning &amp; Core ML:</strong> PyTorch, TensorFlow, Keras, XGBoost, Scikit-learn,
Pandas, NumPy.</p>

<p><strong>Engineering &amp; MLOps:</strong> Python, PostgreSQL, CUDA/GPU Acceleration, Docker,
AWS EC2, Flask.</p>

<p>I'd love to bring my expertise in building scalable, autonomous AI solutions to the team.
Please find my resume attached for a deeper dive into my work.</p>

<p>
  📁 <a href="https://tandon07.github.io/">Portfolio</a><br>
  📄 <a href="https://saurabh.tiecv.com/">Resume (Online)</a> — also attached
</p>

<p>Thanks &amp; Regards,<br>
<strong>Saurabh Tandon</strong><br>
📞 8789499866</p>
</body></html>"""


def send_job_application(
    app_sender_email: str,
    app_sender_password: str,
    recruiter_email: str,
    role_title: str,
    recruiter_name: str,
    resume_pdf_path: Path,
) -> bool:
    """
    Send the actual job application email to the recruiter.
    """
    subject = f"{role_title} Application - Saurabh Tandon"
    text_body = APPLICATION_TEMPLATE.format(
        role_title=role_title,
    )
    html_body = APPLICATION_TEMPLATE_HTML.format(
        role_title=role_title,
    )

    return _send_email(
        sender_email=app_sender_email,
        sender_password=app_sender_password,
        recipient=recruiter_email,
        subject=subject,
        html_body=html_body,
        text_body=text_body,
        attachments=[resume_pdf_path] if resume_pdf_path.exists() else None,
    )
