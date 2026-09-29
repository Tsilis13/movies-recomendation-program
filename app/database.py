from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

# Where the database lives. "sqlite:///./app.db" means: a file called app.db in the
# folder you run the program from. It is created automatically if it does not exist.
DATABASE_URL = "sqlite:///./app.db"

# The engine is the "communication line" to the database.
# check_same_thread=False: FastAPI uses several threads and SQLite needs to be told that is OK.
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})


# SQLite does NOT enforce foreign keys unless you ask it to.
# This hook asks for it on every new connection. (Explained in Step 1.3.)
@event.listens_for(engine, "connect")
def enable_sqlite_foreign_keys(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


# SessionLocal is a factory that creates sessions.
# A session is a conversation with the database: add, commit, query.
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    """Every model (table) inherits from this class."""
    pass


def get_db():
    """Used from Phase 2 on, inside the endpoints. Yields a session and always closes it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()