import json
from pathlib import Path


def load_state(path: str) -> dict:
    state_path = Path(path)
    if not state_path.exists():
        return {"last_ip": None}

    with state_path.open() as f:
        return json.load(f)


def save_state(path: str, state: dict) -> None:
    state_path = Path(path)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    with state_path.open("w") as f:
        json.dump(state, f, indent=2)
