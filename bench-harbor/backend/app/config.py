from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="BENCH_HARBOR_")

    # Repo root (parent of bench-harbor); tasks live at <repo>/tasks
    repo_root: Path = Path(__file__).resolve().parents[3]
    tasks_dir_name: str = "tasks"
    data_dir: Path = Path(__file__).resolve().parents[2] / "data"

    @property
    def tasks_root(self) -> Path:
        return self.repo_root / self.tasks_dir_name


settings = Settings()
