"""
The vector layer: makes reviews searchable by meaning.

Two rules:
  1. SQLite is the source of truth. This index can always be rebuilt from it (reindex_all).
  2. Every search is limited to one user (the user_id filter).
"""
import logging

import chromadb
from sentence_transformers import SentenceTransformer

from app import models

logger = logging.getLogger(__name__)

# Loaded once, when this file is first imported (this takes a few seconds).
embedder = SentenceTransformer("all-MiniLM-L6-v2")

chroma_client = chromadb.PersistentClient(path="./chroma_db")

# cosine distance: 0 = identical meaning, bigger = less related.
collection = chroma_client.get_or_create_collection(
    name="reviews", metadata={"hnsw:space": "cosine"}
)
overviews_collection = chroma_client.get_or_create_collection(
    name="movie_overviews", metadata={"hnsw:space": "cosine"}
)


def embed(texts: list[str]) -> list[list[float]]:
    return embedder.encode(texts).tolist()


def build_document(text: str, mood_tags: list[str]) -> str:
    """The text that gets embedded: mood tags first, then the review. No movie title on purpose."""
    if mood_tags:
        return f"Mood: {', '.join(mood_tags)}. {text}"
    return text


def index_review(review_id: int, user_id: int, movie_id: int, text: str, mood_tags: list[str]) -> None:
    """Add a review to the index, or replace it if it is already there (upsert)."""
    try:
        document = build_document(text, mood_tags)
        collection.upsert(
            ids=[f"review-{review_id}"],
            embeddings=embed([document]),
            documents=[document],
            metadatas=[{"user_id": user_id, "movie_id": movie_id, "review_id": review_id}],
        )
    except Exception:
        logger.exception("Could not index review %s (SQLite is fine; run reindex.py to repair)", review_id)


def remove_review(review_id: int) -> None:
    try:
        collection.delete(ids=[f"review-{review_id}"])
    except Exception:
        logger.exception("Could not remove review %s from the index", review_id)


def remove_movie_reviews(movie_id: int) -> None:
    """Remove the vectors of every review of a movie (used when the movie is deleted)."""
    try:
        collection.delete(where={"movie_id": movie_id})
    except Exception:
        logger.exception("Could not remove the reviews of movie %s from the index", movie_id)


def build_movie_document(overview: str, genres: list[str]) -> str:
    """The text that gets embedded: Genres first, then the plot overview."""
    text = overview or ""
    if genres:
        return f"Genres: {', '.join(genres)}. {text}"
    return text


def remove_movie_overview(movie_id: int) -> None:
    try:
        overviews_collection.delete(ids=[f"movie-{movie_id}"])
    except Exception:
        pass  # If it wasn't indexed, it's fine


def index_movie_overview(movie_id: int, user_id: int, overview: str | None, genres: list[str]) -> None:
    """Embed a movie's overview so the recommender can surface it later (upsert)."""
    if not overview:
        # No plot to embed. Also drop any OLD vector, or it would keep matching stale text.
        remove_movie_overview(movie_id)
        return

    try:
        document = build_movie_document(overview, genres)
        overviews_collection.upsert(
            ids=[f"movie-{movie_id}"],
            embeddings=embed([document]),
            documents=[document],
            metadatas=[{"user_id": user_id, "movie_id": movie_id}],
        )
    except Exception:
        logger.exception("Could not index overview for movie %s", movie_id)


# ---- Searching

def search_reviews(user_id: int, query: str, top_k: int = 5) -> list[dict]:
    """The top_k reviews of THIS user closest in meaning to the query, closest first."""
    if collection.count() == 0:
        return []

    results = collection.query(
        query_embeddings=embed([query]),
        n_results=top_k,
        where={"user_id": user_id},     # the privacy rule
    )

    # Chroma returns one inner list per query. We sent one query, so we take [0] of each.
    hits = []
    for meta, distance, document in zip(
        results["metadatas"][0], results["distances"][0], results["documents"][0]
    ):
        hits.append({
            "review_id": meta["review_id"],
            "movie_id": meta["movie_id"],
            "distance": distance,
            "document": document,
        })
    return hits


def search_unseen_movies(user_id: int, query: str, top_k: int = 10) -> list[dict]:
    """Find movie overviews matching the vibe query for this user."""
    if overviews_collection.count() == 0:
        return []

    results = overviews_collection.query(
        query_embeddings=embed([query]),
        n_results=top_k,
        where={"user_id": user_id},     # the privacy rule
    )

    hits = []
    for meta, distance in zip(results["metadatas"][0], results["distances"][0]):
        hits.append({
            "movie_id": meta["movie_id"],
            "distance": distance,
        })
    return hits


# ---- Rebuilding

def _upsert_in_batches(coll, ids, documents, metas, batch_size: int = 200) -> None:
    for i in range(0, len(ids), batch_size):
        coll.upsert(
            ids=ids[i : i + batch_size],
            embeddings=embed(documents[i : i + batch_size]),
            documents=documents[i : i + batch_size],
            metadatas=metas[i : i + batch_size],
        )


def reindex_all(db) -> int:
    """Empty the review index and rebuild it from SQLite. Returns how many reviews were indexed."""
    existing_ids = collection.get()["ids"]
    if existing_ids:
        collection.delete(ids=existing_ids)

    # A review has no user_id of its own: its owner is the movie's owner, so we JOIN.
    rows = (
        db.query(models.Review, models.Movie.user_id)
        .join(models.Movie, models.Review.movie_id == models.Movie.id)
        .all()
    )
    if not rows:
        return 0

    documents = [build_document(review.text, review.mood_tags) for review, _ in rows]
    ids = [f"review-{review.id}" for review, _ in rows]
    metas = [{"user_id": uid, "movie_id": r.movie_id, "review_id": r.id} for r, uid in rows]
    _upsert_in_batches(collection, ids, documents, metas)
    return len(rows)


def reindex_movie_overviews(db) -> int:
    """Empty the overview index and rebuild it from SQLite. Returns how many movies were indexed."""
    existing_ids = overviews_collection.get()["ids"]
    if existing_ids:
        overviews_collection.delete(ids=existing_ids)

    movies = (
        db.query(models.Movie)
        .filter(models.Movie.overview.isnot(None), models.Movie.overview != "")
        .all()
    )
    if not movies:
        return 0

    documents = [build_movie_document(m.overview, m.genres) for m in movies]
    ids = [f"movie-{m.id}" for m in movies]
    metas = [{"user_id": m.user_id, "movie_id": m.id} for m in movies]
    _upsert_in_batches(overviews_collection, ids, documents, metas)
    return len(movies)