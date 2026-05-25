"""
debug_dom.py
Quick script to dump the DOM structure around LinkedIn feed posts
to understand what attributes/links are available for URL extraction.
"""
import os
import time
import json
from pathlib import Path
from dotenv import load_dotenv
from selenium.webdriver.common.by import By
from linkedin_scraper import _build_driver, login_linkedin

load_dotenv()

EMAIL = os.getenv("LINKEDIN_EMAIL", "")
PASSWORD = os.getenv("LINKEDIN_PASSWORD", "")

driver = _build_driver(headless=False)

try:
    success = login_linkedin(driver, EMAIL, PASSWORD)
    if not success:
        print("Login failed!")
        exit(1)
    
    time.sleep(5)
    
    # Dump all elements with data-urn on the page
    print("\n=== ALL data-urn elements ===")
    urn_els = driver.find_elements(By.CSS_SELECTOR, "[data-urn]")
    print(f"Found {len(urn_els)} elements with data-urn")
    for i, el in enumerate(urn_els[:5]):
        print(f"  [{i}] tag={el.tag_name}, data-urn={el.get_attribute('data-urn')}")
    
    # Check expandable text boxes
    print("\n=== expandable-text-box elements ===")
    text_boxes = driver.find_elements(By.CSS_SELECTOR, "[data-testid='expandable-text-box']")
    print(f"Found {len(text_boxes)} text boxes")
    
    if text_boxes:
        # For the first text box, walk up the DOM and dump attributes
        print("\n=== Walking up from first text box ===")
        result = driver.execute_script("""
            var el = arguments[0];
            var info = [];
            var current = el;
            var depth = 0;
            while (current && depth < 20) {
                var attrs = {};
                for (var i = 0; i < current.attributes.length; i++) {
                    var attr = current.attributes[i];
                    // Only log interesting attributes
                    if (['class', 'data-urn', 'data-id', 'id', 'role', 'data-testid', 'aria-label'].indexOf(attr.name) !== -1) {
                        attrs[attr.name] = attr.value.substring(0, 100);
                    }
                }
                info.push({
                    depth: depth,
                    tag: current.tagName,
                    attrs: attrs
                });
                current = current.parentElement;
                depth++;
            }
            return info;
        """, text_boxes[0])
        
        for item in result:
            print(f"  depth={item['depth']} <{item['tag']}> {json.dumps(item['attrs'])}")
        
        # For the first text box, look for any links in the parent chain
        print("\n=== Links near first text box (searching up 15 levels) ===")
        links_info = driver.execute_script("""
            var el = arguments[0];
            var current = el;
            var depth = 0;
            var results = [];
            while (current && depth < 15) {
                var links = current.querySelectorAll('a');
                if (links.length > 0) {
                    for (var i = 0; i < Math.min(links.length, 10); i++) {
                        var href = links[i].getAttribute('href') || '';
                        if (href.indexOf('linkedin.com') !== -1 || href.indexOf('/feed/') !== -1 || href.indexOf('activity') !== -1) {
                            results.push({
                                depth: depth,
                                href: href.substring(0, 200),
                                text: links[i].textContent.substring(0, 50).trim(),
                                ariaLabel: (links[i].getAttribute('aria-label') || '').substring(0, 100)
                            });
                        }
                    }
                }
                current = current.parentElement;
                depth++;
            }
            return results;
        """, text_boxes[0])
        
        for link in links_info:
            print(f"  depth={link['depth']} href={link['href']}")
            if link['text']:
                print(f"    text: {link['text']}")
            if link['ariaLabel']:
                print(f"    aria-label: {link['ariaLabel']}")
        
        # Check the 3-dot menu / overflow button
        print("\n=== Looking for menu/overflow buttons near posts ===")
        menu_info = driver.execute_script("""
            var el = arguments[0];
            var current = el;
            var depth = 0;
            var results = [];
            while (current && depth < 15) {
                var buttons = current.querySelectorAll('button');
                for (var i = 0; i < buttons.length; i++) {
                    var label = buttons[i].getAttribute('aria-label') || '';
                    var cls = buttons[i].getAttribute('class') || '';
                    if (label || cls.indexOf('menu') !== -1 || cls.indexOf('control') !== -1 || cls.indexOf('dropdown') !== -1) {
                        results.push({
                            depth: depth,
                            ariaLabel: label.substring(0, 100),
                            class: cls.substring(0, 150),
                            text: buttons[i].textContent.substring(0, 50).trim()
                        });
                    }
                }
                if (results.length > 0) break;  // found buttons, stop
                current = current.parentElement;
                depth++;
            }
            return results;
        """, text_boxes[0])
        
        for btn in menu_info:
            print(f"  depth={btn['depth']} aria-label='{btn['ariaLabel']}' class='{btn['class']}'")
            if btn['text']:
                print(f"    text: {btn['text']}")
        
        # Check the container matched by our XPath
        print("\n=== Container matched by ancestor::div[position()=5] ===")
        container = driver.find_element(
            By.XPATH,
            "//span[@data-testid='expandable-text-box']/ancestor::div[position()=5]"
        )
        container_info = driver.execute_script("""
            var el = arguments[0];
            var attrs = {};
            for (var i = 0; i < el.attributes.length; i++) {
                attrs[el.attributes[i].name] = el.attributes[i].value.substring(0, 200);
            }
            return {
                tag: el.tagName,
                attrs: attrs,
                childCount: el.children.length,
                outerHTMLLen: el.outerHTML.length
            };
        """, container)
        print(f"  <{container_info['tag']}> children={container_info['childCount']} html_len={container_info['outerHTMLLen']}")
        print(f"  attrs: {json.dumps(container_info['attrs'], indent=2)}")
        
        # Try to find the REAL post container by searching for a common parent
        print("\n=== Looking for the real post container with identifying attrs ===")
        real_container = driver.execute_script("""
            var el = arguments[0];
            var current = el;
            var depth = 0;
            while (current && depth < 20) {
                // Check for any attribute that looks like an identifier
                var urn = current.getAttribute('data-urn') || '';
                var dataId = current.getAttribute('data-id') || '';
                var id = current.id || '';
                
                if (urn || dataId || (id && id.length > 5)) {
                    return {
                        depth: depth,
                        tag: current.tagName,
                        dataUrn: urn,
                        dataId: dataId,
                        id: id,
                        className: (current.className || '').substring(0, 200)
                    };
                }
                current = current.parentElement;
                depth++;
            }
            return null;
        """, text_boxes[0])
        
        if real_container:
            print(f"  Found at depth {real_container['depth']}: <{real_container['tag']}>")
            print(f"    data-urn: {real_container['dataUrn']}")
            print(f"    data-id: {real_container['dataId']}")
            print(f"    id: {real_container['id']}")
            print(f"    class: {real_container['className']}")
        else:
            print("  No parent with identifying attributes found!")
            
        # Last resort: dump a snippet of the outerHTML at various ancestor levels
        print("\n=== HTML snippets at various ancestor levels ===")
        snippets = driver.execute_script("""
            var el = arguments[0];
            var current = el;
            var depth = 0;
            var results = [];
            while (current && depth < 15) {
                var html = current.outerHTML || '';
                results.push({
                    depth: depth,
                    tag: current.tagName,
                    htmlStart: html.substring(0, 300),
                    className: (current.className || '').substring(0, 100)
                });
                current = current.parentElement;
                depth++;
            }
            return results;
        """, text_boxes[0])
        
        for s in snippets:
            print(f"\n  --- depth={s['depth']} <{s['tag']}> class='{s['className']}' ---")
            print(f"  {s['htmlStart'][:200]}...")

finally:
    input("\nPress Enter to close browser...")
    driver.quit()
