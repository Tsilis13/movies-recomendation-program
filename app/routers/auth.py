from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import models, schemas, security
from app.database import get_db
from app.dependencies import get_current_user
from app.limiter import limiter   # shared with every router; main.py plugs it into the app

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=schemas.UserResponse, status_code=201)
@limiter.limit("5/minute")
def register(request: Request, data: schemas.UserCreate, db: Session = Depends(get_db)):
    user = models.User(username=data.username, password_hash=security.hash_password(data.password))
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        # The UNIQUE constraint on username decides (same idea as duplicate movies).
        db.rollback()
        raise HTTPException(status_code=409, detail="This username is already taken.")
    db.refresh(user)
    return user


@router.post("/login", response_model=schemas.TokenResponse)
@limiter.limit("5/minute")
def login(request: Request, form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    # Usernames are stored lowercase (see UserCreate), so compare them lowercase too.
    username = form.username.strip().lower()
    user = db.query(models.User).filter(models.User.username == username).first()

    hash_to_check = user.password_hash if user else security.DUMMY_HASH
    password_ok = security.verify_password(form.password, hash_to_check)

    if user is None or not password_ok:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return {"access_token": security.create_access_token(user.id), "token_type": "bearer"}


@router.get("/me", response_model=schemas.UserResponse)
def read_me(current_user: models.User = Depends(get_current_user)):
    return current_user