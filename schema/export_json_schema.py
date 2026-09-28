"""Regenerate problem.schema.json / solution.schema.json from schema/models.py."""

import json
from pathlib import Path

from schema.models import Problem, Solution

HERE = Path(__file__).resolve().parent
TARGETS = {"problem.schema.json": Problem, "solution.schema.json": Solution}


def render(model) -> str:
    return json.dumps(model.model_json_schema(), indent=2) + "\n"


if __name__ == "__main__":
    for fname, model in TARGETS.items():
        (HERE / fname).write_text(render(model), encoding="utf-8")
        print(f"wrote schema/{fname}")
