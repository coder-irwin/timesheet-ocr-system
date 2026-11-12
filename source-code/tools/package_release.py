"""Assemble the deployable ZIP.

Stages the operator files, the employee roster, the demo samples and the full
source, exports the pre-built container images, then zips and verifies the
result. Client documents are deliberately EXCLUDED -- only the roster and the
ten demo pages leave this machine.

    python tools/package_release.py 2.0.0
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

BASE = Path(__file__).parent.parent
DIST = BASE / "dist"


def run(cmd: list[str], cwd: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=True, cwd=cwd or str(BASE))


def main() -> None:
    version = sys.argv[1] if len(sys.argv) > 1 else "2.0.0"
    pkg = DIST / "timesheet-app"
    if pkg.exists():
        shutil.rmtree(pkg)
    for sub in ("data", "demo", "source"):
        (pkg / sub).mkdir(parents=True, exist_ok=True)

    # --- operator-facing files -------------------------------------------
    for f in ("START-HERE.md", "TROUBLESHOOTING.md", "VERIFICATION.md",
              "config.env", "docker-compose.yml"):
        shutil.copy2(BASE / "deploy" / f, pkg / f)
    for f in list((BASE / "deploy").glob("*.sh")) + \
            list((BASE / "deploy").glob("*.bat")):
        shutil.copy2(f, pkg / f.name)
    for f in pkg.glob("*.sh"):
        f.chmod(0o755)

    # --- data the app needs to run ---------------------------------------
    shutil.copy2(BASE / "data" / "roster.csv", pkg / "data" / "roster.csv")
    # The designation vocabulary is read from TS_DATA_DIR at runtime (D-046 audit found it missing from 2.4.0).
    if (BASE / "data" / "designations.csv").exists():
        shutil.copy2(BASE / "data" / "designations.csv", pkg / "data" / "designations.csv")
    for f in list((BASE / "demo").glob("*.pdf")) + \
            [BASE / "demo" / "MANIFEST.json"]:
        if f.exists():
            shutil.copy2(f, pkg / "demo" / f.name)

    # --- full source, for the client's own developers --------------------
    for d in ("app", "web", "tools", "docs"):
        shutil.copytree(BASE / d, pkg / "source" / d,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for f in ("requirements.txt", "Dockerfile", ".dockerignore", "README.md",
              "TECHNICAL-DOC.md", "SCALE-AND-DEPLOYMENT.md", "DEMO-BRIEF.md"):
        if (BASE / f).exists():
            shutil.copy2(BASE / f, pkg / "source" / f)

    # --- container images -------------------------------------------------
    images = {"amd64": f"timesheet-app:{version}-amd64",
              "arm64": f"timesheet-app:{version}-arm64"}
    for arch, tag in images.items():
        have = subprocess.run(["docker", "image", "inspect", tag],
                              capture_output=True)
        if have.returncode != 0:
            print(f"  WARNING: {tag} not built -- skipping {arch}")
            continue
        dest = pkg / f"timesheet-app-{arch}.tar.gz"
        print(f"  exporting {tag} ...", flush=True)
        with dest.open("wb") as fh:
            save = subprocess.Popen(["docker", "save", tag],
                                    stdout=subprocess.PIPE)
            gz = subprocess.Popen(["gzip", "-6"], stdin=save.stdout, stdout=fh)
            save.stdout.close()
            gz.communicate()
        print(f"    {dest.name}  {dest.stat().st_size/1e6:.0f} MB", flush=True)

    # --- safety audit: no client documents may ship ----------------------
    leaks = []
    for pat in ("*Timesheet*2026*", "*.xls", "*.xlsx", "*.db"):
        leaks += [p for p in pkg.rglob(pat)]
    pdfs = [p for p in pkg.rglob("*.pdf") if p.parent.name != "demo"]
    if leaks or pdfs:
        print("  REFUSING TO PACKAGE -- client data found:")
        for p in (leaks + pdfs)[:10]:
            print("    ", p.relative_to(pkg))
        sys.exit(2)

    # --- zip and verify ---------------------------------------------------
    zip_path = DIST / f"timesheet-app-v{version}-deployment.zip"
    if zip_path.exists():
        zip_path.unlink()
    print("  zipping ...", flush=True)
    run(["zip", "-r", "-1", "-q", str(zip_path.name), "timesheet-app",
         "-x", "*.DS_Store"], cwd=str(DIST))

    with zipfile.ZipFile(zip_path) as z:
        bad = z.testzip()
        names = z.namelist()
    if bad:
        print(f"  ARCHIVE CORRUPT at {bad}")
        sys.exit(3)

    size = zip_path.stat().st_size / 1e6
    print(f"\n  {zip_path}")
    print(f"  {size:.0f} MB, {len(names)} entries, integrity verified")
    manifest = {
        "version": version,
        "entries": len(names),
        "size_mb": round(size, 1),
        "images": [a for a, t in images.items()
                   if (pkg / f"timesheet-app-{a}.tar.gz").exists()],
    }
    (DIST / "package_manifest.json").write_text(json.dumps(manifest, indent=1))
    print(f"  manifest: {manifest}")


if __name__ == "__main__":
    main()
