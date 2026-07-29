"""Strict runtime configuration and credential composition boundary."""

from .errors import ConfigurationViolation
from .loader import (
    DeploymentProfile,
    EffectiveConfig,
    PreflightRequirements,
    environment_override_manifest,
    load_effective_config,
    preflight_config,
    runtime_config_schema,
    schema_bytes,
)
from .models import RUNTIME_CONFIG_SCHEMA_VERSION, RuntimeConfig
from .secrets import EnvironmentFileCredentialPort

__all__ = (
    "RUNTIME_CONFIG_SCHEMA_VERSION",
    "ConfigurationViolation",
    "DeploymentProfile",
    "EffectiveConfig",
    "EnvironmentFileCredentialPort",
    "PreflightRequirements",
    "RuntimeConfig",
    "environment_override_manifest",
    "load_effective_config",
    "preflight_config",
    "runtime_config_schema",
    "schema_bytes",
)
