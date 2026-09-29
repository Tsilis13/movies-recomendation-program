from fastapi import FastAPI

from app import models  # noqa: F401  (the import registers the tables with Base)
from app.database import Base, engine
from app.routers import movies

# Create the tables if they do not exist yet (Alembic will replace this later).
Base.metadata.create_all(bind=engine)

app = FastAPI(title="Movie Watchlist Hub", version="0.1.0")

# Plug the movies router into the application.
app.include_router(movies.router)


@app.get("/")
def health_check():
    return {"status": "online"}