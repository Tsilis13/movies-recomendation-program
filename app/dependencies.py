from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app import models, security
from app.database import get_db

# Tells /docs where to send the username and password when you press "Authorize".
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> models.User:
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    user_id = security.decode_access_token(token)
    if user_id is None:
        raise credentials_error

    # A valid token for a user who no longer exists must not work.
    user = db.get(models.User, user_id)
    if user is None:
        raise credentials_error
    return user