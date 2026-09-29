"""
One shared rate limiter for the whole app.

It lives in its own file so every router can import it without importing each other
(auth.py used to own it, which would make tmdb.py / reviews.py depend on auth.py).

main.py plugs it into the app:  app.state.limiter = limiter
"""
from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from app import security


def user_or_ip_key(request: Request) -> str:
    """
    Rate-limit logged-in users per ACCOUNT, everyone else per IP address.

    - Per account: users behind the same office/school IP don't block each other, and one
      user can't dodge the limit by changing IP.
    - The token is really verified (decode_access_token), so nobody can pick someone
      else's bucket by sending a fake token: an invalid token falls back to the IP.
    """
    header = request.headers.get("Authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() == "bearer" and token:
        user_id = security.decode_access_token(token)
        if user_id is not None:
            return f"user:{user_id}"
    return get_remote_address(request)


limiter = Limiter(key_func=user_or_ip_key)