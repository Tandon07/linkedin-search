"""
ai_classifier.py
----------------
Uses Claude (via Anthropic API) to decide whether a LinkedIn post
is a relevant job opening for Saurabh Tandon, and extracts structured
data (role title, experience required, recruiter name, email).
"""

import json
import logging
import re
from dataclasses import dataclass
from typing import Optional

from langchain_groq import ChatGroq

logger = logging.getLogger(__name__)

# ── Keywords that indicate a relevant role ──────────────────────────────────
HIRING_KEYWORDS = [
    "hiring", "opening", "looking for"
]

RELEVANT_KEYWORDS = [
    "data science", "data scientist",
    "machine learning", "ml engineer",
    "artificial intelligence", "ai engineer", "ai specialist",
    "nlp", "natural language processing",
    "computer vision", "cv engineer",
    "llm", "large language model",
    "rag", "retrieval augmented",
    "agents", "agentic", "multi-agent",
    "generative ai", "genai",
    "langchain", "langgraph", "crewai",
    "pytorch", "tensorflow",
    "fine-tuning", "finetuning",
    "deep learning",
    "mlops",
]

# ── Experience filter ────────────────────────────────────────────────────────
# We want roles where the MINIMUM experience is 6 years or less.
MAX_EXPERIENCE_YEARS = 6


@dataclass
class ClassificationResult:
    is_relevant: bool
    role_title: str
    recruiter_name: str
    recruiter_email: str
    experience_required: str        # e.g. "2-4 Years"
    company_name: str
    location: str
    key_skills: list[str]
    apply_links: list[str]          # Links to apply if email is missing
    reason: str                     # short explanation from AI


def _quick_keyword_filter(post_text: str) -> bool:
    """Fast pre-filter — skip LLM API call if no keywords match at all."""
    text_lower = post_text.lower()
    has_hiring = any(kw in text_lower for kw in HIRING_KEYWORDS)
    has_role = any(kw in text_lower for kw in RELEVANT_KEYWORDS)
    return has_hiring and has_role


def _parse_experience_range(experience_str: str) -> tuple[int, int]:
    """
    Parse '2-4 Years' or '5+ Years' into (min, max).
    Returns (0, 999) if unparseable.
    """
    numbers = re.findall(r"\d+", experience_str)
    if not numbers:
        return (0, 999)
    if len(numbers) == 1:
        n = int(numbers[0])
        return (n, n + 10)   # treat "5+ Years" as (5, 15)
    return (int(numbers[0]), int(numbers[1]))


def classify_post(post_text: str, api_key: str) -> ClassificationResult:
    """
    Send post text to LLM and get a structured classification.
    """
    # Fast path — skip API call if no relevant keywords
    if not _quick_keyword_filter(post_text):
        return ClassificationResult(
            is_relevant=False,
            role_title="",
            recruiter_name="",
            recruiter_email="",
            experience_required="",
            company_name="",
            location="",
            key_skills=[],
            apply_links=[],
            reason="No relevant keywords found (pre-filter).",
        )

    llm = ChatGroq(
        model="llama-3.1-8b-instant",
        temperature=0,
        groq_api_key=api_key,
    )

    system_prompt = f"""You are a job relevance classifier for a candidate named Saurabh Tandon.

Saurabh is an AI Specialist with 4.4 years of experience and a Master's in AI/ML from BITS Pilani.

A post is RELEVANT if ALL of the following are true:
1. It is a job opening / hiring post.
   - If a post lists MULTIPLE roles (e.g. Java, Mobile, AI/ML), it is RELEVANT if at least ONE of them is an AI/ML or Data role.
2. The role (or one of the roles) falls into: Data Science, AI, ML, NLP, Computer Vision, LLM, RAG, Agents, Generative AI, MLOps, Data Engineering, or Data Architect. 
   - NOTE: Data Architect is a highly relevant role for Saurabh.
3. The MINIMUM experience required is {MAX_EXPERIENCE_YEARS} years or LESS.
   - IMPORTANT: Do NOT guess or infer the experience level. If NO years are mentioned in the text, you MUST mark it as RELEVANT.
   - Saurabh has 4.4 years, so "2+ years", "4+ years", "5-8 years", and "6+ years" are all RELEVANT.
   - REJECT only if the text explicitly states a minimum of 7+ years or more (e.g. "8-10 years", "12+ years").
4. The post contains EITHER an email address OR an application link (URL) to apply.

Respond ONLY with a JSON object (no markdown, no extra text):
{{
  "is_relevant": true/false,
  "role_title": "...",
  "recruiter_name": "...",
  "recruiter_email": "...",
  "experience_required": "...",
  "company_name": "...",
  "location": "...",
  "key_skills": ["skill1", "skill2"],
  "apply_links": ["https://..."],
  "reason": "one sentence explanation"
}}"""

    user_prompt = f"Classify this LinkedIn post:\n\n{post_text[:3000]}"

    try:
        response = llm.invoke([
            ("system", system_prompt),
            ("human", user_prompt)
        ])
        raw = response.content.strip()

        # Strip any accidental markdown fences
        raw = re.sub(r"^```json\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)

        data = json.loads(raw)

        # Double-check experience range server-side
        is_relevant = data.get("is_relevant", False)
        exp_str = data.get("experience_required", "")
        if is_relevant and exp_str:
            exp_min, _ = _parse_experience_range(exp_str)
            # If the minimum requirement is more than 6 years, reject it.
            # (Candidate has 4.4 yrs, so 6+ is too senior)
            if exp_min > 6:
                is_relevant = False
                data["reason"] = f"Minimum experience required ({exp_str}) is too high for candidate."

        return ClassificationResult(
            is_relevant=is_relevant,
            role_title=data.get("role_title", ""),
            recruiter_name=data.get("recruiter_name", ""),
            recruiter_email=data.get("recruiter_email", ""),
            experience_required=data.get("experience_required", ""),
            company_name=data.get("company_name", ""),
            location=data.get("location", ""),
            key_skills=data.get("key_skills", []),
            apply_links=data.get("apply_links", []),
            reason=data.get("reason", ""),
        )

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse LLM response as JSON: {e}\nRaw: {raw}")
        return ClassificationResult(
            is_relevant=False,
            role_title="", recruiter_name="", recruiter_email="",
            experience_required="", company_name="", location="",
            key_skills=[], apply_links=[], reason=f"JSON parse error: {e}",
        )
    except Exception as e:
        logger.error(f"LLM API error: {e}")
        return ClassificationResult(
            is_relevant=False,
            role_title="", recruiter_name="", recruiter_email="",
            experience_required="", company_name="", location="",
            key_skills=[], apply_links=[], reason=f"API error: {e}",
        )
