import os
from dotenv import load_dotenv
from ai_classifier import classify_post

load_dotenv()
api_key = os.getenv("GROQ_API_KEY")

post_text = """We are still #hiring! Know anyone who might be interested?
One of our client is looking a Data Scientist.The client is a category-leading consumer internet unicorn-scale platform in Mumbai.

We need experienced candidates with over 3+ years of experience based in Mumbai.
You can go through the JD and share your resume at hr@alphasqmax.com

#DataScientist
#MumbaiJobs2026
#HiringNow
#MLEngineers
#AIEngineers"""

result = classify_post(post_text, api_key)
print(f"Relevant: {result.is_relevant}")
print(f"Reason: {result.reason}")
