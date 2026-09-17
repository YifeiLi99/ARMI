"""JSON Schema-compatible text primitives; lengths remain owned by each contract."""

# Include Python's extra whitespace controls explicitly so JSON Schema and
# Pydantic's Rust regex engine agree with str.strip() at Owner boundaries.
NONBLANK_TEXT_PATTERN = r"^[^\x00]*[^\s\x00\x1c-\x1f][^\x00]*$"
NUL_FREE_TEXT_PATTERN = r"^[^\x00]*$"

__all__ = ("NONBLANK_TEXT_PATTERN", "NUL_FREE_TEXT_PATTERN")
