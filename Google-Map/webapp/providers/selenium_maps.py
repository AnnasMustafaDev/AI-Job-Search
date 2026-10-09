"""Google Maps via Selenium — the original main.py approach, as a provider.

Selectors (feed ``div[role=feed]``, cards ``a.hfpxzc``, title ``h1.DUwDvf``,
website ``data-item-id=authority``) come from main.py.
"""
import os
import random
import re
import subprocess
import time
from urllib.parse import parse_qs, quote_plus, unquote, urlparse
from urllib.request import urlopen

CARD_XPATH = ".//a[contains(@class,'hfpxzc') and contains(@href,'/maps/place/')]"
CONSENT_XPATHS = [
    "//button[contains(., 'Alle akzeptieren')]", "//button[contains(., 'Accept all')]",
    "//button[contains(., 'Zustimmen')]", "//button[@aria-label='Accept all']",
    "//button[@aria-label='Alle akzeptieren']",
]
SPONSORED_TOKENS = ("sponsored", "gesponsert", "promoted", "anzeige")


def create_driver(browser_cfg, log):
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options

    mode = browser_cfg.get("mode", "attach")
    options = Options()
    if mode == "attach":
        port = int(browser_cfg.get("debug_port", 9222))
        address = f"127.0.0.1:{port}"
        if not _debug_endpoint_up(address):
            chrome = browser_cfg.get("chrome_path")
            if not chrome or not os.path.exists(chrome):
                raise RuntimeError("Chrome not found. Set the Chrome path under Crawler & Browser.")
            os.makedirs(browser_cfg["profile_dir"], exist_ok=True)
            log("info", f"Starting Chrome with remote debugging on {address}")
            subprocess.Popen([chrome, f"--remote-debugging-port={port}",
                              f"--user-data-dir={browser_cfg['profile_dir']}",
                              "--no-first-run", "--no-default-browser-check"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            for _ in range(40):
                if _debug_endpoint_up(address):
                    break
                time.sleep(0.5)
            else:
                raise RuntimeError(f"Chrome debug endpoint {address} did not come up.")
        options.add_experimental_option("debuggerAddress", address)
        log("ok", f"Attached to Chrome at {address}")
    else:
        if mode == "headless":
            options.add_argument("--headless=new")
        options.add_argument("--window-size=1400,1000")
        options.add_argument("--lang=de-DE")
    # Selenium 4.6+ resolves a matching chromedriver by itself (Selenium Manager).
    return webdriver.Chrome(options=options)


def _debug_endpoint_up(address):
    try:
        with urlopen(f"http://{address}/json/version", timeout=1.5) as r:
            return r.status == 200
    except Exception:
        return False


def resolve_google_redirect(url):
    if url and "google." in url and "/url?" in url:
        q = parse_qs(urlparse(url).query)
        target = (q.get("q") or q.get("url") or [None])[0]
        if target:
            return unquote(target)
    return url


def _accept_consent(driver):
    from selenium.webdriver.common.by import By
    for xp in CONSENT_XPATHS:
        buttons = driver.find_elements(By.XPATH, xp)
        if buttons:
            try:
                buttons[0].click()
                time.sleep(1)
                return True
            except Exception:
                continue
    return False


def _text(driver, xpath):
    from selenium.webdriver.common.by import By
    els = driver.find_elements(By.XPATH, xpath)
    return els[0].text.strip() if els else None


def _attr(driver, xpath, attr):
    from selenium.webdriver.common.by import By
    els = driver.find_elements(By.XPATH, xpath)
    return els[0].get_attribute(attr) if els else None


def _place_details(driver):
    name = _text(driver, "//h1[contains(@class,'DUwDvf')]")
    website = _attr(driver, "//a[contains(@data-item-id,'authority') and @href]", "href") \
        or _attr(driver, "//a[contains(@aria-label,'Website') and @href]", "href") \
        or _attr(driver, "//a[contains(@aria-label,'Webseite') and @href]", "href")
    address = _attr(driver, "//button[@data-item-id='address']", "aria-label")
    phone = _attr(driver, "//button[starts-with(@data-item-id,'phone:tel:')]", "data-item-id")
    rating_text = _text(driver, "//div[contains(@class,'F7nice')]/span/span[@aria-hidden='true']") or ""
    # Maps in the EU shows no review count any more; keep None (unknown) rather than 0.
    reviews_label = _attr(driver, "//div[contains(@class,'F7nice')]//span[contains(@aria-label,'Rezensionen') or contains(@aria-label,'reviews')]", "aria-label") or ""
    category = _text(driver, "//button[contains(@jsaction,'category')]")
    closed_text = (_text(driver, "//span[contains(., 'Dauerhaft geschlossen') or contains(., 'Permanently closed')]") or "")
    return {
        "name": name,
        "website": resolve_google_redirect(website).split("?")[0] if website else None,
        "address": address.split(":", 1)[-1].strip() if address else None,
        "phone": phone.replace("phone:tel:", "") if phone else None,
        "rating": _num(rating_text),
        "reviews": int(_num(reviews_label.replace(".", "").replace(",", ""))) if _num(reviews_label.replace(".", "").replace(",", "")) else None,
        "category": category,
        "closed": bool(closed_text),
    }


CARD_RATING_RE = re.compile(r"(\d[,.]\d)\s*\(([\d.,\s]+)\)")


def _card_rating(text):
    """Result cards show rating and review count as '4,5(2.345)'."""
    m = CARD_RATING_RE.search(text or "")
    if not m:
        return None, None
    return float(m.group(1).replace(",", ".")), int(re.sub(r"\D", "", m.group(2)) or 0)


def _num(label):
    m = re.search(r"\d+(?:[.,]\d+)?", label or "")
    return float(m.group(0).replace(",", ".")) if m else None


def _wait_for_results(driver, timeout=12):
    """Wait until Maps shows a results feed, a single place panel, or a 'no results' message."""
    from selenium.webdriver.common.by import By
    end = time.time() + timeout
    while time.time() < end:
        if driver.find_elements(By.XPATH, "//div[@role='feed']"):
            return "feed"
        if driver.find_elements(By.XPATH, "//h1[contains(@class,'DUwDvf')]"):
            return "place"
        if _text(driver, "//div[contains(., 'Google Maps kann') or contains(., \"Google Maps can't find\")]"):
            return "none"
        time.sleep(0.5)
    return "none"


def _card_info(driver, href):
    """Re-find a card by its link each time: clicking a listing re-renders the feed,
    so element references from an earlier lookup go stale."""
    from selenium.webdriver.common.by import By
    cards = [c for c in driver.find_elements(By.XPATH, "//div[@role='feed']" + CARD_XPATH[1:])
             if c.get_attribute("href") == href]
    if not cards:
        return None, False, ""
    card = cards[0]
    label = " ".join(filter(None, [card.get_attribute("aria-label"), card.text])).lower()
    try:
        label += " " + card.find_element(By.XPATH, "./..").text.lower()
    except Exception:
        pass
    return card, any(t in label for t in SPONSORED_TOKENS), label


def _feed_hrefs(driver):
    from selenium.common.exceptions import StaleElementReferenceException
    from selenium.webdriver.common.by import By
    hrefs = []
    for c in driver.find_elements(By.XPATH, "//div[@role='feed']" + CARD_XPATH[1:]):
        try:
            h = c.get_attribute("href")
        except StaleElementReferenceException:
            continue
        if h and h not in hrefs:
            hrefs.append(h)
    return hrefs


def search(query, ctx):
    from selenium.common.exceptions import StaleElementReferenceException, WebDriverException
    from selenium.webdriver.common.by import By

    driver = ctx.driver()
    zoom = ctx.search.get("zoom", 14)
    lang = ctx.search.get("language", "de")
    url = f"https://www.google.com/maps/search/{quote_plus(query)}/?hl={lang}"
    if ctx.center:
        url = f"https://www.google.com/maps/search/{quote_plus(query)}/@{ctx.center['lat']},{ctx.center['lng']},{zoom}z?hl={lang}"
    driver.get(url)
    time.sleep(1)
    if _accept_consent(driver):
        ctx.log("info", "Privacy dialog accepted")

    kind = _wait_for_results(driver)
    if kind == "none":
        ctx.log("warn", f"No results on Google Maps for: {query}")
        return
    if kind == "place":
        # A single exact match opens the place panel directly.
        details = _place_details(driver)
        details.update(maps_url=driver.current_url, sponsored=False, lat=None, lng=None)
        yield details
        return

    seen, yielded, stagnant, errors = set(), 0, 0, 0
    while yielded < ctx.max_results and stagnant < 4 and not ctx.should_stop():
        ctx.wait_if_paused()
        hrefs = [h for h in _feed_hrefs(driver) if h not in seen]
        if not hrefs:
            feeds = driver.find_elements(By.XPATH, "//div[@role='feed']")
            if feeds:
                try:
                    driver.execute_script("arguments[0].scrollTop = arguments[0].scrollHeight", feeds[0])
                except StaleElementReferenceException:
                    pass
            time.sleep(1.5 + random.random())
            stagnant += 1
            if _text(driver, "//span[contains(., 'Ende der Liste') or contains(., \"You've reached the end\")]"):
                return
            continue
        stagnant = 0
        ctx.log("info", f"Feed loaded {len(seen) + len(hrefs)} listings")
        for href in hrefs:
            if ctx.should_stop() or yielded >= ctx.max_results:
                return
            ctx.wait_if_paused()
            seen.add(href)
            try:
                card, sponsored, card_text = _card_info(driver, href)
                if card is None:
                    continue
                name_hint = card.get_attribute("aria-label")
                if sponsored:
                    yield {"name": name_hint, "website": None, "sponsored": True, "maps_url": href}
                    continue
                driver.execute_script("arguments[0].scrollIntoView({block:'center'})", card)
                card.click()
                time.sleep(ctx.delay())
                details = _place_details(driver)
            except (StaleElementReferenceException, WebDriverException) as e:
                errors += 1
                ctx.log("warn", f"Could not open listing ({type(e).__name__}); skipping")
                if errors > 15:
                    raise RuntimeError("Too many listing errors; Google Maps layout may have changed") from e
                continue
            m = re.search(r"!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)", unquote(href))
            details.update(maps_url=href, sponsored=False,
                           lat=float(m.group(1)) if m else None, lng=float(m.group(2)) if m else None)
            details["name"] = details["name"] or name_hint
            card_rating, card_reviews = _card_rating(card_text)
            details["rating"] = details["rating"] or card_rating
            details["reviews"] = details["reviews"] if details["reviews"] is not None else card_reviews
            yielded += 1
            yield details
