from typing import Protocol


class Provider(Protocol):
    name: str

    def tickers(self, day: str) -> list[dict]: ...

    def close(self, ticker: str, day: str) -> dict: ...

    def details(self, ticker: str, day: str) -> dict: ...
