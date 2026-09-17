"""Visible structural text constraints for bounded internal work."""

from typing import Annotated

from armi_kernel.contracts import NONBLANK_TEXT_PATTERN, NUL_FREE_TEXT_PATTERN
from pydantic import StringConstraints

type Text256 = Annotated[
    str, StringConstraints(min_length=1, max_length=256, pattern=NONBLANK_TEXT_PATTERN)
]
type Text512 = Annotated[
    str, StringConstraints(min_length=1, max_length=512, pattern=NONBLANK_TEXT_PATTERN)
]
type Text1024 = Annotated[
    str, StringConstraints(min_length=1, max_length=1024, pattern=NONBLANK_TEXT_PATTERN)
]
type Text2048 = Annotated[
    str, StringConstraints(min_length=1, max_length=2048, pattern=NONBLANK_TEXT_PATTERN)
]
type Text65536 = Annotated[
    str,
    StringConstraints(min_length=1, max_length=65536, pattern=NONBLANK_TEXT_PATTERN),
]
type Metadata = dict[
    Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9._-]{0,63}$")],
    Annotated[str, StringConstraints(max_length=512, pattern=NUL_FREE_TEXT_PATTERN)],
]
