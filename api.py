import asyncio
import json
import logging
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import AsyncGenerator

from dotenv import load_dotenv
from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from models import SearchConfig
from runner import run_search

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# ── Config from environment ───────────────────────────────────────────────────

RESULTS_DIR = Path(os.getenv("RESULTS_DIR", Path(__file__).parent / "results"))
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

FRONTEND_DIR = Path(__file__).parent / "frontend" / "dist"

_allowed_origins = os.getenv("ALLOWED_ORIGINS", "http://localhost:5173,http://localhost:3000")
ALLOWED_ORIGINS = [o.strip() for o in _allowed_origins.split(",")]

# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(title="Job Searcher API", docs_url="/api/docs", redoc_url=None)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory state (single-worker only — see Dockerfile note)
_queues:  dict[str, asyncio.Queue] = {}
_results: dict[str, Path] = {}


# ── Request model ─────────────────────────────────────────────────────────────

class SearchRequest(BaseModel):
    role: str
    location: str = "Remote"
    prefer_remote: bool = False
    experience_years: int = 0
    salary_min: int = 0
    salary_currency: str = "USD"
    results_per_source: int = 15
    posted_within_hours: int = 0
    sources: dict[str, bool] = {
        "linkedin": True, "glassdoor": True, "indeed": True,
        "jobicy": True,   "remoteok": True,  "weworkremotely": True,
    }
    ranking_weights: dict[str, float] = {
        "relevance": 0.35, "salary": 0.25, "recency": 0.25, "remote": 0.15,
    }


# ── Background search ─────────────────────────────────────────────────────────

async def _run(search_id: str, config: SearchConfig) -> None:
    queue = _queues[search_id]

    async def progress(event_type: str, message: str) -> None:
        await queue.put({"type": event_type, "message": message})

    try:
        log.info("Search %s started: %s", search_id[:8], config.role)
        ranked = await run_search(config, progress)

        if not ranked:
            await queue.put({"type": "error", "message": "No jobs found."})
            return

        slug      = config.role.lower().replace(" ", "_")
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        path      = RESULTS_DIR / f"{slug}_{timestamp}.json"

        records = [
            {
                "rank":            i,
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
            }
            for i, job in enumerate(ranked, 1)
        ]

        path.write_text(json.dumps(
            {"role": config.role, "searched_at": timestamp, "jobs": records},
            indent=2,
        ))
        _results[search_id] = path
        log.info("Search %s done: %d jobs saved to %s", search_id[:8], len(ranked), path.name)
        await queue.put({"type": "done", "message": str(len(ranked)), "file": path.name})

    except Exception as e:
        log.exception("Search %s failed", search_id[:8])
        await queue.put({"type": "error", "message": str(e)})
    finally:
        await queue.put(None)   # sentinel — signals SSE stream to close


# ── API routes ────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/api/search")
async def start_search(req: SearchRequest, background_tasks: BackgroundTasks):
    search_id = str(uuid.uuid4())
    _queues[search_id] = asyncio.Queue()
    config = SearchConfig(**req.model_dump())
    background_tasks.add_task(_run, search_id, config)
    return {"search_id": search_id}


@app.get("/api/search/{search_id}/stream")
async def stream_progress(search_id: str):
    if search_id not in _queues:
        raise HTTPException(404, "Search not found")

    async def generator() -> AsyncGenerator[str, None]:
        queue = _queues[search_id]
        try:
            while True:
                event = await queue.get()
                if event is None:
                    break
                yield f"data: {json.dumps(event)}\n\n"
        finally:
            _queues.pop(search_id, None)

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",   # tells nginx not to buffer SSE
        },
    )


@app.get("/api/search/{search_id}/results")
async def get_results(search_id: str):
    path = _results.get(search_id)
    if not path or not path.exists():
        raise HTTPException(404, "Results not ready yet")
    return json.loads(path.read_text())


@app.get("/api/history")
async def list_history():
    files = sorted(RESULTS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    out = []
    for f in files[:50]:
        try:
            data = json.loads(f.read_text())
            out.append({
                "file":        f.name,
                "role":        data.get("role", ""),
                "searched_at": data.get("searched_at", ""),
                "count":       len(data.get("jobs", [])),
            })
        except Exception:
            continue
    return out


@app.get("/api/history/{filename}")
async def get_history_file(filename: str):
    path = RESULTS_DIR / filename
    if not path.exists():
        raise HTTPException(404, "File not found")
    return json.loads(path.read_text())


# ── Serve React frontend (production) ────────────────────────────────────────
# Mount AFTER all /api routes so they take priority.

if FRONTEND_DIR.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIR / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str):
        """Return index.html for any non-API path so React Router works."""
        return FileResponse(FRONTEND_DIR / "index.html")
