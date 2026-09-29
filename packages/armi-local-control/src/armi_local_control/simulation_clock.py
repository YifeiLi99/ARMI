"""Explicit source-lab clock state, shared by its Runtime and Admin readers."""

import json
from pathlib import Path


class SimulationClock:
    def __init__(self, root: Path, environment_id: str) -> None:
        self.path = root / "simulation-clock.json"
        self.environment_id = environment_id
        self.offset = 0
        self.seed: int | None = None

    def validate(self) -> None:
        document = json.loads(self.path.read_text(encoding="utf-8"))
        if (
            set(document) != {"schema_kind", "environment_id", "random_seed"}
            or document["schema_kind"] != "armi.simulation-clock"
            or document["environment_id"] != self.environment_id
        ):
            raise ValueError("SIMULATION-CLOCK-INVALID")
        seed = document["random_seed"]
        if seed is not None and type(seed) is not int:
            raise ValueError("SIMULATION-CLOCK-SEED")
        self.seed = seed

    def read(self) -> int:
        return self.offset

    def set_offset(self, value: int) -> None:
        if type(value) is not int or value < self.offset:
            raise ValueError("SIMULATION-CLOCK-OFFSET")
        self.offset = value

    def initialize(self, seed: int | None = None) -> None:
        if self.path.exists():
            self.validate()
            if seed is not None and seed != self.seed:
                raise ValueError("SIMULATION-CLOCK-SEED-CHANGED")
            return
        self.seed = seed
        with self.path.open("x", encoding="utf-8", newline="\n") as output:
            json.dump(self.document(), output, indent=2)
            output.write("\n")

    def document(self) -> dict[str, object]:
        return {
            "schema_kind": "armi.simulation-clock",
            "environment_id": self.environment_id,
            "random_seed": self.seed,
        }
