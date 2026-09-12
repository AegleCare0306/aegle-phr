"""
Database engine and session handling.

SYNC, NOT ASYNC, and that is deliberate. Every route handler in this app is
a plain `def` (see aegle_phr/api.py), because everything downstream of a
route blocks: abdm_core talks to ABDM with `requests`, and this module uses
sync SQLAlchemy. FastAPI runs a `def` handler in a threadpool, which is the
correct place for blocking work. An `async def` handler making a blocking
call stalls the event loop for every other request in the process -- the
existing backend already shipped and fixed exactly that bug (commit
6a1d748, "Fix event-loop deadlock in M2/M3 self-referential data push"),
and once the PHR is mounted into that same process the blast radius is
shared. Hence: psycopg (sync), not asyncpg.

NO ENGINE IS CREATED AT IMPORT. init_engine() is called from bootstrap()
and is idempotent -- a host application that has already bootstrapped must
not get a second engine (and therefore a second connection pool) just
because something imported this module again.
"""

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

# Module-level slots, deliberately None until init_engine() runs. Assigning
# None is not a side effect: nothing is opened, resolved, or connected.
_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None

# libpq connect_timeout, in seconds. Without this an unreachable database
# does not fail fast: measured on this machine, a connect to a port with
# nothing listening on it blocked for roughly FOUR MINUTES before giving
# up. That makes GET /phr/health useless (a health check that hangs tells
# a load balancer nothing) and would stall a threadpool worker on every
# inbound callback while Postgres is down. 5s is well above a healthy
# local/VPC connect and far below anything a caller would wait out.
_CONNECT_TIMEOUT_SECONDS = 5


def init_engine(database_url: str, echo: bool = False) -> Engine:
    """
    Creates the process-wide engine and session factory, once.

    IDEMPOTENT: if an engine already exists it is returned unchanged and
    `database_url` is ignored. Callers that genuinely need to point at a
    different database (tests) must call reset_engine() first -- silently
    rebuilding on a differing URL would make a double bootstrap() quietly
    swap the database underneath live sessions.
    """
    global _engine, _session_factory

    if _engine is not None:
        return _engine

    _engine = create_engine(
        database_url,
        echo=echo,
        pool_pre_ping=True,  # a recycled Postgres connection must not 500 a callback
        future=True,
        connect_args={"connect_timeout": _CONNECT_TIMEOUT_SECONDS},
    )
    _session_factory = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


def get_engine() -> Engine:
    """
    The engine created by init_engine().

    Raises:
        RuntimeError: If bootstrap() was never called -- a loud, explicit
            error naming the fix, rather than a None dereference deep
            inside a request.
    """
    if _engine is None:
        raise RuntimeError(
            "aegle_phr database engine is not initialised. Call "
            "aegle_phr.bootstrap.bootstrap(settings) once at application "
            "startup before handling requests."
        )
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    """The session factory created by init_engine(). Raises if unbootstrapped."""
    if _session_factory is None:
        get_engine()  # raises the explanatory RuntimeError
    assert _session_factory is not None
    return _session_factory


@contextmanager
def session_scope() -> Iterator[Session]:
    """
    Transactional scope around a series of operations. Commits on clean
    exit, rolls back on any exception, always closes.
    """
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def check_connection() -> bool:
    """
    True if the database answers a trivial query. Never raises -- this
    backs GET /phr/health, which must report a down database as
    `"database": false` rather than failing the health check itself with
    a 500 (a health endpoint that 500s tells a load balancer nothing it
    can distinguish from the app being wedged).
    """
    try:
        with get_engine().connect() as connection:
            connection.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


def reset_engine() -> None:
    """
    Disposes the engine and clears both slots.

    For tests and for the standalone server's shutdown path. Not something
    a mounted PHR should ever call -- the host owns process lifecycle.
    """
    global _engine, _session_factory

    if _engine is not None:
        _engine.dispose()

    _engine = None
    _session_factory = None
