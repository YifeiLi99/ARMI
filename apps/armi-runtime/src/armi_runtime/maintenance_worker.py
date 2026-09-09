"""One bounded local maintenance invocation, owned by the Admin parent."""

from __future__ import annotations

import json
import sys
from typing import Any, cast

from armi_adapter_esp32_display import MoodDisplayViolation
from armi_kernel.application import BirthViolation, ModelViolation
from armi_live_vision.api import LiveVisionViolation
from armi_live_voice.api import LiveVoiceViolation
from armi_local_control import ConfigurationViolation, RuntimeViolation
from armi_local_control.maintenance import (
    ConfigurationInvocation,
    MaintenanceInvocation,
)
from armi_web_observation.api import WebObservationViolation
from pydantic import ValidationError

from .composition.configuration_management import execute_configuration
from .composition.database import DatabaseViolation
from .composition.maintenance import execute_maintenance


def main() -> int:
    try:
        raw = sys.stdin.buffer.read(65537)
        if len(raw) > 65536:
            raise ValueError("ADMIN-MAINTENANCE-SIZE")
        values = json.loads(raw)
        if (
            isinstance(values, dict)
            and cast(dict[str, Any], values).get("schema_version")
            == "armi.local-configuration.v2"
        ):
            result = execute_configuration(
                ConfigurationInvocation.model_validate(values)
            )
        else:
            result = execute_maintenance(MaintenanceInvocation.model_validate(values))
    except (
        ConfigurationViolation,
        RuntimeViolation,
        DatabaseViolation,
        BirthViolation,
        ModelViolation,
        LiveVoiceViolation,
        LiveVisionViolation,
        WebObservationViolation,
        MoodDisplayViolation,
    ) as error:
        print(json.dumps({"status": "failed", "error_code": error.code}))
        return 3
    except ValueError as error:
        code = str(error)
        allowed = {
            "ADMIN-CONFIG-PATH",
            "ADMIN-CONFIG-SIZE",
            "ADMIN-CONFIG-VERSION-CONFLICT",
            "ADMIN-CONFIG-TYPE",
            "ADMIN-CONFIG-FIELDS",
            "ADMIN-ENVIRONMENT-MISMATCH",
            "ADMIN-CONFIG-READ-ARGUMENTS",
            "ADMIN-CONFIG-VERSION-REQUIRED",
        }
        print(
            json.dumps(
                {
                    "status": "rejected",
                    "error_code": code
                    if code in allowed
                    else "ADMIN-MAINTENANCE-INPUT",
                }
            )
        )
        return 2
    except OSError, ValidationError:
        print(
            json.dumps({"status": "rejected", "error_code": "ADMIN-MAINTENANCE-INPUT"})
        )
        return 2
    print(json.dumps({"status": "succeeded", "result": result}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

__all__ = ("main",)
