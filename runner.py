"""
Core search logic — shared by the CLI (main.py) and the API (api.py).
"""
import asyncio
from typing import Callable, Awaitable

from models import Job, SearchConfig
from scrapers.jobspy_scraper import scrape_jobspy
from scrapers.anakin_scraper import scrape_anakin
from scrapers.native_boards import scrape_jobicy, scrape_remoteok, scrape_weworkremotely
from ranker import rank_jobs

ProgressCb = Callable[[str, str], Awaitable[None]]  # (event_type, message)

ANAKIN_BOARDS = {"indeed", "jobicy", "remoteok", "weworkremotely"}


async def run_search(config: SearchConfig, progress: ProgressCb) -> list[Job]:
    await progress("step", "Scraping LinkedIn & Glassdoor…")
    await progress("step", "Scraping via Anakin Wire (Indeed / Jobicy / RemoteOK / WWR)…")

    jobspy_jobs, anakin_jobs = await asyncio.gather(
        scrape_jobspy(config),
        scrape_anakin(config),
    )

    anakin_by_board: dict[str, int] = {}
    for job in anakin_jobs:
        anakin_by_board[job.source] = anakin_by_board.get(job.source, 0) + 1

    await progress("scraped", (
        f"LinkedIn/Glassdoor: {len(jobspy_jobs)}  |  "
        f"Indeed: {anakin_by_board.get('indeed', 0)}  "
        f"Jobicy: {anakin_by_board.get('jobicy', 0)}  "
        f"RemoteOK: {anakin_by_board.get('remoteok', 0)}  "
        f"WWR: {anakin_by_board.get('weworkremotely', 0)}"
    ))

    # Native fallback for any Anakin board that returned 0
    fallback_needed = {
        board for board in ANAKIN_BOARDS
        if config.sources.get(board, True) and anakin_by_board.get(board, 0) == 0
    }

    async def _skip():
        return []

    if fallback_needed:
        await progress("step", f"Native fallback for: {', '.join(sorted(fallback_needed))}…")
        jobicy_jobs, remoteok_jobs, wwr_jobs = await asyncio.gather(
            scrape_jobicy(config)         if "jobicy" in fallback_needed else _skip(),
            scrape_remoteok(config)       if "remoteok" in fallback_needed else _skip(),
            scrape_weworkremotely(config) if "weworkremotely" in fallback_needed else _skip(),
        )
    else:
        jobicy_jobs = remoteok_jobs = wwr_jobs = []

    all_jobs = jobspy_jobs + anakin_jobs + jobicy_jobs + remoteok_jobs + wwr_jobs
    await progress("total", str(len(all_jobs)))

    if not all_jobs:
        return []

    await progress("step", f"Ranking {len(all_jobs)} jobs with OpenAI…")
    ranked = await rank_jobs(all_jobs, config)
    await progress("done", str(len(ranked)))

    return ranked
