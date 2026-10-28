from alembic import context
from sqlalchemy import create_engine

from src.dtest.core import models  # noqa: F401  (registers tables)
from src.dtest.core.config import get_settings
from src.dtest.core.db import Base
from src.dtest.gaia_bridge import models as gaia_models  # noqa: F401

config = context.config
url = config.get_main_option("sqlalchemy.url") or get_settings().database_url


def run() -> None:
    engine = create_engine(url)
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=Base.metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


run()
