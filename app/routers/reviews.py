from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app import models, rag, schemas
from app.database import get_db
from app.dependencies import get_current_user
from app.routers.movies import get_owned_movie_or_404

# No prefix here: reviews live under TWO different paths.
#   /movies/{movie_id}/reviews   -> "the reviews OF this movie" (create, list)
#   /reviews/{review_id}         -> one specific review (get, edit, delete)
router = APIRouter(tags=["reviews"])


def get_owned_review_or_404(db: Session, review_id: int, user: models.User) -> models.Review:
    """
    A review has no user_id: it belongs to a movie, and the movie belongs to a user.
    So to check ownership we JOIN the two tables and filter on the movie's owner.
    Same rule as for movies: "does not exist" and "not yours" both give 404.
    """
    review = (
        db.query(models.Review)
        .join(models.Movie, models.Review.movie_id == models.Movie.id)
        .filter(models.Review.id == review_id, models.Movie.user_id == user.id)
        .first()
    )
    if review is None:
        raise HTTPException(status_code=404, detail="Review not found.")
    return review


# ---------------------------------------------------------------------------
# The two endpoints that live under a movie
# ---------------------------------------------------------------------------

@router.post("/movies/{movie_id}/reviews", response_model=schemas.ReviewResponse, status_code=201)
def create_review(
    movie_id: int,
    data: schemas.ReviewCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    # First prove the movie is the user's. Without this, anyone could attach
    # reviews to a movie of somebody else just by guessing its id.
    movie = get_owned_movie_or_404(db, movie_id, current_user)

    review = models.Review(**data.model_dump(), movie_id=movie.id)
    db.add(review)
    db.commit()
    db.refresh(review)
    rag.index_review(review.id, current_user.id, movie.id, review.text, review.mood_tags)
    return review


@router.get("/movies/{movie_id}/reviews", response_model=list[schemas.ReviewResponse])
def list_movie_reviews(
    movie_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    # Check the movie FIRST: for somebody else's movie the answer must be 404,
    # not an empty list (an empty list would confirm that the movie exists).
    movie = get_owned_movie_or_404(db, movie_id, current_user)

    # Newest first; the id is the tie-breaker, as in the movies list.
    return (
        db.query(models.Review)
        .filter(models.Review.movie_id == movie.id)
        .order_by(models.Review.created_at.desc(), models.Review.id.desc())
        .all()
    )


@router.get("/reviews/search", response_model=list[schemas.ReviewSearchHit])
def search_movie_reviews(
    q: str = Query(..., min_length=1, max_length=200),
    top_k: int = Query(default=5, ge=1, le=20),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    hits = rag.search_reviews(current_user.id, q, top_k=top_k)
    if not hits:
        return []

    # Fetch titles to map back to the vector hits
    movie_ids = [hit["movie_id"] for hit in hits]
    movies = db.query(models.Movie.id, models.Movie.title).filter(models.Movie.id.in_(movie_ids)).all()
    title_map = {m.id: m.title for m in movies}

    return [
        {
            "review_id": hit["review_id"],
            "movie_id": hit["movie_id"],
            "movie_title": title_map.get(hit["movie_id"], "Unknown"),
            "distance": hit["distance"],
            "document": hit["document"],
        }
        for hit in hits
    ]

@router.get("/reviews/{review_id}", response_model=schemas.ReviewResponse)
def get_review(
    review_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return get_owned_review_or_404(db, review_id, current_user)


@router.patch("/reviews/{review_id}", response_model=schemas.ReviewResponse)
def update_review(
    review_id: int,
    data: schemas.ReviewUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    review = get_owned_review_or_404(db, review_id, current_user)

    # Only the fields the client really sent. {"mood_tags": ["sad"]} leaves the text alone.
    # (An empty body {} changes nothing and returns the review as it is.)
    changes = data.model_dump(exclude_unset=True)

    # There is no cross-field rule and no UNIQUE constraint on reviews, so there is
    # nothing to check first and no IntegrityError to catch here.
    for field, value in changes.items():
        setattr(review, field, value)   # mood_tags gets a NEW list, so the JSON column notices the change

    db.commit()
    db.refresh(review)
    rag.index_review(review.id, current_user.id, review.movie_id, review.text, review.mood_tags)
    return review


@router.delete("/reviews/{review_id}", status_code=204)
def delete_review(
    review_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    review = get_owned_review_or_404(db, review_id, current_user)
    db.delete(review)
    db.commit()
    rag.remove_review(review_id)
    # 204: nothing to send back.