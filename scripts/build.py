"""Build the local-only practice app on the host OS with PyInstaller."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
WORK = ROOT / "build"
IS_WINDOWS = os.name == "nt"
HOST = "PracticeAgentHost.exe" if IS_WINDOWS else "PracticeAgentHost"
RUNNER_HOST = "PracticeRunnerHost.exe" if IS_WINDOWS else "PracticeRunnerHost"


def _ignore_secret_files(_directory: str, names: list[str]) -> set[str]:
    """Keep common local credentials out of the frozen participant bundle."""
    ignored = set()
    for name in names:
        lowered = name.lower()
        if (
            lowered == ".env"
            or lowered.startswith(".env.")
            or lowered.endswith((".env", ".pem", ".key"))
            or "secret" in lowered
            or "credential" in lowered
            or "password" in lowered
            or "passwd" in lowered
            or "api_key" in lowered
            or "apikey" in lowered
            or "access_token" in lowered
            or "refresh_token" in lowered
        ):
            ignored.add(name)
    return ignored


def pyinstaller(*args: str) -> None:
    subprocess.run([sys.executable, "-m", "PyInstaller", *args], cwd=ROOT, check=True)


def prepare_agent_bundle() -> Path:
    """Stage the bundled agent without local credentials or interpreter caches."""
    staged = WORK / "agent-bundle"
    if staged.exists():
        shutil.rmtree(staged)
    shutil.copytree(
        ROOT / "agent",
        staged,
        ignore=lambda directory, names: _ignore_secret_files(directory, names)
        | {name for name in names if name == "__pycache__" or name.endswith((".pyc", ".pyo"))},
    )
    return staged


def main() -> int:
    DIST.mkdir(exist_ok=True)
    staged_agent = prepare_agent_bundle()
    pyinstaller(
        "--noconfirm", "--clean", "--onefile", "--console",
        "--name", "PracticeAgentHost",
        "--hidden-import", "ssl",
        "--hidden-import", "sqlite3",
        "--hidden-import", "asyncio",
        "--hidden-import", "multiprocessing",
        "--hidden-import", "subprocess",
        "--hidden-import", "logging",
        "--hidden-import", "urllib.request",
        "--hidden-import", "http.client",
        "--hidden-import", "email",
        "--distpath", str(DIST / "helper"),
        "--workpath", str(WORK / "helper"),
        "--specpath", str(WORK / "spec"),
        str(ROOT / "practice_worker.py"),
    )
    helper = DIST / "helper" / HOST
    if not helper.is_file():
        raise FileNotFoundError(helper)
    pyinstaller(
        "--noconfirm", "--clean", "--onefile", "--console",
        "--name", "PracticeRunnerHost",
        "--add-data", f"{ROOT / 'vendor' / 'gosim-official-v4'}:vendor/gosim-official-v4",
        "--distpath", str(DIST / "runner-helper"),
        "--workpath", str(WORK / "runner-helper"),
        "--specpath", str(WORK / "spec"),
        str(ROOT / "runner_worker.py"),
    )
    runner_helper = DIST / "runner-helper" / RUNNER_HOST
    if not runner_helper.is_file():
        raise FileNotFoundError(runner_helper)
    pyinstaller(
        "--noconfirm", "--clean", "--onefile", "--windowed",
        "--name", "GOSIMPractice",
        "--add-data", f"{staged_agent}:agent",
        "--add-binary", f"{helper}:.",
        "--add-binary", f"{runner_helper}:.",
        "--distpath", str(DIST),
        "--workpath", str(WORK / "gui"),
        "--specpath", str(WORK / "spec"),
        str(ROOT / "practice_gui.py"),
    )
    if IS_WINDOWS:
        executable = DIST / "GOSIMPractice.exe"
        if not executable.is_file():
            raise FileNotFoundError(executable)
        archive = DIST / "GOSIMPractice-Windows-x64.zip"
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(executable, executable.name)
    else:
        app = DIST / "GOSIMPractice.app"
        if not app.is_dir():
            raise FileNotFoundError(app)
        archive = DIST / f"GOSIMPractice-macOS-{platform.machine().lower()}.zip"
        subprocess.run(["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", str(app), str(archive)], check=True)
    print(archive)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
