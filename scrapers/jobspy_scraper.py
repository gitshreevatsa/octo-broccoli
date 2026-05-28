import asyncio
from datetime import datetime
from typing import Optional
import anyio

from models import Job, SearchConfig


def _safe_int(value) -> Optional[int]:
    try:
        return int(value) if value and str(value).strip() not in ("", "nan", "None") else None
    except (ValueError, TypeError):
        return None


def _parse_date(value) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except Exception:
        return None


def _row_to_job(row, source: str) -> Optional[Job]:
    try:
        title = str(row.get("title", "")).strip()
        company = str(row.get("company", "")).strip()
        location = str(row.get("location", "")).strip()
        url = str(row.get("job_url", "")).strip()

        if not title or not company or not url:
            return None

        is_remote = (
            row.get("is_remote") is True
            or "remote" in location.lower()
            or "remote" in title.lower()
        )

        return Job(
            title=title,
            company=company,
            location=location or "Not specified",
            is_remote=is_remote,
            salary_min=_safe_int(row.get("min_amount")),
            salary_max=_safe_int(row.get("max_amount")),
            posted_date=_parse_date(row.get("date_posted")),
            description=str(row.get("description", ""))[:3000],
            url=url,
            source=source,
        )
    except Exception:
        return None


async def scrape_jobspy(config: SearchConfig) -> list[Job]:
    """Scrape LinkedIn, Indeed, and Glassdoor via python-jobspy."""
    site_map = {
        "linkedin": "linkedin",
        "indeed": "indeed",
        "glassdoor": "glassdoor",
    }

    active_sites = [
        site_map[key]
        for key in ("linkedin", "indeed", "glassdoor")
        if config.sources.get(key, True)
    ]

    if not active_sites:
        return []

    def _run_jobspy():
        from jobspy import scrape_jobs
        import pandas as pd

        df = scrape_jobs(
            site_name=active_sites,
            search_term=config.role,
            location=config.location,
            results_wanted=config.results_per_source,
            hours_old=72 * 7,  # last 3 weeks
            country_indeed="USA",
        )
        return df

    try:
        df = await anyio.to_thread.run_sync(_run_jobspy)
    except Exception as e:
        print(f"[jobspy] scrape failed: {e}")
        return []

    jobs: list[Job] = []
    for _, row in df.iterrows():
        source = str(row.get("site", "unknown"))
        job = _row_to_job(row.to_dict(), source)
        if job:
            jobs.append(job)

    return jobs
