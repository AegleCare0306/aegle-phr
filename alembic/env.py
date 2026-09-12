"""
Alembic environment.

The database URL comes from aegle_phr.settings (i.e. .env), never from
alembic.ini -- see that file's own header comment. This module runs as an
Alembic CLI entry point, so reading settings at module scope is correct
here; it is NOT an exception to the no-side-effects-at-import rule that
governs the aegle_phr package itself.
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from aegle_phr.models import Base
from aegle_phr.settings import load_settings

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Injected from settings rather than read from alembic.ini.
config.set_main_option("sqlalchemy.url", load_settings().database_url)

# Autogenerate compares against this.
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Emit SQL to stdout without connecting (`alembic upgrade head --sql`)."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Connect and run migrations against the live database."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
