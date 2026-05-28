"""
Anakin Holocron Wire scraper.

API base: https://api.anakin.io/v1
Auth:     X-API-Key header (your Anakin API key — that's all you need)

Flow per board:
  1. Search the catalog for the board's action_id
  2. For Indeed: fetch saved identity credential_id from /holocron/identities
  3. POST /holocron/task  → get job_id
  4. Poll GET /holocron/jobs/{job_id} until completed or failed
  5. Parse the result into Job objects
"""

import asyncio
import json
import os
import re
from datetime import datetime
from typing import Optional

import httpx

from models import Job, SearchConfig

BASE = "https://api.anakin.io/v1"

BOARD_SEARCH_QUERIES = {
    "indeed":         "indeed jobs",
    "jobicy":         "jobicy jobs",
    "remoteok":       "remoteok jobs",
    "weworkremotely": "we work remotely jobs",
}

BOARD_SLUGS = {
    "indeed":         "indeed",
    "jobicy":         "jobicy",
    "remoteok":       "remoteok",
    "weworkremotely": "weworkremotely",
}

# Cache so we only search once per run
_action_id_cache: dict[str, str] = {}
_credential_id_cache: dict[str, str] = {}  # board → credential_id
_catalog_uuid_cache: dict[str, str] = {}   # slug → catalog UUID


def _headers(api_key: str) -> dict:
    return {"X-API-Key": api_key, "Content-Type": "application/json"}


# ── Step 1: discover action IDs ───────────────────────────────────────────────

def _pick_action(actions: list, board: str) -> Optional[str]:
    """Pick the search/list action — prefer search/find/list, avoid detail/view/profile."""
    PREFER = ("search", "find", "list", "jobs")
    AVOID  = ("detail", "view", "profile", "company", "salary_estimate", "description", "apply")

    preferred, fallback = [], []
    for action in actions:
        action_id = str(action.get("action_id") or action.get("id") or "")
        name = str(action.get("name") or action.get("title") or "").lower()
        combined = action_id.lower() + " " + name
        if any(kw in combined for kw in AVOID):
            continue
        if any(kw in combined for kw in PREFER):
            preferred.append(action_id)
        else:
            fallback.append(action_id)

    result = (preferred or fallback or [None])[0]
    return result or None


async def _find_action_id(board: str, api_key: str, client: httpx.AsyncClient) -> Optional[str]:
    if board in _action_id_cache:
        return _action_id_cache[board]

    # Strategy 1: search endpoint
    query = BOARD_SEARCH_QUERIES.get(board, board)
    try:
        resp = await client.get(
            f"{BASE}/holocron/search",
            params={"q": query, "category": "jobs"},
            headers=_headers(api_key),
        )
        if resp.status_code == 200:
            data = resp.json()
            actions = data if isinstance(data, list) else data.get("actions") or data.get("data") or []
            action_id = _pick_action(actions, board)
            if action_id:
                _action_id_cache[board] = action_id
                return action_id
    except Exception:
        pass

    # Strategy 2: fetch catalog/{slug} which returns the full action roster
    slug = BOARD_SLUGS.get(board, board)
    try:
        resp = await client.get(
            f"{BASE}/holocron/catalog/{slug}",
            headers=_headers(api_key),
        )
        if resp.status_code == 200:
            data = resp.json()
            actions = data.get("actions") or []
            action_id = _pick_action(actions, board)
            if action_id:
                _action_id_cache[board] = action_id
                return action_id
    except Exception:
        pass

    print(f"[anakin/{board}] could not discover action_id — skipping")
    return None


# ── Step 2a: resolve board slug → catalog UUID ────────────────────────────────

async def _get_catalog_uuid(slug: str, api_key: str, client: httpx.AsyncClient) -> Optional[str]:
    if slug in _catalog_uuid_cache:
        return _catalog_uuid_cache[slug]
    try:
        resp = await client.get(f"{BASE}/holocron/catalog", headers=_headers(api_key))
        resp.raise_for_status()
        for entry in resp.json().get("catalog", []):
            entry_slug = str(entry.get("slug", "")).lower()
            entry_domain = str(entry.get("domain", "")).lower()
            if entry_slug == slug or entry_domain.startswith(slug):
                _catalog_uuid_cache[slug] = entry["id"]
                return entry["id"]
    except Exception:
        pass
    return None


# ── Step 2b: fetch saved credential ID for authenticated boards ───────────────

async def _find_credential_id(board: str, api_key: str, client: httpx.AsyncClient) -> Optional[str]:
    """
    Fetches the active credential_id for a board using the identity you already
    authenticated on https://anakin.io. Filters by catalog UUID so matching is exact.
    """
    if board in _credential_id_cache:
        return _credential_id_cache[board]

    slug = BOARD_SLUGS.get(board, board)
    catalog_uuid = await _get_catalog_uuid(slug, api_key, client)

    params = {"catalog_id": catalog_uuid} if catalog_uuid else {}
    try:
        resp = await client.get(
            f"{BASE}/holocron/identities",
            params=params,
            headers=_headers(api_key),
        )
        resp.raise_for_status()
        identities = resp.json().get("identities", [])
    except Exception as e:
        print(f"[anakin/{board}] identity fetch failed: {e}")
        return None

    for identity in identities:
        for cred in identity.get("credentials", []):
            if cred.get("status") == "active":
                _credential_id_cache[board] = cred["id"]
                return cred["id"]

    return None


# ── Step 2c: submit task ──────────────────────────────────────────────────────

async def _submit_task(
    board: str,
    action_id: str,
    params: dict,
    api_key: str,
    client: httpx.AsyncClient,
) -> Optional[str]:
    payload: dict = {"action_id": action_id, "params": params}

    # Boards marked as needing auth: auto-fetch the saved credential
    AUTH_REQUIRED_BOARDS = {"indeed"}
    if board in AUTH_REQUIRED_BOARDS:
        cred_id = await _find_credential_id(board, api_key, client)
        if cred_id:
            payload["credential_id"] = cred_id
        else:
            print(f"[anakin/{board}] no active credential found — make sure you authenticated on anakin.io")

    try:
        resp = await client.post(
            f"{BASE}/holocron/task",
            headers=_headers(api_key),
            json=payload,
        )
        if resp.status_code == 402:
            print(f"[anakin/{board}] skipped — this Wire action requires Anakin credits (402). Top up at anakin.io/settings.")
            return None
        resp.raise_for_status()
        body = resp.json()
        return body.get("job_id") or body.get("id")
    except Exception as e:
        print(f"[anakin/{board}] task submit failed: {e}")
        return None


# ── Step 3: poll for result ───────────────────────────────────────────────────

async def _poll_job(job_id: str, api_key: str, client: httpx.AsyncClient) -> Optional[list]:
    for attempt in range(20):          # max ~40 s
        await asyncio.sleep(2)
        try:
            resp = await client.get(
                f"{BASE}/holocron/jobs/{job_id}",
                headers=_headers(api_key),
            )
            resp.raise_for_status()
            body = resp.json()
        except Exception as e:
            print(f"[anakin] poll error: {e}")
            continue

        status = body.get("status", "")
        if status == "completed":
            raw = body.get("data") or body.get("result") or []
            # Unwrap nested dicts until we find the jobs list.
            # Pattern: body.data → {status, data: {query, jobs: [...]}}
            for _ in range(4):
                if isinstance(raw, list):
                    break
                if not isinstance(raw, dict):
                    break
                # Check if a direct key holds the list of jobs
                found_list = False
                for key in ("jobs", "results", "listings", "items"):
                    if isinstance(raw.get(key), list):
                        raw = raw[key]
                        found_list = True
                        break
                if found_list:
                    break
                # No list found at this level — follow "data" whether it's a dict or list
                inner = raw.get("data")
                if isinstance(inner, list):
                    raw = inner
                    break
                elif isinstance(inner, dict):
                    raw = inner
                else:
                    raw = [raw]  # give up
                    break
            return raw if isinstance(raw, list) else [raw]
        if status == "failed":
            err = body.get("error", {})
            code = err.get("code", "") if isinstance(err, dict) else str(err)
            msg  = err.get("message", "") if isinstance(err, dict) else ""
            if "auth_expired" in code or "auth_expired" in msg:
                print("[anakin/indeed] credential expired — go to anakin.io → Settings → Credentials → refresh your Indeed login")
            else:
                print(f"[anakin] task failed: {err}")
            return None

    print("[anakin] polling timed out")
    return None


# ── Parsing ───────────────────────────────────────────────────────────────────

def _parse_salary(text: str) -> tuple[Optional[int], Optional[int]]:
    if not text:
        return None, None
    nums = [int(n.replace(",", "")) for n in re.findall(r"\d[\d,]{2,}", str(text).replace("k", "000"))]
    if len(nums) >= 2:
        return nums[0], nums[1]
    if len(nums) == 1:
        return nums[0], None
    return None, None


def _parse_date(value: str) -> Optional[datetime]:
    if not value:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d", "%a, %d %b %Y %H:%M:%S %z"):
        try:
            return datetime.strptime(value.strip(), fmt).replace(tzinfo=None)
        except Exception:
            continue
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        return None


def _to_jobs(items: list[dict], source: str) -> list[Job]:
    jobs = []
    for item in items:
        try:
            # "position" used by RemoteOK, "title" used by everyone else
            title = str(item.get("title") or item.get("position") or "").strip()
            url = str(item.get("url") or item.get("link") or item.get("applyUrl") or "").strip()
            if not title or not url:
                continue

            location = str(item.get("location") or item.get("jobGeo") or "Remote")
            sal_min, sal_max = _parse_salary(
                item.get("salary") or item.get("jobSalary") or item.get("salaryRange") or ""
            )
            # Indeed uses "date_posted" as a relative string like "30+ days ago" or "5 days ago"
            # "published" used by WWR, "date_posted" by Indeed, "pubDate" by Jobicy
            posted_raw = (
                item.get("posted_date") or item.get("pubDate") or item.get("datePosted")
                or item.get("date_posted") or item.get("published") or ""
            )
            posted = _parse_date(str(posted_raw))
            # Fallback: parse relative strings from Indeed ("5 days ago", "30+ days ago")
            if posted is None and "day" in str(posted_raw):
                import re as _re
                nums = _re.findall(r"\d+", str(posted_raw))
                if nums:
                    from datetime import timedelta
                    posted = datetime.now() - timedelta(days=int(nums[0]))

            jobs.append(Job(
                title=title,
                company=str(item.get("company") or item.get("companyName") or item.get("employer") or "").strip(),
                location=location,
                is_remote=(
                    "remote" in location.lower()
                    or "remote" in title.lower()
                    or item.get("remote") is True
                ),
                salary_min=sal_min,
                salary_max=sal_max,
                posted_date=posted,
                description=str(item.get("description") or item.get("snippet") or item.get("jobExcerpt") or "")[:3000],
                url=url,
                source=source,
            ))
        except Exception:
            continue
    return jobs


# ── Per-board params ──────────────────────────────────────────────────────────

def _params_for(board: str, config: SearchConfig) -> dict:
    tag = "-".join(config.role.lower().split()[:2])  # e.g. "machine-learning"
    if board == "indeed":
        return {"query": config.role, "location": config.location, "limit": config.results_per_source}
    if board == "jobicy":
        return {"query": config.role, "keyword": config.role, "tag": tag, "count": config.results_per_source}
    if board == "remoteok":
        return {"tag": tag, "limit": config.results_per_source}
    if board == "weworkremotely":
        return {"query": config.role, "category": config.role, "limit": config.results_per_source}
    return {"query": config.role, "limit": config.results_per_source}


# ── Main entry ────────────────────────────────────────────────────────────────

async def scrape_anakin(config: SearchConfig) -> list[Job]:
    api_key = os.getenv("ANAKIN_API_KEY", "")
    if not api_key:
        print("[anakin] Skipping — ANAKIN_API_KEY not set in .env")
        return []

    active_boards = [b for b in BOARD_SEARCH_QUERIES if config.sources.get(b, True)]
    if not active_boards:
        return []

    async with httpx.AsyncClient(timeout=60) as client:

        async def _fetch_board(board: str) -> list[Job]:
            action_id = await _find_action_id(board, api_key, client)
            if not action_id:
                print(f"[anakin/{board}] could not find action_id — skipping")
                return []

            job_id = await _submit_task(board, action_id, _params_for(board, config), api_key, client)
            if not job_id:
                print(f"[anakin/{board}] no job_id returned — skipping")
                return []

            items = await _poll_job(job_id, api_key, client)
            if not items:
                return []

            jobs = _to_jobs(items, source=board)
            if not jobs and items:
                # Show a sample to help debug field mapping for new boards
                print(f"[anakin/{board}] 0 parsed — sample keys: {list(items[0].keys()) if isinstance(items[0], dict) else items[0]}")
            else:
                print(f"[anakin/{board}] {len(jobs)} jobs")
            return jobs

        batches = await asyncio.gather(*[_fetch_board(b) for b in active_boards])

    return [job for batch in batches for job in batch]
