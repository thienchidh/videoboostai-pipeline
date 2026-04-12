"""modules/pipeline — Video pipeline components."""

from modules.pipeline.config_loader import PipelineConfig, ConfigLoader

# Lazy import to avoid hard runtime dependency on psycopg2 (db.py imports it)
__all__ = ["PipelineConfig", "ConfigLoader"]
