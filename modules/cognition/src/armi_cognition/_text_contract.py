"""Visible structural text constraints for bounded internal work."""

from typing import Annotated

from pydantic import StringConstraints

_NONBLANK = r"^[^\x00]*[^\s\x00][^\x00]*$"

type Text256 = Annotated[
    str, StringConstraints(min_length=1, max_length=256, pattern=_NONBLANK)
]
type Text512 = Annotated[
    str, StringConstraints(min_length=1, max_length=512, pattern=_NONBLANK)
]
type Text1024 = Annotated[
    str, StringConstraints(min_length=1, max_length=1024, pattern=_NONBLANK)
]
type Text2048 = Annotated[
    str, StringConstraints(min_length=1, max_length=2048, pattern=_NONBLANK)
]
type Text65536 = Annotated[
    str, StringConstraints(min_length=1, max_length=65536, pattern=_NONBLANK)
]
type Metadata = dict[
    Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9._-]{0,63}$")],
    Annotated[str, StringConstraints(max_length=512, pattern=r"^[^\x00]*$")],
]
