"""Load, digest, redact, and preflight the effective runtime configuration."""

from __future__ import annotations

import copy
import hashlib
import json
import re
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Self, cast

from armi_kernel.application import CredentialPurpose
from armi_kernel.contracts import Digest
from pydantic import ValidationError

from .errors import ConfigurationViolation
from .models import RuntimeConfig
from .paths import canonical_absolute, has_reparse_point, require_within_roots
from .secrets import EnvironmentFileCredentialPort

_UNSIGNED_DECIMAL = re.compile(r"^(?:0|[1-9][0-9]*)$", re.ASCII)
_LOCATOR_NAME = re.compile(r"^[a-z][a-z0-9._-]{0,63}$", re.ASCII)
_SENSITIVE_KEY = re.compile(
    r"(?:password|passwd|token|api[_-]?key|private[_-]?key|authorization|secret)",
    re.IGNORECASE,
)
_ALLOWED_SCHEMES = frozenset({"env", "file"})
_ENV_OVERRIDES: dict[str, tuple[tuple[str, str], str]] = {
    "ARMI_ENVIRONMENT_ID": (("environment", "environment_id"), "string"),
    "ARMI_DATA_ROOT": (("environment", "data_root"), "string"),
    "ARMI_DB_POOL_MIN": (("database", "pool_min"), "integer"),
    "ARMI_DB_POOL_MAX": (("database", "pool_max"), "integer"),
    "ARMI_DB_POOL_ACQUIRE_TIMEOUT_SECONDS": (
        ("database", "pool_acquire_timeout_seconds"),
        "integer",
    ),
    "ARMI_DB_STATEMENT_TIMEOUT_SECONDS": (
        ("database", "statement_timeout_seconds"),
        "integer",
    ),
    "ARMI_DB_DIAGNOSTIC_TIMEOUT_SECONDS": (
        ("database", "diagnostic_statement_timeout_seconds"),
        "integer",
    ),
    "ARMI_DB_MAINTENANCE_TIMEOUT_SECONDS": (
        ("database", "maintenance_statement_timeout_seconds"),
        "integer",
    ),
    "ARMI_RUNTIME_LEASE_SECONDS": (("runtime", "lease_seconds"), "integer"),
    "ARMI_RUNTIME_HEARTBEAT_SECONDS": (
        ("runtime", "heartbeat_seconds"),
        "integer",
    ),
    "ARMI_WORK_LEASE_SECONDS": (("work", "lease_seconds"), "integer"),
    "ARMI_WORK_HEARTBEAT_SECONDS": (("work", "heartbeat_seconds"), "integer"),
    "ARMI_WORK_MAX_DEADLINE_SECONDS": (
        ("work", "max_deadline_seconds"),
        "integer",
    ),
    "ARMI_MODEL_CONCURRENCY": (("model", "concurrency"), "integer"),
    "ARMI_MODEL_ATTEMPT_TIMEOUT_SECONDS": (
        ("model", "attempt_timeout_seconds"),
        "integer",
    ),
    "ARMI_MODEL_MAX_ATTEMPTS": (
        ("model", "episode_max_attempts"),
        "integer",
    ),
    "ARMI_WEB_CONCURRENCY": (("web", "concurrency"), "integer"),
    "ARMI_WEB_STEP_TIMEOUT_SECONDS": (
        ("web", "step_timeout_seconds"),
        "integer",
    ),
    "ARMI_WEB_TOTAL_TIMEOUT_SECONDS": (
        ("web", "total_timeout_seconds"),
        "integer",
    ),
    "ARMI_CODEX_CONCURRENCY": (("codex", "concurrency"), "integer"),
    "ARMI_CODEX_TOTAL_TIMEOUT_SECONDS": (
        ("codex", "total_timeout_seconds"),
        "integer",
    ),
    "ARMI_CREATOR_PORT": (("creator", "port"), "integer"),
    "ARMI_CREATOR_REQUEST_BODY_MAX_BYTES": (
        ("creator", "request_body_max_bytes"),
        "integer",
    ),
    "ARMI_CREATOR_BOOTSTRAP_TTL_SECONDS": (
        ("creator", "bootstrap_ttl_seconds"),
        "integer",
    ),
    "ARMI_CREATOR_SESSION_TTL_SECONDS": (
        ("creator", "session_ttl_seconds"),
        "integer",
    ),
    "ARMI_ARTIFACT_MAX_BYTES": (
        ("artifacts", "max_object_bytes"),
        "integer",
    ),
    "ARMI_ARTIFACT_ORPHAN_GRACE_SECONDS": (
        ("artifacts", "orphan_grace_seconds"),
        "integer",
    ),
    "ARMI_DIAGNOSTIC_ROTATION_MAX_BYTES": (
        ("diagnostics", "rotation_max_bytes"),
        "integer",
    ),
    "ARMI_DIAGNOSTIC_RETENTION_SECONDS": (
        ("diagnostics", "retention_seconds"),
        "integer",
    ),
    "ARMI_OBSERVABILITY_SAMPLE_INTERVAL_SECONDS": (
        ("observability", "sample_interval_seconds"),
        "integer",
    ),
    "ARMI_DISK_WARNING_FREE_BYTES": (
        ("observability", "disk_warning_free_bytes"),
        "integer",
    ),
    "ARMI_DISK_CRITICAL_FREE_BYTES": (
        ("observability", "disk_critical_free_bytes"),
        "integer",
    ),
    "ARMI_GRACEFUL_SHUTDOWN_SECONDS": (
        ("lifecycle", "graceful_shutdown_seconds"),
        "integer",
    ),
    "ARMI_IDLE_POLL_INITIAL_SECONDS": (
        ("scheduler", "idle_poll_initial_seconds"),
        "integer",
    ),
    "ARMI_IDLE_POLL_MAX_SECONDS": (
        ("scheduler", "idle_poll_max_seconds"),
        "integer",
    ),
    "ARMI_MAINTENANCE_CONSIDERATION_AFTER_SECONDS": (
        ("maintenance", "consideration_after_seconds"),
        "integer",
    ),
    "ARMI_MAINTENANCE_DEADLINE_AFTER_SECONDS": (
        ("maintenance", "deadline_after_seconds"),
        "integer",
    ),
}


@dataclass(frozen=True, slots=True)
class EffectiveConfig:
    config: RuntimeConfig
    applied_sources: tuple[str, ...]

    def redacted_view(self) -> dict[str, object]:
        view = self.config.model_dump(mode="json")
        environment = view["environment"]
        assert isinstance(environment, dict)
        environment["data_root"] = {"configured": True}
        locators: dict[str, object] = {}
        for name, locator in self.config.secret_locators.items():
            reference = Digest.from_bytes(locator.identity().encode("utf-8")).to_wire()
            locators[name] = {
                "scheme": locator.scheme,
                "reference_digest": reference,
            }
        view["secret_locators"] = locators
        return view


@dataclass(frozen=True, slots=True)
class DeploymentProfile:
    allowed_data_roots: tuple[Path, ...]
    allowed_secret_roots: tuple[Path, ...]
    enabled_locator_schemes: frozenset[str] = _ALLOWED_SCHEMES
    maximum_secret_bytes: int = 65_536

    @classmethod
    def create(
        cls,
        *,
        allowed_data_roots: tuple[Path, ...],
        allowed_secret_roots: tuple[Path, ...],
        enabled_locator_schemes: frozenset[str] = _ALLOWED_SCHEMES,
        maximum_secret_bytes: int = 65_536,
    ) -> Self:
        if (
            not allowed_data_roots
            or not allowed_secret_roots
            or maximum_secret_bytes <= 0
            or not enabled_locator_schemes
            or not enabled_locator_schemes.issubset(_ALLOWED_SCHEMES)
        ):
            raise ConfigurationViolation("CFG-PROFILE", "deployment profile is invalid")
        data_roots = tuple(
            canonical_absolute(path, code="CFG-PROFILE") for path in allowed_data_roots
        )
        secret_roots = tuple(
            canonical_absolute(path, code="CFG-PROFILE")
            for path in allowed_secret_roots
        )
        return cls(
            allowed_data_roots=data_roots,
            allowed_secret_roots=secret_roots,
            enabled_locator_schemes=enabled_locator_schemes,
            maximum_secret_bytes=maximum_secret_bytes,
        )


@dataclass(frozen=True, slots=True)
class PreflightRequirements:
    required_secret_names: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if len(set(self.required_secret_names)) != len(self.required_secret_names):
            raise ConfigurationViolation(
                "CFG-REQUIREMENTS", "required credential names must be unique"
            )
        if any(
            _LOCATOR_NAME.fullmatch(name) is None for name in self.required_secret_names
        ):
            raise ConfigurationViolation(
                "CFG-REQUIREMENTS", "required credential name is invalid"
            )


def load_effective_config(
    *,
    defaults_path: Path,
    environment_path: Path,
    environment: Mapping[str, str] | None = None,
) -> EffectiveConfig:
    """Apply defaults, environment TOML, then the explicit environment allowlist."""

    defaults = _read_toml(defaults_path, required=True)
    environment_values = _read_toml(environment_path, required=True)
    _reject_plaintext_secrets(defaults)
    _reject_plaintext_secrets(environment_values)
    merged = _merge(defaults, environment_values)
    applied_sources = ["defaults.toml", "environment.toml"]
    overrides: Mapping[str, str] = environment if environment is not None else {}
    _reject_unknown_armi_environment(overrides)
    if _apply_environment_overrides(merged, overrides):
        applied_sources.append("explicit-environment")
    try:
        config = RuntimeConfig.model_validate(merged)
    except ValidationError as error:
        raise _translate_validation_error(error) from None
    return EffectiveConfig(
        config=config,
        applied_sources=tuple(applied_sources),
    )


def preflight_config(
    effective: EffectiveConfig,
    *,
    profile: DeploymentProfile,
    requirements: PreflightRequirements,
    environment: Mapping[str, str],
) -> None:
    """Validate trusted paths and only the explicitly required credentials."""

    data_root, trusted_root = require_within_roots(
        effective.config.environment.data_root,
        profile.allowed_data_roots,
        code="CFG-DATA-ROOT",
    )
    if not data_root.is_dir():
        raise ConfigurationViolation(
            "CFG-DATA-ROOT", "data root is not an existing directory"
        )
    if has_reparse_point(data_root, root=trusted_root):
        raise ConfigurationViolation(
            "CFG-DATA-REPARSE", "data root contains a reparse point"
        )
    for locator in effective.config.secret_locators.values():
        if locator.scheme not in profile.enabled_locator_schemes:
            raise ConfigurationViolation(
                "SEC-SECRET-SCHEME", "credential locator scheme is unsupported"
            )
    credential_port = EnvironmentFileCredentialPort(
        environment=environment,
        secret_roots=profile.allowed_secret_roots,
        maximum_bytes=profile.maximum_secret_bytes,
    )
    for name in requirements.required_secret_names:
        locator = effective.config.secret_locators.get(name)
        if locator is None:
            raise ConfigurationViolation(
                "SEC-SECRET-MISSING", "required credential locator is not configured"
            )
        purpose = CredentialPurpose(f"preflight.{name}")
        handle = credential_port.resolve(locator, purpose)
        handle.close()


def runtime_config_schema() -> dict[str, object]:
    return RuntimeConfig.model_json_schema(
        mode="validation",
        ref_template="#/$defs/{model}",
    )


def schema_bytes() -> bytes:
    text = json.dumps(
        runtime_config_schema(),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        separators=(",", ": "),
    )
    return f"{text}\n".encode()


def environment_override_manifest() -> dict[str, dict[str, object]]:
    return {
        name: {
            "path": ".".join(path),
            "type": kind,
            "env_overridable": True,
        }
        for name, (path, kind) in sorted(_ENV_OVERRIDES.items())
    }


def sha256_hex(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _read_toml(path: Path, *, required: bool) -> dict[str, Any]:
    try:
        content = path.read_bytes()
    except OSError:
        if required:
            raise ConfigurationViolation(
                "CFG-FILE", "required configuration file is unavailable"
            ) from None
        return {}
    try:
        parsed = tomllib.loads(content.decode("utf-8"))
    except UnicodeDecodeError, tomllib.TOMLDecodeError:
        raise ConfigurationViolation(
            "CFG-TOML", "configuration file is malformed"
        ) from None
    return parsed


def _merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(base)
    for key, value in override.items():
        existing = result.get(key)
        if isinstance(existing, dict) and isinstance(value, dict):
            result[key] = _merge(
                cast(dict[str, Any], existing),
                cast(dict[str, Any], value),
            )
        else:
            result[key] = copy.deepcopy(value)
    return result


def _reject_plaintext_secrets(value: object, *, path: tuple[str, ...] = ()) -> None:
    if not isinstance(value, dict):
        return
    mapping = cast(dict[object, object], value)
    for key, nested in mapping.items():
        current = (*path, str(key))
        if current[0] != "secret_locators" and _SENSITIVE_KEY.search(str(key)):
            raise ConfigurationViolation(
                "CFG-SECRET-PLAINTEXT",
                "plaintext sensitive configuration keys are forbidden",
                field=".".join(current),
            )
        _reject_plaintext_secrets(nested, path=current)


def _reject_unknown_armi_environment(environment: Mapping[str, str]) -> None:
    unknown = sorted(
        name
        for name in environment
        if name.startswith("ARMI_")
        and not name.startswith("ARMI_SECRET_")
        and name not in _ENV_OVERRIDES
    )
    if unknown:
        raise ConfigurationViolation(
            "CFG-UNKNOWN-ENV", "an unregistered ARMI environment override was set"
        )


def _apply_environment_overrides(
    target: dict[str, Any], environment: Mapping[str, str]
) -> bool:
    changed = False
    for name, (path, kind) in _ENV_OVERRIDES.items():
        if name not in environment:
            continue
        raw = environment[name]
        if kind == "integer":
            if _UNSIGNED_DECIMAL.fullmatch(raw) is None:
                raise ConfigurationViolation(
                    "CFG-ENV-TYPE",
                    "environment override must be unsigned decimal text",
                    field=".".join(path),
                )
            value: object = int(raw)
        else:
            value = raw
        current = target
        for segment in path[:-1]:
            child = current.get(segment)
            if isinstance(child, dict):
                current = cast(dict[str, Any], child)
            else:
                replacement: dict[str, Any] = {}
                current[segment] = replacement
                current = replacement
        current[path[-1]] = value
        changed = True
    return changed


def _translate_validation_error(error: ValidationError) -> ConfigurationViolation:
    first = error.errors(include_input=False, include_url=False)[0]
    error_type = str(first["type"])
    field = ".".join(str(part) for part in first["loc"]) or None
    if error_type == "extra_forbidden":
        code, message = "CFG-UNKNOWN-FIELD", "unknown configuration field"
    elif error_type == "missing":
        code, message = "CFG-MISSING", "required configuration field is missing"
    elif error_type in {"value_error", "literal_error"}:
        code, message = "CFG-RELATION", "configuration value violates a fixed rule"
    else:
        code, message = "CFG-TYPE", "configuration value has an invalid type"
    return ConfigurationViolation(code, message, field=field)


__all__ = (
    "DeploymentProfile",
    "EffectiveConfig",
    "PreflightRequirements",
    "environment_override_manifest",
    "load_effective_config",
    "preflight_config",
    "runtime_config_schema",
    "schema_bytes",
    "sha256_hex",
)
