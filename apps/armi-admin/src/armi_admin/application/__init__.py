"""Administration application boundary."""

from .configuration import (
    ADMIN_CONFIG_ENV,
    AdminConfig,
    AdminConfigError,
    AdminEnvironmentKind,
    load_admin_config,
)
from .control_plane import AdminControlError, AdminControlPlane
from .corrections import AdminCorrectionCoordinator, AdminCorrectionError
from .credentials import AdminCredentialPort, AdminSecretError
from .package_identity import (
    admin_program_identity,
)

__all__ = (
    "ADMIN_CONFIG_ENV",
    "AdminConfig",
    "AdminConfigError",
    "AdminControlError",
    "AdminControlPlane",
    "AdminCorrectionCoordinator",
    "AdminCorrectionError",
    "AdminCredentialPort",
    "AdminEnvironmentKind",
    "AdminSecretError",
    "admin_program_identity",
    "load_admin_config",
)
