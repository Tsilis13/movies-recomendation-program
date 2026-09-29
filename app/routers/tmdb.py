import logging
import os

import httpx
from dotenv import load_dotenv
from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from pydantic import BaseModel

from app.dependencies import get_current_user
from app.limiter import limiter

# This file reads its config at import time, so it must not depend on some other module
# having called load_dotenv() first.
load_dotenv()

logger = logging.getLogger(__name__)

# Every endpoint here requires a logged-in user (otherwise anyone could burn the TMDB quota).
router = APIRouter(
    prefix="/tmdb",
    tags=["tmdb"],
    dependencies=[Depends(get_current_user)],
)

# This must be TMDB's "API Read Access Token" (the long one), not the short v3 API key.
TMDB_API_KEY = os.getenv("TMDB_API_KEY")
TMDB_BASE_URL = "https://api.themoviedb.org/3"
IMAGE_BASE_URL = "https://image.tmdb.org/t/p/w500"

# Never wait forever on an outside service.
TMDB_TIMEOUT = httpx.Timeout(10.0, connect=5.0)


class TMDBMovieResult(BaseModel):
    tmdb_id: int
    title: str
    year: int | None
    overview: str | None
    poster_url: str | None
    genres: list[str]
    runtime_minutes: int | None
    director: str | None


def parse_year(release_date: str | None) -> int | None:
    """TMDB sends "" or null for unreleased/unknown dates, so be defensive."""
    if release_date and release_date[:4].isdigit():
        return int(release_date[:4])
    return None


async def fetch_tmdb(endpoint: str, params: dict | None = None) -> dict:
    """
    Call TMDB. Every failure becomes a clean HTTPException:
      - our own config problem            -> 503 (details only in the log)
      - TMDB unreachable                  -> 502
      - TMDB too slow                     -> 504
      - TMDB says "not found"             -> 404
      - TMDB rate-limits us               -> 503
      - any other TMDB error / bad JSON   -> 502
    We never forward TMDB's own status code: a bad TMDB key would otherwise show up as a
    401 for the user, who would think THEIR login is wrong.
    """
    if not TMDB_API_KEY:
        logger.error("TMDB_API_KEY is not configured.")
        raise HTTPException(status_code=503, detail="Movie lookup is temporarily unavailable.")

    headers = {"Authorization": f"Bearer {TMDB_API_KEY}"}
    try:
        async with httpx.AsyncClient(timeout=TMDB_TIMEOUT) as client:
            response = await client.get(f"{TMDB_BASE_URL}{endpoint}", params=params, headers=headers)
    except httpx.TimeoutException:
        logger.warning("TMDB request timed out: %s", endpoint)
        raise HTTPException(status_code=504, detail="TMDB took too long to respond.")
    except httpx.RequestError:
        logger.exception("Could not reach TMDB: %s", endpoint)
        raise HTTPException(status_code=502, detail="Could not reach TMDB.")

    if response.status_code == 404:
        raise HTTPException(status_code=404, detail="Movie not found on TMDB.")
    if response.status_code == 429:
        logger.warning("TMDB is rate-limiting us.")
        raise HTTPException(status_code=503, detail="TMDB is busy, try again in a moment.")
    if response.status_code != 200:
        # 401 here means OUR key is wrong: that is a server problem, so log it loudly.
        logger.error("TMDB returned HTTP %s for %s", response.status_code, endpoint)
        raise HTTPException(status_code=502, detail="TMDB request failed.")

    try:
        return response.json()
    except ValueError:
        logger.error("TMDB returned invalid JSON for %s", endpoint)
        raise HTTPException(status_code=502, detail="TMDB returned an invalid response.")


@router.get("/search", response_model=list[TMDBMovieResult])
@limiter.limit("30/minute")
async def search_tmdb(request: Request, q: str = Query(..., min_length=1, max_length=100)):
    """Search for movies to add to the watchlist."""
    data = await fetch_tmdb("/search/movie", {"query": q})

    results = []
    for item in data.get("results", [])[:10]:
        poster_path = item.get("poster_path")

        results.append(TMDBMovieResult(
            tmdb_id=item["id"],
            title=item.get("title") or "Untitled",
            year=parse_year(item.get("release_date")),
            overview=item.get("overview"),
            poster_url=f"{IMAGE_BASE_URL}{poster_path}" if poster_path else None,
            genres=[],  # Search API doesn't return full genre names, just IDs
            runtime_minutes=None,
            director=None,
        ))
    return results


@router.get("/{tmdb_id}", response_model=TMDBMovieResult)
@limiter.limit("60/minute")
async def get_tmdb_details(request: Request, tmdb_id: int = Path(gt=0)):
    """Get the full metadata needed to populate the MovieCreate schema."""
    # append_to_response lets us fetch credits (directors) in one network request
    data = await fetch_tmdb(f"/movie/{tmdb_id}", {"append_to_response": "credits"})

    poster_path = data.get("poster_path")
    genres = [g["name"] for g in data.get("genres", []) if g.get("name")][:5]  # Cap at 5 genres

    director = next(
        (crew.get("name") for crew in data.get("credits", {}).get("crew", []) if crew.get("job") == "Director"),
        None,
    )

    return TMDBMovieResult(
        tmdb_id=data["id"],
        title=data.get("title") or "Untitled",
        year=parse_year(data.get("release_date")),
        overview=data.get("overview"),
        poster_url=f"{IMAGE_BASE_URL}{poster_path}" if poster_path else None,
        genres=genres,
        runtime_minutes=data.get("runtime"),
        director=director,
    )