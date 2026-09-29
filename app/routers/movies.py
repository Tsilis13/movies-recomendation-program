from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import models, rag, schemas
from app.database import get_db
from app.dependencies import get_current_user

# Every endpoint in this file lives under /movies.
router = APIRouter(prefix="/movies", tags=["movies"])

# Only these columns can be used for sorting (the client sends the key, never a column).
SORT_COLUMNS = {
    "created_at": models.Movie.created_at,
    "title": models.Movie.title,
    "year": models.Movie.year,
    "rating": models.Movie.rating,
}


def get_owned_movie_or_404(db: Session, movie_id: int, user: models.User) -> models.Movie:
    """
    Find a movie ONLY among this user's movies.
    If it does not exist, or belongs to someone else, the answer is the same (404),
    so nobody can discover which ids exist in the system.
    """
    movie = (
        db.query(models.Movie)
        .filter(models.Movie.id == movie_id, models.Movie.user_id == user.id)
        .first()
    )
    if movie is None:
        raise HTTPException(status_code=404, detail="Movie not found.")
    return movie


@router.get("", response_model=schemas.MovieListResponse)
def list_movies(
    status: models.WatchStatus | None = None,
    search: str | None = Query(default=None, min_length=1, max_length=100),
    min_rating: int | None = Query(default=None, ge=1, le=10),
    max_runtime: int | None = Query(default=None, gt=0, le=1000),
    sort: Literal["created_at", "title", "year", "rating"] = "created_at",
    descending: bool = True,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    # Always start from "this user's movies", then add a filter for each option that was sent.
    query = db.query(models.Movie).filter(models.Movie.user_id == current_user.id)

    if status is not None:
        query = query.filter(models.Movie.status == status)
    if search:
        # Case-insensitive "contains". % and _ are escaped so they match literally.
        safe_search = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        query = query.filter(models.Movie.title.ilike(f"%{safe_search}%", escape="\\"))
    if min_rating is not None:
        query = query.filter(models.Movie.rating >= min_rating)
    if max_runtime is not None:
        query = query.filter(models.Movie.runtime_minutes <= max_runtime)

    # Count AFTER all filters but BEFORE limit/offset: the number of matches across all pages.
    total = query.count()

    sort_column = SORT_COLUMNS[sort]
    ordering = sort_column.desc().nulls_last() if descending else sort_column.asc().nulls_last()

    # The id is a tie-breaker: without a fully deterministic order, movies with equal
    # values could appear on two different pages or on none.
    items = query.order_by(ordering, models.Movie.id).offset(offset).limit(limit).all()

    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get("/{movie_id}", response_model=schemas.MovieResponse)
def get_movie(
    movie_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return get_owned_movie_or_404(db, movie_id, current_user)


@router.post("", response_model=schemas.MovieResponse, status_code=201)
def create_movie(
    data: schemas.MovieCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    # user_id comes from the logged-in user, NEVER from what the client sent.
    movie = models.Movie(**data.model_dump(), user_id=current_user.id)
    db.add(movie)
    try:
        db.commit()
    except IntegrityError:
        # Pydantic already checked every other rule, so the only one that can still
        # fail here is the UNIQUE (user_id, tmdb_id) constraint.
        db.rollback()
        raise HTTPException(status_code=409, detail="This movie is already in your list.")
    db.refresh(movie)   # reload it to get the id and created_at that the database filled in
    rag.index_movie_overview(movie.id, current_user.id, movie.overview, movie.genres)
    return movie


@router.patch("/{movie_id}", response_model=schemas.MovieResponse)
def update_movie(
    movie_id: int,
    data: schemas.MovieUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    movie = get_owned_movie_or_404(db, movie_id, current_user)

    # exclude_unset=True: only the fields the client really sent.
    # {"rating": 8} changes the rating and leaves everything else untouched.
    changes = data.model_dump(exclude_unset=True)

    # Check the rating/status rule against the FINAL state (new values where sent,
    # stored values otherwise), BEFORE changing anything.
    final_status = changes.get("status", movie.status)
    final_rating = changes.get("rating", movie.rating)
    if final_rating is not None and final_status != models.WatchStatus.WATCHED:
        raise HTTPException(
            status_code=422,
            detail="A movie can only have a rating while its status is 'watched'.",
        )

    for field, value in changes.items():
        setattr(movie, field, value)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Another movie in your list already has this tmdb_id.")
    db.refresh(movie)
    if "overview" in changes or "genres" in changes:
        # index_movie_overview also removes the old vector when the overview is now empty.
        rag.index_movie_overview(movie.id, current_user.id, movie.overview, movie.genres)
    return movie


@router.delete("/{movie_id}", status_code=204)
def delete_movie(
    movie_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    movie = get_owned_movie_or_404(db, movie_id, current_user)
    db.delete(movie)    # its reviews are deleted too (cascade in models.py)
    db.commit()
    rag.remove_movie_reviews(movie_id)
    rag.remove_movie_overview(movie_id)
    # 204 means "done, nothing to send back", so there is no return value.