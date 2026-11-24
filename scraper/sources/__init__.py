"""Source registry.

Adding a new operator is one file plus one line here.
"""
from __future__ import annotations

from .base import Context, Source


def build_sources(enabled: dict) -> list[Source]:
    """Instantiate only the sources turned on in config.yaml."""
    out: list[Source] = []

    if enabled.get("flix"):
        from .flix import FlixSource
        out.append(FlixSource())
    if enabled.get("wanderu"):
        from .wanderu import WanderuSource
        out.append(WanderuSource())
    if enabled.get("amtrak"):
        from .amtrak import AmtrakSource
        out.append(AmtrakSource())
    if enabled.get("megabus"):
        from .megabus import MegabusSource
        out.append(MegabusSource())
    if enabled.get("air"):
        from .air import AirSource
        out.append(AirSource())
    if enabled.get("transit"):
        from .transit import TransitSource
        out.append(TransitSource())
    if enabled.get("driving"):
        from .driving import DrivingSource
        out.append(DrivingSource())

    return out


__all__ = ["Context", "Source", "build_sources"]
