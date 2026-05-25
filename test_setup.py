"""
test_setup.py
-------------
Run this BEFORE starting the main automator to verify:
  1. Environment variables are loaded
  2. Approval sender email (rahul.raj787807@gmail.com) can send
  3. Application sender email (tandonsaurabh07@gmail.com) can send
  4. Approval receiver inbox (saurabhtandon787807@gmail.com) can be polled via IMAP
  5. Resume PDF exists

Usage:
    python test_setup.py
"""

import os
import sys
import imaplib
import smtplib
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

def check(label, condition, fix=""):
    icon = "✅" if condition else "❌"
    print(f"  {icon}  {label}")
    if not condition and fix:
        print(f"       ↳ {fix}")
    return condition


def test_smtp(email_addr, password, label):
    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as s:
            s.ehlo()
            s.starttls()
            s.login(email_addr, password)
        return True
    except smtplib.SMTPAuthenticationError:
        return False
    except Exception as e:
        print(f"       ↳ Error: {e}")
        return False


def test_imap(email_addr, password):
    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(email_addr, password)
        mail.logout()
        return True
    except imaplib.IMAP4.error:
        return False
    except Exception as e:
        print(f"       ↳ Error: {e}")
        return False


def main():
    print("\n🔧 LinkedIn Automator — Setup Test\n" + "=" * 45)

    all_ok = True

    # 1. Env vars
    print("\n[1] Environment Variables")
    vars_to_check = [
        "LINKEDIN_EMAIL", "LINKEDIN_PASSWORD",
        "GROQ_API_KEY",
        "APPROVAL_SENDER_EMAIL", "APPROVAL_SENDER_PASSWORD",
        "APPROVAL_RECEIVER_EMAIL",
        "APPLICATION_SENDER_EMAIL", "APPLICATION_SENDER_PASSWORD",
    ]
    for v in vars_to_check:
        ok = bool(os.getenv(v))
        all_ok &= check(v, ok, f"Set {v} in your .env file")

    # 2. Resume PDF
    print("\n[2] Resume PDF")
    pdf_path = Path(os.getenv("RESUME_PDF_PATH", "resume/Saurabh_Tandon_Resume.pdf"))
    ok = pdf_path.exists()
    all_ok &= check(f"Resume found at {pdf_path}", ok,
                    f"Place your resume PDF at: {pdf_path.resolve()}")

    # 3. SMTP — approval sender
    print("\n[3] SMTP — Approval Sender (rahul.raj787807@gmail.com)")
    email_a = os.getenv("APPROVAL_SENDER_EMAIL", "")
    pass_a  = os.getenv("APPROVAL_SENDER_PASSWORD", "")
    if email_a and pass_a:
        ok = test_smtp(email_a, pass_a, "Approval sender")
        all_ok &= check(f"SMTP login for {email_a}", ok,
                        "Use a Gmail App Password (16-char), not your real password.\n"
                        "       Enable at: https://myaccount.google.com/apppasswords")
    else:
        print("  ⚠️   Skipped (credentials not set)")

    # 4. SMTP — application sender
    print("\n[4] SMTP — Application Sender (tandonsaurabh07@gmail.com)")
    email_b = os.getenv("APPLICATION_SENDER_EMAIL", "")
    pass_b  = os.getenv("APPLICATION_SENDER_PASSWORD", "")
    if email_b and pass_b:
        ok = test_smtp(email_b, pass_b, "Application sender")
        all_ok &= check(f"SMTP login for {email_b}", ok,
                        "Use a Gmail App Password. Enable 2FA first, then create App Password.")
    else:
        print("  ⚠️   Skipped (credentials not set)")

    # 5. IMAP — approval receiver inbox poll
    print("\n[5] IMAP — Approval Receiver Inbox (saurabhtandon787807@gmail.com)")
    email_c = os.getenv("APPROVAL_RECEIVER_EMAIL", "")
    # Note: IMAP needs its own App Password — we reuse APPROVAL_SENDER_PASSWORD here
    # but ideally you'd set APPROVAL_RECEIVER_PASSWORD too.
    pass_c  = os.getenv("APPROVAL_SENDER_PASSWORD", "")  # or a separate env var
    if email_c and pass_c:
        ok = test_imap(email_c, pass_c)
        all_ok &= check(f"IMAP login for {email_c}", ok,
                        "This inbox needs IMAP access + App Password. "
                        "Check Gmail Settings → Forwarding and POP/IMAP → Enable IMAP.")
    else:
        print("  ⚠️   Skipped (credentials not set)")

    # Summary
    print("\n" + "=" * 45)
    if all_ok:
        print("✅  All checks passed! You're ready to run: python main.py")
    else:
        print("❌  Some checks failed. Fix the issues above before running main.py")
    print()


if __name__ == "__main__":
    main()
