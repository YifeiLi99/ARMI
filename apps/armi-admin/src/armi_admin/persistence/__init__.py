"""Administration persistence adapter boundary."""

from .role_session import AdminRoleSessionError
from .schema_gateway import AdminSchemaGateway, AdminSchemaSnapshot

__all__ = (
    "AdminRoleSessionError",
    "AdminSchemaGateway",
    "AdminSchemaSnapshot",
)
