"""Creates a second user with one movie, to test that users cannot see each other's data."""
from app import models
from app.database import Base, SessionLocal, engine

Base.metadata.create_all(bind=engine)

db = SessionLocal()

other = db.query(models.User).filter_by(username="other").first()
if other is None:
    other = models.User(username="other", password_hash="not-a-real-hash")
    db.add(other)
    db.commit()
    db.refresh(other)

movie = db.query(models.Movie).filter_by(user_id=other.id, title="Secret Movie").first()
if movie is None:
    movie = models.Movie(user_id=other.id, title="Secret Movie", year=2001)
    db.add(movie)
    db.commit()
    db.refresh(movie)

print(f"User 'other' has id={other.id}. Their movie 'Secret Movie' has id={movie.id}.")
print("Now, as the demo user, GET /movies/<that id> must return 404.")
db.close()