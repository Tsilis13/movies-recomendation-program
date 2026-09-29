"""
Rebuilds the vector indexes (reviews AND movie overviews) from SQLite.

    python reindex.py

Run it from the project root (the folder that contains the app/ folder).

SQLite is the source of truth and the vector index is only a searchable copy, so this is
always safe: it throws the copy away and makes a new one. Run it:
  - once now, to index the reviews that existed before the sync hooks,
  - any time the index and the database might disagree (for example after deleting chroma_db/).

Stop the server first: a running server keeps its own copy of the index in memory and would
not see the changes until it is restarted.
"""
from app import models, rag
from app.database import SessionLocal


def main() -> None:
    db = SessionLocal()
    try:
        indexed = rag.reindex_all(db)
        in_sqlite = db.query(models.Review).count()
        print(f"Reviews in SQLite:      {in_sqlite}")
        print(f"Reviews now in index:   {indexed}")
        print(f"Vectors in the store:   {rag.collection.count()}")
        if indexed == in_sqlite == rag.collection.count():
            print("OK: the review index matches the database.")
        else:
            print("WARNING: the review numbers above should all be equal.")

        movies_indexed = rag.reindex_movie_overviews(db)
        with_overview = db.query(models.Movie).filter(
            models.Movie.overview.isnot(None), models.Movie.overview != ""
        ).count()
        print(f"Movies with overview:   {with_overview}")
        print(f"Overviews now indexed:  {movies_indexed}")
        print(f"Overview vectors:       {rag.overviews_collection.count()}")
        if movies_indexed == with_overview == rag.overviews_collection.count():
            print("OK: the overview index matches the database.")
        else:
            print("WARNING: the overview numbers above should all be equal.")
    finally:
        db.close()


if __name__ == "__main__":
    main()