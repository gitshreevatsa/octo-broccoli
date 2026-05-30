import json
import math
import os
import re
import asyncio
from typing import Optional

from openai import AsyncOpenAI

from models import Job, SearchConfig

_client: Optional[AsyncOpenAI] = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"])
    return _client


# ── De-duplication ────────────────────────────────────────────────────────────

def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def deduplicate(jobs: list[Job]) -> list[Job]:
    """Remove duplicate listings (same title+company across sources). Keep the one with more info."""
    seen: dict[str, Job] = {}
    for job in jobs:
        key = _normalize(job.title)[:40] + "|" + _normalize(job.company)[:30]
        if key not in seen:
            seen[key] = job
        else:
            existing = seen[key]
            # Prefer the richer record
            if _richness(job) > _richness(existing):
                seen[key] = job
    return list(seen.values())


def _richness(job: Job) -> int:
    score = 0
    if job.salary_min:      score += 3
    if job.salary_max:      score += 1
    if len(job.description) > 200: score += 2
    if job.posted_date:     score += 1
    return score


# ── Salary scoring ────────────────────────────────────────────────────────────

# Conversion rates: currency → USD (approximate)
CURRENCY_TO_USD: dict[str, float] = {
    "USD": 1.0,
    "INR": 1 / 84,
    "GBP": 1.27,
    "EUR": 1.09,
    "CAD": 0.74,
    "AUD": 0.65,
    "SGD": 0.75,
    "AED": 0.27,
}

# Signals found in job text to auto-detect currency
_CURRENCY_SIGNALS = [
    (r"₹",           1 / 84),  # Indian rupee
    (r"£",           1.27),    # GBP
    (r"€",           1.09),    # EUR
    (r"CAD|CA\$",    0.74),    # Canadian dollar
    (r"AUD|A\$",     0.65),    # Australian dollar
    (r"SGD|S\$",     0.75),    # Singapore dollar
    (r"AED|د\.إ",    0.27),    # UAE dirham
    (r"\ba month\b", 12),      # monthly → annual multiplier
    (r"\ba week\b",  52),      # weekly → annual multiplier
]

def _normalize_salary_usd(job: Job) -> Optional[int]:
    raw_text = ""
    # Try to find currency signals in description or salary field
    for field in (job.description, job.title, job.location):
        raw_text += field + " "

    effective = job.salary_min or job.salary_max
    if not effective:
        return None

    multiplier = 1.0
    for pattern, factor in _CURRENCY_SIGNALS:
        if re.search(pattern, raw_text, re.IGNORECASE):
            multiplier = factor
            break

    # If salary looks like a monthly value (< 10k) assume monthly → annual
    if effective < 10_000:
        effective *= 12

    return int(effective * multiplier)


def _score_salary(job: Job, salary_min_threshold: int, salary_currency: str = "USD") -> float:
    usd = _normalize_salary_usd(job)
    if not usd:
        return 0.35
    # Convert user's threshold to USD before comparing
    rate = CURRENCY_TO_USD.get(salary_currency.upper(), 1.0)
    threshold_usd = salary_min_threshold * rate
    if threshold_usd and usd < threshold_usd:
        return 0.05
    # Curve: $80k → 0.3, $150k → 0.75, $250k+ → 1.0
    return min(1.0, max(0.0, (usd - 60_000) / 210_000))


# ── Recency scoring ───────────────────────────────────────────────────────────

def _score_recency(job: Job) -> float:
    days = job.days_ago
    if days is None:
        return 0.45   # unknown — slight penalty
    # Exponential decay: 1.0 today, ~0.5 at 7d, ~0.1 at 30d
    return math.exp(-0.033 * days)


# ── Remote scoring ────────────────────────────────────────────────────────────

def _score_remote(job: Job, prefer_remote: bool) -> float:
    if not prefer_remote:
        return 0.5
    return 1.0 if job.is_remote else 0.15


# ── Completeness bonus ────────────────────────────────────────────────────────

def _score_completeness(job: Job) -> float:
    """Reward listings that have salary and a real description."""
    s = 0.0
    if job.salary_min or job.salary_max:
        s += 0.5
    if len(job.description) > 150:
        s += 0.5
    return s  # 0.0 / 0.5 / 1.0


# ── Role expansion: generate equivalent titles upfront ───────────────────────

_EXPANSION_PROMPT = """\
Given a target job role, list all common alternative titles, abbreviations, and \
closely related roles that a recruiter might use when posting the same or nearly \
identical position. Include: abbreviations, seniority variants, adjacent titles \
with heavy overlap, and common misspellings/alternate spellings.

Target role: {role}

Reply ONLY with a JSON array of strings (no explanation), e.g.:
["Title A", "Title B", "Title C"]
Limit to 20 items."""


async def _expand_role(role: str) -> list[str]:
    """One-shot call to get all equivalent/related titles for the searched role."""
    try:
        resp = await _get_client().chat.completions.create(
            model="gpt-4o-mini",
            max_tokens=300,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": "You produce JSON arrays only."},
                {"role": "user", "content": _EXPANSION_PROMPT.format(role=role)},
            ],
        )
        raw = resp.choices[0].message.content
        # Response might be {"titles": [...]} or just [...]
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return parsed
        for v in parsed.values():
            if isinstance(v, list):
                return v
    except Exception:
        pass
    return []


# ── OpenAI relevance scoring ──────────────────────────────────────────────────

_BATCH_RELEVANCE_PROMPT = """\
You are evaluating job listings against a candidate's target role.

Target role: {role}
Candidate experience: {experience}

Known equivalent / closely related titles (treat any of these as a strong match):
{equivalents}

Scoring guide:
  1.0 = exact match or equivalent title, experience level aligns
  0.8 = very similar role or one seniority level off
  0.5 = related field, significant skill overlap
  0.2 = tangential — shares some skills but clearly different role
  0.0 = unrelated

Experience matching rules:
  - If candidate has {experience} and the listing clearly requires 2× more or is intern/trainee, score ≤ 0.4
  - If candidate has {experience} and the listing is VP/Director/C-suite, score ≤ 0.3
  - A ±2 year mismatch is acceptable, do not penalise

Jobs to score:
{jobs_text}

Reply ONLY with a JSON array in the same order, e.g.:
[{{"id": 0, "score": 0.9}}, {{"id": 1, "score": 0.3}}]"""


def _title_prescreen(job: Job, role: str, equivalents: list[str]) -> Optional[float]:
    """Return a score without an API call when the title is an obvious match or miss."""
    title_lower = job.title.lower()
    role_lower = role.lower()
    eq_lower = [e.lower() for e in equivalents]

    # Obvious match: title contains the role or one of the equivalents
    if role_lower in title_lower or any(eq in title_lower for eq in eq_lower):
        return 0.9

    # Obvious non-match: title contains a clearly unrelated seniority/type marker
    # and none of the role keywords appear anywhere
    role_words = set(role_lower.split())
    title_words = set(title_lower.split())
    if not role_words & title_words and not any(
        any(rw in eq for rw in role_words) for eq in eq_lower
    ):
        non_tech_markers = {"driver", "nurse", "teacher", "accountant", "chef", "cleaner"}
        if title_words & non_tech_markers:
            return 0.05

    return None  # ambiguous — needs API


async def _batch_relevance_scores(jobs: list[Job], role: str, equivalents: list[str], experience_years: int) -> list[float]:
    eq_text = "\n".join(f"  - {t}" for t in equivalents) if equivalents else "  (none listed)"
    exp_text = f"{experience_years} years" if experience_years > 0 else "not specified"
    jobs_text = "\n".join(
        f'  {{"id": {i}, "title": "{j.title}", "company": "{j.company}", "snippet": "{j.description[:200].replace(chr(10), " ")}"}}'
        for i, j in enumerate(jobs)
    )
    try:
        resp = await _get_client().chat.completions.create(
            model="gpt-4o-mini",
            max_tokens=len(jobs) * 30 + 50,
            messages=[
                {"role": "system", "content": "Job relevance evaluator. Reply only with the requested JSON array."},
                {"role": "user", "content": _BATCH_RELEVANCE_PROMPT.format(
                    role=role,
                    experience=exp_text,
                    equivalents=eq_text,
                    jobs_text=jobs_text,
                )},
            ],
        )
        raw = resp.choices[0].message.content or "[]"
        # Strip markdown code fences if present
        raw = re.sub(r"```[a-z]*\n?", "", raw).strip()
        data = json.loads(raw)
        scores = {item["id"]: float(item["score"]) for item in data}
        return [max(0.0, min(1.0, scores.get(i, 0.5))) for i in range(len(jobs))]
    except Exception:
        return [0.5] * len(jobs)


# ── Batch ranking ─────────────────────────────────────────────────────────────

BATCH_SIZE = 50
PRE_RANK_CAP = 300


async def rank_jobs(jobs: list[Job], config: SearchConfig) -> list[Job]:
    # 1. De-duplicate
    jobs = deduplicate(jobs)

    weights = config.ranking_weights
    w_rel  = weights.get("relevance", 0.35)
    w_sal  = weights.get("salary", 0.25)
    w_rec  = weights.get("recency", 0.25)
    w_rem  = weights.get("remote", 0.15) if config.prefer_remote else 0.0
    total_w = w_rel + w_sal + w_rec + w_rem
    w_rel, w_sal, w_rec, w_rem = (w / total_w for w in (w_rel, w_sal, w_rec, w_rem))

    # 2. Expand the role into equivalent titles (one API call)
    equivalents = await _expand_role(config.role)
    if equivalents:
        print(f"[ranker] equivalent titles: {', '.join(equivalents[:6])}{'…' if len(equivalents) > 6 else ''}")

    # 3. Pre-screen by title (no API call), batch the rest
    exp = config.experience_years
    rel_scores: list[float] = [0.5] * len(jobs)
    needs_api: list[int] = []

    for i, job in enumerate(jobs):
        pre = _title_prescreen(job, config.role, equivalents)
        if pre is not None:
            rel_scores[i] = pre
        else:
            needs_api.append(i)

    # Cap to PRE_RANK_CAP freshest/most complete jobs before hitting the API
    if len(needs_api) > PRE_RANK_CAP:
        needs_api.sort(key=lambda i: (_score_recency(jobs[i]) + _score_completeness(jobs[i])), reverse=True)
        skipped = needs_api[PRE_RANK_CAP:]
        needs_api = needs_api[:PRE_RANK_CAP]
        for i in skipped:
            rel_scores[i] = 0.3  # stale/empty listings get a low default

    print(f"[ranker] pre-screened {len(jobs) - len(needs_api)}/{len(jobs)} jobs by title — {len(needs_api)} sent to API in parallel batches")

    # Run all batches in parallel
    api_jobs = [jobs[i] for i in needs_api]
    batches = [api_jobs[s:s + BATCH_SIZE] for s in range(0, len(api_jobs), BATCH_SIZE)]
    batch_results = await asyncio.gather(*[
        _batch_relevance_scores(b, config.role, equivalents, exp) for b in batches
    ])
    api_scores = [score for batch in batch_results for score in batch]

    for idx, score in zip(needs_api, api_scores):
        rel_scores[idx] = score

    # 4. Compute total score for each job
    for job, rel in zip(jobs, rel_scores):
        job.score_relevance = rel
        job.score_salary    = _score_salary(job, config.salary_min, config.salary_currency)
        job.score_recency   = _score_recency(job)
        job.score_remote    = _score_remote(job, config.prefer_remote)

        base = (
            w_rel * job.score_relevance
            + w_sal * job.score_salary
            + w_rec * job.score_recency
            + w_rem * job.score_remote
        )
        # Completeness nudge: up to +5% bonus
        bonus = 0.05 * _score_completeness(job)
        job.total_score = min(1.0, base + bonus)

    return sorted(jobs, key=lambda j: j.total_score, reverse=True)
