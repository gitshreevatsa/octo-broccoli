from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class Job(BaseModel):
    title: str
    company: str
    location: str
    is_remote: bool = False
    salary_min: Optional[int] = None
    salary_max: Optional[int] = None
    posted_date: Optional[datetime] = None
    description: str = ""
    url: str
    source: str

    # Computed by ranker
    score_relevance: float = 0.0
    score_salary: float = 0.0
    score_recency: float = 0.0
    score_remote: float = 0.0
    total_score: float = 0.0

    @property
    def salary_display(self) -> str:
        if self.salary_min and self.salary_max:
            return f"${self.salary_min:,} – ${self.salary_max:,}"
        if self.salary_min:
            return f"${self.salary_min:,}+"
        if self.salary_max:
            return f"up to ${self.salary_max:,}"
        return "Not listed"

    @property
    def days_ago(self) -> Optional[int]:
        if not self.posted_date:
            return None
        delta = datetime.now() - self.posted_date.replace(tzinfo=None)
        return max(0, delta.days)


class SearchConfig(BaseModel):
    role: str
    location: str = "Remote"
    prefer_remote: bool = True
    salary_min: int = 0
    results_per_source: int = 15
    sources: dict[str, bool] = Field(default_factory=dict)
    experience_years: int = 0
    posted_within_hours: int = 0
    ranking_weights: dict[str, float] = Field(
        default_factory=lambda: {
            "relevance": 0.35,
            "salary": 0.25,
            "recency": 0.25,
            "remote": 0.15,
        }
    )
