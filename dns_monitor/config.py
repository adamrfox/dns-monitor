from pathlib import Path

import yaml

REQUIRED_TOP_LEVEL_KEYS = ("unifi", "state_file", "records")


def load_config(path: str) -> dict:
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(
            f"Config file not found: {config_path}. Copy config.example.yaml to {config_path} and fill it in."
        )

    with config_path.open() as f:
        config = yaml.safe_load(f)

    missing = [key for key in REQUIRED_TOP_LEVEL_KEYS if key not in config]
    if missing:
        raise ValueError(f"Config is missing required keys: {missing}")

    return config
