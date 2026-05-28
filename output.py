from rich.console import Console
from rich.table import Table
from rich import box
from rich.text import Text
from rich.panel import Panel

from models import Job, SearchConfig

console = Console()


def _score_bar(score: float, width: int = 10) -> str:
    filled = round(score * width)
    return "█" * filled + "░" * (width - filled)


def _score_color(score: float) -> str:
    if score >= 0.75:
        return "bold green"
    if score >= 0.5:
        return "yellow"
    return "red"


def _posted_label(days: int | None) -> str:
    if days is None:   return "?"
    if days == 0:      return "Today"
    if days == 1:      return "1d ago"
    return f"{days}d ago"


def print_results(jobs: list[Job], config: SearchConfig) -> None:
    console.print()
    console.print(
        Panel(
            f"[bold cyan]Job Search Results[/bold cyan]  ·  "
            f"Role: [bold]{config.role}[/bold]  ·  "
            f"Location: [bold]{config.location}[/bold]  ·  "
            f"[bold]{len(jobs)}[/bold] ranked listings",
            box=box.ROUNDED,
        )
    )
    console.print()

    table = Table(
        box=box.SIMPLE_HEAVY,
        show_lines=True,
        expand=True,
        header_style="bold white on #1a1a2e",
    )

    table.add_column("#",       style="dim", width=3,  justify="right")
    table.add_column("Score",   width=14,               justify="center")
    table.add_column("Title",   min_width=28)
    table.add_column("Company", min_width=18)
    table.add_column("Location",min_width=16)
    table.add_column("Salary",  min_width=16)
    table.add_column("Posted",  width=9,                justify="center")
    table.add_column("Apply",   min_width=12)

    for i, job in enumerate(jobs, 1):
        # Score bar
        score_cell = Text()
        score_cell.append(_score_bar(job.total_score) + " ", style=_score_color(job.total_score))
        score_cell.append(f"{job.total_score * 100:.0f}%", style="bold " + _score_color(job.total_score))

        # Clickable title
        title_cell = Text()
        title_cell.append(job.title, style=f"bold link {job.url}")

        # Location + remote badge
        loc_cell = Text()
        loc_cell.append(job.location)
        if job.is_remote:
            loc_cell.append(" ", style="default")
            loc_cell.append("remote", style="bold cyan")

        # Apply link — short label that's clickable
        apply_cell = Text()
        apply_cell.append("Apply →", style=f"blue underline link {job.url}")

        table.add_row(
            str(i),
            score_cell,
            title_cell,
            job.company,
            loc_cell,
            job.salary_display,
            _posted_label(job.days_ago),
            apply_cell,
        )

    console.print(table)
    console.print()
    console.print(
        "[dim]Scores: relevance (35%) + salary (25%) + recency (25%) + remote (15%)  "
        "·  Click title or Apply → to open job[/dim]"
    )
    console.print()
