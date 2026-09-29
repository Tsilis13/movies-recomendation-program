"""
TEMPORARY file. In Phase 3 (authentication) it is replaced by real JWT login.

For now the "logged-in user" is always the user with id=1
(the demo user created by seed.py). This lets us build and test the endpoints
before login exists. Only THIS function will change later, not the endpoints.
"""
from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from app import models
from app.database import get_db


def get_current_user(db: Session = Depends(get_db)) -> models.User:
    user = db.get(models.User, 1)
    if user is None:
        raise HTTPException(
            status_code=401,
            detail="Temporary auth: run seed.py first to create the demo user.",
        )
    return user