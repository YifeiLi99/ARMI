"""Explicit Web Search provider composition for the isolated live gate."""

from armi_web_observation.bootstrap import (
    normalize_web_search_provider_response as normalize_provider_response,
)
from armi_web_observation.bootstrap import (
    web_search_api_base as API_BASE,
)
from armi_web_observation.bootstrap import (
    web_search_binding_id as BINDING_ID,
)
from armi_web_observation.bootstrap import (
    web_search_model as MODEL,
)
from armi_web_observation.bootstrap import (
    web_search_tool_declaration as TOOL_DECLARATION,
)
from armi_web_observation.bootstrap import (
    web_search_violation as WebSearchViolation,
)

__all__ = (
    "API_BASE",
    "BINDING_ID",
    "MODEL",
    "TOOL_DECLARATION",
    "WebSearchViolation",
    "normalize_provider_response",
)
