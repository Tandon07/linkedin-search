# 🤖 LinkedIn Job Application Automator

Automates your LinkedIn job hunt — scrolls your feed, finds relevant AI/ML job posts, asks for your approval via email, then fires off your application automatically.

---

## How It Works

```
LinkedIn Feed
     │
     ▼ (Selenium scrolls every 3 hrs)
Find posts with email addresses
     │
     ▼ (Groq LLM classifies)
Is it a relevant AI/ML/DS role? (2–5 yrs exp?)
     │ YES
     ▼
Send approval email ──► saurabhtandon787807@gmail.com
                              │
                    You reply "ok"
                              │
                              ▼
              Send application from tandonsaurabh07@gmail.com
              (with resume PDF attached) ──► recruiter
```

---

## Quick Setup

### Step 1: Install dependencies

```bash
pip install -r requirements.txt
```

> Also install Google Chrome if not already installed.

### Step 2: Configure `.env`

```bash
cp .env.example .env
# Edit .env with your credentials
```

Fill in:
| Variable | What it is |
|---|---|
| `LINKEDIN_EMAIL` | Your LinkedIn login email |
| `LINKEDIN_PASSWORD` | Your LinkedIn password |
| `GROQ_API_KEY` | Get from https://console.groq.com |
| `APPROVAL_SENDER_EMAIL` | `rahul.raj787807@gmail.com` |
| `APPROVAL_SENDER_PASSWORD` | **App Password** for above (see below) |
| `APPROVAL_RECEIVER_EMAIL` | `saurabhtandon787807@gmail.com` |
| `APPLICATION_SENDER_EMAIL` | `tandonsaurabh07@gmail.com` |
| `APPLICATION_SENDER_PASSWORD` | **App Password** for above |
| `RESUME_PDF_PATH` | Path to your resume PDF |

### Step 3: Gmail App Passwords (IMPORTANT)

Gmail blocks plain password SMTP. You need **App Passwords** for each Gmail account used.

1. Go to https://myaccount.google.com/security
2. Enable **2-Step Verification** (required)
3. Go to https://myaccount.google.com/apppasswords
4. Create a new App Password → name it "LinkedIn Automator"
5. Copy the 16-character password → paste into `.env`

Do this for **both** `rahul.raj787807@gmail.com` and `tandonsaurabh07@gmail.com`.

Also enable IMAP for `saurabhtandon787807@gmail.com`:
- Gmail → Settings → See All Settings → Forwarding and POP/IMAP → Enable IMAP

### Step 4: Add your resume

```
mkdir resume
cp /path/to/your/resume.pdf resume/Saurabh_Tandon_Resume.pdf
```

### Step 5: Test your setup

```bash
python test_setup.py
```

Fix any ❌ issues before running.

### Step 6: Run!

```bash
python main.py
```

---

## File Structure

```
linkedin_automator/
├── main.py              # Orchestrator + scheduler (run this)
├── linkedin_scraper.py  # Selenium-based LinkedIn feed scraper
├── ai_classifier.py     # Groq LLM job relevance classifier
├── email_handler.py     # Approval + application email logic
├── state_tracker.py     # JSON persistence (tracks what's been seen/applied)
├── test_setup.py        # Pre-flight check script
├── .env.example         # Template for your credentials
├── requirements.txt
├── resume/              # Place your PDF here
│   └── Saurabh_Tandon_Resume.pdf
├── data/
│   └── state.json       # Auto-created — tracks all state
└── logs/
    └── automator.log    # Auto-created — all activity logged
```

---

## Approval Flow

When a relevant job is found, you'll receive an email at **saurabhtandon787807@gmail.com** like:

```
Subject: [JOB APPROVAL NEEDED] Associate AI Engineer @ Johnnette Technologies | recruitment@johnnette.com

🔔 New Job Match Found
Role       : Associate AI Engineer
Company    : Johnnette Technologies
Location   : Noida
Experience : 2-4 Years
Recruiter  : Pushkar Sharma
Email      : recruitment@johnnette.com
Skills     : Python, Computer Vision, CNN, PyTorch

👉 Reply with "ok" to send the application.
   Reply with "skip" to ignore.
```

Just reply **ok** (or okay / yes / approve) — the automator polls every 15 minutes and will fire the application.

---

## What "Relevant" Means

The AI looks for posts matching **any** of:

`Data Science · AI · ML · NLP · LLM · RAG · Agents · AgenticAI · Generative AI · LangChain · LangGraph · PyTorch · TensorFlow · Fine-tuning · Computer Vision · Deep Learning · MLOps`

**And** experience required is **≤ 5 years**.

---

## Running 24/7

To keep it running in the background:

```bash
# Using nohup (Linux/Mac)
nohup python main.py > logs/nohup.log 2>&1 &

# Using screen
screen -S linkedin_bot
python main.py
# Ctrl+A then D to detach
```

Or set up a systemd service (Linux) for auto-restart on reboot.

---

## Troubleshooting

| Issue | Fix |
|---|---|
| LinkedIn shows CAPTCHA | Run with `headless=False` in scraper, log in manually once |
| SMTP auth failed | Make sure you're using App Password, not real Gmail password |
| No posts found | LinkedIn's HTML may have changed — check `logs/automator.log` |
| Duplicate applications | `data/state.json` tracks everything — won't double-apply |
| Want to reset | Delete `data/state.json` to start fresh |

---

## Notes

- LinkedIn may occasionally require CAPTCHA or 2FA. If login fails, try logging in once manually in a browser, then re-run.
- The scraper only picks up posts **containing an email address** (the format you described).
- All activity is logged to `logs/automator.log`.
