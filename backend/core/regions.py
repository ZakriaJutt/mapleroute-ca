"""Region parsing from Bedrock ARNs: the one implementation (UT-10, R-03)."""

from __future__ import annotations

from collections.abc import Iterable


class ArnError(ValueError):
    pass


def region_of_arn(arn: str) -> str:
    parts = arn.split(":")
    if len(parts) < 6 or parts[0] != "arn" or not parts[1].startswith("aws") or parts[2] != "bedrock":
        raise ArnError("not a Bedrock ARN")
    if not parts[3]:
        raise ArnError("ARN has no Region")
    return parts[3]


def regions_of_arns(arns: Iterable[str]) -> frozenset[str]:
    return frozenset(region_of_arn(a) for a in arns)
