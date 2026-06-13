import logging
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)


@dataclass
class RangeInfo:
    allocated: bool
    operator: str | None = None
    region: str | None = None
    operator_inn: str | None = None


def parse_response(data: object) -> RangeInfo | None:
    """Parse a voxlink JSON object.

    Resolved (has `operator`) -> RangeInfo(allocated=True).
    "Number not found" / missing operator / non-dict -> None (collapses into
    the fail-open path; voxlink never asserts "not allocated").
    """
    if not isinstance(data, dict):
        return None
    operator = data.get("operator")
    if not operator:
        return None
    region = data.get("region")
    return RangeInfo(
        allocated=True,
        operator=str(operator).strip(),
        region=str(region).strip() if region else None,
        operator_inn=None,
    )


async def lookup(
    msisdn10: str,
    url: str,
    timeout: float,
    client: httpx.AsyncClient | None = None,
) -> RangeInfo | None:
    """GET voxlink for msisdn (10 digits). Returns RangeInfo on a resolved
    number, or None on not-found / non-200 / unreachable / unparseable
    (caller fail-opens). Pass `client` to reuse a connection (backfill)."""
    own = client is None
    if own:
        client = httpx.AsyncClient(timeout=timeout)
    try:
        resp = await client.get(
            url,
            params={"num": msisdn10},
            headers={"User-Agent": "sms-gate/1.0"},
        )
        if resp.status_code != 200:
            logger.warning("voxlink HTTP %d for %s", resp.status_code, msisdn10)
            return None
        try:
            data = resp.json()
        except ValueError:
            logger.warning("voxlink: non-JSON response for %s", msisdn10)
            return None
        return parse_response(data)
    except httpx.HTTPError as e:
        logger.warning("voxlink request failed for %s: %s", msisdn10, e)
        return None
    finally:
        if own:
            await client.aclose()
