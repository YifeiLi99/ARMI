from __future__ import annotations

import json
import os
from typing import Any


def pytest_configure(config: Any) -> None:
    del config
    encoded = os.environ.get("ARMI_TEST_POSTGRESQL_WORKER_DSNS")
    worker_id = os.environ.get("PYTEST_XDIST_WORKER")
    if encoded is None or worker_id is None:
        return
    if not worker_id.startswith("gw") or not worker_id[2:].isdigit():
        raise RuntimeError("PG-INTEGRATION-WORKER-IDENTITY")
    values = json.loads(encoded)
    if not isinstance(values, list) or not all(
        isinstance(value, str) for value in values
    ):
        raise RuntimeError("PG-INTEGRATION-WORKER-DSN")
    worker_index = int(worker_id[2:])
    if worker_index >= len(values):
        raise RuntimeError("PG-INTEGRATION-WORKER-COUNT")
    os.environ["S009_ADMIN_DSN"] = values[worker_index]
    del os.environ["ARMI_TEST_POSTGRESQL_WORKER_DSNS"]
