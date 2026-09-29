from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models import WatchStatus


class MovieCreate(BaseModel):
    """
    What the user sends when adding a movie.
    Note what is NOT here: id, user_id and created_at. The user cannot choose those.
    """

    # Strip spaces around text BEFORE the length checks, so a title of "   " is rejected.
    model_config = ConfigDict(str_strip_whitespace=True)

    title: str = Field(min_length=1, max_length=200)
    year: int | None = Field(default=None, ge=1800, le=2100)
    director: str | None = Field(default=None, max_length=200)
    overview: str | None = None
    poster_url: str | None = Field(default=None, max_length=500)
    runtime_minutes: int | None = Field(default=None, gt=0, le=1000)
    tmdb_id: int | None = Field(default=None, gt=0)
    rating: int | None = Field(default=None, ge=1, le=10)
    genres: list[str] = Field(default_factory=list)
    status: WatchStatus = WatchStatus.PLANNED

    # A rule that involves TWO fields, so it cannot be a simple Field(...) limit.
    @model_validator(mode="after")
    def rating_requires_watched(self):
        if self.rating is not None and self.status != WatchStatus.WATCHED:
            raise ValueError("A movie can only be rated after it has been watched.")
        return self


class MovieResponse(BaseModel):
    """What the API returns for a movie. Only these fields ever leave the server."""

    # Lets Pydantic read the fields straight from a SQLAlchemy object (movie.title, ...).
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    title: str
    year: int | None
    director: str | None
    overview: str | None
    poster_url: str | None
    runtime_minutes: int | None
    tmdb_id: int | None
    rating: int | None
    genres: list[str]
    status: WatchStatus
    created_at: datetime