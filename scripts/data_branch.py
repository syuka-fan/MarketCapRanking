"""Keep collected records on the data branch without changing the source checkout."""

import argparse
import subprocess
from pathlib import Path


def git(*args: str, cwd: Path | None = None, check: bool = True):
    return subprocess.run(["git", *args], cwd=cwd, check=check, capture_output=True, text=True)


def prepare(path: Path) -> None:
    remote = git("ls-remote", "--exit-code", "--heads", "origin", "data", check=False)
    if remote.returncode == 0:
        git("fetch", "origin", "data")
        git("worktree", "add", "--detach", str(path), "FETCH_HEAD")
    elif remote.returncode == 2:
        git("worktree", "add", "--detach", str(path), "HEAD")
        git("switch", "--orphan", "data", cwd=path)
    else:
        raise RuntimeError("Cannot read origin/data; refusing to initialize an empty replacement")
    (path / ".gitignore").write_text(".lock\n.closes.lock\n.tmp-*\n", encoding="utf-8")


def persist(path: Path) -> None:
    git("add", "--all", cwd=path)
    changed = git("diff", "--cached", "--quiet", cwd=path, check=False)
    if changed.returncode == 0:
        print("No data changes to persist")
        return
    if changed.returncode != 1:
        raise RuntimeError("Cannot inspect staged data")
    git(
        "-c",
        "user.name=github-actions[bot]",
        "-c",
        "user.email=41898282+github-actions[bot]@users.noreply.github.com",
        "commit",
        "-m",
        "Update daily market-cap records",
        cwd=path,
    )
    git("push", "origin", "HEAD:refs/heads/data", cwd=path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["prepare", "persist"])
    parser.add_argument("--path", type=Path, default=Path(".marketcap-data"))
    args = parser.parse_args()
    {"prepare": prepare, "persist": persist}[args.action](args.path.resolve())
