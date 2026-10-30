"""One Alembic environment per database; no application role can perform DDL."""

from pathlib import Path

from alembic import command
from alembic.config import Config
from qfr_core.config import RuntimeSettings, logging_config
from qfr_core.correlation import bind
from qfr_core.logging import JsonLogger

settings = RuntimeSettings()
logger = JsonLogger("migrate", "control", settings.log_dir, logging_config(settings.config_dir))
for database in ("registry", "research", "eval", "control"):
    cfg = Config()
    cfg.set_main_option("script_location", str(Path("infra/migrations") / database))
    cfg.set_main_option("database", database)
    with bind(principal=f"{database}_migrator"):
        command.upgrade(cfg, "head")
        logger.logger.info("migration_completed", outcome="ok", payload={"database": database})
