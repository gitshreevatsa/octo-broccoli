"""
ATS scraper — dynamically discovers companies via DuckDuckGo then fetches
structured job data from their public ATS APIs.

Supported:
  Greenhouse  → boards-api.greenhouse.io     (US)
              → boards-api.eu.greenhouse.io  (EU)
  Lever       → api.lever.co/v0/postings/{slug}
  Ashby       → api.ashbyhq.com/jobBoard.getJobBoard

Discovery flow:
  1. DuckDuckGo: "{role}" site:boards.greenhouse.io  (+ EU domain)
  2. Extract (slug, api_url) pairs from result URLs
  3. Hit each company's public API in parallel
  4. Filter results by role keywords
"""

import asyncio
import re
import time
from datetime import datetime, timezone
from typing import Optional

import anyio
import httpx

from models import Job, SearchConfig

# ── API endpoints ─────────────────────────────────────────────────────────────

# Both US and EU Greenhouse companies use the same backend API
GREENHOUSE_API = "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"
LEVER_API      = "https://api.lever.co/v0/postings/{slug}"
ASHBY_API      = "https://api.ashbyhq.com/jobBoard.getJobBoard"

# Search both Greenhouse frontend domains to maximise discovery;
# both resolve via the same backend API
ATS_CONFIG = {
    "greenhouse": [
        {
            "site":    "boards.greenhouse.io",
            "pattern": r"boards\.greenhouse\.io/([a-zA-Z0-9_-]+)",
            "api":     GREENHOUSE_API,
        },
        {
            "site":    "job-boards.eu.greenhouse.io",
            "pattern": r"job-boards\.eu\.greenhouse\.io/([a-zA-Z0-9_-]+)",
            "api":     GREENHOUSE_API,   # EU frontend, same backend
        },
    ],
    "lever": [
        {
            "site":    "jobs.lever.co",
            "pattern": r"jobs\.lever\.co/([a-zA-Z0-9_-]+)",
            "api":     LEVER_API,
        },
    ],
    "ashby": [
        {
            "site":    "jobs.ashbyhq.com",
            "pattern": r"jobs\.ashbyhq\.com/([a-zA-Z0-9_-]+)",
            "api":     ASHBY_API,
        },
    ],
}

SKIP_SLUGS = {"jobs", "careers", "apply", "embed", "api", "v1", "v2"}
HEADERS    = {"User-Agent": "JobSearchAgent/1.0"}

_DDG_CACHE: dict[str, tuple[float, list[str]]] = {}
_DDG_TTL   = 1800  # 30 minutes


# ── DuckDuckGo discovery ──────────────────────────────────────────────────────

def _ddg_search(query: str, max_results: int = 40) -> list[str]:
    now = time.time()
    if query in _DDG_CACHE:
        ts, urls = _DDG_CACHE[query]
        if now - ts < _DDG_TTL:
            print(f"[ddg] cache hit: {query!r}")
            return urls
    try:
        from ddgs import DDGS
        with DDGS() as ddgs:
            urls = [r["href"] for r in ddgs.text(query, max_results=max_results) if r.get("href")]
        _DDG_CACHE[query] = (now, urls)
        return urls
    except Exception as e:
        print(f"[ddg] search failed: {e}")
        return []


async def _discover(
    role: str,
    ats: str,
    pinned: dict[str, list[str]] | None = None,
) -> list[tuple[str, str]]:
    """
    Returns a deduplicated list of (slug, api_template) pairs.
    Combines DuckDuckGo discovery with manually pinned slugs.
    """
    seen:   set[str]              = set()
    result: list[tuple[str, str]] = []

    # ── Pinned slugs first (guaranteed to be checked) ─────────────────────────
    if pinned:
        pin_map = {
            "greenhouse": [
                (pinned.get("greenhouse_slugs",    []), GREENHOUSE_API),
                (pinned.get("greenhouse_eu_slugs", []), GREENHOUSE_API),
            ],
            "lever": [
                (pinned.get("lever_slugs", []), LEVER_API),
            ],
            "ashby": [
                (pinned.get("ashby_slugs", []), ASHBY_API),
            ],
        }
        for slugs, api in pin_map.get(ats, []):
            for slug in slugs:
                slug = slug.lower().strip()
                if slug and slug not in seen:
                    seen.add(slug)
                    result.append((slug, api))

    # ── DuckDuckGo discovery ──────────────────────────────────────────────────
    for cfg in ATS_CONFIG[ats]:
        query = f'"{role}" site:{cfg["site"]}'
        urls  = await anyio.to_thread.run_sync(lambda q=query: _ddg_search(q))

        for url in urls:
            m = re.search(cfg["pattern"], url)
            if not m:
                continue
            slug = m.group(1).lower()
            if slug in SKIP_SLUGS or slug in seen:
                continue
            seen.add(slug)
            result.append((slug, cfg["api"]))

    return result


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_iso(value: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        return None


def _parse_epoch_ms(value: int) -> Optional[datetime]:
    try:
        return datetime.fromtimestamp(value / 1000, tz=timezone.utc).replace(tzinfo=None)
    except Exception:
        return None


def _matches(title: str, keywords: list[str]) -> bool:
    t = title.lower()
    return any(kw in t for kw in keywords)


# ── Greenhouse ────────────────────────────────────────────────────────────────

async def _fetch_greenhouse(
    slug: str,
    api_template: str,
    keywords: list[str],
    client: httpx.AsyncClient,
) -> list[Job]:
    try:
        resp = await client.get(
            api_template.format(slug=slug),
            params={"content": "true"},
            headers=HEADERS,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return []

    jobs = []
    for item in data.get("jobs", []):
        title = item.get("title", "").strip()
        if not _matches(title, keywords):
            continue

        url = item.get("absolute_url", "")
        if not url:
            continue

        location = item.get("location", {}).get("name", "") or "Not specified"
        jobs.append(Job(
            title=title,
            company=slug.replace("-", " ").title(),
            location=location,
            is_remote="remote" in location.lower() or "remote" in title.lower(),
            salary_min=None,
            salary_max=None,
            posted_date=_parse_iso(item.get("updated_at", "")),
            description=item.get("content", "")[:3000],
            url=url,
            source="greenhouse",
        ))
    return jobs


async def scrape_greenhouse(config: SearchConfig) -> list[Job]:
    if not config.sources.get("greenhouse", False):
        return []

    print("[greenhouse] discovering companies…")
    pairs = await _discover(config.role, "greenhouse", config.pinned_companies)
    print(f"[greenhouse] {len(pairs)} companies found")

    keywords = config.role.lower().split()
    async with httpx.AsyncClient(timeout=15) as client:
        results = await asyncio.gather(
            *[_fetch_greenhouse(slug, api, keywords, client) for slug, api in pairs],
            return_exceptions=True,
        )

    jobs = [j for r in results if isinstance(r, list) for j in r]
    print(f"[greenhouse] {len(jobs)} matching jobs")
    return jobs


# ── Lever ─────────────────────────────────────────────────────────────────────

async def _fetch_lever(slug: str, keywords: list[str], client: httpx.AsyncClient) -> list[Job]:
    try:
        resp = await client.get(
            LEVER_API.format(slug=slug),
            params={"mode": "json"},
            headers=HEADERS,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return []

    jobs = []
    for item in data:
        title = item.get("text", "").strip()
        if not _matches(title, keywords):
            continue

        cats     = item.get("categories", {})
        location = cats.get("location") or (cats.get("allLocations") or [""])[0]
        url      = item.get("hostedUrl", "")
        if not url:
            continue

        jobs.append(Job(
            title=title,
            company=slug.replace("-", " ").title(),
            location=location or "Not specified",
            is_remote="remote" in (location or "").lower() or "remote" in title.lower(),
            salary_min=None,
            salary_max=None,
            posted_date=_parse_epoch_ms(item.get("createdAt", 0)),
            description=item.get("description", "")[:3000],
            url=url,
            source="lever",
        ))
    return jobs


async def scrape_lever(config: SearchConfig) -> list[Job]:
    if not config.sources.get("lever", False):
        return []

    print("[lever] discovering companies…")
    pairs = await _discover(config.role, "lever", config.pinned_companies)
    print(f"[lever] {len(pairs)} companies found")

    keywords = config.role.lower().split()
    async with httpx.AsyncClient(timeout=15) as client:
        results = await asyncio.gather(
            *[_fetch_lever(slug, keywords, client) for slug, _ in pairs],
            return_exceptions=True,
        )

    jobs = [j for r in results if isinstance(r, list) for j in r]
    print(f"[lever] {len(jobs)} matching jobs")
    return jobs


# ── Ashby ─────────────────────────────────────────────────────────────────────

async def _fetch_ashby(slug: str, keywords: list[str], client: httpx.AsyncClient) -> list[Job]:
    try:
        resp = await client.post(
            ASHBY_API,
            json={"organizationHostedJobsPageName": slug},
            headers={**HEADERS, "Content-Type": "application/json"},
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return []

    jobs = []
    for item in data.get("results", data).get("jobPostings", []):
        title = item.get("title", "").strip()
        if not _matches(title, keywords):
            continue

        location = item.get("locationName") or item.get("location") or "Not specified"
        job_id   = item.get("id", "")
        url      = f"https://jobs.ashbyhq.com/{slug}/{job_id}" if job_id else ""
        if not url:
            continue

        jobs.append(Job(
            title=title,
            company=slug.replace("-", " ").title(),
            location=location,
            is_remote=(
                item.get("isRemote", False)
                or "remote" in location.lower()
                or "remote" in title.lower()
            ),
            salary_min=None,
            salary_max=None,
            posted_date=_parse_iso(item.get("publishedDate", "")),
            description=item.get("descriptionSocial", "")[:3000],
            url=url,
            source="ashby",
        ))
    return jobs


async def scrape_ashby(config: SearchConfig) -> list[Job]:
    if not config.sources.get("ashby", False):
        return []

    print("[ashby] discovering companies…")
    pairs = await _discover(config.role, "ashby", config.pinned_companies)
    print(f"[ashby] {len(pairs)} companies found")

    keywords = config.role.lower().split()
    async with httpx.AsyncClient(timeout=15) as client:
        results = await asyncio.gather(
            *[_fetch_ashby(slug, keywords, client) for slug, _ in pairs],
            return_exceptions=True,
        )

    jobs = [j for r in results if isinstance(r, list) for j in r]
    print(f"[ashby] {len(jobs)} matching jobs")
    return jobs


# ── Combined entry point ──────────────────────────────────────────────────────

async def scrape_ats(config: SearchConfig) -> list[Job]:
    results = await asyncio.gather(
        scrape_greenhouse(config),
        scrape_lever(config),
        scrape_ashby(config),
    )
    return [job for batch in results for job in batch]
