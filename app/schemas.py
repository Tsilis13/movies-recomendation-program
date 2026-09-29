from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

from app.models import WatchStatus


# One genre name: trimmed, 1-50 characters (used by both create and update).
Genre = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)]


# Movie-related schemas

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
    overview: str | None = Field(default=None, max_length=5000)
    poster_url: str | None = Field(default=None, max_length=500, pattern="^https?://")
    runtime_minutes: int | None = Field(default=None, gt=0, le=1000)
    tmdb_id: int | None = Field(default=None, gt=0)
    rating: int | None = Field(default=None, ge=1, le=10)
    genres: list[Genre] = Field(default_factory=list, max_length=15)
    status: WatchStatus = WatchStatus.PLANNED

    # A rule that involves TWO fields, so it cannot be a simple Field(...) limit.
    @model_validator(mode="after")
    def rating_requires_watched(self):
        if self.rating is not None and self.status != WatchStatus.WATCHED:
            raise ValueError("A movie can only be rated after it has been watched.")
        return self


class MovieUpdate(BaseModel):
    """
    For PATCH: EVERY field is optional. The client sends only what it wants to change.
    Field limits are the same as in MovieCreate.
    The rating/status rule is checked in the endpoint, because it depends on the
    movie that is already stored in the database.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    title: str | None = Field(default=None, min_length=1, max_length=200)
    year: int | None = Field(default=None, ge=1800, le=2100)
    director: str | None = Field(default=None, max_length=200)
    overview: str | None = Field(default=None, max_length=5000)
    poster_url: str | None = Field(default=None, max_length=500, pattern="^https?://")
    runtime_minutes: int | None = Field(default=None, gt=0, le=1000)
    tmdb_id: int | None = Field(default=None, gt=0)
    rating: int | None = Field(default=None, ge=1, le=10)
    genres: list[Genre] | None = Field(default=None, max_length=15)
    status: WatchStatus | None = None

    # "Not sent" and "sent as null" look the same in the field values, but they are different:
    # model_fields_set contains only the fields the client actually sent.
    @model_validator(mode="after")
    def required_fields_cannot_be_null(self):
        for name in ("title", "genres", "status"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"'{name}' cannot be null.")
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


class MovieListResponse(BaseModel):
    """One page of results, plus what a frontend needs to build page controls."""

    items: list[MovieResponse]
    total: int      # how many movies match the filters, across ALL pages
    limit: int
    offset: int


# Review-related schemas

MAX_MOOD_TAGS = 10
MAX_TAG_LENGTH = 30
MAX_REVIEW_LENGTH = 1500


def normalize_mood_tags(tags: list[str]) -> list[str]:
    """
    Make tags comparable: "Cozy", " cozy " and "COZY" must be the SAME tag,
    because the recommender will later match on them.
    Lowercase, collapse inner spaces, drop empty ones and duplicates (keeping the order).
    """
    cleaned: list[str] = []
    for tag in tags:
        tag = " ".join(tag.lower().split())
        if not tag:
            continue    # a trailing comma in a form should not be an error
        if len(tag) > MAX_TAG_LENGTH:
            raise ValueError(f"A mood tag can be at most {MAX_TAG_LENGTH} characters.")
        if tag not in cleaned:
            cleaned.append(tag)
    if len(cleaned) > MAX_MOOD_TAGS:
        raise ValueError(f"A review can have at most {MAX_MOOD_TAGS} mood tags.")
    return cleaned


class ReviewCreate(BaseModel):
    """What the user sends when writing a review. movie_id comes from the URL, not from here."""

    model_config = ConfigDict(str_strip_whitespace=True)

    text: str = Field(min_length=1, max_length=MAX_REVIEW_LENGTH)
    mood_tags: list[str] = Field(default_factory=list)

    @field_validator("mood_tags")
    @classmethod
    def clean_tags(cls, tags: list[str]) -> list[str]:
        return normalize_mood_tags(tags)


class ReviewUpdate(BaseModel):
    """For PATCH: both fields optional, the client sends only what it changes."""

    model_config = ConfigDict(str_strip_whitespace=True)

    text: str | None = Field(default=None, min_length=1, max_length=MAX_REVIEW_LENGTH)
    mood_tags: list[str] | None = None

    @field_validator("mood_tags")
    @classmethod
    def clean_tags(cls, tags: list[str] | None) -> list[str] | None:
        # None means "not sent" or "sent as null"; the validator below decides which is allowed.
        return None if tags is None else normalize_mood_tags(tags)

    @model_validator(mode="after")
    def fields_cannot_be_null(self):
        for name in ("text", "mood_tags"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"'{name}' cannot be null.")
        return self


class ReviewResponse(BaseModel):
    """What the API returns for a review."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    movie_id: int
    text: str
    mood_tags: list[str]
    created_at: datetime

class ReviewSearchHit(BaseModel):
    """Payload for meaning-based review searches."""
    review_id: int
    movie_id: int
    movie_title: str
    distance: float
    document: str


# User-related schemas
class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=20)
    password: str = Field(min_length=8, max_length=128)

    @field_validator("username")
    @classmethod
    def lowercase_username(cls, v: str) -> str:
        return v.lower()


class UserResponse(BaseModel):
    """Note what is NOT here: password_hash never leaves the server."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"