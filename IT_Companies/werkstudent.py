#!/usr/bin/env python3
"""
LinkedIn Werkstudent Job Scraper
=================================
Platform  : Linux (headless or GUI)
Goal      : Surface 25+ high-quality targeted jobs per day
Scope     : LinkedIn only (career pages = separate script)

What it does:
- Searches LinkedIn with Berlin-focused + broad keywords
- Extracts job description, classifies relevance (3 tiers)
- Tags location zone (Berlin / Remote / Near / Stretch / Other)
- Deduplicates across runs using Apply Link as key
- Saves to timestamped CSV + canonical CSV
- Uploads fresh jobs to Google Sheets
"""

import csv
import os
import re
import sys
import time
import random
import shutil
import tempfile
from datetime import datetime, timezone
from urllib.parse import urlencode

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException,
    NoSuchElementException,
    StaleElementReferenceException,
    WebDriverException,
    SessionNotCreatedException,
)

try:
    import gspread
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    GSHEETS_AVAILABLE = True
except ImportError:
    gspread = Credentials = InstalledAppFlow = Request = None
    GSHEETS_AVAILABLE = False


# ===========================================================================
# CONFIGURATION
# ===========================================================================

UPLOAD_ONLY_MODE = False  # True = skip scraping, only push existing CSV to Sheets
DEBUG_MODE       = False  # True = print verbose step logs

# --- LinkedIn Search ---
# Keywords are shuffled at runtime (anti-bot). Specific → broad ordering is
# intentional for readability but does not affect execution order.
SEARCH_KEYWORDS = [
    "working student data engineer",
    "werkstudent python sql",
    "werkstudent data analytics",
    "working student analytics english",
    "werkstudent data science",
    "working student devops",
    "werkstudent devops",
    "working student cloud infrastructure",
    "werkstudent cloud",
    "working student kubernetes",
    "werkstudent platform engineer",
    "student assistant data engineer",
    "student assistant data analytics",
    "student assistant devops",
    "student assistant cloud",
    "student assistant english",
    "student assistent",
    "research assistant",
    "research assistant germany english",
    "research assistent",
    "student jobs english speaking germany",
    "student job english speaking",
    "working student english speaking germany",
    "working student",
    "werkstudent",
    "student assistant",
]

LOCATION              = "Germany"
TIME_FILTER           = "r86400"        # past 24 hours — keeps results fresh
TIME_FILTER_LABEL     = "Past 24 Hours"
MAX_PAGES_PER_KEYWORD = 4               # freshest jobs are on page 1; 3 is enough
JOB_TYPE_FILTER       = "P,I,F"        # P = Part-time, I = Internship, F = Full-time (Werkstudent often mislabelled)

# --- Timing (anti-bot) ---
WAIT_SECONDS          = 15
ACTION_DELAY          = (1.5, 3.5)
PAGE_TRANSITION_DELAY = (2.0, 4.5)
SCROLL_PAUSE          = (0.7, 1.5)
CLICK_PAUSE           = (0.2, 0.6)
KEYWORD_COOLDOWN_EVERY = 4             # pause every N keywords
KEYWORD_COOLDOWN_RANGE = (15.0, 28.0)

# --- Paths ---
BASE_DIR  = os.path.dirname(os.path.abspath(__file__))
JOBS_DIR  = os.path.join(BASE_DIR, "Jobs")

SCRAPED_DATE_FORMAT = "%Y-%m-%d %H:%M"

# --- Google Sheets ---
GOOGLE_SHEET_ID = "1EtJXQmaOu2M51KAQ-KbXF_MiWaVOoVx7oE_xRrMG76o"
GOOGLE_SCOPES   = ["https://www.googleapis.com/auth/spreadsheets"]
SHEET_RELEVANT      = "Werkstudent Jobs (Relevant)"
SHEET_NON_RELEVANT  = "Werkstudent Jobs (Non Relevant)"

SHEET_HEADER = [
    "Scraped Date", "Time Filter", "Keyword",
    "Job Title", "Company", "Location", "Location_Zone",
    "Apply Link", "Skills Found", "Job_Category", "German_Level",
    "Relevance_Score", "Relevance", "Search_Tag",
]

OUTPUT_FIELDNAMES = SHEET_HEADER  # CSV columns match sheet columns

# --- LinkedIn CSS selectors ---
# Multiple fallbacks per element — LinkedIn changes these regularly
JOB_CARD_SELECTOR = (
    "div.base-search-card, "
    "li.jobs-search-results__list-item, "
    "div.job-card-container"
)
TITLE_SELECTOR = (
    "h3.base-search-card__title, "
    "a.job-card-list__title, "
    "a.job-card-container__link strong"
)
COMPANY_SELECTOR = (
    "h4.base-search-card__subtitle, "
    "span.job-card-container__primary-description, "
    ".job-card-container__company-name, "
    "a.job-card-container__company-name, "
    ".artdeco-entity-lockup__subtitle span, "
    ".job-card-list__company-name, "
    ".job-card-container__company-name a"
)
# Selectors for company name in the right-side detail panel (after clicking a card)
COMPANY_DETAIL_SELECTORS = (
    ".jobs-unified-top-card__company-name",
    "a.jobs-unified-top-card__company-name",
    "span.jobs-unified-top-card__company-name",
    ".job-details-jobs-unified-top-card__company-name",
    ".job-details-jobs-unified-top-card__company-name a",
    ".jobs-details-top-card__company-url",
)
LOCATION_SELECTOR = (
    "span.job-search-card__location, "
    "ul.job-card-container__metadata-wrapper li"
)
LINK_SELECTOR = (
    "a.base-card__full-link, "
    "a.job-card-list__title, "
    "a.job-card-container__link"
)
POSTED_DATE_SELECTOR = (
    "time.job-search-card__listdate, "
    "time.job-search-card__listdate--new, "
    "time[datetime]"
)
POSTED_TEXT_SELECTOR = (
    "time, "
    ".job-search-card__listdate, "
    ".job-search-card__listdate--new, "
    ".job-search-card__listdate--reposted"
)
DESCRIPTION_SELECTORS = (
    "div.show-more-less-html__markup",
    "div.jobs-description__content",
    "div.jobs-box__html-content",
)
PAGINATION_SELECTOR = "div.jobs-search-pagination"
LIST_SCROLL_SELECTORS = (
    ".scaffold-layout__list",
    ".jobs-search-results-list",
    ".jobs-search-results-list__list-container",
)


# ===========================================================================
# LOCATION ZONES
# Ranked by commute viability from Berlin/Cottbus.
# Checked in order: Remote → Zone1 → Zone2 → Zone3 → Other
# ===========================================================================

_ZONE_REMOTE = [
    "remote", "homeoffice", "home office",
    "anywhere", "deutschlandweit",
]
_ZONE1 = [
    "berlin", "potsdam", "cottbus", "falkensee", "oranienburg",
    "bernau", "erkner", "strausberg", "ludwigsfelde", "teltow",
    "zossen", "hennigsdorf", "velten", "nauen", "eberswalde",
    "neuruppin", "rathenow",
]
_ZONE2 = [  # ~1-2 hr by train
    "leipzig", "halle", "dresden", "hamburg", "hannover",
    "magdeburg", "rostock", "erfurt", "jena", "chemnitz",
    "schwerin", "braunschweig", "wolfsburg",
]
_ZONE3 = [  # ~2-3 hr, stretch
    "cologne", "koeln", "köln", "duesseldorf", "düsseldorf",
    "frankfurt", "munich", "muenchen", "münchen", "stuttgart",
    "nuremberg", "nuernberg", "nürnberg", "dortmund", "essen",
    "bremen", "wiesbaden", "mainz", "mannheim", "heidelberg",
    "karlsruhe", "freiburg", "bonn", "bielefeld", "muenster",
    "münster", "augsburg",
]

ZONE_ORDER = {
    "Zone1_Berlin": 0,
    "Remote":       1,
    "Zone2_Near":   2,
    "Zone3_Stretch":3,
    "Other":        4,
}


# ===========================================================================
# SKILL PATTERNS
# Core skills count 2x in scoring. Supporting skills count 1x.
# Jobs with 0 core + <2 supporting = non_relevant (filtered out).
# ===========================================================================

_DATA_CORE_SKILLS = [
    (r"\bpython\b",           "Python"),
    (r"\bsql\b",              "SQL"),
    (r"\bdata\s+engineering\b","Data Engineering"),
    (r"\betl\b",              "ETL"),
    (r"\bairflow\b",          "Airflow"),
    (r"\bpipeline\b",         "Pipeline"),
    (r"\bdata\s+science\b",   "Data Science"),
    (r"\bmachine\s+learning\b","Machine Learning"),
]
_WEB_CORE_SKILLS = [
    (r"\bjavascript\b|\bjs\b",          "JavaScript"),
    (r"\btypescript\b",                 "TypeScript"),
    (r"\breact\b",                      "React"),
    (r"\bnode\.?js\b",                  "Node.js"),
    (r"\bjava\b",                       "Java"),
    (r"\bspring\b",                     "Spring"),
    (r"\bbackend\b",                    "Backend"),
    (r"\bfull[\s-]?stack\b",            "Full-Stack"),
    (r"\bfrontend\b",                   "Frontend"),
    (r"\bvue\.?js\b|\bvuejs\b",         "Vue.js"),
    (r"\bangular\b",                    "Angular"),
    (r"\bdjango\b",                     "Django"),
    (r"\bfastapi\b",                    "FastAPI"),
    (r"\brest\s*(api|ful)?\b",          "REST API"),
    (r"\bgraphql\b",                    "GraphQL"),
]
_WEB_SUPPORTING_SKILLS = [
    (r"\bgit\b",                        "Git"),
    (r"\bhtml\b",                       "HTML"),
    (r"\bcss\b",                        "CSS"),
    (r"\bpostgresql\b|\bpostgres\b",    "PostgreSQL"),
    (r"\bmysql\b",                      "MySQL"),
    (r"\bmongodb\b",                    "MongoDB"),
    (r"\bredis\b",                      "Redis"),
    (r"\bflask\b",                      "Flask"),
    (r"\brust\b",                       "Rust"),
    (r"\bgo\b|\bgolang\b",              "Go"),
    (r"\bc\+\+\b",                      "C++"),
    (r"\bc#\b|\bdotnet\b|\.net\b",      ".NET"),
    (r"\bscrum\b|\bagile\b",            "Agile"),
    (r"\bjira\b",                       "Jira"),
]
_DATA_SUPPORTING_SKILLS = [
    (r"\bpower\s*bi\b",       "Power BI"),
    (r"\btableau\b",          "Tableau"),
    (r"\baws\b",              "AWS"),
    (r"\bazure\b",            "Azure"),
    (r"\bgcp\b|\bgoogle\s+cloud\b", "GCP"),
    (r"\bdata\s+analytics?\b","Data Analytics"),
    (r"\bdata\s+analysis\b",  "Data Analysis"),
    (r"\bpandas\b",           "Pandas"),
    (r"\bnumpy\b",            "NumPy"),
    (r"\blinux\b",            "Linux"),
    (r"\bartificial\s+intelligence\b|\bai\b", "AI"),
    (r"k[uü]nstliche\s+intelligenz|\bki\b",   "KI"),
    (r"\bexcel\b",            "Excel"),
]
_DEVOPS_CORE_SKILLS = [
    (r"\bdevops\b",              "DevOps"),
    (r"\bci\s*/\s*cd\b",         "CI/CD"),
    (r"\bcicd\b",                 "CI/CD"),
    (r"\bgithub\s+actions\b",    "GitHub Actions"),
    (r"\bjenkins\b",              "Jenkins"),
    (r"\bkubernetes\b|\bk8s\b",  "Kubernetes"),
    (r"\bterraform\b",            "Terraform"),
    (r"\bansible\b",              "Ansible"),
    (r"\bhelm\b",                 "Helm"),
    (r"\bdocker\b",               "Docker"),
    (r"\bsite\s+reliability\b|\bsre\b", "SRE"),
    (r"\bplatform\s+engineering\b", "Platform Engineering"),
]
_DEVOPS_SUPPORTING_SKILLS = [
    (r"\bcloud\b",                "Cloud"),
    (r"\baws\b",                  "AWS"),
    (r"\baurora\b",               "AWS Aurora"),
    (r"\beks\b",                  "EKS"),
    (r"\becs\b",                  "ECS"),
    (r"\bec2\b",                  "EC2"),
    (r"\bs3\b",                   "S3"),
    (r"\blambda\b",               "Lambda"),
    (r"\bgcp\b|\bgoogle\s+cloud\b", "GCP"),
    (r"\bazure\b",                "Azure"),
    (r"\blinux\b",                "Linux"),
    (r"\bmonitoring\b",           "Monitoring"),
    (r"\bobservability\b",        "Observability"),
    (r"\bprometheus\b",           "Prometheus"),
    (r"\bgrafana\b",              "Grafana"),
    (r"\bgitlab\s+ci\b",         "GitLab CI"),
]
_EXCLUDE_TITLE_PATTERNS = [
    r"\bdatenschutz\b",
    r"\bcyber\s*security\b",
    r"\bembedded\b",
    r"\bhardware\b",
    r"\baccounting\b",
    r"\bsales\b",
    r"\bmarketing\b",
    r"\bsocial\s+media\b",
    r"\beinkauf\b",
    r"\blogistik\b",
    r"\bpcb\b",
    r"\breception\b",
    r"\bcustomer\s+service\b",
    r"\bhuman\s+resources\b",
]

_EXCLUDED_COMPANIES_RAW = [
    # Exact companies to skip (case / punctuation variations handled at runtime)
    "adesso SE",
    "Mercor",   # explicitly exclude Mercor (user requested strict exclusion)
    "Deloitte",
]

_REPOSTED_PATTERNS = [
    r"\breposted\b",
    r"\bre-publication\b",
    r"\brepublished\b",
    r"\berneut\s+veroeffentlicht\b",
    r"\berneut\s+vero\b",  # catches short OCR-like truncation variants
]


# ===========================================================================
# HELPERS
# ===========================================================================

def debug(msg):
    if DEBUG_MODE:
        print(f"[DEBUG] {msg}")


def pause(delay_range, reason=""):
    lo, hi = delay_range
    if hi < lo:
        lo, hi = hi, lo
    secs = random.uniform(lo, hi)
    debug(f"Pause {secs:.2f}s — {reason}")
    time.sleep(secs)


def _normalize(text):
    """Lowercase + fold German umlauts for location matching."""
    t = (text or "").strip().lower()
    return (t.replace("ä", "ae").replace("ö", "oe")
             .replace("ü", "ue").replace("ß", "ss"))


def _normalize_company(name):
    """Normalize company names for exact blocking checks."""
    cleaned = _normalize(name)
    return re.sub(r"[^a-z0-9]+", "", cleaned)


def is_excluded_company(company_name):
    """Return True if company_name matches any excluded company.

    Matching is case-insensitive and folded — punctuation and whitespace are
    removed before comparison so variants like "Adesso SE", "adesso se",
    "AdessoSE GmbH" will be caught. The function checks exact normalized
    equality and also substring presence to cover common suffixes/prefixes.
    """
    if not company_name:
        return False
    normalized = _normalize_company(company_name)
    for raw in _EXCLUDED_COMPANIES_RAW:
        raw_norm = re.sub(r"[^a-z0-9]+", "", (raw or "").strip().lower())
        if not raw_norm:
            continue
        if normalized == raw_norm:
            return True
        if raw_norm in normalized:
            return True
    return False


def classify_location_zone(location_text):
    n = _normalize(location_text)
    for tok in _ZONE_REMOTE:
        if tok in n:
            return "Remote"
    for tok in _ZONE1:
        if tok in n:
            return "Zone1_Berlin"
    for tok in _ZONE2:
        if tok in n:
            return "Zone2_Near"
    for tok in _ZONE3:
        if tok in n:
            return "Zone3_Stretch"
    return "Other"


def extract_skills(description):
    text = (description or "").lower()
    found = []
    all_patterns = (
        _DATA_CORE_SKILLS + _DATA_SUPPORTING_SKILLS
        + _DEVOPS_CORE_SKILLS + _DEVOPS_SUPPORTING_SKILLS
        + _WEB_CORE_SKILLS + _WEB_SUPPORTING_SKILLS
    )
    for pattern, label in all_patterns:
        if re.search(pattern, text) and label not in found:
            found.append(label)
    return ", ".join(found)


def _count_skill_hits(text, skill_patterns):
    return sum(1 for pattern, _ in skill_patterns if re.search(pattern, text))


def classify_job_category(title, description):
    text = f"{title or ''}\n{description or ''}".lower()
    data_hits = _count_skill_hits(text, _DATA_CORE_SKILLS) * 2 + _count_skill_hits(text, _DATA_SUPPORTING_SKILLS)
    devops_hits = _count_skill_hits(text, _DEVOPS_CORE_SKILLS) * 2 + _count_skill_hits(text, _DEVOPS_SUPPORTING_SKILLS)
    web_hits = _count_skill_hits(text, _WEB_CORE_SKILLS) * 2 + _count_skill_hits(text, _WEB_SUPPORTING_SKILLS)

    best = max(data_hits, devops_hits, web_hits)
    if best == 0:
        return "Other"
    if web_hits == best:
        return "Web/Backend"
    if devops_hits == best:
        return "DevOps"
    return "Data"


def classify_german(description):
    text = _normalize(description)
    compact = _normalize_company(description)
    negative = [
        r"\bno\s+(german|deutsch)\b",
        r"\bwithout\s+(german|deutsch)\b",
        r"\b(german|deutsch).{0,30}\bnot\s+required\b",
        r"\b(german|deutsch).{0,30}\bnot\s+mandatory\b",
        r"\benglish\s+only\b",
        r"\bno\s+german\s+required\b",
        r"\bno\s+deutsch\s+required\b",
        r"\bkeine\s+deutschkenntnisse\s+erforderlich\b",
        r"\bkeine\s+deutschen\s+kenntnisse\s+erforderlich\b",
        r"\bkeine\s+deutschkenntnisse\b",
        r"\bkeine\s+deutschen\s+kenntnisse\b",
        r"\bkein\s+deutsch\s+erforderlich\b",
        r"\bdeutschkenntnisse\s+nicht\s+erforderlich\b",
        r"\bdeutsche\s+kenntnisse\s+nicht\s+erforderlich\b",
    ]
    required = [
        r"\bflie(ss|ß)end\s+deutsch\b",
        r"\bfluent\s+in\s+german\b",
        r"\bbusiness\s+fluent\s+german\b",
        r"\bgerman\s+language\s+skills\s+(required|mandatory)\b",
        r"\bgerman\s+skills\s+(required|mandatory)\b",
        r"\bgerman\s+(language\s+)?(is\s+)?(required|mandatory|a\s+must|must)\b",
        r"\bdeutsch\s+(is\s+)?(required|mandatory|necessary|needed)\b",
        r"\bverhandlungssicher\b",
        r"\bsehr\s+gute\s+deutschkenntnisse\b",
        r"\bsehr\s+gute\s+deutsche\s+kenntnisse\b",
        r"\bgute\s+kenntnisse\s+der\s+deutschen\s+sprache\b",
        r"\bdeutsch\s+in\s+wort\s+und\s+schrift\b",
        r"\bdeutschkenntnisse\s+(sind\s+)?(erforderlich|vorausgesetzt|notwendig|gefordert|needed|required)\b",
        r"\b(deutsche\s+kenntnisse|deutschkenntnisse|deutsch\s+sprachkenntnisse)\s+(sind\s+)?(erforderlich|vorausgesetzt|notwendig|gefordert|needed|required)\b",
        r"\b(b2|c1|c2)\b.{0,40}(deutsch|german|german\s+language)",
        r"(deutsch|german|german\s+language).{0,40}\b(b2|c1|c2)\b",
        r"\b(native|fluent|excellent|very\s+good)\s+(german|deutsch)\b",
        r"\b(german|deutsch)\s+(native|fluent|excellent|very\s+good)\b",
        r"\b(german|deutsch).{0,40}\b(required|mandatory|necessary|needed|erforderlich|vorausgesetzt|notwendig|gefordert)\b",
    ]
    preferred = [
        r"\bgute\s+deutschkenntnisse\b",
        r"\bgute\s+deutsche\s+kenntnisse\b",
        r"\bdeutschkenntnisse.{0,40}(von\s+vorteil|wuenschenswert|plus|nice)\b",
        r"\bdeutsche\s+kenntnisse.{0,40}(von\s+vorteil|wuenschenswert|plus|nice)\b",
        r"\bgerman.{0,40}(nice\s+to\s+have|plus|preferred|advantage|beneficial)\b",
        r"\bdeutsch.{0,40}(nice\s+to\s+have|plus|preferred|advantage|beneficial)\b",
        r"\bgute\s+kenntnisse\s+in\s+deutsch\b",
        r"\b(b1)\b.{0,40}(deutsch|german).{0,40}(required|mandatory|erforderlich|vorausgesetzt)",
        r"\b(a1|a2|b1)\b.{0,40}(deutsch|german)",
        r"(deutsch|german).{0,40}\b(a1|a2|b1)\b",
    ]
    compact_negative = [
        "nodeutsch",
        "nogerman",
        "keinedeutschkenntnisse",
        "keinedeutschenkenntnisse",
        "keindeutsch",
        "deutschkenntnissenichterforderlich",
        "deutschekenntnissenichterforderlich",
        "germannotrequired",
        "germannotmandatory",
        "germanisnotrequired",
        "deutschisnotrequired",
    ]
    for token in compact_negative:
        if token in compact:
            return "not_required"
    for p in negative:
        if re.search(p, text):
            return "not_required"
    for p in required:
        if re.search(p, text):
            return "required"
    for p in preferred:
        if re.search(p, text):
            return "preferred"
    return "not_required"


def classify_relevance(title, description):
    """
    Returns (relevance_label, score).
    relevance_label: 'high_relevant' | 'relevant' | 'non_relevant'
    Score = core_hits*2 + supporting_hits + title_core_hits*3 (higher = better match).
    """
    title_lower = (title or "").lower()
    text = (description or "").lower()

    # Reject by title first — fast filter
    for pat in _EXCLUDE_TITLE_PATTERNS:
        if re.search(pat, title_lower):
            debug(f"Title excluded: {title!r} matched {pat}")
            return "non_relevant", 0.0

    all_core = _DATA_CORE_SKILLS + _DEVOPS_CORE_SKILLS + _WEB_CORE_SKILLS
    all_supporting = _DATA_SUPPORTING_SKILLS + _DEVOPS_SUPPORTING_SKILLS + _WEB_SUPPORTING_SKILLS

    core_hits = _count_skill_hits(text, all_core)
    supporting_hits = _count_skill_hits(text, all_supporting)
    # Title matches are weighted higher — a job titled "Werkstudent React Developer"
    # should surface even if the description is thin.
    title_core_hits = _count_skill_hits(title_lower, all_core)
    score = float(core_hits * 2 + supporting_hits + title_core_hits * 3)

    if core_hits >= 1 or title_core_hits >= 1:
        return "high_relevant", score
    if supporting_hits >= 2:
        return "relevant", score
    return "non_relevant", 0.0


def classify_search_tag(keyword, title, description):
    text = f"{keyword or ''}\n{title or ''}\n{description or ''}".lower()
    if re.search(r"\bstudent\s+assistan[te]t\b", text):
        return "Student Assistent"
    if re.search(r"\bresearch\s+assistan[te]t\b", text):
        return "Research Assistent"
    if re.search(r"\benglish\s*[- ]?speaking\b", text) and re.search(r"\bstudent\b|\bworking\s+student\b|\bwerkstudent\b", text):
        return "English Speaking Student Job"
    return ""


# ===========================================================================
# SELENIUM HELPERS
# ===========================================================================

def build_driver():
    """
    Build Chrome driver for Linux.
    Persistent profile keeps LinkedIn session alive across runs —
    you only need to log in manually once.
    """
    opts = webdriver.ChromeOptions()

    # Use the installed Chrome binary explicitly when available.
    chrome_binary = shutil.which("google-chrome") or shutil.which("google-chrome-stable")
    if chrome_binary:
        opts.binary_location = chrome_binary

    # Run headless when no X session is available; otherwise use the desktop session.
    headless = not os.environ.get("DISPLAY")
    if headless:
        opts.add_argument("--headless=new")
        opts.add_argument("--disable-gpu")

    # Persistent Chrome profile — stores LinkedIn login session
    profile_path = os.path.join(BASE_DIR, "chrome_linkedin_profile")
    os.makedirs(profile_path, exist_ok=True)
    for stale_name in ("DevToolsActivePort", "SingletonLock", "SingletonSocket", "SingletonCookie"):
        stale_path = os.path.join(profile_path, stale_name)
        if os.path.exists(stale_path):
            try:
                os.remove(stale_path)
            except OSError:
                pass
    opts.add_argument(f"--user-data-dir={profile_path}")
    opts.add_argument("--profile-directory=Default")

    # Ubuntu / Linux stability flags
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    # NOTE: --disable-gpu intentionally omitted — causes rendering issues on Ubuntu GUI
    # NOTE: --disable-extensions intentionally omitted — can break LinkedIn scripts

    # Anti-bot: hide webdriver fingerprint
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)

    # Window size — good resolution helps LinkedIn render all elements correctly
    opts.add_argument("--window-size=1920,1080")

    try:
        driver = webdriver.Chrome(options=opts)
    except SessionNotCreatedException:
        # If the persistent profile is temporarily unhealthy, retry with a clean profile.
        fallback_profile = tempfile.mkdtemp(prefix="werkstudent-chrome-")
        fallback_opts = webdriver.ChromeOptions()
        if chrome_binary:
            fallback_opts.binary_location = chrome_binary
        if headless:
            fallback_opts.add_argument("--headless=new")
            fallback_opts.add_argument("--disable-gpu")
        fallback_opts.add_argument(f"--user-data-dir={fallback_profile}")
        fallback_opts.add_argument("--profile-directory=Default")
        fallback_opts.add_argument("--no-sandbox")
        fallback_opts.add_argument("--disable-dev-shm-usage")
        fallback_opts.add_argument("--disable-blink-features=AutomationControlled")
        fallback_opts.add_experimental_option("excludeSwitches", ["enable-automation"])
        fallback_opts.add_experimental_option("useAutomationExtension", False)
        fallback_opts.add_argument("--window-size=1920,1080")
        driver = webdriver.Chrome(options=fallback_opts)

    driver.maximize_window()

    # Additional fingerprint mask via CDP
    driver.execute_cdp_cmd(
        "Page.addScriptToEvaluateOnNewDocument",
        {"source": "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"},
    )
    return driver


def first_text(container, selector, default=""):
    els = container.find_elements(By.CSS_SELECTOR, selector)
    for el in els:
        t = (el.text or "").strip()
        if t:
            return t
    return default


def first_href(container, selector):
    els = container.find_elements(By.CSS_SELECTOR, selector)
    for el in els:
        href = (el.get_attribute("href") or "").strip()
        if href:
            return href.split("?")[0]
    return ""


def extract_job_id(link):
    """Extract stable LinkedIn job id from URL when available."""
    if not link:
        return ""
    m = re.search(r"/view/(\d+)", link)
    if m:
        return m.group(1)
    m = re.search(r"currentJobId=(\d+)", link)
    return m.group(1) if m else ""


def is_reposted_card(card):
    """Detect explicit repost markers shown on LinkedIn cards."""
    text_parts = []

    # Prefer dedicated posted-date/metadata elements when present.
    for el in card.find_elements(By.CSS_SELECTOR, POSTED_TEXT_SELECTOR):
        t = (el.text or "").strip().lower()
        if t:
            text_parts.append(t)

    # Fallback to full card text if metadata selectors are absent.
    if not text_parts:
        t = (card.text or "").strip().lower()
        if t:
            text_parts.append(t)

    joined = "\n".join(text_parts)
    return any(re.search(pat, joined) for pat in _REPOSTED_PATTERNS)


def scroll_list_pane(driver):
    """Scroll the left-side job list pane to trigger lazy loading."""
    for sel in LIST_SCROLL_SELECTORS:
        try:
            pane = driver.find_element(By.CSS_SELECTOR, sel)
            driver.execute_script("arguments[0].scrollTop = arguments[0].scrollHeight;", pane)
            return
        except (NoSuchElementException, WebDriverException):
            continue
    driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")


def load_all_cards(driver, wait):
    """Scroll until no new job cards appear. Returns final list of card elements."""
    try:
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, JOB_CARD_SELECTOR)))
    except TimeoutException:
        return []

    last_count = 0
    stagnant = 0
    while stagnant < 4:
        cards = driver.find_elements(By.CSS_SELECTOR, JOB_CARD_SELECTOR)
        count = len(cards)
        if count > last_count:
            stagnant = 0
            last_count = count
        else:
            stagnant += 1
        scroll_list_pane(driver)
        if cards:
            try:
                driver.execute_script("arguments[0].scrollIntoView({block:'end'});", cards[-1])
            except WebDriverException:
                pass
        pause(SCROLL_PAUSE)

    return driver.find_elements(By.CSS_SELECTOR, JOB_CARD_SELECTOR)


def fetch_description(driver, wait, card):
    """Click a job card to open the detail panel, return (description, company_from_panel)."""
    try:
        links = card.find_elements(By.CSS_SELECTOR, LINK_SELECTOR)
        target = links[0] if links else card
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", target)
        pause(CLICK_PAUSE)
        driver.execute_script("arguments[0].click();", target)
    except WebDriverException:
        return "", ""

    pause((0.4, 0.9))

    # Extract company from detail panel — more reliable than job card selectors
    company_panel = ""
    for sel in COMPANY_DETAIL_SELECTORS:
        try:
            for el in driver.find_elements(By.CSS_SELECTOR, sel):
                t = (el.text or "").strip()
                if t:
                    company_panel = t
                    break
            if company_panel:
                break
        except WebDriverException:
            continue

    for sel in DESCRIPTION_SELECTORS:
        try:
            wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, sel)))
            for el in driver.find_elements(By.CSS_SELECTOR, sel):
                text = (el.text or "").strip()
                if text:
                    return text, company_panel
        except (TimeoutException, WebDriverException):
            continue
    return "", company_panel


def get_page_number(driver):
    selectors = [
        f"{PAGINATION_SELECTOR} button.jobs-search-pagination__indicator-button--active",
        f"{PAGINATION_SELECTOR} button[aria-current='page']",
    ]
    for sel in selectors:
        try:
            el = driver.find_element(By.CSS_SELECTOR, sel)
            label = (el.get_attribute("aria-label") or "").lower()
            m = re.search(r"page\s+(\d+)", label)
            if m:
                return int(m.group(1))
            t = (el.text or "").strip()
            if t.isdigit():
                return int(t)
        except (NoSuchElementException, WebDriverException):
            continue
    try:
        state = driver.find_element(
            By.CSS_SELECTOR,
            f"{PAGINATION_SELECTOR} p.jobs-search-pagination__page-state",
        )
        m = re.search(r"page\s+(\d+)", (state.text or "").lower())
        if m:
            return int(m.group(1))
    except (NoSuchElementException, WebDriverException):
        pass
    return None


def get_max_pages(driver):
    try:
        state = driver.find_element(
            By.CSS_SELECTOR,
            f"{PAGINATION_SELECTOR} p.jobs-search-pagination__page-state",
        )
        m = re.search(r"of\s+(\d+)", (state.text or "").lower())
        if m:
            return int(m.group(1))
    except (NoSuchElementException, WebDriverException):
        pass
    try:
        buttons = driver.find_elements(
            By.CSS_SELECTOR,
            f"{PAGINATION_SELECTOR} button.jobs-search-pagination__indicator-button",
        )
        nums = []
        for btn in buttons:
            label = (btn.get_attribute("aria-label") or "").lower()
            m = re.search(r"page\s+(\d+)", label)
            if m:
                nums.append(int(m.group(1)))
        if nums:
            return max(nums)
    except WebDriverException:
        pass
    return 1


def ensure_pagination_visible(driver):
    """Scroll until pagination controls are rendered."""
    for _ in range(5):
        scroll_list_pane(driver)
        try:
            WebDriverWait(driver, 2).until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, f"{PAGINATION_SELECTOR} p.jobs-search-pagination__page-state")
                )
            )
            return True
        except TimeoutException:
            pass
    return False


def go_to_page(driver, target_page):
    """Navigate to a specific page number in LinkedIn job results."""
    if target_page <= 1:
        return True

    # Try clicking the exact page button first
    for attempt in (
        f"{PAGINATION_SELECTOR} button[aria-label='Page {target_page}']",
        f"//div[contains(@class,'jobs-search-pagination')]//button[@aria-label='Page {target_page}']",
    ):
        try:
            if attempt.startswith("//"):
                btn = WebDriverWait(driver, 5).until(
                    EC.element_to_be_clickable((By.XPATH, attempt))
                )
            else:
                btn = WebDriverWait(driver, 5).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, attempt))
                )
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
            pause(CLICK_PAUSE)
            driver.execute_script("arguments[0].click();", btn)
            try:
                WebDriverWait(driver, 6).until(lambda d: get_page_number(d) == target_page)
                return True
            except TimeoutException:
                pause((1.0, 2.0))
                if get_page_number(driver) == target_page:
                    return True
        except (TimeoutException, WebDriverException):
            continue

    # Fallback: click Next until we reach target
    current = get_page_number(driver) or 1
    next_selectors = [
        f"{PAGINATION_SELECTOR} button.jobs-search-pagination__button--next",
        f"{PAGINATION_SELECTOR} button[aria-label='View next page']",
    ]
    while current < target_page:
        clicked = False
        for sel in next_selectors:
            try:
                btn = WebDriverWait(driver, 5).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, sel))
                )
                if (btn.get_attribute("disabled") or "").lower() in ("true", "disabled"):
                    return False
                driver.execute_script("arguments[0].click();", btn)
                clicked = True
                break
            except (TimeoutException, WebDriverException):
                continue
        if not clicked:
            return False
        try:
            WebDriverWait(driver, 6).until(
                lambda d: (get_page_number(d) or 0) > current
            )
        except TimeoutException:
            pause((1.0, 2.0))
        new = get_page_number(driver) or current
        if new <= current:
            return False
        current = new

    return current == target_page


# ===========================================================================
# CSV / DEDUP HELPERS
# ===========================================================================

def build_paths(now_utc):
    os.makedirs(JOBS_DIR, exist_ok=True)
    day_dir = os.path.join(JOBS_DIR, now_utc.strftime("%d-%m-%Y"))
    os.makedirs(day_dir, exist_ok=True)
    run_time = now_utc.strftime("%H-%M")
    return {
        "day_dir":            day_dir,
        "canonical_relevant": os.path.join(JOBS_DIR, "Live_Jobs_Relevant.csv"),
        "canonical_nr":       os.path.join(JOBS_DIR, "Live_Jobs_NonRelevant.csv"),
        "run_relevant":       os.path.join(day_dir, f"{run_time}_relevant.csv"),
        "run_nr":             os.path.join(day_dir, f"{run_time}_non_relevant.csv"),
    }


def load_seen_links(paths):
    """
    Load Apply Links from canonical CSVs only (not full history).
    Keeps dedup fast regardless of how many historical files exist.
    """
    seen = set()
    seen_job_ids = set()
    for key in ("canonical_relevant", "canonical_nr"):
        fpath = paths[key]
        if not os.path.exists(fpath):
            continue
        with open(fpath, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                link = (row.get("Apply Link") or "").strip()
                if link:
                    seen.add(link)
                    jid = extract_job_id(link)
                    if jid:
                        seen_job_ids.add(jid)
    return seen, seen_job_ids


def save_csv(filepath, jobs):
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_FIELDNAMES)
        writer.writeheader()
        for job in jobs:
            writer.writerow({k: job.get(k, "") for k in OUTPUT_FIELDNAMES})


# ===========================================================================
# GOOGLE SHEETS HELPERS
# ===========================================================================

def get_sheets_client():
    if not GSHEETS_AVAILABLE:
        print("⚠️  gspread not installed. Run: pip install gspread google-auth-oauthlib")
        return None

    token_path = os.path.join(BASE_DIR, "token.json")
    creds_path = os.path.join(BASE_DIR, "credentials.json")
    creds = None

    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, GOOGLE_SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            # GUI Ubuntu: opens browser automatically for OAuth consent
            flow = InstalledAppFlow.from_client_secrets_file(creds_path, GOOGLE_SCOPES)
            creds = flow.run_local_server(port=0)

        with open(token_path, "w", encoding="utf-8") as f:
            f.write(creds.to_json())

    return gspread.authorize(creds)


def _row_key(row_values):
    """Stable dedupe key: prefer Apply Link (col index 7), else full row."""
    padded = list(row_values) + [""] * max(0, 8 - len(row_values))
    link = str(padded[7] if len(padded) > 7 else "").strip()
    return ("link", link) if link else ("row", tuple(str(x).strip() for x in padded[:8]))


def upload_to_sheets(jobs, tab_name):
    if not jobs:
        return

    # Only skip non-relevant jobs — German_Level is just a label now, not a gate.
    filtered_jobs = [
        job for job in jobs
        if (job.get("Relevance") or "").strip().lower() in ("high_relevant", "relevant")
    ]
    skipped_count = len(jobs) - len(filtered_jobs)
    if not filtered_jobs:
        print(f"   ⏭  Sheet '{tab_name}': nothing to upload after filters ({skipped_count} skipped)")
        return

    client = get_sheets_client()
    if not client:
        return

    try:
        wb = client.open_by_key(GOOGLE_SHEET_ID)
    except Exception as e:
        print(f"⚠️  Could not open Google Sheet: {e}")
        return

    try:
        ws = wb.worksheet(tab_name)
    except gspread.exceptions.WorksheetNotFound:
        ws = wb.add_worksheet(title=tab_name, rows="10000", cols=str(len(SHEET_HEADER)))
        ws.append_row(SHEET_HEADER)

    if not ws.row_values(1):
        ws.append_row(SHEET_HEADER)

    # Fetch existing keys for dedup
    all_values = ws.get_all_values()
    existing_keys = {_row_key(r) for r in (all_values[1:] if len(all_values) > 1 else [])}

    new_rows = []
    for job in filtered_jobs:
        row = [job.get(col, "") for col in SHEET_HEADER]
        key = _row_key(row)
        if key not in existing_keys:
            new_rows.append(row)
            existing_keys.add(key)

    if new_rows:
        ws.append_rows(new_rows, value_input_option="RAW")

    print(
        f"   ☁️  Sheet '{tab_name}': +{len(new_rows)} new, "
        f"{len(filtered_jobs)-len(new_rows)} skipped (dupes), {skipped_count} skipped (filters)"
    )


# ===========================================================================
# MAIN SCRAPE LOGIC
# ===========================================================================

def build_url(keyword):
    params = {
        "keywords": keyword,
        "location": LOCATION,
        "geoId": "101282230",   # Germany — stable LinkedIn geo ID for reliable coverage
        "f_TPR": TIME_FILTER,
        "sortBy": "DD",
    }
    if JOB_TYPE_FILTER:
        params["f_JT"] = JOB_TYPE_FILTER
    return f"https://www.linkedin.com/jobs/search/?{urlencode(params)}"


def is_within_24h(card, now_utc):
    """Return False if the card's datetime attribute shows it was posted >24 h ago."""
    from datetime import timedelta, timezone as tz
    els = card.find_elements(By.CSS_SELECTOR, POSTED_DATE_SELECTOR)
    for el in els:
        dt_str = el.get_attribute("datetime")
        if not dt_str:
            continue
        try:
            # datetime attr is usually "YYYY-MM-DD" or full ISO string
            if "T" in dt_str:
                posted = datetime.fromisoformat(dt_str.rstrip("Z")).replace(tzinfo=tz.utc)
            else:
                posted = datetime.strptime(dt_str, "%Y-%m-%d").replace(tzinfo=tz.utc)
            return (now_utc - posted) <= timedelta(hours=24)
        except ValueError:
            continue
    return True  # no date found — don't discard


def scrape():
    now_utc   = datetime.now(timezone.utc)
    timestamp = now_utc.strftime(SCRAPED_DATE_FORMAT)
    paths     = build_paths(now_utc)
    seen, seen_job_ids = load_seen_links(paths)

    print(f"\n🚀 LinkedIn scrape started — {timestamp}")
    print(f"   Dedup pool: {len(seen)} known links from canonical CSVs")
    print(f"   Dedup pool: {len(seen_job_ids)} known LinkedIn job IDs")
    print(f"   Keywords  : {len(SEARCH_KEYWORDS)}")
    print(f"   Max pages : {MAX_PAGES_PER_KEYWORD} per keyword\n")

    driver = build_driver()
    wait   = WebDriverWait(driver, WAIT_SECONDS)
    fresh  = []          # jobs found in this run
    run_seen = set()     # dedup within this run (links)
    run_seen_job_ids = set()  # dedup within this run (job IDs)

    try:
        driver.get("https://www.linkedin.com/login")
        pause((2.5, 4.5), "login page load")

        # Check if already logged in via persistent profile
        # LinkedIn redirects to /feed or /jobs when authenticated
        if "linkedin.com/login" in driver.current_url or "authwall" in driver.current_url:
            print("\n⚠️  Not logged in to LinkedIn.")
            print("   The Chrome window is open. Please log in manually now.")
            input("   👉 Press [ENTER] here once you are logged in and see your feed: ")
            pause((1.5, 2.5), "post-login settle")

        keywords = SEARCH_KEYWORDS[:]
        random.shuffle(keywords)

        for ki, keyword in enumerate(keywords):
            if ki > 0:
                pause(ACTION_DELAY, "between keywords")
            if ki > 0 and ki % KEYWORD_COOLDOWN_EVERY == 0:
                print(f"   ⏸  Cooldown after {ki} keywords...")
                pause(KEYWORD_COOLDOWN_RANGE, "keyword cooldown")

            print(f"🔍 [{ki+1}/{len(keywords)}] {keyword!r}")
            driver.get(build_url(keyword))
            pause(PAGE_TRANSITION_DELAY, "results page load")

            try:
                wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, JOB_CARD_SELECTOR)))
            except TimeoutException:
                print("   ⚠️  No job cards found — skipping keyword")
                continue

            page1_cards = load_all_cards(driver, wait)
            ensure_pagination_visible(driver)
            max_pages = min(MAX_PAGES_PER_KEYWORD, get_max_pages(driver))
            print(f"   Pages to scan: {max_pages}")

            for page_num in range(1, max_pages + 1):
                if page_num == 1:
                    cards = page1_cards
                else:
                    pause((0.8, 1.8), "before page nav")
                    if not go_to_page(driver, page_num):
                        print(f"   ⚠️  Could not reach page {page_num} — stopping")
                        break
                    cards = load_all_cards(driver, wait)

                print(f"   Page {page_num}: {len(cards)} cards")

                for idx, card in enumerate(cards, 1):
                    try:
                        title    = first_text(card, TITLE_SELECTOR, "Unknown Title")
                        company  = first_text(card, COMPANY_SELECTOR, "Unknown Company")
                        location = first_text(card, LOCATION_SELECTOR, "Germany")
                        link     = first_href(card, LINK_SELECTOR)
                        job_id   = extract_job_id(link)

                        if not link:
                            continue
                        if link in seen or link in run_seen:
                            continue
                        if job_id and (job_id in seen_job_ids or job_id in run_seen_job_ids):
                            continue
                        if not is_within_24h(card, now_utc):
                            debug(f"   ⏭  Skipping old job: {title}")
                            continue
                        if is_reposted_card(card):
                            debug(f"   ⏭  Skipping reposted job: {title}")
                            continue

                        desc, company_panel = fetch_description(driver, wait, card)
                        if company in ("Unknown Company", "") and company_panel:
                            company = company_panel
                        if is_excluded_company(company):
                            debug(f"   ⏭  Excluded company: {company}")
                            continue

                        german = classify_german(desc)

                        relevance, score = classify_relevance(title, desc)
                        skills       = extract_skills(desc)
                        category     = classify_job_category(title, desc)
                        zone         = classify_location_zone(location)

                        job = {
                            "Scraped Date":   timestamp,
                            "Time Filter":    TIME_FILTER_LABEL,
                            "Keyword":        keyword,
                            "Job Title":      title,
                            "Company":        company,
                            "Location":       location,
                            "Location_Zone":  zone,
                            "Apply Link":     link,
                            "Skills Found":   skills,
                            "Job_Category":   category,
                            "German_Level":   german,
                            "Relevance_Score": score,
                            "Relevance":      relevance,
                            "Search_Tag":     classify_search_tag(keyword, title, desc),
                        }
                        fresh.append(job)
                        run_seen.add(link)
                        if job_id:
                            run_seen_job_ids.add(job_id)

                        if relevance != "non_relevant":
                            debug(f"   ✅ {relevance} | {zone} | {title} @ {company}")

                    except (NoSuchElementException, StaleElementReferenceException, WebDriverException) as e:
                        debug(f"   Card {idx} error: {e}")

    except WebDriverException as e:
        print(f"❌ Chrome error: {e}")
    finally:
        driver.quit()
        print("   Browser closed")

    # --- Split and sort ---
    relevant     = [j for j in fresh if j["Relevance"] in ("high_relevant", "relevant")]
    non_relevant = [j for j in fresh if j["Relevance"] == "non_relevant"]

    relevant.sort(key=lambda j: (
        ZONE_ORDER.get(j["Location_Zone"], 4),
        -j.get("Relevance_Score", 0),
    ))

    # --- Print summary ---
    h  = sum(1 for j in relevant if j["Relevance"] == "high_relevant")
    r  = sum(1 for j in relevant if j["Relevance"] == "relevant")
    nr = len(non_relevant)
    data_relevant   = sum(1 for j in relevant if j.get("Job_Category") == "Data")
    devops_relevant = sum(1 for j in relevant if j.get("Job_Category") == "DevOps")
    web_relevant    = sum(1 for j in relevant if j.get("Job_Category") == "Web/Backend")
    other_relevant  = sum(1 for j in relevant if j.get("Job_Category") == "Other")
    print(f"\n📊 Run summary")
    print(f"   Total new jobs  : {len(fresh)}")
    print(f"   High relevant   : {h}  (core skill match — apply these first)")
    print(f"   Relevant        : {r}  (supporting skill match)")
    print(f"   Non-relevant    : {nr}")
    print(f"   Data jobs       : {data_relevant}")
    print(f"   DevOps jobs     : {devops_relevant}")
    print(f"   Web/Backend jobs: {web_relevant}")
    if other_relevant:
        print(f"   Other jobs      : {other_relevant}")
    print(f"\n📍 Relevant — location breakdown:")
    for zone in ["Zone1_Berlin", "Remote", "Zone2_Near", "Zone3_Stretch", "Other"]:
        count = sum(1 for j in relevant if j["Location_Zone"] == zone)
        if count:
            print(f"   {zone:<18}: {count}")

    if not fresh:
        print("⚠️  No new jobs found this run.")
        return

    # --- Save CSVs ---
    # Append fresh jobs to canonical files (read existing + merge + rewrite)
    for canon_key, new_jobs in [
        ("canonical_relevant", relevant),
        ("canonical_nr",       non_relevant),
    ]:
        canon = paths[canon_key]
        existing = []
        if os.path.exists(canon):
            with open(canon, encoding="utf-8-sig") as f:
                existing = list(csv.DictReader(f))
        merged = new_jobs + existing
        save_csv(canon, merged)

    # Also save timestamped run files
    save_csv(paths["run_relevant"], relevant)
    save_csv(paths["run_nr"],       non_relevant)
    print(f"\n💾 CSVs saved → {paths['day_dir']}")

    # --- Upload to Google Sheets ---
    print("\n☁️  Uploading to Google Sheets...")
    upload_to_sheets(relevant, SHEET_RELEVANT)
    print("   ⏭  Skipping non-relevant upload for now")

    print(f"\n✅ Done. {h + r} relevant jobs ready to review.")
    if h + r >= 25:
        print("🎯 Daily target of 25 reached!")
    else:
        print(f"⏳ {25 - h - r} more needed to hit today's target of 25.")


# ===========================================================================
# UPLOAD-ONLY MODE — push existing CSVs without scraping
# ===========================================================================

def upload_only():
    now_utc = datetime.now(timezone.utc)
    paths   = build_paths(now_utc)

    for csv_path, tab_name in [
        (paths["canonical_relevant"], SHEET_RELEVANT),
    ]:
        if not os.path.exists(csv_path):
            print(f"⚠️  File not found: {csv_path}")
            continue
        jobs = []
        with open(csv_path, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                # Backfill Location_Zone for old rows
                if not row.get("Location_Zone"):
                    row["Location_Zone"] = classify_location_zone(row.get("Location", ""))
                jobs.append(row)
        print(f"☁️  Uploading {len(jobs)} rows from {os.path.basename(csv_path)} → '{tab_name}'")
        upload_to_sheets(jobs, tab_name)


# ===========================================================================
# ENTRY POINT
# ===========================================================================

if __name__ == "__main__":
    if UPLOAD_ONLY_MODE:
        upload_only()
    else:
        scrape()