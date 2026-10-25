"""Builds the Sims 4 script mod.

    python build.py            # needs Python 3.7 (the game's version): compiles to .pyc
    python build.py --source   # any Python: ships .py sources instead, for quick local testing

Output in dist/:
    voxta_bridge.ts4script       the mod itself
    voxta_bridge-<version>.zip   what users download: a "Voxta" folder to drop into Mods

The game only loads compiled files made by its own Python version, which is why release builds run
on Python 3.7 (see .github/workflows/sims-mod.yml).
"""

import argparse
import os
import py_compile
import re
import shutil
import sys
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
PACKAGE = "voxta_bridge"
SRC = os.path.join(HERE, "src", PACKAGE)
DIST = os.path.join(HERE, "dist")


def version():
    with open(os.path.join(SRC, "__init__.py"), encoding="utf-8") as handle:
        match = re.search(r'^MOD_VERSION = "([^"]+)"', handle.read(), re.M)
    if not match:
        raise SystemExit("MOD_VERSION not found in __init__.py")
    return match.group(1)


def build_ts4script(path, source):
    with tempfile.TemporaryDirectory() as tmp, zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(os.listdir(SRC)):
            if not name.endswith(".py"):
                continue
            src = os.path.join(SRC, name)
            if source:
                archive.write(src, "{}/{}".format(PACKAGE, name))
                continue
            # Sourceless import from a zip wants module.pyc next to where module.py would be,
            # not in __pycache__.
            compiled = os.path.join(tmp, name + "c")
            py_compile.compile(src, cfile=compiled, dfile="{}/{}".format(PACKAGE, name), doraise=True)
            archive.write(compiled, "{}/{}c".format(PACKAGE, name))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", action="store_true", help="ship .py sources (any Python version)")
    args = parser.parse_args()

    if not args.source and sys.version_info[:2] != (3, 7):
        raise SystemExit(
            "The Sims 4 runs Python 3.7 and only loads .pyc files compiled by 3.7. "
            "You are on {}.{}. Use Python 3.7, or pass --source for a quick local test build.".format(*sys.version_info[:2])
        )

    ver = version()
    if os.path.isdir(DIST):
        shutil.rmtree(DIST)
    os.makedirs(DIST)

    script = os.path.join(DIST, PACKAGE + ".ts4script")
    build_ts4script(script, args.source)

    package_zip = os.path.join(DIST, "{}-{}.zip".format(PACKAGE, ver))
    with zipfile.ZipFile(package_zip, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.write(script, "Voxta/{}.ts4script".format(PACKAGE))
        archive.write(os.path.join(HERE, "voxta_bridge.cfg"), "Voxta/voxta_bridge.cfg")
        archive.write(os.path.join(HERE, "INSTALL.txt"), "Voxta/INSTALL.txt")

    print("Built {} ({})".format(script, "sources" if args.source else "compiled with Python 3.7"))
    print("Built {}".format(package_zip))


if __name__ == "__main__":
    main()
