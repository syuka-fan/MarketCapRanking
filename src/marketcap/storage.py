import csv
import gzip
import hashlib
import json
import os
import tempfile
from datetime import date
from pathlib import Path

from marketcap.models import DataError

PRICE_COLUMNS = [
    "company_name",
    "ticker",
    "close",
    "trade_date",
    "instrument_id",
    "security_id",
    "currency",
    "source",
    "collected_at",
]
RANK_COLUMNS = [
    "trade_date",
    "instrument_id",
    "company_name",
    "market_cap_usd",
    "rank",
    "ticker",
    "shares_outstanding",
    "shares_source",
    "security_type",
    "method",
    "source",
]


def json_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(json_bytes(value))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class Store:
    def __init__(self, root: Path):
        self.root = root

    def dates(self) -> list[date]:
        return sorted(
            date.fromisoformat(p.parent.name)
            for p in (self.root / "snapshots").glob("*/current.json")
        )

    def load(self, day: date) -> dict:
        directory = self.root / "snapshots" / day.isoformat()
        pointer = json.loads((directory / "current.json").read_text())
        revision = pointer["revision"]
        if len(revision) != 64 or any(c not in "0123456789abcdef" for c in revision):
            raise DataError("Invalid snapshot revision")
        return json.loads((directory / "revisions" / revision / "snapshot.json").read_text())

    def save(self, snapshot: dict, raw: dict) -> bool:
        existing_days = self.dates()
        if existing_days:
            last = self.load(existing_days[-1])
            if last["source"] != snapshot["source"]:
                raise DataError("Use separate data directories for demo and live providers")
            if last["policy"] != snapshot["policy"]:
                raise DataError(
                    "Ranking policy changed; use a new data directory and rebuild history"
                )
        semantic = {k: v for k, v in snapshot.items() if k != "collected_at"}
        revision = hashlib.sha256(json_bytes(semantic)).hexdigest()
        day_dir = self.root / "snapshots" / snapshot["trade_date"]
        pointer = day_dir / "current.json"
        if pointer.exists() and json.loads(pointer.read_text())["revision"] == revision:
            return False
        target = day_dir / "revisions" / revision
        if (target / "complete.json").exists():
            # Reverting a correction points back to its original immutable revision.
            atomic_json(pointer, {"revision": revision})
            return True
        target.mkdir(parents=True, exist_ok=True)
        # Readers see the old revision until current.json is replaced as the last operation.
        atomic_json(target / "snapshot.json", snapshot)
        atomic_json(target / "securities.json", snapshot["securities"])
        for name, columns, rows in (
            ("prices.csv", PRICE_COLUMNS, snapshot["prices"]),
            ("rankings.csv", RANK_COLUMNS, snapshot["rankings"]),
        ):
            with (target / name).open("w", newline="", encoding="utf-8") as stream:
                writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
                writer.writeheader()
                for row in rows:
                    writer.writerow(
                        {
                            **row,
                            "trade_date": snapshot["trade_date"],
                            "source": snapshot["source"],
                            "collected_at": snapshot["collected_at"],
                        }
                    )
        with (target / "raw.json.gz").open("wb") as stream:
            stream.write(gzip.compress(json_bytes(raw), mtime=0))
        atomic_json(target / "complete.json", {"revision": revision})
        atomic_json(pointer, {"revision": revision})
        return True

    def status(self, value: dict) -> None:
        atomic_json(self.root / "status.json", value)
