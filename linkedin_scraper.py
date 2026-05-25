"""
linkedin_scraper.py
-------------------
Logs into LinkedIn using Selenium, scrolls the feed, and extracts
job-related posts that contain email addresses.

Uses a persistent Chrome profile to avoid repeated logins,
and randomized scroll timing to reduce bot-detection risk.
"""

import os
import time
import re
import random
import hashlib
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException,
    NoSuchElementException,
    StaleElementReferenceException,
    WebDriverException,
)

logger = logging.getLogger(__name__)

# Persistent Chrome profile directory — keeps cookies/session alive
CHROME_PROFILE_DIR = str(Path(__file__).parent / "chrome_profile")

# Flag to dump DOM diagnostics only once per run
_url_debug_dumped = False


@dataclass
class LinkedInPost:
    post_id: str
    author_name: str
    author_title: str
    post_text: str
    recruiter_email: Optional[str]
    post_url: str
    raw_html: str = field(default="", repr=False)


def _extract_email(text: str) -> Optional[str]:
    """Pull the first email address from post text."""
    pattern = r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}"
    match = re.search(pattern, text)
    return match.group(0) if match else None


def _build_driver(headless: bool = True) -> webdriver.Chrome:
    """Create and return a configured Chrome WebDriver with persistent profile."""
    options = Options()
    if headless:
        options.add_argument("--headless=new")
    options.add_argument("--log-level=3")  # Suppress noisy Chrome logs
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--disable-notifications")
    options.add_argument(f"--user-data-dir={CHROME_PROFILE_DIR}")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
    driver = webdriver.Chrome(options=options)
    driver.execute_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    )
    driver.set_window_size(1920, 1080)
    return driver


def _is_already_logged_in(driver: webdriver.Chrome) -> bool:
    """Check if we're already logged in by navigating to feed."""
    try:
        driver.get("https://www.linkedin.com/feed/")
        time.sleep(4)
        current_url = driver.current_url
        # If we land on the feed, we're logged in
        if "feed" in current_url and "login" not in current_url:
            logger.info("Already logged in (session reused from previous run).")
            return True
        return False
    except Exception:
        return False


def login_linkedin(driver: webdriver.Chrome, email: str, password: str) -> bool:
    """Log into LinkedIn. Skips if already logged in. Returns True on success."""

    # First, check if the persisted session is still valid
    if _is_already_logged_in(driver):
        return True

    try:
        driver.get("https://www.linkedin.com/login")
        
        # Hard sleep to allow all scripts and social buttons to fully render
        # Sometimes LinkedIn dynamically re-renders the form which clears inputs
        logger.info("Waiting 5 seconds for login page to stabilize...")
        time.sleep(5)

        wait = WebDriverWait(driver, 15)

        # Robustly find the VISIBLE email field
        email_fields = driver.find_elements(By.CSS_SELECTOR, "input#username, input[name='session_key'], input[type='email'], input[autocomplete*='username']")
        visible_email = next((f for f in email_fields if f.is_displayed()), None)
        if visible_email:
            try:
                visible_email.clear()
                visible_email.send_keys(email)
            except Exception as e:
                logger.debug(f"Falling back to JS for email: {e}")
                driver.execute_script("arguments[0].value = arguments[1];", visible_email, email)

        time.sleep(random.uniform(0.5, 1.5))  # human-like pause

        # Robustly find the VISIBLE password field
        pass_fields = driver.find_elements(By.CSS_SELECTOR, "input#password, input[name='session_password'], input[type='password'], input[autocomplete*='current-password']")
        visible_pass = next((f for f in pass_fields if f.is_displayed()), None)
        if visible_pass:
            try:
                visible_pass.clear()
                visible_pass.send_keys(password)
            except Exception as e:
                logger.debug(f"Falling back to JS for password: {e}")
                driver.execute_script("arguments[0].value = arguments[1];", visible_pass, password)

        time.sleep(random.uniform(0.3, 1.0))  # human-like pause

        # Click the VISIBLE sign-in button
        all_buttons = driver.find_elements(By.TAG_NAME, "button")
        visible_submit = None
        for b in all_buttons:
            if b.is_displayed():
                text = b.text.strip().lower()
                # Exact match to avoid clicking "Sign in with Google/Microsoft"
                if text == "sign in" or text == "agree & join":
                    visible_submit = b
                    break
        
        # Fallback to older known submit button selectors if exact text match failed
        if not visible_submit:
            fallback_btns = driver.find_elements(By.XPATH, "//button[@type='submit'] | //button[@data-id='sign-in-form__submit-btn']")
            visible_submit = next((b for b in fallback_btns if b.is_displayed()), None)

        if visible_submit:
            try:
                visible_submit.click()
            except Exception:
                driver.execute_script("arguments[0].click();", visible_submit)

        # Wait for feed to confirm login (up to 5 mins for 2FA)
        logger.info("Waiting up to 5 minutes for login confirmation (CAPTCHA/2FA)...")
        wait_for_login = WebDriverWait(driver, 300)
        wait_for_login.until(EC.url_contains("feed"))
        logger.info("LinkedIn login successful.")
        return True

    except TimeoutException:
        logger.error("LinkedIn login failed or CAPTCHA/2FA required.")
        return False


def _random_delay(min_s: float = 2.0, max_s: float = 5.0):
    """Sleep for a random duration to mimic human behavior."""
    delay = random.uniform(min_s, max_s)
    time.sleep(delay)


def _scroll_and_collect_posts(
    driver: webdriver.Chrome, max_posts: int = 50
) -> list[dict]:
    """
    Scroll through the LinkedIn feed and collect raw post data.
    Returns a list of dicts with keys: post_id, author_name, author_title,
    post_text, post_url.
    """
    # Make sure we're on the feed
    if "feed" not in driver.current_url:
        driver.get("https://www.linkedin.com/feed/")
    time.sleep(4)

    seen_ids: set[str] = set()
    posts_data: list[dict] = []
    scroll_attempts = 0
    max_scrolls = 50  # Production grade: Increased from 5 to 50
    no_new_post_count = 0   # stop early if feed is exhausted

    # --- Debug: dump what selectors can find on first load ---
    _debug_selectors(driver)

    while len(posts_data) < max_posts and scroll_attempts < max_scrolls:
        try:
            # Try multiple selector strategies for post containers using XPath
            post_containers = driver.find_elements(
                By.XPATH,
                "//div[contains(@class, 'feed-shared-update-v2')] | "
                "//div[@data-urn] | "
                "//div[@data-id] | "
                "//article | "
                "//div[contains(@class, 'occludable-update')] | "
                "//span[@data-testid='expandable-text-box']/ancestor::div[position()=5]"
            )
        except WebDriverException as e:
            logger.warning(f"Browser connection lost. Ending scroll early: {e}")
            break

        new_this_scroll = 0

        for container in post_containers:
            try:
                # Use data-urn or data-id as unique post ID
                post_id = (
                    container.get_attribute("data-urn")
                    or container.get_attribute("data-id")
                    or ""
                )
                # Fallback: generate hash from outerHTML snippet
                if not post_id:
                    snippet = container.get_attribute("outerHTML")[:200] if container.get_attribute("outerHTML") else ""
                    if snippet:
                        post_id = hashlib.md5(snippet.encode()).hexdigest()
                    else:
                        continue

                if post_id in seen_ids:
                    continue
                seen_ids.add(post_id)
                new_this_scroll += 1

                # Click "...see more" to expand truncated text
                _try_click_see_more(driver, container)

                # Extract text content — try multiple strategies
                post_text = _extract_post_text(container)

                if not post_text or len(post_text) < 20:
                    continue

                # Only keep posts that mention email addresses OR have hiring keywords + an application link
                email = _extract_email(post_text)
                text_lower = post_text.lower()
                has_hiring_keywords = any(kw in text_lower for kw in ["hiring", "looking for", "job", "opportunity", "opening", "vacancy"])
                has_link = "http" in post_text or "www." in post_text or "lnkd.in" in post_text
                
                if not email and not (has_hiring_keywords and has_link):
                    continue

                # Author name
                author_name = _extract_element_text(
                    container,
                    [
                        "span.feed-shared-actor__name",
                        "span.update-components-actor__name",
                        "a.app-aware-link span[aria-hidden='true']",
                        ".update-components-actor__title span",
                    ],
                    default="Unknown Recruiter",
                )

                # Author title/headline
                author_title = _extract_element_text(
                    container,
                    [
                        "span.feed-shared-actor__description",
                        "span.update-components-actor__description",
                        ".update-components-actor__subtitle span",
                    ],
                    default="",
                )

                # Post URL (try to find permalink)
                post_url = _extract_post_url(driver, container, data_urn=post_id)

                posts_data.append({
                    "post_id": post_id,
                    "author_name": author_name,
                    "author_title": author_title,
                    "post_text": post_text,
                    "recruiter_email": email,
                    "post_url": post_url,
                })

                # Incrementally save backup to disk so no data is lost if it crashes
                try:
                    os.makedirs("data", exist_ok=True)
                    with open("data/fetched_posts_backup.json", "w", encoding="utf-8") as f:
                        import json
                        json.dump(posts_data, f, indent=4, ensure_ascii=False)
                except Exception as e:
                    logger.debug(f"Failed to write backup JSON: {e}")

                logger.info(
                    f"  [FOUND] Post with email/link ({email or 'Link'}) by {author_name}"
                )

                if len(posts_data) >= max_posts:
                    break

            except StaleElementReferenceException:
                continue  # element was removed from DOM during iteration
            except Exception as e:
                logger.debug(f"Error parsing post container: {e}")
                continue

        # Track if we're making progress
        if new_this_scroll == 0:
            no_new_post_count += 1
        else:
            no_new_post_count = 0

        if no_new_post_count >= 5:
            logger.info("Feed appears exhausted (no new posts in 5 scrolls). Stopping.")
            break

        # Scroll down with randomized behavior
        scroll_px = random.randint(800, 1500)
        try:
            driver.execute_script(f"""
                window.scrollBy(0, {scroll_px});
                var feed = document.querySelector('.scaffold-finite-scroll');
                if (feed) feed.scrollBy(0, {scroll_px});
            """)
        except WebDriverException as e:
            logger.warning(f"Browser connection lost (likely crashed due to memory). Ending scroll early: {e}")
            break
        if post_containers:
            try:
                driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'end'});", post_containers[-1])
            except Exception:
                pass
                
        _random_delay(2.5, 5.0)
        scroll_attempts += 1
        logger.info(
            f"Scrolled feed ({scroll_attempts}/{max_scrolls}). "
            f"New this scroll: {new_this_scroll}, Total checked: {len(seen_ids)}, "
            f"Posts with email: {len(posts_data)}"
        )

    logger.info(f"Collected {len(posts_data)} posts with emails from feed.")
    return posts_data


def _debug_selectors(driver: webdriver.Chrome):
    """Log what we can find on the page to help debug selector issues."""
    selectors_to_try = [
        ("div.feed-shared-update-v2", "feed-shared-update-v2"),
        ("div[data-urn]", "data-urn"),
        ("div[data-id]", "data-id"),
        ("[data-urn*='activity']", "data-urn with activity"),
        ("article", "article"),
        ("div.occludable-update", "occludable-update"),
        ("div.scaffold-finite-scroll__content > div", "scaffold children"),
        ("a[href*='activity']", "links with activity"),
        ("a[href*='/feed/update/']", "links with /feed/update/"),
    ]
    logger.info("--- DEBUG: Checking which selectors find elements ---")
    for selector, label in selectors_to_try:
        count = len(driver.find_elements(By.CSS_SELECTOR, selector))
        logger.info(f"  Selector '{label}': found {count} elements")

    # Sample a data-urn value if any exist
    try:
        urn_elements = driver.find_elements(By.CSS_SELECTOR, "[data-urn]")
        if urn_elements:
            sample_urns = [e.get_attribute("data-urn") for e in urn_elements[:3]]
            logger.info(f"  Sample data-urn values: {sample_urns}")
    except Exception:
        pass

    # Also dump a small piece of the page body for analysis
    try:
        body_text = driver.find_element(By.TAG_NAME, "body").text[:500]
        logger.info(f"  Page body preview: {body_text[:200]}...")
    except Exception:
        pass
    logger.info("--- END DEBUG ---")


def _try_click_see_more(driver: webdriver.Chrome, container):
    """Try to click the 'see more' button within a post container."""
    see_more_selectors = [
        "button[data-testid='expandable-text-button']",
        "button.feed-shared-inline-show-more-text__see-more-less-toggle",
        "button[class*='see-more']",
        "button[aria-label*='see more']",
        "button[aria-label*='See more']",
        "span.feed-shared-inline-show-more-text__see-more-less-toggle",
    ]
    for sel in see_more_selectors:
        try:
            btn = container.find_element(By.CSS_SELECTOR, sel)
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
            time.sleep(0.3)
            driver.execute_script("arguments[0].click();", btn)
            time.sleep(0.5)
            return
        except (NoSuchElementException, StaleElementReferenceException):
            continue


def _extract_post_text(container) -> str:
    """Try multiple selector strategies to get the post's text content."""
    text_selectors = [
        "span[data-testid='expandable-text-box']",
        "div[data-testid='expandable-text-box']",
        "*[data-testid='expandable-text-box']",
        "span.break-words",
        "div.feed-shared-text span[dir='ltr']",
        "div.feed-shared-text",
        "div.feed-shared-update-v2__description",
        "div.update-components-text",
        "div[class*='update-components-text']",
        "div[class*='feed-shared-text']",
    ]
    for sel in text_selectors:
        try:
            el = container.find_element(By.CSS_SELECTOR, sel)
            text = el.text.strip()
            if text and len(text) > 20:
                return text
        except (NoSuchElementException, StaleElementReferenceException):
            continue

    # Fallback: get all text from the container itself
    try:
        return container.text.strip()
    except StaleElementReferenceException:
        return ""


def _extract_element_text(container, selectors: list[str], default: str = "") -> str:
    """Try multiple selectors and return the first match's text."""
    for sel in selectors:
        try:
            el = container.find_element(By.CSS_SELECTOR, sel)
            text = el.text.strip()
            if text:
                return text
        except (NoSuchElementException, StaleElementReferenceException):
            continue
    return default


def _extract_post_url(driver, container, data_urn: str = "") -> str:
    """Try multiple strategies to extract the post's permalink.
    
    Strategy priority:
    1. Construct URL from data-urn if it contains an activity ID
    2. Use JavaScript to walk up/down the DOM tree to find any data-urn with 'activity'
    3. Find <a> tags whose href contains an activity URN or post permalink
    4. Use the three-dot menu → 'Copy link to post' as last resort
    5. Fall back to generic feed URL
    """
    # Strategy 1: Build URL directly from the data-urn attribute (if passed in)
    if data_urn and "activity" in data_urn:
        url = f"https://www.linkedin.com/feed/update/{data_urn}/"
        logger.info(f"  [URL] Strategy 1 (data-urn param): {url}")
        return url

    # Strategy 2: Use JavaScript to search ancestors and descendants for data-urn
    try:
        urn_from_js = driver.execute_script("""
            var el = arguments[0];
            
            // Check the element itself
            var urn = el.getAttribute('data-urn') || el.getAttribute('data-id') || '';
            if (urn && urn.indexOf('activity') !== -1) return urn;
            
            // Walk up the DOM tree (ancestors)
            var parent = el.parentElement;
            var depth = 0;
            while (parent && depth < 10) {
                urn = parent.getAttribute('data-urn') || parent.getAttribute('data-id') || '';
                if (urn && urn.indexOf('activity') !== -1) return urn;
                parent = parent.parentElement;
                depth++;
            }
            
            // Search descendants
            var descendants = el.querySelectorAll('[data-urn], [data-id]');
            for (var i = 0; i < descendants.length; i++) {
                urn = descendants[i].getAttribute('data-urn') || descendants[i].getAttribute('data-id') || '';
                if (urn && urn.indexOf('activity') !== -1) return urn;
            }
            
            return '';
        """, container)
        if urn_from_js and "activity" in urn_from_js:
            url = f"https://www.linkedin.com/feed/update/{urn_from_js}/"
            logger.info(f"  [URL] Strategy 2 (JS DOM walk): {url}")
            return url
    except (WebDriverException, StaleElementReferenceException):
        pass

    # Strategy 3: Use JavaScript to find any <a> with an activity/post permalink
    try:
        url_from_js = driver.execute_script("""
            var el = arguments[0];
            var links = el.querySelectorAll('a');
            for (var i = 0; i < links.length; i++) {
                var href = links[i].getAttribute('href') || '';
                if (href.indexOf('/feed/update/') !== -1 || 
                    (href.indexOf('activity') !== -1 && href.indexOf('linkedin.com') !== -1)) {
                    return href.split('?')[0];
                }
            }
            return '';
        """, container)
        if url_from_js and ("activity" in url_from_js or "/feed/update/" in url_from_js):
            logger.info(f"  [URL] Strategy 3 (JS link search): {url_from_js}")
            return url_from_js
    except (WebDriverException, StaleElementReferenceException):
        pass

    # Strategy 4: Try clicking the three-dot menu and extract the "Copy link to post" URL
    try:
        post_url = _extract_url_from_menu(driver, container)
        if post_url and post_url != "https://www.linkedin.com/feed/":
            logger.info(f"  [URL] Strategy 4 (menu click): {post_url}")
            return post_url
        else:
            logger.info(f"  [URL] Strategy 4 returned empty: '{post_url}'")
    except Exception as e:
        logger.info(f"  [URL] Strategy 4 exception: {type(e).__name__}: {e}")

    # Dump DOM diagnostics on first failure to help debug
    global _url_debug_dumped
    if not _url_debug_dumped:
        _url_debug_dumped = True
        _dump_dom_diagnostics(driver, container)

    logger.warning("  [URL] All strategies failed — falling back to generic feed URL")
    return "https://www.linkedin.com/feed/"


def _dump_dom_diagnostics(driver, container):
    """Dump DOM structure around a post container for debugging URL extraction."""
    import json as _json
    try:
        diag = driver.execute_script("""
            var el = arguments[0];
            var result = {};
            
            // Walk up ancestors and collect attributes
            var ancestors = [];
            var current = el;
            var depth = 0;
            while (current && depth < 15) {
                var attrs = {};
                for (var i = 0; i < current.attributes.length; i++) {
                    var a = current.attributes[i];
                    attrs[a.name] = a.value.substring(0, 200);
                }
                ancestors.push({
                    depth: depth,
                    tag: current.tagName,
                    attrs: attrs
                });
                current = current.parentElement;
                depth++;
            }
            result.ancestors = ancestors;
            
            // All links in container
            var links = el.querySelectorAll('a');
            var linkList = [];
            for (var i = 0; i < Math.min(links.length, 20); i++) {
                linkList.push({
                    href: (links[i].getAttribute('href') || '').substring(0, 300),
                    text: links[i].textContent.substring(0, 80).trim(),
                    ariaLabel: (links[i].getAttribute('aria-label') || '').substring(0, 100)
                });
            }
            result.links = linkList;
            
            // All links in ancestors (up 10 levels)
            current = el.parentElement;
            depth = 0;
            var parentLinks = [];
            while (current && depth < 10) {
                var pLinks = current.querySelectorAll('a[href*="activity"], a[href*="/feed/update/"], a[href*="/posts/"]');
                for (var i = 0; i < pLinks.length; i++) {
                    parentLinks.push({
                        parentDepth: depth,
                        href: (pLinks[i].getAttribute('href') || '').substring(0, 300)
                    });
                }
                current = current.parentElement;
                depth++;
            }
            result.parentLinks = parentLinks;
            
            // Buttons in container
            var buttons = el.querySelectorAll('button');
            var btnList = [];
            for (var i = 0; i < Math.min(buttons.length, 10); i++) {
                btnList.push({
                    ariaLabel: (buttons[i].getAttribute('aria-label') || '').substring(0, 100),
                    text: buttons[i].textContent.substring(0, 80).trim(),
                    class: (buttons[i].className || '').substring(0, 150)
                });
            }
            result.buttons = btnList;
            
            // Container's opening HTML tag (first 500 chars)
            result.containerHtml = el.outerHTML.substring(0, 500);
            
            return result;
        """, container)
        
        os.makedirs("logs", exist_ok=True)
        with open("logs/dom_debug.json", "w", encoding="utf-8") as f:
            _json.dump(diag, f, indent=2, ensure_ascii=False)
        logger.info("  [URL DEBUG] DOM diagnostics saved to logs/dom_debug.json")
        
        # Also log key findings
        logger.info(f"  [URL DEBUG] Links in container: {len(diag.get('links', []))}")
        logger.info(f"  [URL DEBUG] Activity links in parents: {len(diag.get('parentLinks', []))}")
        logger.info(f"  [URL DEBUG] Buttons in container: {len(diag.get('buttons', []))}")
        for link in diag.get('links', [])[:5]:
            logger.info(f"    Link: {link['href'][:100]}")
        for btn in diag.get('buttons', [])[:3]:
            logger.info(f"    Button: aria-label='{btn['ariaLabel']}' text='{btn['text']}'")
    except Exception as e:
        logger.warning(f"  [URL DEBUG] Failed to dump diagnostics: {e}")

def _extract_url_from_menu(driver, container) -> str:
    """Click the three-dot (overflow) menu on a post and extract the post URL
    from the 'Copy link to post' option.
    
    LinkedIn has removed data-urn and activity links from the feed DOM.
    The only reliable way to get the post URL is through this menu.
    """
    try:
        # Step 1: Find the three-dot menu button
        # From DOM diagnostics: aria-label="Open control menu for post by <Author>"
        menu_btn = None
        try:
            menu_btn = container.find_element(
                By.CSS_SELECTOR, "button[aria-label*='control menu']"
            )
        except NoSuchElementException:
            pass
        
        if not menu_btn:
            # Broader search
            try:
                buttons = container.find_elements(By.TAG_NAME, "button")
                for btn in buttons:
                    label = btn.get_attribute("aria-label") or ""
                    if "control menu" in label.lower() or "more actions" in label.lower():
                        menu_btn = btn
                        break
            except Exception:
                pass
        
        if not menu_btn:
            logger.info("  [MENU] No menu button found in container")
            return ""
        
        # Step 2: Scroll into view and click the menu
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", menu_btn)
        time.sleep(0.5)
        driver.execute_script("arguments[0].click();", menu_btn)
        time.sleep(1.0)
        
        # Step 3: Find "Copy link to post" in the dropdown
        # LinkedIn dropdowns may be portalled to body, so search the whole page
        copy_link_el = None
        
        # Method A: Find by text content using XPath (most reliable)
        copy_link_xpaths = [
            "//*[contains(text(), 'Copy link to post')]",
            "//*[contains(text(), 'Copy link')]",
            "//span[contains(text(), 'Copy link')]",
            "//p[contains(text(), 'Copy link')]",
            "//div[contains(text(), 'Copy link')]",
        ]
        for xpath in copy_link_xpaths:
            try:
                elements = driver.find_elements(By.XPATH, xpath)
                for el in elements:
                    if el.is_displayed():
                        copy_link_el = el
                        break
                if copy_link_el:
                    break
            except Exception:
                continue
        
        if not copy_link_el:
            # Method B: Use JavaScript to find any visible element with "Copy link" text
            try:
                copy_link_el = driver.execute_script("""
                    var walker = document.createTreeWalker(
                        document.body, NodeFilter.SHOW_TEXT, null, false
                    );
                    while (walker.nextNode()) {
                        var text = walker.currentNode.textContent.trim();
                        if (text === 'Copy link to post' || text === 'Copy link') {
                            var parent = walker.currentNode.parentElement;
                            if (parent && parent.offsetParent !== null) {
                                return parent;
                            }
                        }
                    }
                    return null;
                """)
            except Exception:
                pass
        
        if not copy_link_el:
            logger.info("  [MENU] 'Copy link' option not found in dropdown")
            # Close menu
            try:
                driver.execute_script("arguments[0].click();", menu_btn)
                time.sleep(0.3)
            except Exception:
                # Press Escape to close dropdown
                try:
                    from selenium.webdriver.common.keys import Keys
                    driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
                    time.sleep(0.3)
                except Exception:
                    pass
            return ""
        
        # Step 4: Click the "Copy link" element (it copies URL to clipboard)
        # First, try to find the clickable parent (li or div that acts as menu item)
        clickable = driver.execute_script("""
            var el = arguments[0];
            // Walk up to find the clickable menu item (usually an li or div with role)
            var current = el;
            var depth = 0;
            while (current && depth < 5) {
                var role = current.getAttribute('role') || '';
                var tag = current.tagName.toLowerCase();
                if (role === 'menuitem' || role === 'option' || tag === 'li' || 
                    current.onclick || current.getAttribute('tabindex')) {
                    return current;
                }
                current = current.parentElement;
                depth++;
            }
            return arguments[0];  // fallback to the element itself
        """, copy_link_el)
        
        # Step 5: Intercept the clipboard write BEFORE clicking
        # Override navigator.clipboard.writeText to capture the URL
        driver.execute_script("""
            window.__capturedClipboard = '';
            var origWrite = navigator.clipboard.writeText.bind(navigator.clipboard);
            navigator.clipboard.writeText = function(text) {
                window.__capturedClipboard = text;
                return origWrite(text);
            };
        """)
        
        driver.execute_script("arguments[0].click();", clickable)
        time.sleep(1.0)
        
        # Step 6: Read the intercepted clipboard value
        try:
            captured_url = driver.execute_script("return window.__capturedClipboard || '';")
            if captured_url and "linkedin.com" in captured_url:
                logger.info(f"  [MENU] Got URL from clipboard interception: {captured_url}")
                return captured_url.split("?")[0]
            else:
                logger.info(f"  [MENU] Clipboard interception captured: '{captured_url}'")
        except Exception as e:
            logger.info(f"  [MENU] Clipboard interception read failed: {e}")
        
        # Fallback: Try navigator.clipboard.readText() via async JS
        try:
            clipboard_url = driver.execute_async_script("""
                var callback = arguments[arguments.length - 1];
                navigator.clipboard.readText().then(function(text) {
                    callback(text);
                }).catch(function(err) {
                    callback('');
                });
            """)
            if clipboard_url and "linkedin.com" in clipboard_url:
                logger.info(f"  [MENU] Got URL from clipboard read: {clipboard_url}")
                return clipboard_url.split("?")[0]
        except Exception:
            pass
        
        # Fallback: Use pyperclip (system clipboard)
        try:
            import pyperclip
            clipboard_url = pyperclip.paste()
            if clipboard_url and "linkedin.com" in clipboard_url:
                logger.info(f"  [MENU] Got URL from pyperclip: {clipboard_url}")
                return clipboard_url.split("?")[0]
        except Exception:
            pass
        
        logger.info("  [MENU] Could not read clipboard after clicking 'Copy link'")
    
    except (NoSuchElementException, StaleElementReferenceException, TimeoutException) as e:
        logger.info(f"  [MENU] Error: {e}")
    except Exception as e:
        logger.info(f"  [MENU] Unexpected error: {e}")
    
    return ""


def scrape_linkedin_feed(
    email: str,
    password: str,
    max_posts: int = 50,
    headless: bool = False,
) -> list[LinkedInPost]:
    """
    Main entry point. Logs in (or reuses session), scrolls feed,
    returns list of LinkedInPost objects that contain an email address.
    """
    driver = _build_driver(headless=headless)
    posts: list[LinkedInPost] = []

    try:
        success = login_linkedin(driver, email, password)
        if not success:
            logger.error("Aborting scrape -- login failed.")
            return []

        raw_posts = _scroll_and_collect_posts(driver, max_posts=max_posts)

        for rp in raw_posts:
            posts.append(
                LinkedInPost(
                    post_id=rp["post_id"],
                    author_name=rp["author_name"],
                    author_title=rp["author_title"],
                    post_text=rp["post_text"],
                    recruiter_email=rp["recruiter_email"],
                    post_url=rp["post_url"],
                )
            )

    finally:
        driver.quit()

    return posts
