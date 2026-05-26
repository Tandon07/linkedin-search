#!/usr/bin/env python3
"""
azure_cookie_injector.py
------------------------
Bypasses CAPTCHA and 2FA on cloud VMs by injecting your active 
Windows browser's "li_at" session cookie directly into the VM's Chrome profile.
"""

import os
import time
import logging
from pathlib import Path
from selenium.webdriver.common.by import By

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

def inject_session_cookie():
    from linkedin_scraper import _build_driver, _is_already_logged_in

    print("\n" + "="*75)
    print("      LINKEDIN SESSION COOKIE INJECTOR (BYPASS CAPTCHA & 2FA)")
    print("="*75)
    
    li_at_value = input("👉 Paste your copied 'li_at' cookie value here:\n").strip()
    
    if not li_at_value or len(li_at_value) < 20:
        logger.error("Error: Invalid cookie value provided. It should be a long string of letters and numbers.")
        return

    logger.info("Initializing Headless Chrome Driver on VM...")
    driver = _build_driver(headless=True)

    try:
        # Delete SingletonLock just in case
        lock_file = Path(__file__).parent / "chrome_profile" / "SingletonLock"
        if lock_file.exists():
            try:
                lock_file.unlink()
                logger.info("Removed legacy Chrome profile SingletonLock.")
            except Exception as e:
                logger.warning(f"Could not remove lock: {e}")

        # Selenium requires us to navigate to the target domain BEFORE adding a cookie for it
        logger.info("Navigating to LinkedIn homepage (required domain context)...")
        driver.get("https://www.linkedin.com")
        time.sleep(4)

        logger.info("Injecting your session cookie...")
        driver.delete_all_cookies() # Clear any broken ones
        
        cookie_dict = {
            "name": "li_at",
            "value": li_at_value,
            "domain": ".www.linkedin.com", # Target exact domain
            "path": "/",
            "secure": True
        }
        
        # Inject standard cookie
        driver.add_cookie(cookie_dict)
        
        # Inject root domain cookie for maximum safety
        cookie_dict_root = cookie_dict.copy()
        cookie_dict_root["domain"] = ".linkedin.com"
        driver.add_cookie(cookie_dict_root)
        
        logger.info("Cookie injected! Navigating to feed to verify session...")
        driver.get("https://www.linkedin.com/feed/")
        time.sleep(5)

        current_url = driver.current_url
        if "feed" in current_url and "login" not in current_url:
            logger.info("🎉 SUCCESS: Session cookie injected and verified! You are fully logged in on this VM!")
        else:
            logger.error(f"❌ Verification failed. Redirected to: {current_url}")
            logger.error("Please ensure your local browser session is active and you copied the complete cookie value.")

    except Exception as e:
        logger.error(f"An error occurred during injection: {e}")
    finally:
        driver.quit()

if __name__ == "__main__":
    inject_session_cookie()
