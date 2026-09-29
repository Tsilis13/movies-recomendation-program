from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from fastapi.responses import FileResponse

from app import models  # noqa: F401  (the import registers the tables with Base)
from app.database import Base, engine
from app.limiter import limiter
from app.routers import auth, movies, reviews, tmdb, recommendations

# Create the tables if they do not exist yet (Alembic will replace this later).
Base.metadata.create_all(bind=engine)

app = FastAPI(title="Movie Watchlist Hub", version="0.2.0")

# Only these origins may call the API from a browser (SKH allowed "*"). The token is sent in
# the Authorization header, so no cookies/credentials are needed. Add your frontend's address here.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8000", "http://127.0.0.1:8000",
                   "http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)

# Rate limiting: login/register, TMDB lookups, review search and recommendations.
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.include_router(auth.router)
app.include_router(movies.router)
app.include_router(reviews.router)
app.include_router(tmdb.router)
app.include_router(recommendations.router)


@app.get("/")
def serve_frontend():
    return FileResponse("index.html")