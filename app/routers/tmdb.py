import os
import httpx
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

router = APIRouter(prefix="/tmdb", tags=["tmdb"])

TMDB_API_KEY = os.getenv("TMDB_API_KEY")
TMDB_BASE_URL = "https://api.themoviedb.org/3"
IMAGE_BASE_URL = "https://image.tmdb.org/t/p/w500"

class TMDBMovieResult(BaseModel):
    tmdb_id: int
    title: str
    year: int | None
    overview: str | None
    poster_url: str | None
    genres: list[str]
    runtime_minutes: int | None
    director: str | None

async def fetch_tmdb(endpoint: str, params: dict = None):
    if not TMDB_API_KEY:
        raise HTTPException(status_code=500, detail="TMDB_API_KEY is not configured.")
    
    headers = {"Authorization": f"Bearer {TMDB_API_KEY}"}
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{TMDB_BASE_URL}{endpoint}", params=params, headers=headers)
        
    if response.status_code != 200:
        raise HTTPException(status_code=response.status_code, detail="TMDB API request failed.")
    return response.json()

@router.get("/search", response_model=list[TMDBMovieResult])
async def search_tmdb(q: str = Query(..., min_length=1)):
    """Search for movies to add to the watchlist."""
    data = await fetch_tmdb("/search/movie", {"query": q})
    
    results = []
    for item in data.get("results", [])[:10]:
        release_date = item.get("release_date", "")
        poster_path = item.get("poster_path")
        
        results.append(TMDBMovieResult(
            tmdb_id=item["id"],
            title=item["title"],
            year=int(release_date[:4]) if release_date else None,
            overview=item.get("overview"),
            poster_url=f"{IMAGE_BASE_URL}{poster_path}" if poster_path else None,
            genres=[], # Search API doesn't return full genre names, just IDs
            runtime_minutes=None,
            director=None
        ))
    return results

@router.get("/{tmdb_id}", response_model=TMDBMovieResult)
async def get_tmdb_details(tmdb_id: int):
    """Get the full metadata needed to populate the MovieCreate schema."""
    # Append to response allows us to fetch credits (directors) in one network request
    data = await fetch_tmdb(f"/movie/{tmdb_id}", {"append_to_response": "credits"})
    
    release_date = data.get("release_date", "")
    poster_path = data.get("poster_path")
    genres = [g["name"] for g in data.get("genres", [])][:5] # Cap at 5 genres
    
    director = next(
        (crew["name"] for crew in data.get("credits", {}).get("crew", []) if crew["job"] == "Director"),
        None
    )
    
    return TMDBMovieResult(
        tmdb_id=data["id"],
        title=data["title"],
        year=int(release_date[:4]) if release_date else None,
        overview=data.get("overview"),
        poster_url=f"{IMAGE_BASE_URL}{poster_path}" if poster_path else None,
        genres=genres,
        runtime_minutes=data.get("runtime"),
        director=director
    )