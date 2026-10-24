"""Thick-film parasite counting and density estimation.

Darubini follows the counting procedure taught in WHO *Basic Malaria Microscopy*
(2nd ed., 2010): parasites are counted against white blood cells (WBC) in a thick
film and converted to parasites per microlitre using an assumed WBC count.

Every threshold lives in :class:`CountingProtocol` so a lab can match its own SOP.
These defaults must be confirmed by a qualified microscopist before any use
beyond research.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum

from darubini.types import FieldResult


@dataclass(frozen=True)
class CountingProtocol:
    """Thresholds for the thick-film counting rule.

    Attributes:
        assumed_wbc_per_ul: WBC per microlitre used to convert ratios to density.
        first_wbc_target: WBC to count before the first decision point.
        extended_wbc_target: WBC to count when few parasites are seen.
        min_parasites_at_first_target: parasites needed at ``first_wbc_target`` to stop.
        fields_before_negative: fields to examine with no parasites before reporting negative.

    """

    assumed_wbc_per_ul: int = 8000
    first_wbc_target: int = 200
    extended_wbc_target: int = 500
    min_parasites_at_first_target: int = 10
    fields_before_negative: int = 100

    def __post_init__(self) -> None:
        if self.assumed_wbc_per_ul <= 0:
            raise ValueError("assumed_wbc_per_ul must be positive")
        if not 0 < self.first_wbc_target <= self.extended_wbc_target:
            raise ValueError("need 0 < first_wbc_target <= extended_wbc_target")
        if self.fields_before_negative <= 0:
            raise ValueError("fields_before_negative must be positive")


WHO_DEFAULT = CountingProtocol()


class CountStatus(str, Enum):
    """Where the counting procedure stands."""

    CONTINUE = "continue"
    COMPLETE = "complete"
    NEGATIVE = "negative"


@dataclass(frozen=True)
class SlideCount:
    """Running totals for a slide and the decision they lead to."""

    fields_examined: int
    usable_fields: int
    parasites: int
    wbcs: int
    status: CountStatus
    density_per_ul: float | None
    reason: str

    @property
    def is_positive(self) -> bool | None:
        """True or False once decided, None while counting continues."""
        if self.status is CountStatus.NEGATIVE:
            return False
        if self.status is CountStatus.COMPLETE:
            return self.parasites > 0
        return None


def parasite_density(parasites: int, wbcs: int, protocol: CountingProtocol = WHO_DEFAULT) -> float:
    """Convert a parasite-to-WBC count into parasites per microlitre.

    Args:
        parasites: parasites counted.
        wbcs: white blood cells counted alongside them.
        protocol: supplies the assumed WBC count per microlitre.

    Returns:
        Estimated parasites per microlitre of blood.

    Raises:
        ValueError: if counts are negative or no WBC were counted.

    """
    if parasites < 0 or wbcs < 0:
        raise ValueError("counts cannot be negative")
    if wbcs == 0:
        raise ValueError("cannot estimate density without counted WBC")
    return parasites * protocol.assumed_wbc_per_ul / wbcs


def evaluate_slide(
    fields: Iterable[FieldResult], protocol: CountingProtocol = WHO_DEFAULT
) -> SlideCount:
    """Apply the stopping rule to the fields examined so far.

    Unusable fields (blocking quality flags) are skipped and do not count
    towards totals or the negative threshold.
    """
    examined = usable = parasites = wbcs = 0
    for f in fields:
        examined += 1
        if not f.usable:
            continue
        usable += 1
        parasites += f.parasites
        wbcs += f.wbcs

    def done(reason: str) -> SlideCount:
        return SlideCount(
            examined,
            usable,
            parasites,
            wbcs,
            CountStatus.COMPLETE,
            parasite_density(parasites, wbcs, protocol),
            reason,
        )

    if wbcs >= protocol.extended_wbc_target:
        return done(f"reached {protocol.extended_wbc_target} WBC")
    if wbcs >= protocol.first_wbc_target and parasites >= protocol.min_parasites_at_first_target:
        return done(
            f"{parasites} parasites at {wbcs} WBC "
            f"(>= {protocol.min_parasites_at_first_target} at {protocol.first_wbc_target})"
        )
    if parasites == 0 and usable >= protocol.fields_before_negative:
        return SlideCount(
            examined,
            usable,
            0,
            wbcs,
            CountStatus.NEGATIVE,
            0.0,
            f"no parasites in {usable} usable fields",
        )

    if parasites > 0 and wbcs >= protocol.first_wbc_target:
        reason = f"few parasites; continue to {protocol.extended_wbc_target} WBC"
    elif parasites > 0:
        reason = f"continue to {protocol.first_wbc_target} WBC"
    else:
        reason = f"no parasites yet; examine {protocol.fields_before_negative} usable fields"
    density = parasite_density(parasites, wbcs, protocol) if wbcs else None
    return SlideCount(examined, usable, parasites, wbcs, CountStatus.CONTINUE, density, reason)
