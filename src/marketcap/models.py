import json
from dataclasses import asdict, dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path


class DataError(ValueError):
    """A data contract failed; the previous published snapshot remains authoritative."""


def positive(value: object, label: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise DataError(f"{label}: missing or invalid number") from None
    if not result.is_finite() or result <= 0:
        raise DataError(f"{label}: expected a finite positive number")
    return result


@dataclass(frozen=True)
class Settings:
    exchanges: tuple[str, ...] = ("XNYS", "XNAS", "XASE")
    security_types: tuple[str, ...] = ("CS",)
    requests_per_minute: int = 20
    max_requests_per_run: int = 80
    max_retries: int = 3
    minimum_companies: int = 1000
    minimum_universe_ratio: float = 0.9
    minimum_quote_coverage: float = 0.98
    canonical_tickers: dict[str, str] = field(default_factory=dict)
    company_names: dict[str, str] = field(default_factory=dict)
    identity_overrides: dict[str, dict[str, str]] = field(default_factory=dict)

    @classmethod
    def read(cls, path: Path) -> "Settings":
        values = json.loads(path.read_text())
        for key in ("exchanges", "security_types"):
            if key in values:
                values[key] = tuple(values[key])
        result = cls(**values)
        if (
            result.requests_per_minute <= 0
            or result.max_requests_per_run < 1
            or not 0 <= result.max_retries <= 8
        ):
            raise DataError("Invalid request limit or retry count")
        if result.minimum_companies < 1 or not 0 < result.minimum_universe_ratio <= 1:
            raise DataError("Invalid universe coverage threshold")
        if not 0 < result.minimum_quote_coverage <= 1:
            raise DataError("Invalid quote coverage threshold")
        if result.security_types != ("CS",):
            raise DataError("Only CS is supported; ADRs require a separate conversion policy")
        if not result.exchanges or set(result.exchanges) - {"XNYS", "XNAS", "XASE"}:
            raise DataError("Unsupported exchange calendar")
        return result

    def policy(self) -> dict:
        values = asdict(self)
        return json.loads(
            json.dumps(
                {
                    k: v
                    for k, v in values.items()
                    if k not in ("requests_per_minute", "max_requests_per_run", "max_retries")
                }
            )
        )


@dataclass(frozen=True)
class Security:
    company_id: str
    security_id: str
    company_name: str
    ticker: str
    exchange: str
    share_type: str
    currency: str = "USD"
