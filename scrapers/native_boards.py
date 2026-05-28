"""
Free public API scrapers — no auth, no credits needed:
  - Jobicy          → REST API  https://jobicy.com/api/v2/remote-jobs
  - Remote OK       → JSON API  https://remoteok.com/api
  - We Work Remotely → RSS feed https://weworkremotely.com/remote-jobs.rss
"""

import re
import xml.etree.ElementTree as ET
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Optional

import httpx

from models import Job, SearchConfig

HEADERS = {"User-Agent": "JobSearchAgent/1.0"}


def _parse_salary(text: str) -> tuple[Optional[int], Optional[int]]:
    if not text:
        return None, None
    nums = [int(n.replace(",", "")) for n in re.findall(r"\d[\d,]{2,}", str(text).replace("k", "000"))]
    if len(nums) >= 2:
        return nums[0], nums[1]
    if len(nums) == 1:
        return nums[0], None
    return None, None


def _short_tag(role: str) -> str:
    """Convert a role like 'Machine Learning Engineer' → 'machine-learning' (max 2 words)."""
    words = role.lower().split()
    return "-".join(words[:2])


async def scrape_jobicy(config: SearchConfig) -> list[Job]:
    tag = _short_tag(config.role)
    try:
        async with httpx.AsyncClient(headers=HEADERS, timeout=30) as client:
            # Try with tag first; if 0 results, retry without tag and filter by role keyword
            resp = await client.get(
                "https://jobicy.com/api/v2/remote-jobs",
                params={"count": config.results_per_source * 3, "tag": tag},
            )
            resp.raise_for_status()
            data = resp.json()
            if not data.get("jobs"):
                # Fallback: fetch general listing and filter client-side
                resp = await client.get(
                    "https://jobicy.com/api/v2/remote-jobs",
                    params={"count": 50},
                )
                resp.raise_for_status()
                data = resp.json()
    except Exception as e:
        print(f"[jobicy] failed: {e}")
        return []

    keywords = config.role.lower().split()
    raw_jobs = [
        j for j in data.get("jobs", [])
        if any(kw in (j.get("jobTitle", "") + j.get("jobExcerpt", "")).lower() for kw in keywords)
    ][: config.results_per_source]
    jobs = []
    for item in raw_jobs:
        sal_min, sal_max = _parse_salary(item.get("jobSalary", ""))
        try:
            posted = datetime.fromisoformat(item.get("pubDate", "").replace("Z", "+00:00")).replace(tzinfo=None)
        except Exception:
            posted = None
        jobs.append(Job(
            title=item.get("jobTitle", ""),
            company=item.get("companyName", ""),
            location=item.get("jobGeo", "Remote"),
            is_remote=True,
            salary_min=sal_min,
            salary_max=sal_max,
            posted_date=posted,
            description=item.get("jobExcerpt", "")[:3000],
            url=item.get("url", ""),
            source="jobicy",
        ))
    return jobs


async def scrape_remoteok(config: SearchConfig) -> list[Job]:
    tag = _short_tag(config.role)
    try:
        async with httpx.AsyncClient(headers=HEADERS, timeout=30) as client:
            resp = await client.get(f"https://remoteok.com/api?tag={tag}")
            resp.raise_for_status()
            raw = resp.json()
    except Exception as e:
        print(f"[remoteok] failed: {e}")
        return []

    items = [i for i in raw if isinstance(i, dict) and i.get("id")]
    jobs = []
    for item in items[: config.results_per_source]:
        try:
            posted = datetime.utcfromtimestamp(int(item.get("epoch", 0)))
        except Exception:
            posted = None
        jobs.append(Job(
            title=item.get("position", ""),
            company=item.get("company", ""),
            location="Remote",
            is_remote=True,
            salary_min=int(item["salary_min"]) if item.get("salary_min") else None,
            salary_max=int(item["salary_max"]) if item.get("salary_max") else None,
            posted_date=posted,
            description=item.get("description", "")[:3000],
            url=item.get("url", f"https://remoteok.com/remote-jobs/{item.get('id', '')}"),
            source="remoteok",
        ))
    return jobs


async def scrape_weworkremotely(config: SearchConfig) -> list[Job]:
    keywords = config.role.lower().split()
    try:
        async with httpx.AsyncClient(headers=HEADERS, timeout=30) as client:
            resp = await client.get("https://weworkremotely.com/remote-jobs.rss")
            resp.raise_for_status()
            root = ET.fromstring(resp.content)
    except Exception as e:
        print(f"[weworkremotely] failed: {e}")
        return []

    jobs = []
    for item in root.findall(".//item"):
        title = (item.findtext("title") or "").strip()
        link  = (item.findtext("link") or "").strip()
        pub   = item.findtext("pubDate") or ""
        desc  = (item.findtext("description") or "")[:3000]

        if not any(kw in title.lower() for kw in keywords):
            continue

        try:
            posted = parsedate_to_datetime(pub).replace(tzinfo=None)
        except Exception:
            posted = None

        company = ""
        if ": " in title:
            company, title = title.split(": ", 1)

        jobs.append(Job(
            title=title.strip(),
            company=company.strip(),
            location="Remote",
            is_remote=True,
            salary_min=None,
            salary_max=None,
            posted_date=posted,
            description=desc,
            url=link,
            source="weworkremotely",
        ))
        if len(jobs) >= config.results_per_source:
            break

    return jobs
