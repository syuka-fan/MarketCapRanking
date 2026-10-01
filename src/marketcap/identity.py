from marketcap.models import DataError, Security, Settings


def identify(rows: list[dict], settings: Settings) -> list[Security]:
    result = []
    seen_tickers: set[str] = set()
    seen_securities: set[str] = set()
    for row in rows:
        if (
            row.get("primary_exchange") not in settings.exchanges
            or row.get("type") not in settings.security_types
        ):
            continue
        ticker = row.get("ticker", "")
        if not ticker or row.get("currency_name", "").upper() != "USD":
            raise DataError(f"{ticker}: missing ticker or non-USD currency")
        override = settings.identity_overrides.get(ticker, {})
        cik = str(row.get("cik") or "").strip()
        company_id = (
            override.get("company_id")
            or row.get("company_id")
            or (f"cik:{int(cik):010d}" if cik.isdigit() and int(cik) > 0 else "")
        )
        figi = row.get("share_class_figi") or row.get("composite_figi")
        security_id = (
            override.get("security_id")
            or row.get("security_id")
            or (f"figi:{figi}" if figi else "")
        )
        if not company_id or not security_id:
            raise DataError(f"{ticker}: stable identity missing; add an identity_overrides entry")
        if ticker in seen_tickers or security_id in seen_securities:
            raise DataError(f"{ticker}: duplicate ticker or security identity")
        name = settings.company_names.get(company_id) or row.get("name")
        if not name:
            raise DataError(f"{ticker}: missing company name")
        result.append(
            Security(company_id, security_id, name, ticker, row["primary_exchange"], row["type"])
        )
        seen_tickers.add(ticker)
        seen_securities.add(security_id)
    if len(result) < settings.minimum_instruments:
        raise DataError("Eligible universe is below minimum_instruments; refusing partial rankings")
    return sorted(result, key=lambda s: s.security_id)
