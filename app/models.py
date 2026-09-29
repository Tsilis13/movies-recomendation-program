import enum
from datetime import datetime

from sqlalchemy import (
    JSON, CheckConstraint, DateTime, Enum, ForeignKey,
    String, Text, UniqueConstraint, func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class WatchStatus(str, enum.Enum):
    PLANNED = "planned"   # on the watchlist, not seen yet
    WATCHED = "watched"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))

    movies: Mapped[list["Movie"]] = relationship(back_populates="owner", cascade="all, delete-orphan")


class Movie(Base):
    """A movie in one user's list."""
    __tablename__ = "movies"
    __table_args__ = (
        UniqueConstraint("user_id", "tmdb_id", name="uq_user_tmdb"),
        CheckConstraint("rating IS NULL OR (rating BETWEEN 1 AND 10)", name="ck_rating_range"),
        CheckConstraint("year IS NULL OR (year BETWEEN 1800 AND 2100)", name="ck_year_range"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    # Foreign key: this value must be an existing id in the users table.
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)

    title: Mapped[str] = mapped_column(String(200))

    # Optional columns ("| None" allows NULL, meaning "no value")
    year: Mapped[int | None]
    director: Mapped[str | None] = mapped_column(String(200))
    overview: Mapped[str | None] = mapped_column(Text)
    poster_url: Mapped[str | None] = mapped_column(String(500))
    runtime_minutes: Mapped[int | None]                         # lets us recommend "something short"
    tmdb_id: Mapped[int | None]                                 # the movie's id on themoviedb.org
    rating: Mapped[int | None]                                  # stays NULL until you have seen it

    genres: Mapped[list[str]] = mapped_column(JSON, default=list)

    status: Mapped[WatchStatus] = mapped_column(Enum(WatchStatus), default=WatchStatus.PLANNED)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    owner: Mapped["User"] = relationship(back_populates="movies")
    reviews: Mapped[list["Review"]] = relationship(back_populates="movie", cascade="all, delete-orphan")


class Review(Base):
    """A personal note about a movie. Ownership is derived through the movie."""
    __tablename__ = "reviews"
 
    id: Mapped[int] = mapped_column(primary_key=True)
    movie_id: Mapped[int] = mapped_column(ForeignKey("movies.id", ondelete="CASCADE"), index=True)
 
    text: Mapped[str] = mapped_column(Text)
    mood_tags: Mapped[list[str]] = mapped_column(JSON, default=list)   # e.g. ["cozy", "funny"]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
 
    movie: Mapped["Movie"] = relationship(back_populates="reviews")
 