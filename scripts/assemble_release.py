"""Assemble a portable Windows release without copying the development workspace.

Run with the provisioned Python 3.12 runtime after main.py --package-agent.
The source runtime must contain Tk, PyInstaller and pytest. No downloads occur.
"""
import argparse
import hashlib
import json
import shutil
from pathlib import Path


EXCLUDED = {"__pycache__", ".pytest_cache", "pygame", "pip", "ensurepip", "idlelib", "turtledemo"}


def ignore_runtime(directory, names):
    return [name for name in names if name in EXCLUDED
            or name.startswith(("pygame-", "pip-")) or name.endswith((".pyc", ".pyo"))]


def assemble(runtime, destination):
    root = Path(__file__).resolve().parents[1]
    runtime, destination = Path(runtime).resolve(), Path(destination).resolve()
    if destination.exists():
        raise ValueError("Choose a new release directory; existing releases are preserved.")
    if destination.is_relative_to(runtime) or runtime.is_relative_to(destination):
        raise ValueError("Release and runtime directories must not overlap.")
    for required in ("python.exe", "python312.dll", "LICENSE.txt", "Lib/site-packages/PyInstaller"):
        if not (runtime / required).exists():
            raise ValueError("Incomplete Python 3.12 build runtime: " + required)
    if not (root / "Forge.exe").is_file():
        raise ValueError("Package Forge.exe first.")
    destination.mkdir(parents=True)
    shutil.copy2(root / "Forge.exe", destination / "Forge.exe")
    target = destination / "runtime"
    target.mkdir()
    for name in ("Lib", "DLLs", "tcl"):
        shutil.copytree(runtime / name, target / name, ignore=ignore_runtime)
    for path in runtime.iterdir():
        if path.is_file() and (path.suffix.lower() in {".dll", ".exe"} or path.name == "LICENSE.txt"):
            shutil.copy2(path, target / path.name)
    shutil.copytree(root / "input", destination / "inputs")
    licenses = destination / "licenses"
    licenses.mkdir()
    shutil.copy2(runtime / "LICENSE.txt", licenses / "Python.txt")
    (licenses / "README.txt").write_text(
        "Python license: Python.txt and runtime/LICENSE.txt.\n"
        "Third-party package licenses remain in runtime/Lib/site-packages/*dist-info/\n"
        "and their package directories. Tcl/Tk notices remain in runtime/tcl/.\n"
        "Forge also bundles requests and its dependencies; their metadata is retained in runtime.\n",
        encoding="utf-8")
    (destination / "README.txt").write_text(
        "FORGE — WINDOWS DESKTOP CODING AGENT\n\n"
        "Extract this complete folder before running Forge.exe. Keep runtime beside it.\n"
        "Windows x64. Python, GitHub and development tools need not be installed.\n"
        "Internet and your own API credit are needed for generation.\n\n"
        "1. Start Forge.exe. Official DeepSeek is selected by default.\n"
        "2. Enter your key (optional Remember uses Windows account encryption).\n"
        "3. Select a writable destination and attach both Markdown files in inputs.\n"
        "4. Generate game. Play game becomes available after basic checks/building.\n"
        "5. Open SpaceFractions.exe inside the generated project folder, or click\n"
        "   Play game. It prefers the EXE once available, including with test warnings.\n"
        "   Activity shows the EXE path. The resulting game runs offline.\n\n"
        "New games use simple fraction answers such as 3/4, 1/2 and 2/3, with exact\n"
        "fraction matching and one answer field. Whole-number answers are supported too.\n"
        "New games do not require decimal tolerance, negatives or mixed numbers. Resume\n"
        "keeps an older project's original contract. Reviewed UI components are supplied by\n"
        "Forge; game logic, content, storage, controller and tests are model-generated.\n"
        "New builds must pass independent real-control gameplay checks in source and\n"
        "inside the executable. Up to two repair rounds address confirmed failures.\n"
        "Help/editor checks and model-written tests are advisory; their warnings\n"
        "do not trigger paid repairs. Model-written tests run once after the EXE is available;\n"
        "test warnings do not suppress the EXE or trigger paid repairs. Visual review\n"
        "is reported separately. Check logs for remaining warnings.\n\n"
        "Options contains the per-run budget (maximum $0.95). Estimates reserve peak,\n"
        "uncached pricing; they are not an account-level spending limit. Resume preserves\n"
        "the previous run's usage. Each independent generation has its own budget.\n"
        "Build existing project repeats local tests/builds without paid model calls.\n"
        "Generated source and .agent logs/checkpoints stay in the selected destination.\n"
        "Run generated code only as a normal user; local execution is not a sandbox.\n",
        encoding="utf-8")
    inventory = []
    for path in sorted(destination.rglob("*")):
        if path.is_file():
            inventory.append({"path": path.relative_to(destination).as_posix(),
                              "bytes": path.stat().st_size,
                              "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    report = {"format": 1, "platform": "windows-x64", "runtime_source": str(runtime),
              "bytes": sum(item["bytes"] for item in inventory), "files": inventory}
    (destination / "release-manifest.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    report = assemble(args.runtime, args.output)
    print(json.dumps({"output": args.output, "files": len(report["files"]), "MiB": round(report["bytes"] / 1048576, 2)}))
