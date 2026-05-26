#!/usr/bin/env python3
"""
azure_login_helper.py
---------------------
Interactive one-time login helper for headless cloud environments.
Handles entering 2FA/verification codes directly from the terminal console.
"""

import os
import time
import logging
from pathlib import Path
from dotenv import load_dotenv
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Load local env
load_dotenv()

LINKEDIN_EMAIL = os.getenv("LINKEDIN_EMAIL", "")
LINKEDIN_PASSWORD = os.getenv("LINKEDIN_PASSWORD", "")

def run_interactive_login():
    # Import scraper functions
    from linkedin_scraper import _build_driver, _is_already_logged_in, login_linkedin

    if not LINKEDIN_EMAIL or not LINKEDIN_PASSWORD:
        logger.error("Error: LINKEDIN_EMAIL or LINKEDIN_PASSWORD not set in your .env file.")
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
                logger.warning(f"Could not remove lock file: {e}")

        logger.info("Checking if already logged in...")
        if _is_already_logged_in(driver):
            logger.info("🎉 SUCCESS: You are ALREADY logged in on this VM!")
            return

        logger.info(f"Navigating to login page for {LINKEDIN_EMAIL}...")
        driver.get("https://www.linkedin.com/login")
        time.sleep(5)

        # Find and input email
        email_field = driver.find_element(By.ID, "username")
        email_field.clear()
        email_field.send_keys(LINKEDIN_EMAIL)

        # Find and input password
        password_field = driver.find_element(By.ID, "password")
        password_field.clear()
        password_field.send_keys(LINKEDIN_PASSWORD)

        # Click submit
        submit_btn = driver.find_element(By.XPATH, "//button[@type='submit']")
        submit_btn.click()
        logger.info("Login submitted. Waiting to see if 2FA/Verification is required...")
        time.sleep(6)

        current_url = driver.current_url
        if "feed" in current_url:
            logger.info("🎉 SUCCESS: Logged in immediately without 2FA!")
            return

        # Check if we are on a checkpoint/challenge page (2FA)
        if "checkpoint" in current_url or "challenge" in current_url:
            logger.warning("🛡️ LinkedIn triggered a security verification (2FA/Email Pin)!")
            
            # Check email pin input field
            pin_selectors = [
                "input#input__email-verification-pin",
                "input[name='pin']",
                "input[type='text']",
                "input[autocomplete='one-time-code']"
            ]
            
            pin_input = None
            for sel in pin_selectors:
                try:
                    pin_input = driver.find_element(By.CSS_SELECTOR, sel)
                    if pin_input.is_displayed():
                        break
                except Exception:
                    continue

            if pin_input:
                logger.info("Verification code input field detected.")
                # Prompt user in terminal
                print("\n" + "="*70)
                verification_code = input("👉 Enter the 6-digit verification code sent to your email: ").strip()
                print("="*70 + "\n")
                
                pin_input.clear()
                pin_input.send_keys(verification_code)
                time.sleep(1)

                # Submit pin
                submit_selectors = [
                    "button#email-pin-submit-button",
                    "button[type='submit']",
                    "input[type='submit']"
                ]
                submit_btn = None
                for sel in submit_selectors:
                    try:
                        submit_btn = driver.find_element(By.CSS_SELECTOR, sel)
                        if submit_btn.is_displayed():
                            break
                    except Exception:
                        continue

                if submit_btn:
                    submit_btn.click()
                else:
                    pin_input.submit()

                logger.info("Verification code submitted. Waiting for login confirmation...")
                time.sleep(7)

                if "feed" in driver.current_url:
                    logger.info("🎉 SUCCESS: Verification approved! Headless login successful.")
                else:
                    logger.error(f"Failed to verify login. Current URL: {driver.current_url}")
            else:
                logger.error("Could not find pin input field. You might need to solve a CAPTCHA or run it non-headlessly once.")
        else:
            logger.error(f"Login failed or got redirected to an unexpected page: {current_url}")

    except Exception as e:
        logger.error(f"An error occurred during interactive login: {e}")
    finally:
        driver.quit()

if __name__ == "__main__":
    run_interactive_login()
