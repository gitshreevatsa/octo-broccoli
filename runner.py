"""
Core search logic — shared by the CLI (main.py) and the API (api.py).
"""
import asyncio
from typing import Any, Callable, Awaitable

from models import Job, SearchConfig
from scrapers.jobspy_scraper import scrape_jobspy
from scrapers.anakin_scraper import scrape_anakin
from scrapers.native_boards import scrape_jobicy, scrape_remoteok, scrape_weworkremotely
from scrapers.ats_scraper import scrape_ats
from ranker import rank_jobs

ProgressCb = Callable[[str, Any], Awaitable[None]]

ANAKIN_BOARDS = {"indeed", "jobicy", "remoteok", "weworkremotely"}


def _job_to_dict(job: Job) -> dict:
    return {
        "title":           job.title,
        "company":         job.company,
        "location":        job.location,
        "remote":          job.is_remote,
        "salary_min":      job.salary_min,
        "salary_max":      job.salary_max,
        "posted_days_ago": job.days_ago,
        "source":          job.source,
        "url":             job.url,
        "score":           None,
        "rank":            None,
    }


async def run_search(config: SearchConfig, progress: ProgressCb) -> list[Job]:

    async def _skip():
        return []

    # ── Phase 1: all scrapers in parallel, emit partials as each finishes ────
    await progress("step", "Scraping job boards…")

    async def _emit(coro) -> list[Job]:
        jobs = await coro
        if jobs:
            await progress("partial", [_job_to_dict(j) for j in jobs])
        return jobs

    jobspy_jobs, anakin_jobs, ats_jobs = await asyncio.gather(
        _emit(scrape_jobspy(config)),
        _emit(scrape_anakin(config)),
        _emit(scrape_ats(config)),
    )

    # ── Anakin fallback for boards that returned 0 ────────────────────────────
    anakin_by_board: dict[str, int] = {}
    for job in anakin_jobs:
        anakin_by_board[job.source] = anakin_by_board.get(job.source, 0) + 1

    fallback_needed = {
        board for board in ANAKIN_BOARDS
        if config.sources.get(board, False) and anakin_by_board.get(board, 0) == 0
    }

    if fallback_needed:
        await progress("step", f"Native fallback for: {', '.join(sorted(fallback_needed))}…")
        jobicy_jobs, remoteok_jobs, wwr_jobs = await asyncio.gather(
            scrape_jobicy(config)         if "jobicy"         in fallback_needed else _skip(),
            scrape_remoteok(config)       if "remoteok"       in fallback_needed else _skip(),
            scrape_weworkremotely(config) if "weworkremotely" in fallback_needed else _skip(),
        )
    else:
        jobicy_jobs = remoteok_jobs = wwr_jobs = []

    # ── Tally & report ────────────────────────────────────────────────────────
    ats_by_board: dict[str, int] = {}
    for job in ats_jobs:
        ats_by_board[job.source] = ats_by_board.get(job.source, 0) + 1

    await progress("scraped", (
        f"jobspy: {len(jobspy_jobs)}  |  "
        f"Anakin: {len(anakin_jobs)}  |  "
        f"Greenhouse: {ats_by_board.get('greenhouse', 0)}  "
        f"Lever: {ats_by_board.get('lever', 0)}  "
        f"Ashby: {ats_by_board.get('ashby', 0)}"
    ))

    all_jobs = (
        jobspy_jobs + anakin_jobs
        + jobicy_jobs + remoteok_jobs + wwr_jobs
        + ats_jobs
    )
    await progress("total", str(len(all_jobs)))

    if not all_jobs:
        return []

    await progress("step", f"Ranking {len(all_jobs)} jobs…")
    ranked = await rank_jobs(all_jobs, config)
    await progress("done", str(len(ranked)))

    return ranked
