"""Mirror one USD asset and its full dependency closure from an HTTP(S) asset root.

Runs with plain usd-core on a CPU node, without Kit, Nucleus or a GPU. The local copy
keeps the root-relative layout (dest/Isaac/Robots/...), so relative references resolve
unchanged. Absolute URLs under the same root are rewritten to relative paths, which
lets the mirrored stage compose with no network access.

Bare names that do not exist next to the referencing layer (for example
`OmniPBR.mdl`) are left to Kit's MDL search path. They are reported, not fetched.
"""
from __future__ import annotations

import posixpath
import urllib.error
import urllib.request
from pathlib import Path

from pxr import Sdf, UsdUtils

USD_EXT = (".usd", ".usda", ".usdc")


def _fetch(url: str, dst: Path, timeout: float) -> bool:
    if dst.is_file():
        return True
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            data = resp.read()
    except urllib.error.HTTPError as exc:
        if exc.code in (403, 404):
            return False
        raise
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + ".part")
    tmp.write_bytes(data)
    tmp.replace(dst)
    return True


def mirror_usd(root_url: str, rel: str, dest, timeout: float = 120.0) -> dict:
    """Download `root_url + rel` and everything it references under `root_url` into `dest`.

    Returns a report: files, downloaded, rewritten, search_path_assets, outside_root, missing, udim.
    Raises FileNotFoundError if the requested asset itself does not exist.
    """
    root = root_url.rstrip("/")
    dest = Path(dest)
    start = rel.lstrip("/")
    rep = {"root": root, "asset": "/" + start, "files": [], "downloaded": 0, "rewritten": 0,
           "search_path_assets": [], "outside_root": [], "missing": [], "udim": []}

    def get(r: str) -> bool:
        local = dest / r
        existed = local.is_file()
        ok = _fetch(f"{root}/{r}", local, timeout)
        if ok and not existed:
            rep["downloaded"] += 1
        return ok

    if not get(start):
        raise FileNotFoundError(f"{root}/{start}")
    queue, seen = [start], {start}

    def enqueue(r: str):
        if r not in seen:
            seen.add(r)
            queue.append(r)

    while queue:
        cur = queue.pop(0)
        rep["files"].append(cur)
        if not cur.lower().endswith(USD_EXT):
            continue
        base = posixpath.dirname(cur)
        layer = Sdf.Layer.FindOrOpen(str(dest / cur))
        changed = [False]

        def visit(path: str) -> str:
            if not path:
                return path
            if "://" in path:
                if path.startswith(root + "/"):
                    target = path[len(root) + 1:]
                    if target not in seen and not get(target):
                        rep["missing"].append(f"{cur}: {path}")
                        return path
                    enqueue(target)
                    new = posixpath.relpath(target, base or ".")
                    new = new if new.startswith(".") else "./" + new
                    rep["rewritten"] += 1
                    changed[0] = True
                    return new
                if path not in rep["outside_root"]:
                    rep["outside_root"].append(path)
                return path
            if "<UDIM>" in path or "<udim>" in path:
                rep["udim"].append(f"{cur}: {path}")
                return path
            if path.startswith("/"):
                rep["missing"].append(f"{cur}: absolute local path {path}")
                return path
            target = posixpath.normpath(posixpath.join(base, path))
            bare = "/" not in path and not path.startswith(".")
            if target in seen:
                return path
            if get(target):
                enqueue(target)
            elif bare:
                if path not in rep["search_path_assets"]:
                    rep["search_path_assets"].append(path)
            else:
                rep["missing"].append(f"{cur}: {path}")
            return path

        UsdUtils.ModifyAssetPaths(layer, visit)
        if changed[0]:
            layer.Save()

    rep["search_path_assets"].sort()
    return rep
