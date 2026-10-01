import subprocess
from pathlib import Path


def git(cwd, *args):
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout


def test_data_branch_is_created_and_loaded_without_changing_source(tmp_path):
    remote = tmp_path / "remote.git"
    git(tmp_path, "init", "--bare", str(remote))
    source = tmp_path / "source"
    git(tmp_path, "clone", str(remote), str(source))
    git(source, "config", "user.name", "Test")
    git(source, "config", "user.email", "test@example.com")
    (source / "source.txt").write_text("unchanged")
    git(source, "add", "source.txt")
    git(source, "commit", "-m", "Initial source")
    git(source, "push", "origin", "HEAD")
    script = Path(__file__).resolve().parents[1] / "scripts/data_branch.py"
    path = tmp_path / "data-checkout"
    subprocess.run(["python3", str(script), "prepare", "--path", str(path)], cwd=source, check=True)
    (path / "status.json").write_text('{"state":"ok"}')
    subprocess.run(["python3", str(script), "persist", "--path", str(path)], cwd=source, check=True)
    assert (source / "source.txt").read_text() == "unchanged"
    assert not (path / "source.txt").exists()
    restored = tmp_path / "restored"
    subprocess.run(
        ["python3", str(script), "prepare", "--path", str(restored)], cwd=source, check=True
    )
    assert (restored / "status.json").read_text() == '{"state":"ok"}'
