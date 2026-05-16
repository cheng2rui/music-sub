"""Database setup with SQLAlchemy."""
import os
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, DeclarativeBase

DB_PATH = os.environ.get("MUSIC_SUB_DB", "data/music_sub.db")

engine = create_engine(f"sqlite:///{DB_PATH}", echo=False)
SessionLocal = sessionmaker(bind=engine)


class Base(DeclarativeBase):
    pass


def _ensure_column(table: str, column: str, ddl: str):
    """Add a SQLite column when upgrading an existing local database."""
    with engine.begin() as conn:
        columns = {row[1] for row in conn.execute(text(f"PRAGMA table_info({table})"))}
        if column not in columns:
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))


def _run_lightweight_migrations():
    """Apply additive SQLite migrations for deployments without Alembic."""
    if engine.dialect.name != "sqlite":
        return
    for column, ddl in {
        "track_number": "INTEGER",
        "disc_number": "INTEGER",
        "sample_rate": "INTEGER",
        "channels": "INTEGER",
    }.items():
        _ensure_column("music_files", column, ddl)


def init_db():
    """Create all tables and apply safe additive migrations."""
    # Ensure ORM models are registered even when init_db() is called in isolation.
    import app.models  # noqa: F401

    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    Base.metadata.create_all(bind=engine)
    _run_lightweight_migrations()


def get_db():
    """Dependency for FastAPI."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
