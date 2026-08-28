"""Fail when tracked files cross Fly Club's public/private repository boundary."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALLOWED_WORKFLOWS = {"ci.yml", "secret-scan.yml"}
FORBIDDEN_EXACT_PATHS = {
    ".env",
    "config/routes.yaml",
    "config/routes.local.yaml",
    "config/flexible-markets.yaml",
    "config/flexible-markets.local.yaml",
}
FORBIDDEN_SUFFIXES = {".key", ".p12", ".pem", ".pfx", ".secret", ".secrets"}
FORBIDDEN_FILENAMES = {"credentials.json"}


def tracked_paths() -> tuple[str, ...]:
    result = subprocess.run(
        ["git", "-c", f"safe.directory={ROOT.as_posix()}", "ls-files", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return tuple(path for path in result.stdout.split("\0") if path)


def violations(paths: tuple[str, ...]) -> list[str]:
    problems: list[str] = []
    normalized = {path.replace("\\", "/") for path in paths}
    for path in sorted(normalized):
        candidate = Path(path)
        lower_name = candidate.name.lower()
        lower_path = path.lower()
        if path in FORBIDDEN_EXACT_PATHS:
            problems.append(f"private configuration is tracked: {path}")
        if lower_name.startswith(".env") and lower_name != ".env.example":
            problems.append(f"environment file is tracked: {path}")
        if candidate.suffix.lower() in FORBIDDEN_SUFFIXES:
            problems.append(f"credential-like file is tracked: {path}")
        if lower_name in FORBIDDEN_FILENAMES or lower_name.startswith("service-account"):
            problems.append(f"credential JSON is tracked: {path}")
        if "/.secrets/" in f"/{lower_path}/" or lower_path.startswith(".secrets/"):
            problems.append(f"secrets directory is tracked: {path}")
        if lower_path.startswith("config/") and ".local." in lower_name:
            problems.append(f"local configuration is tracked: {path}")

    workflows = {Path(path).name for path in normalized if path.startswith(".github/workflows/")}
    if workflows != ALLOWED_WORKFLOWS:
        problems.append(
            "active workflows must be exactly "
            f"{sorted(ALLOWED_WORKFLOWS)}; found {sorted(workflows)}"
        )

    env_example = ROOT / ".env.example"
    for line_number, line in enumerate(env_example.read_text(encoding="utf-8").splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" not in stripped or not stripped.endswith("="):
            problems.append(f".env.example:{line_number} must contain an empty assignment")
    return problems


def main() -> int:
    problems = violations(tracked_paths())
    if problems:
        print("Public repository boundary check failed:", file=sys.stderr)
        for problem in problems:
            print(f"- {problem}", file=sys.stderr)
        return 1
    print("Public repository boundary check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
