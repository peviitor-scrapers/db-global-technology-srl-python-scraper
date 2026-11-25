#!/usr/bin/env python3
"""Scraper for DB GLOBAL TECHNOLOGY SRL (CUI 32193007) -> peviitor.ro.

Source: Deutsche Bank's official Workday careers site ( Romania facet ).
GDPR: only title, canonical employer URL, company identity and non-personal
optional fields are used. Job descriptions, CVs and candidate data are never
fetched, copied or stored.

Default behaviour is DRY RUN: nothing is written to the peviitor API unless
--upload is passed explicitly.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------------------------

COMPANY_CIF = "32193007"
COMPANY_NAME = "DB GLOBAL TECHNOLOGY SRL"
COMPANY_BRAND = "Deutsche Bank"
CAREER_URL = "https://careers.db.com"
WEBSITE_URL = "https://www.db.com"

WORKDAY_HOST = "https://db.wd3.myworkdayjobs.com"
WORKDAY_SITE = "DBWebsite"
SEARCH_URL = f"{WORKDAY_HOST}/wday/cxs/db/{WORKDAY_SITE}/jobs"
# Workday facet id for "Romania", read from the search response itself.
ROMANIA_FACET_ID = "f2e609fe92974a55a05fc1cdc2852122"

API_BASE = "https://api.peviitor.ro/v1"
USER_AGENT = "db-global-technology-srl-python-scraper/1.0 (+https://peviitor.ro)"

PAGE_SIZE = 20
PAGE_DELAY = 1.0  # be polite to the source; also avoids Workday rate limits
PLACEHOLDERS = {"n/a", "na", "-", "--", "nespecificat", "none", "null"}

DATA_DIR = Path(__file__).resolve().parent / "data"
STATE_FILE = DATA_DIR / "state.json"
UPLOADED_FILE = DATA_DIR / "uploaded_urls.txt"


# ---------------------------------------------------------------------------
# HTTP / STATE HELPERS
# ---------------------------------------------------------------------------


def http_json(method, url, body=None, timeout=30, attempts=4):
    """Small JSON HTTP client with retry/backoff for 429 and 5xx responses."""
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"

    last_error = None
    for attempt in range(attempts):
        try:
            request = urllib.request.Request(url, data=data, headers=headers, method=method)
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            last_error = error
            if error.code in (400, 401, 403, 404, 405, 415, 422):
                raise
            retry_after = error.headers.get("Retry-After")
            delay = int(retry_after) if retry_after and retry_after.isdigit() else 2**attempt
            time.sleep(delay)
        except (urllib.error.URLError, TimeoutError, ValueError) as error:
            last_error = error
            if attempt < attempts - 1:
                time.sleep(2**attempt)
    raise last_error


def load_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return dict(default)


def save_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def load_uploaded_urls():
    try:
        return {
            line.strip()
            for line in UPLOADED_FILE.read_text(encoding="utf-8").splitlines()
            if line.strip()
        }
    except OSError:
        return set()


def append_uploaded_urls(urls):
    if not urls:
        return
    UPLOADED_FILE.parent.mkdir(parents=True, exist_ok=True)
    with UPLOADED_FILE.open("a", encoding="utf-8") as handle:
        for url in urls:
            handle.write(f"{url}\n")


def utc_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


# ---------------------------------------------------------------------------
# FETCH + PARSE (search endpoint only; no job descriptions are requested)
# ---------------------------------------------------------------------------


def build_job_url(external_path):
    """Build the canonical employer URL from a Workday externalPath."""
    if not external_path or not external_path.startswith("/job/"):
        return None
    url = f"{WORKDAY_HOST}/{WORKDAY_SITE}{external_path}"
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or parsed.netloc != urllib.parse.urlsplit(WORKDAY_HOST).netloc:
        return None
    if parsed.query or "&" in url:
        return None
    return url


def clean_title(title):
    """Return a usable title, or an empty string for placeholders/junk."""
    value = re.sub(r"\s+", " ", html.unescape(title or "")).strip()
    if len(value) < 3 or len(value) > 200:
        return ""
    if value.lower() in PLACEHOLDERS:
        return ""
    return value


def is_romanian_location(location_text):
    """Defensive filter in case the Workday facet behaviour changes."""
    value = (location_text or "").lower()
    return any(
        token in value
        for token in ("bucharest", "bucure", "romania", "român", "cluj", "timisoara", "timișoara")
    )


def fetch_jobs(page_size=PAGE_SIZE, page_delay=PAGE_DELAY):
    """Fetch all Romania job postings from the Workday search endpoint."""
    jobs = []
    seen = set()
    offset = 0
    expected_total = None

    while True:
        payload = {
            "appliedFacets": {"Country": [ROMANIA_FACET_ID]},
            "limit": page_size,
            "offset": offset,
            "searchText": "",
        }
        result = http_json("POST", SEARCH_URL, payload)
        if expected_total is None:
            # Workday only reports `total` on the first page reliably.
            expected_total = int(result.get("total") or 0)

        postings = result.get("jobPostings") or []
        if not postings:
            break

        for posting in postings:
            location_text = posting.get("locationsText") or ""
            if not is_romanian_location(location_text):
                continue
            url = build_job_url(posting.get("externalPath"))
            title = clean_title(posting.get("title"))
            if not url or not title or url in seen:
                continue
            seen.add(url)
            jobs.append(
                {
                    "title": title,
                    "url": url,
                    "location": location_text,
                    "req_id": (posting.get("bulletFields") or [None])[0],
                    "posted_on": posting.get("postedOn") or "",
                }
            )

        offset += len(postings)
        if expected_total and offset >= expected_total:
            break
        if not expected_total and len(postings) < page_size:
            break
        time.sleep(page_delay)

    return jobs


# ---------------------------------------------------------------------------
# VALIDATION + MAPPING
# ---------------------------------------------------------------------------


def build_peviitor_job(raw_job, scraped_at=None):
    """Map one raw job to the peviitor job model (non-personal fields only)."""
    url = raw_job.get("url")
    title = clean_title(raw_job.get("title"))
    if not url or not title:
        return None

    job = {
        "url": url,
        "title": title,
        "company": COMPANY_NAME,
        "cif": COMPANY_CIF,
        "date": scraped_at or utc_now(),
        "status": "scraped",
    }
    # The source states "Bucharest"; use the Romanian city name with diacritics.
    location = (raw_job.get("location") or "").lower()
    if "bucharest" in location or "bucure" in location:
        job["location"] = ["București"]
    return job


def build_jobs(raw_jobs):
    scraped_at = utc_now()
    jobs = []
    seen = set()
    for raw_job in raw_jobs:
        job = build_peviitor_job(raw_job, scraped_at)
        if job and job["url"] not in seen:
            seen.add(job["url"])
            jobs.append(job)
    return jobs


# ---------------------------------------------------------------------------
# COMPANY + API
# ---------------------------------------------------------------------------


def check_company():
    """Return True if the company is present in peviitor core."""
    url = f"{API_BASE}/firme/company/?cif={COMPANY_CIF}"
    result = http_json("GET", url)
    data = result.get("data") if isinstance(result, dict) else None
    return bool(data) and isinstance(data, list)


def create_company():
    """Explicit opt-in: upsert the company in peviitor core."""
    body = {
        "id": COMPANY_CIF,
        "company": COMPANY_NAME,
        "brand": COMPANY_BRAND,
        "status": "activ",
        "career": [CAREER_URL],
        "website": [WEBSITE_URL],
        "scraperFile": "scraper.py",
        "lastScraped": utc_now()[:10],
    }
    return http_json("PUT", f"{API_BASE}/firme/company/add/", body)


def upload_jobs(jobs):
    """POST a JSON array; return (accepted_count, accepted_urls)."""
    if not jobs:
        return 0, []
    result = http_json("POST", f"{API_BASE}/scraper/jobs/upload/", jobs)
    count = int(result.get("count", len(jobs))) if isinstance(result, dict) else len(jobs)
    count = max(0, min(count, len(jobs)))
    return count, [job["url"] for job in jobs[:count]]


def verify_uploads(urls, rows=50, max_pages=10):
    """Search peviitor by company name and report which uploaded URLs are indexed."""
    wanted = set(urls)
    found = set()
    for page in range(1, max_pages + 1):
        query = urllib.parse.urlencode({"q": COMPANY_NAME, "rows": rows, "page": page})
        result = http_json("GET", f"{API_BASE}/search/?{query}")
        docs = (result.get("response") or {}).get("docs") or [] if isinstance(result, dict) else []
        if not docs:
            break
        found.update(doc.get("url") for doc in docs if doc.get("url") in wanted)
        if found >= wanted:
            break

    missing = wanted - found
    print(f"Verification: {len(found)}/{len(wanted)} uploaded URLs found in peviitor search")
    for url in sorted(missing):
        print(f"  MISSING: {url}")
    return not missing


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upload", action="store_true", help="POST jobs to peviitor (default: dry run)")
    parser.add_argument("--limit", type=int, default=0, help="Upload at most N jobs (0 = all); useful for a test batch")
    parser.add_argument("--create-company", action="store_true", help="Upsert the company in peviitor core before uploading")
    parser.add_argument("--no-verify", action="store_true", help="Skip post-upload search verification")
    parser.add_argument("--page-size", type=int, default=PAGE_SIZE, help="Workday page size")
    parser.add_argument("--page-delay", type=float, default=PAGE_DELAY, help="Seconds between source pages")
    args = parser.parse_args(argv)

    state = load_json(STATE_FILE, {"last_run": None, "uploaded": 0})
    raw_jobs = fetch_jobs(page_size=args.page_size, page_delay=args.page_delay)
    jobs = build_jobs(raw_jobs)

    already_uploaded = load_uploaded_urls()
    fresh_jobs = [job for job in jobs if job["url"] not in already_uploaded]
    if args.limit > 0:
        fresh_jobs = fresh_jobs[: args.limit]

    print(
        f"Fetched={len(raw_jobs)} Valid={len(jobs)} "
        f"AlreadyUploaded={len(jobs) - len([j for j in jobs if j['url'] not in already_uploaded])} "
        f"ToUpload={len(fresh_jobs)} DryRun={not args.upload}"
    )
    for job in fresh_jobs[:5]:
        print(f"  {job['title']} -> {job['url']}")

    if not args.upload:
        state.update(
            {
                "last_run": utc_now(),
                "fetched": len(raw_jobs),
                "valid": len(jobs),
                "uploaded": 0,
                "dry_run": True,
            }
        )
        save_json(STATE_FILE, state)
        print("Dry run complete; nothing was sent to peviitor.")
        return 0

    if args.create_company:
        print("Creating/updating company in peviitor core...")
        print(json.dumps(create_company(), ensure_ascii=False))
    elif not check_company():
        print(
            f"WARNING: company {COMPANY_CIF} was not found in peviitor core. "
            "Create it first (--create-company) or with PUT /v1/firme/company/add/.",
            file=sys.stderr,
        )

    uploaded_count, uploaded_urls = upload_jobs(fresh_jobs)
    append_uploaded_urls(uploaded_urls)

    verified = None
    if uploaded_urls and not args.no_verify:
        verified = verify_uploads(uploaded_urls)

    state.update(
        {
            "last_run": utc_now(),
            "fetched": len(raw_jobs),
            "valid": len(jobs),
            "uploaded": uploaded_count,
            "dry_run": False,
            "verified": verified,
        }
    )
    save_json(STATE_FILE, state)
    print(f"Uploaded={uploaded_count}")
    return 0 if uploaded_count == len(fresh_jobs) else 1


if __name__ == "__main__":
    raise SystemExit(main())
