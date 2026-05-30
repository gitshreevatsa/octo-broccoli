import asyncio
from datetime import datetime
from typing import Optional
import anyio

from models import Job, SearchConfig

# All sites supported by python-jobspy
JOBSPY_SITES = {
    "linkedin":      "linkedin",
    "indeed":        "indeed",
    "glassdoor":     "glassdoor",
    "ziprecruiter":  "zip_recruiter",
    "google":        "google",
}


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
        title   = str(row.get("title", "")).strip()
        company = str(row.get("company", "")).strip()
        location = str(row.get("location", "")).strip()
        url     = str(row.get("job_url", "")).strip()

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
    """Scrape all jobspy-supported boards: LinkedIn, Glassdoor, Indeed, ZipRecruiter, Google Jobs."""
    active_sites = [
        jobspy_name
        for key, jobspy_name in JOBSPY_SITES.items()
        if config.sources.get(key, False)
    ]

    if not active_sites:
        return []

    def _run():
        from jobspy import scrape_jobs

        df = scrape_jobs(
            site_name=active_sites,
            search_term=config.role,
            location=config.location,
            results_wanted=config.results_per_source,
            hours_old=72 * 7,
            country_indeed="USA",
        )
        return df

    try:
        df = await anyio.to_thread.run_sync(_run)
    except Exception as e:
        print(f"[jobspy] scrape failed: {e}")
        return []

    jobs: list[Job] = []
    for _, row in df.iterrows():
        source = str(row.get("site", "unknown"))
        # Map jobspy internal names back to our source names
        source = {"zip_recruiter": "ziprecruiter"}.get(source, source)
        job = _row_to_job(row.to_dict(), source)
        if job:
            jobs.append(job)

    return jobs
