#!/usr/bin/env python3
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

import yaml
from dotenv import load_dotenv
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from models import SearchConfig
from scrapers.jobspy_scraper import scrape_jobspy
from scrapers.anakin_scraper import scrape_anakin
from scrapers.native_boards import scrape_jobicy, scrape_remoteok, scrape_weworkremotely
from ranker import rank_jobs
from output import print_results

load_dotenv()
console = Console()
CONFIG_FILE = Path(__file__).parent / "search_config.yaml"


def load_config() -> SearchConfig:
    if not CONFIG_FILE.exists():
        console.print(f"[red]Config file not found:[/red] {CONFIG_FILE}")
        sys.exit(1)
    with open(CONFIG_FILE) as f:
        data = yaml.safe_load(f)
    return SearchConfig(**data)


def _save_json(jobs: list, config) -> None:
    results_dir = Path(__file__).parent / "results"
    results_dir.mkdir(exist_ok=True)

    slug = config.role.lower().replace(" ", "_")
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    path = results_dir / f"{slug}_{timestamp}.json"

    records = []
    for job in jobs:
        records.append({
            "rank":            jobs.index(job) + 1,
            "score":           round(job.total_score * 100, 1),
            "title":           job.title,
            "company":         job.company,
            "location":        job.location,
            "remote":          job.is_remote,
            "salary_min":      job.salary_min,
            "salary_max":      job.salary_max,
            "posted_days_ago": job.days_ago,
            "source":          job.source,
            "url":             job.url,
            "description":     job.description[:500],
            "scores": {
                "relevance": round(job.score_relevance, 3),
                "salary":    round(job.score_salary, 3),
                "recency":   round(job.score_recency, 3),
                "remote":    round(job.score_remote, 3),
            },
        })

    path.write_text(json.dumps({"role": config.role, "searched_at": timestamp, "jobs": records}, indent=2))
    console.print(f"\n[dim]Results saved → {path}[/dim]")


# Boards Anakin Wire covers — used as primary; native scrapers are fallback
ANAKIN_BOARDS = {"indeed", "jobicy", "remoteok", "weworkremotely"}


async def run():
    config = load_config()

    console.print(f"\n[bold cyan]Searching for:[/bold cyan] {config.role}")
    console.print(f"[dim]Location: {config.location} · Remote preferred: {config.prefer_remote}[/dim]\n")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True,
    ) as progress:
        t1 = progress.add_task("Scraping LinkedIn & Glassdoor…", total=None)
        t2 = progress.add_task("Scraping via Anakin Wire (Indeed / Jobicy / RemoteOK / WWR)…", total=None)

        jobspy_jobs, anakin_jobs = await asyncio.gather(
            scrape_jobspy(config),
            scrape_anakin(config),
        )

        # Tally Anakin results per board so we know which need native fallback
        anakin_by_board: dict[str, int] = {}
        for job in anakin_jobs:
            anakin_by_board[job.source] = anakin_by_board.get(job.source, 0) + 1

        progress.update(t1, description=f"[green]LinkedIn/Glassdoor → {len(jobspy_jobs)} jobs[/green]")
        progress.update(t2, description=(
            f"[green]Anakin → Indeed({anakin_by_board.get('indeed', 0)}) "
            f"Jobicy({anakin_by_board.get('jobicy', 0)}) "
            f"RemoteOK({anakin_by_board.get('remoteok', 0)}) "
            f"WWR({anakin_by_board.get('weworkremotely', 0)})[/green]"
        ))

        # Native fallback: only run for boards where Anakin returned nothing
        async def _skip():
            return []

        fallback_needed = {
            board for board in ANAKIN_BOARDS
            if config.sources.get(board, True) and anakin_by_board.get(board, 0) == 0
        }

        if fallback_needed:
            t3 = progress.add_task(f"Native fallback for: {', '.join(sorted(fallback_needed))}…", total=None)
            jobicy_jobs, remoteok_jobs, wwr_jobs = await asyncio.gather(
                scrape_jobicy(config)         if "jobicy" in fallback_needed else _skip(),
                scrape_remoteok(config)       if "remoteok" in fallback_needed else _skip(),
                scrape_weworkremotely(config) if "weworkremotely" in fallback_needed else _skip(),
            )
            native_total = len(jobicy_jobs) + len(remoteok_jobs) + len(wwr_jobs)
            progress.update(t3, description=f"[green]Native fallback → {native_total} jobs[/green]")
        else:
            jobicy_jobs = remoteok_jobs = wwr_jobs = []

        all_jobs = jobspy_jobs + anakin_jobs + jobicy_jobs + remoteok_jobs + wwr_jobs
        console.print(f"[bold]Total scraped:[/bold] {len(all_jobs)} listings\n")

        if not all_jobs:
            console.print("[yellow]No jobs found. Check your .env keys and search_config.yaml.[/yellow]")
            return

        rank_task = progress.add_task(f"Ranking {len(all_jobs)} jobs with OpenAI…", total=None)
        ranked = await rank_jobs(all_jobs, config)
        progress.update(rank_task, description=f"[green]Ranked {len(ranked)} jobs ✓[/green]")

    if config.posted_within_hours > 0:
        cutoff = config.posted_within_hours / 24
        before = len(ranked)
        ranked = [j for j in ranked if j.days_ago is not None and j.days_ago <= cutoff]
        console.print(f"[dim]Filtered to jobs posted within {config.posted_within_hours}h: {len(ranked)} of {before}[/dim]\n")

    print_results(ranked, config)
    _save_json(ranked, config)


if __name__ == "__main__":
    asyncio.run(run())
