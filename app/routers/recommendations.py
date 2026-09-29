from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app import models, rag, schemas
from app.database import get_db
from app.dependencies import get_current_user

router = APIRouter(prefix="/recommendations", tags=["recommendations"])

@router.get("", response_model=list[schemas.MovieResponse])
def recommend_movies(
    q: str = Query(..., min_length=1, max_length=200, description="What kind of vibe are you looking for?"),
    limit: int = Query(default=5, ge=1, le=20),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    # 1. Fetch more vector hits than we need, because some might already be watched
    hits = rag.search_unseen_movies(current_user.id, q, top_k=limit * 3)
    if not hits:
        return []

    movie_ids = [hit["movie_id"] for hit in hits]

    # 2. Fetch the actual movies from SQLite, keeping ONLY the ones still marked as PLANNED
    movies = (
        db.query(models.Movie)
        .filter(models.Movie.id.in_(movie_ids))
        .filter(models.Movie.status == models.WatchStatus.PLANNED)
        .all()
    )

    # 3. SQL's IN clause does not preserve the order of movie_ids, so we must sort 
    # the results back into the exact order of the vector distances (closest meaning first).
    movie_dict = {m.id: m for m in movies}
    
    recommended = []
    for hit in hits:
        if hit["movie_id"] in movie_dict and len(recommended) < limit:
            recommended.append(movie_dict[hit["movie_id"]])

    return recommended