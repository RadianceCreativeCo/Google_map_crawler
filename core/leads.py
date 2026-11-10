"""Lead rules for Radiance Creative Co.

Everything here is plain rules: no AI service is called, so a crawl costs nothing
beyond the computer it runs on.

- clean_emails / pick_email: drop junk the email regex picks up (image names,
  tracking ids, website-builder addresses) and choose the best address.
- detect_builder: which website builder a homepage was made with.
- find_owner: an owner or founder's name written on the website.
- mark_chains: flag chains and franchises in a crawl's results.
- parse_us_address: city and state from a Maps address.
- mark_area: results Google spilled in from far away (by their map position).
- send_to_flare: hand the finished leads to Flare's Leads page through the
  team member's Flare connector address (FLARE_CONNECTOR_URL).
"""

from __future__ import annotations

import json
import logging
import os
import re
from collections import Counter
from datetime import datetime
from typing import Any, Optional
from urllib.parse import parse_qs, urlparse

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Emails
# ---------------------------------------------------------------------------

FREE_MAIL = {
    "gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "aol.com", "icloud.com",
    "comcast.net", "att.net", "sbcglobal.net", "live.com", "msn.com", "me.com",
    "ymail.com", "frontier.com", "verizon.net", "bellsouth.net", "charter.net",
    "protonmail.com", "proton.me", "mail.com",
}

# Addresses that belong to tools and builders, never to the business
JUNK_EMAIL_DOMAINS = {
    "sentry.io", "sentry-next.wixpress.com", "wixpress.com", "wix.com", "example.com",
    "domain.com", "email.com", "yourdomain.com", "yoursite.com", "company.com",
    "godaddy.com", "squarespace.com", "sentry.wixpress.com", "schema.org",
    "w3.org", "googlegroups.com", "mysite.com", "website.com", "test.com",
    "latofonts.com", "typemade.mx", "ingest.sentry.io", "weebly.com", "shopify.com",
    "duda.co", "yext.com", "localiq.com", "hibu.com",
}
JUNK_LOCAL_PARTS = {"user", "name", "username", "email", "your", "yourname", "john.doe", "jane.doe", "example"}
FILE_ENDINGS = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".css", ".js", ".ico", ".avif", ".bmp", ".tif")


def _domain_of(url: str) -> str:
    try:
        host = urlparse(url if "://" in url else f"https://{url}").netloc.lower()
    except Exception:
        return ""
    host = host.split(":")[0]
    return host[4:] if host.startswith("www.") else host


def clean_emails(emails: list[str]) -> list[str]:
    """Drop addresses that can't be the business's: file names, tracking ids, builder addresses."""
    keep: list[str] = []
    for raw in emails:
        email = raw.strip().strip(".").lower()
        if email.startswith(("u003e", "x22", "%20", "20")):
            email = re.sub(r"^(u003e|x22|%20|20)+", "", email)
        if "@" not in email or email.count("@") != 1:
            continue
        local, domain = email.split("@")
        if not local or not domain or "." not in domain:
            continue
        if email.endswith(FILE_ENDINGS) or "@2x" in email or "@3x" in email:
            continue
        if domain in JUNK_EMAIL_DOMAINS or any(domain.endswith("." + d) for d in JUNK_EMAIL_DOMAINS):
            continue
        if local in JUNK_LOCAL_PARTS:
            continue
        # Error-tracking ids look like 32 hex characters
        if re.fullmatch(r"[0-9a-f]{20,}", local):
            continue
        if len(email) > 80:
            continue
        if email not in keep:
            keep.append(email)
    return keep


def drop_shared_emails(companies: list[dict[str, Any]], at_most: int = 2) -> None:
    """Remove an address found on many different businesses' sites in one crawl.

    That is nearly always the web designer's or a directory's address in a footer.
    A free-mail address is kept unless it is on more sites than `at_most`.
    """
    seen = Counter()
    for company in companies:
        for email in set(company.get("emails") or []):
            seen[email] += 1
    for company in companies:
        company["emails"] = [e for e in (company.get("emails") or []) if seen[e] <= at_most]


def _base(domain: str) -> str:
    """"joes-lawn" from "mail.joes-lawn.co.uk"-style domains (the part before the ending)."""
    parts = domain.lower().split(".")
    if len(parts) >= 3 and parts[-2] in ("co", "com", "org", "net") and len(parts[-1]) == 2:
        return parts[-3]
    return parts[-2] if len(parts) >= 2 else domain


def drop_vendor_emails(emails: list[str], website: str, business_name: str) -> list[str]:
    """Remove addresses at another company's domain (the web designer, a booking tool).

    Kept: the business's own domain, free-mail (gmail…), and other domains that share
    a word with the business's name or website (owner@smithplumbing.net for smithplumbing.com).
    """
    site = _domain_of(website) if website and website != "N/A" else ""
    if not site or is_social(website):
        return emails
    site_base = re.sub(r"[^a-z0-9]", "", _base(site))
    words = [w for w in re.findall(r"[a-z0-9]+", (business_name or "").lower()) if len(w) >= 4 and w not in {"plumbing", "heating", "cooling", "services", "service", "company", "and", "the", "inc", "llc"}]
    keep = []
    for email in emails:
        domain = email.split("@")[1]
        base = re.sub(r"[^a-z0-9]", "", _base(domain))
        if domain == site or domain.endswith("." + site) or domain in FREE_MAIL:
            keep.append(email)
        elif base and (base[:6] in site_base or site_base[:6] in base or any(w in base for w in words)):
            keep.append(email)
    return keep


def pick_email(emails: list[str], website: str) -> str:
    """Best address to write to: one on the business's own domain, then a free-mail one, then any."""
    if not emails:
        return ""
    site = _domain_of(website)
    own = [e for e in emails if site and (e.split("@")[1] == site or e.split("@")[1].endswith("." + site))]
    free = [e for e in emails if e.split("@")[1] in FREE_MAIL]
    for group in (own, free, emails):
        if group:
            # Prefer a named or general inbox over noreply-style ones
            group = sorted(group, key=lambda e: (e.split("@")[0].startswith(("noreply", "no-reply", "donotreply")), len(e)))
            return group[0]
    return ""


# ---------------------------------------------------------------------------
# Website builder
# ---------------------------------------------------------------------------

BUILDER_SIGNS: list[tuple[str, tuple[str, ...]]] = [
    ("Wix", ("static.wixstatic.com", "wix.com website builder", "_wixcss", "wixsite.com")),
    ("Squarespace", ("static1.squarespace.com", "squarespace.com", "squarespace-cdn")),
    ("GoDaddy", ("img1.wsimg.com", "godaddy website builder", "websites.godaddy.com")),
    ("Shopify", ("cdn.shopify.com", "myshopify.com")),
    ("Weebly / Square", ("editmysite.com", "weebly.com", "square.site", "squareup.com/online")),
    ("Webflow", ("data-wf-site", "webflow.com", "website-files.com")),
    ("Duda", ("irp.cdn-website.com", "multiscreensite.com", "dudaone", "cdn-website.com")),
    ("Hibu", ("hibu.com", "hibusite")),
    ("Yola", ("yola.com", "yolacdn")),
    ("Jimdo", ("jimdo", "jimcdn.com")),
    ("Strikingly", ("strikingly.com", "strikinglycdn")),
    ("Site123", ("site123.me", "site123.com")),
    ("Google Sites", ("sites.google.com", "google sites")),
    ("Framer", ("framerusercontent.com", "framer.com")),
    ("Carrd", ("carrd.co",)),
    ("WordPress", ("wp-content", "wp-includes", 'content="wordpress')),
]


def detect_builder(website: str, homepage_html: str) -> str:
    """Name the builder a site is made with, from its homepage HTML. "Unknown" when nothing matches."""
    domain = _domain_of(website)
    if domain.endswith("facebook.com") or domain.endswith("fb.com"):
        return "Facebook page (no website)"
    if domain.endswith("instagram.com"):
        return "Instagram page (no website)"
    html = (homepage_html or "").lower()
    if not html:
        return "Unknown (site didn't load)"
    for name, signs in BUILDER_SIGNS:
        if any(sign in html for sign in signs):
            return name
    return "Unknown"


SOCIAL_DOMAINS = ("facebook.com", "fb.com", "instagram.com", "linktr.ee", "yelp.com", "nextdoor.com", "tiktok.com", "x.com", "twitter.com")


def is_social(website: str) -> bool:
    domain = _domain_of(website)
    return any(domain == d or domain.endswith("." + d) for d in SOCIAL_DOMAINS)


# ---------------------------------------------------------------------------
# Owner name
# ---------------------------------------------------------------------------

_NAME = r"([A-Z][a-z]+(?:\s[A-Z]\.)?(?:\s(?:and|&)\s[A-Z][a-z]+)?\s(?:Mc|Mac|O'|De|Van)?[A-Z][a-z][a-zA-Z'\-]*)"
_ROLE = r"(?:Owner(?:\s?/\s?Operator)?|Co-Owner|Founder|Co-Founder|Proprietor|President|Owner and Operator)"
OWNER_PATTERNS = [
    re.compile(_NAME + r"\s*[,\-–—|:]\s*(?:the\s)?" + _ROLE + r"\b"),
    re.compile(r"\b" + _ROLE + r"\s*[:\-–—,]\s*" + _NAME),
    re.compile(r"\b(?:owned|founded|started|operated)\s(?:and\s(?:operated|run)\s)?by\s" + _NAME),
    re.compile(r"\bI['’]m\s" + _NAME + r",?\s(?:the\s)?(?:owner|founder)"),
    re.compile(r"\bMy name is\s" + _NAME + r"[^.]{0,60}\b(?:owner|founder|started)"),
]
NOT_NAMES = {
    "our team", "contact us", "about us", "read more", "learn more", "south bend", "united states",
    "privacy policy", "terms of", "all rights", "get started", "free estimate", "call now",
    "meet the", "our story", "the owner", "family owned", "locally owned", "veteran owned",
    "generation", "company", "service", "plumbing", "heating", "cooling", "roofing", "lawn",
    "construction", "electric", "general manager", "customer", "business", "llc", "inc",
}


def find_owner(page_text: str) -> str:
    """An owner or founder's name written on a page ("Jane Smith, Owner", "founded by Joe Brown")."""
    if not page_text:
        return ""
    text = re.sub(r"\s+", " ", page_text)
    for pattern in OWNER_PATTERNS:
        for match in pattern.finditer(text):
            name = match.group(1).strip()
            lower = name.lower()
            if any(bad in lower for bad in NOT_NAMES):
                continue
            if len(name.split()) < 2 or len(name) > 60:
                continue
            return name
    return ""


# ---------------------------------------------------------------------------
# Chains and franchises
# ---------------------------------------------------------------------------

# Brands Google Maps returns most in US local-service and shop searches.
KNOWN_CHAINS = {
    # Lawn, home, cleaning, restoration
    "trugreen", "lawn doctor", "weed man", "the grounds guys", "davey tree", "bartlett tree",
    "servpro", "servicemaster", "stanley steemer", "chem-dry", "chemdry", "molly maid", "merry maids",
    "the maids", "two men and a truck", "college hunks", "1-800-got-junk", "junk king",
    "mr. handyman", "mr handyman", "ace handyman", "handyman connection", "mosquito joe",
    "mosquito squad", "orkin", "terminix", "aptive", "truly nolen", "rentokil",
    "roto-rooter", "mr. rooter", "benjamin franklin plumbing", "one hour heating", "aire serv",
    "mr. electric", "mister sparky", "window genie", "fish window cleaning", "men in kilts",
    "rainbow restoration", "puroclean", "paul davis", "belfor", "rescue rooter", "ars rescue",
    "sears home", "home depot", "lowe's", "lowes", "menards", "pella", "andersen windows",
    "renewal by andersen", "bath fitter", "re-bath", "kitchen tune-up", "floor coverings international",
    "certapro", "certa pro", "five star painting", "sherwin-williams", "sherwin williams",
    "overhead door company", "precision garage door", "budget blinds",
    "leaf filter", "leaffilter", "leafguard", "power home remodeling", "window nation",
    "dreamstyle", "west shore home", "mr. appliance", "mr appliance", "glass doctor",
    "dryer vent wizard", "u-haul", "public storage", "extra space storage", "cubesmart",
    # Auto
    "jiffy lube", "valvoline", "midas", "meineke", "firestone", "goodyear", "pep boys",
    "monro", "mavis", "discount tire", "tires plus", "big o tires", "les schwab", "ntb",
    "take 5", "grease monkey", "maaco", "safelite", "caliber collision", "gerber collision",
    "service king", "crash champions", "christian brothers automotive", "autozone",
    "o'reilly", "advance auto", "napa auto", "carmax", "enterprise rent", "hertz", "avis",
    # Food and drink
    "mcdonald's", "burger king", "wendy's", "subway", "starbucks", "dunkin", "taco bell",
    "kfc", "pizza hut", "domino's", "papa john's", "little caesars", "chick-fil-a", "arby's",
    "sonic drive-in", "dairy queen", "culver's", "panera", "chipotle", "jimmy john's",
    "jersey mike's", "firehouse subs", "qdoba", "applebee's", "chili's", "olive garden",
    "red lobster", "buffalo wild wings", "texas roadhouse", "ihop", "denny's", "cracker barrel",
    "bob evans", "steak 'n shake", "white castle", "panda express", "popeyes", "wingstop",
    "dutch bros", "tim hortons", "biggby", "scooter's coffee", "marco's pizza", "hungry howie",
    "jet's pizza", "noodles & company", "potbelly", "portillo's", "raising cane's",
    "zaxby's", "whataburger", "in-n-out", "shake shack", "smoothie king", "tropical smoothie",
    "crumbl", "insomnia cookies", "baskin", "cold stone", "krispy kreme",
    # Retail, health, beauty, fitness, finance
    "walmart", "costco", "sam's club", "kroger", "meijer", "aldi", "walgreens",
    "cvs", "rite aid", "dollar general", "dollar tree", "family dollar", "five below",
    "great clips", "supercuts", "sport clips", "fantastic sams", "cost cutters", "smartstyle",
    "ulta", "sally beauty", "european wax", "massage envy", "hand & stone", "the joint chiropractic",
    "planet fitness", "anytime fitness", "orangetheory", "snap fitness", "crunch fitness",
    "la fitness", "gold's gym", "9round", "f45", "club pilates", "pure barre",
    "aspen dental", "heartland dental", "pacific dental", "western dental", "smile direct",
    "pearle vision", "lenscrafters", "visionworks", "america's best", "my eyedr",
    "h&r block", "jackson hewitt", "liberty tax", "edward jones", "state farm", "allstate",
    "farmers insurance", "american family insurance", "geico", 
    "primerica", "chase bank", "fifth third", "pnc bank", "wells fargo", "bank of america",
    "keller williams", "re/max", "remax", "coldwell banker", "century 21", "berkshire hathaway",
    "exp realty", "sotheby's", "petsmart", "petco", "banfield", "vca animal", "bluepearl",
    "kumon", "mathnasium", "sylvan", "huntington learning", "goddard school", "kindercare",
    "primrose school", "the ups store", "fedex", "office depot", "verizon",
    "at&t", "t-mobile", "cricket wireless", "metro by t-mobile", "boost mobile",
    "medexpress", "minuteclinic", "concentra", "dentalworks",
}

# Website paths a chain's Maps listing usually points to (one location's page on the brand site)
CHAIN_PATH = re.compile(r"/(?:locations?|stores?|store-locator|branch(?:es)?|find-a-location|franchises?)/", re.I)


def _norm_name(name: str) -> str:
    name = name.lower()
    name = re.sub(r"[’`]", "'", name)
    return re.sub(r"\s+", " ", name).strip()


def mark_chains(companies: list[dict[str, Any]]) -> None:
    """Set `chain` ("" when local) and `chain_reason` on each company dict.

    Strong signs (dropped): a known national brand, a website pointing to one
    location's page on a brand site, or the same name or website on 3+ results
    of this crawl. A weaker sign (kept with a note): the same website on 2 results,
    which may be one local business with two shops.
    """
    names = Counter(_norm_name(c.get("name", "")) for c in companies)
    sites = Counter(_domain_of(c.get("website", "")) for c in companies if c.get("website") not in (None, "", "N/A"))

    for company in companies:
        name = _norm_name(company.get("name", ""))
        website = company.get("website") or ""
        domain = _domain_of(website) if website not in ("", "N/A") else ""
        reason = ""
        note = ""

        brand = next((b for b in KNOWN_CHAINS if re.search(r"(?:^|\W)" + re.escape(b) + r"(?:\W|$)", name)), None)
        if brand:
            reason = f"known chain ({brand})"
        elif domain and not is_social(website) and CHAIN_PATH.search(urlparse(website).path + "/"):
            reason = "website is one location's page on a brand site"
        elif names[name] >= 3:
            reason = f"same name on {names[name]} results"
        elif domain and not is_social(website) and sites[domain] >= 3:
            reason = f"same website on {sites[domain]} results"
        elif domain and not is_social(website) and sites[domain] == 2:
            note = "same website on 2 results; may have two locations"

        company["chain"] = "yes" if reason else ""
        company["chain_reason"] = reason
        if note:
            company["chain_note"] = note


# ---------------------------------------------------------------------------
# Place
# ---------------------------------------------------------------------------

US_STATES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID", "IL", "IN", "IA", "KS",
    "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY",
    "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV",
    "WI", "WY", "DC",
}


def parse_us_address(address: str) -> dict[str, str]:
    """Split "123 Main St, South Bend, IN 46601" into street, city, region, postcode."""
    out = {"street": "", "city": "", "region": "", "postcode": ""}
    if not address or address == "N/A":
        return out
    text = re.sub(r",?\s*(United States|USA)$", "", address.strip())
    match = re.search(r"^(?:(.*),\s*)?([^,]+),\s*([A-Z]{2})\s*(\d{5})?(?:-\d{4})?$", text)
    if match and match.group(3) in US_STATES:
        out.update(street=(match.group(1) or "").strip(), city=match.group(2).strip(), region=match.group(3), postcode=match.group(4) or "")
    return out


def coords_of(maps_url: str) -> Optional[tuple[float, float]]:
    """Latitude and longitude from a Google Maps place link (its "!3d<lat>!4d<lng>" part)."""
    match = re.search(r"!3d(-?\d+(?:\.\d+)?)!4d(-?\d+(?:\.\d+)?)", maps_url or "")
    return (float(match.group(1)), float(match.group(2))) if match else None


def _miles(a: tuple[float, float], b: tuple[float, float]) -> float:
    from math import asin, cos, radians, sin, sqrt

    lat1, lng1, lat2, lng2 = map(radians, (*a, *b))
    h = sin((lat2 - lat1) / 2) ** 2 + cos(lat1) * cos(lat2) * sin((lng2 - lng1) / 2) ** 2
    return 3958.8 * 2 * asin(sqrt(h))


def mark_area(companies: list[dict[str, Any]], radius_miles: Optional[float] = None) -> None:
    """Flag results far from where most of the crawl's results are (Google spilling in other cities).

    The middle of the crawl is the median latitude and longitude of all results, so a
    few far-off ones can't move it. Sets `miles_away` and `outside_area` on each company.
    """
    radius = radius_miles or float(os.environ.get("AREA_RADIUS_MILES", "40"))
    points = [coords_of(c.get("maps_url", "")) for c in companies]
    known = sorted(p for p in points if p)
    if len(known) < 3:
        for company in companies:
            company["outside_area"] = False
        return
    lats = sorted(p[0] for p in known)
    lngs = sorted(p[1] for p in known)
    middle = (lats[len(lats) // 2], lngs[len(lngs) // 2])
    for company, point in zip(companies, points):
        if point:
            away = _miles(middle, point)
            company["miles_away"] = round(away, 1)
            company["outside_area"] = away > radius
        else:
            company["outside_area"] = False


# ---------------------------------------------------------------------------
# Flare
# ---------------------------------------------------------------------------


def _flare_website(url: str) -> str:
    """Flare matches websites without their query string, so turn facebook profile.php?id=N into facebook.com/N."""
    try:
        parsed = urlparse(url)
    except Exception:
        return url
    if parsed.netloc.lower().endswith("facebook.com") and parsed.path.rstrip("/").endswith("profile.php"):
        page_id = parse_qs(parsed.query).get("id", [""])[0]
        if page_id:
            return f"https://www.facebook.com/{page_id}"
    return url


def lead_for_flare(company: dict[str, Any]) -> dict[str, Any]:
    """One crawl result as a Flare lead (import_leads' fields, the rest in extra)."""
    place = parse_us_address(company.get("address", ""))
    emails = company.get("emails") or []
    na = lambda v: "" if v in (None, "N/A") else v  # noqa: E731
    extra: dict[str, Any] = {
        "Google Maps": na(company.get("maps_url")),
        "Rating": na(company.get("rating")),
        "Reviews": na(company.get("reviews_count")),
        "Website builder": na(company.get("website_builder")),
        "All emails": ", ".join(emails) if len(emails) > 1 else "",
        "Owner name found on": na(company.get("owner_source")),
        "Hours": na(company.get("opening_hours")),
        "Contact page": na(company.get("contact_page")),
        "Note": na(company.get("chain_note")),
    }
    lead = {
        "business_name": company.get("name", "").strip()[:300],
        "website": _flare_website(na(company.get("website"))),
        "email": company.get("email_primary") or pick_email(emails, na(company.get("website"))),
        "phone": na(company.get("phone")),
        "contact_name": na(company.get("owner_name")),
        "address": place["street"] or na(company.get("address")),
        "city": place["city"],
        "region": place["region"],
        "country": "United States" if place["region"] else "",
        "category": na(company.get("category")),
        "extra": {k: str(v)[:1000] for k, v in extra.items() if v not in ("", None)},
    }
    # A business with only a social page: its own category, so Flare's category filter finds them
    website = na(company.get("website"))
    if website and is_social(website):
        page = "Instagram" if "instagram.com" in _domain_of(website) else "Facebook"
        lead["category"] = f"{page} only"
        lead["extra"]["Trade"] = na(company.get("category")) or ""
        lead["extra"]["Note"] = "; ".join(x for x in (f"{page} page only, no website", lead["extra"].get("Note", "")) if x)
        lead["extra"] = {k: v for k, v in lead["extra"].items() if v}
    elif website and not emails:
        # No email on the site: reach them through its contact form
        lead["category"] = "Contact form only"
        lead["extra"]["Trade"] = na(company.get("category")) or ""
        note = "No email on the website; use its contact form"
        if company.get("website_builder", "").startswith("Unknown (site didn't load)"):
            note = "Website didn't load when crawled; may be down"
        lead["extra"]["Note"] = "; ".join(x for x in (note, lead["extra"].get("Note", "")) if x)
        lead["extra"] = {k: v for k, v in lead["extra"].items() if v}
    return {k: v for k, v in lead.items() if v not in ("", None, {})}


def leads_to_send(companies: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Which results go to Flare: everything that isn't a chain or far from the area searched.

    Businesses without an email still go, under "Contact form only" (or "Facebook only").
    The counts say how many were left out, and how many of those sent had no email.
    """
    counts = {"chain": 0, "outside_area": 0, "form_only": 0}
    keep = []
    for company in companies:
        if company.get("chain"):
            counts["chain"] += 1
        elif company.get("outside_area"):
            counts["outside_area"] += 1
        else:
            if not (company.get("emails") or []):
                counts["form_only"] += 1
            keep.append(lead_for_flare(company))
    return keep, counts


def send_to_flare(leads: list[dict[str, Any]], source: str, connector_url: Optional[str] = None) -> dict[str, Any]:
    """Send leads to Flare's Leads page, 200 at a time, through the Flare connector.

    Returns {"added", "already_there", "skipped", "error"}. Nothing is audited,
    built or emailed by Flare on import.
    """
    import requests

    url = (connector_url or os.environ.get("FLARE_CONNECTOR_URL", "")).strip()
    result: dict[str, Any] = {"added": 0, "already_there": 0, "skipped": 0, "error": None}
    if not url:
        result["error"] = "FLARE_CONNECTOR_URL isn't set, so nothing was sent to Flare."
        return result
    if not leads:
        return result

    for start in range(0, len(leads), 200):
        batch = leads[start : start + 200]
        body = {
            "jsonrpc": "2.0",
            "id": start + 1,
            "method": "tools/call",
            "params": {"name": "import_leads", "arguments": {"source": source[:200], "leads": batch}},
        }
        try:
            response = requests.post(url, json=body, timeout=90, headers={"Accept": "application/json"})
            response.raise_for_status()
            payload = response.json()
            if payload.get("error"):
                raise RuntimeError(payload["error"].get("message", "Flare refused the import"))
            content = payload.get("result", {})
            text = (content.get("content") or [{}])[0].get("text", "")
            if content.get("isError"):
                raise RuntimeError(text or "Flare refused the import")
            data = json.loads(text)
            result["added"] += int(data.get("added", 0))
            result["already_there"] += int(data.get("duplicates", 0))
            result["skipped"] += int(data.get("skipped", 0))
        except Exception as e:  # keep what was sent; report the rest
            logger.error("Sending leads to Flare failed: %s", e)
            result["error"] = f"Stopped after {start} of {len(leads)}: {e}"
            break
    return result


def source_name(prompt: str, city: str) -> str:
    when = datetime.now().strftime("%b %-d")
    place = f", {city}" if city else ""
    return f"{prompt.strip()}{place} (Maps crawler), {when}"
