#!/usr/bin/env python3
"""Build a ready-to-print Bambu Studio project (.3mf) from STL parts, then check it.

Standard library only (Python 3.9+). It never contacts a printer: it writes a file,
and optionally asks the locally installed Bambu Studio to slice that file in a
temporary folder to prove it slices and to count colour changes.

Subcommands
  studio                 where Bambu Studio, its command line and its profiles are
  templates [PATH ...]   list settings templates (.3mf saved by Bambu Studio)
  build JOB.json         write the project described by JOB.json
  check FILE.3mf         slice FILE.3mf with Bambu Studio and report colour changes

Run `python3 bambu_project.py <subcommand> -h` for options.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import pathlib
import platform
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import uuid
import xml.etree.ElementTree as ET
import zipfile
from xml.sax.saxutils import escape, quoteattr

NS_CORE = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
NS_UUID = uuid.UUID("2f0c7a52-8d1e-4f3b-9a51-5b8f3d1c0e00")
SETTINGS_ENTRY = "Metadata/project_settings.config"
MAX_STL_BYTES = 200 * 1024 * 1024        # refuse absurdly large inputs
MAX_ENTRY_BYTES = 64 * 1024 * 1024       # per entry read from a template .3mf
SLICE_TIMEOUT_S = 600

# Keys that hold code or name files. In a template they are never trusted: they are
# replaced with the values of the official profiles installed on this computer.
def _is_code_key(key: str) -> bool:
    return key.endswith("_gcode") or key in ("gcode_flavor", "post_process", "filename_format")


# Printer limits that must match the official printer preset: a template that changes
# them could make the head crash into the bed or print outside the plate.
SAFETY_MACHINE_KEYS = (
    "printable_area", "printable_height", "bed_exclude_area", "extruder_printable_area",
    "extruder_printable_height", "nozzle_diameter", "nozzle_height", "printer_model",
    "printer_variant", "retraction_length", "retract_length_toolchange", "retraction_speed",
    "deretraction_speed", "z_hop", "extruder_clearance_radius",
    "extruder_clearance_height_to_rod", "extruder_clearance_height_to_lid",
    "min_layer_height", "max_layer_height", "z_offset")
# Per-filament motion settings that must match the official filament presets.
SAFETY_FILAMENT_PREFIXES = ("filament_retraction", "filament_retract_", "filament_deretraction",
                            "filament_z_hop", "filament_max_volumetric_speed", "filament_wipe")
# Settings that point Bambu Studio at a network host. Blanked in every project written.
HOST_KEYS = ("print_host", "print_host_webui", "printhost_apikey", "printhost_cafile",
             "printhost_user", "printhost_password", "printhost_port")
TEMP_MARGIN_C = 10      # bed and chamber may be this much above the official value
# Entries of a project that `check` passes to Bambu Studio; anything else is dropped.
CHECK_ENTRIES = ("3D/3dmodel.model", "3D/Objects/object_1.model", "Metadata/model_settings.config",
                 SETTINGS_ENTRY, "Metadata/slice_info.config", "[Content_Types].xml", "_rels/.rels",
                 "3D/_rels/3dmodel.model.rels")
# The only printer this skill builds for, as Bambu Studio writes it in printer_model.
X2D_MODEL = "Bambu Lab X2D"
MODEL_ENTRY = "3D/3dmodel.model"
_APP_RE = re.compile(r'<metadata\s+name="Application"\s*>([^<]*)</metadata>')
TEMPLATE_FIX = ("Do not use it as a template: in Bambu Studio select the Bambu Lab X2D and "
                "save a new template with File, Save Project As.")
PROJECT_FIX = ("Do not print it: build it again from its job with `build JOB.json --force` "
               "and open the new file from Bambu Studio with File, Open project, never with "
               "a double click.")
# Other slicers that open .3mf files and rewrite them for their own printers. Matched
# against application names, lower case, letters only. Bambu Studio itself is skipped.
OTHER_SLICERS = ("qidistudio", "orcaslicer", "elegooslicer", "crealityprint", "anycubicslicer",
                 "snapmakerorca", "prusa", "superslicer", "ultimakercura")


class UserError(Exception):
    """A problem the person can fix; printed without a traceback."""


# --------------------------------------------------------------------------- Bambu Studio

def studio_paths(explicit: str | None = None) -> dict:
    """Locate the Bambu Studio executable and its profile folders."""
    system = platform.system()
    home = pathlib.Path.home()
    exe = None
    candidates = []
    if explicit or os.environ.get("BAMBU_STUDIO"):
        candidates.append(pathlib.Path(explicit or os.environ["BAMBU_STUDIO"]))
    if system == "Darwin":
        candidates.append(pathlib.Path("/Applications/BambuStudio.app/Contents/MacOS/BambuStudio"))
        candidates.append(home / "Applications/BambuStudio.app/Contents/MacOS/BambuStudio")
        data = home / "Library/Application Support/BambuStudio"
    elif system == "Windows":
        pf = pathlib.Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
        candidates.append(pf / "Bambu Studio" / "bambu-studio.exe")
        data = pathlib.Path(os.environ.get("APPDATA", home / "AppData/Roaming")) / "BambuStudio"
    else:
        found = shutil.which("bambu-studio") or shutil.which("BambuStudio")
        if found:
            candidates.append(pathlib.Path(found))
        data = home / ".config/BambuStudio"
    for c in candidates:
        if c.is_file():
            exe = c
            break
    resources = None
    if exe is not None:
        for r in (exe.parent.parent / "Resources/profiles/BBL", exe.parent / "resources/profiles/BBL"):
            if r.is_dir():
                resources = r
                break
    system_dir = data / "system" / "BBL"
    return {
        "executable": str(exe) if exe else None,
        "data_dir": str(data) if data.is_dir() else None,
        "profiles": str(system_dir) if system_dir.is_dir() else (str(resources) if resources else None),
        "platform": system,
    }


def _run_studio(exe: str, args: list, cwd: str) -> subprocess.CompletedProcess:
    try:
        return subprocess.run([exe, *args], cwd=cwd, capture_output=True, text=True,
                              timeout=SLICE_TIMEOUT_S, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired as e:
        raise UserError(f"Bambu Studio did not finish within {SLICE_TIMEOUT_S} s") from e


_META_KEYS = ("name", "inherits", "include", "instantiation", "from", "setting_id", "type",
              "description", "version")


class _Presets:
    """Reads the official Bambu presets installed with Bambu Studio, resolving 'inherits'
    and 'include' the way Bambu Studio does. Asking the Bambu Studio command line to
    export them is not enough: it skips the 'include' files, where the real G-code lives."""

    def __init__(self, profiles_dir: str | None):
        if not profiles_dir:
            raise UserError("Bambu Studio profiles not found. Install Bambu Studio and open it once.")
        self.root = pathlib.Path(profiles_dir)
        index_file = self.root.parent / "BBL.json"
        if not index_file.is_file():
            raise UserError(f"Bambu profile index not found: {index_file}")
        index = json.loads(index_file.read_text(encoding="utf-8"))
        self.index = {}
        for lst in ("machine_model_list", "machine_list", "process_list", "filament_list"):
            for e in index.get(lst, []):
                self.index[e["name"]] = self.root / e["sub_path"]
        self.cache = {}

    def resolve(self, name: str, _depth: int = 0) -> dict:
        if name in self.cache:
            return self.cache[name]
        if _depth > 20:
            raise UserError(f"preset chain too deep at '{name}'")
        path = self.index.get(name)
        if path is None or not path.is_file():
            raise UserError(
                f"'{name}' is not an official Bambu preset on this computer. Save the template "
                "again in Bambu Studio with system presets only (no custom or user presets), "
                "or update Bambu Studio.")
        raw = json.loads(path.read_text(encoding="utf-8"))
        out = dict(self.resolve(raw["inherits"], _depth + 1)) if raw.get("inherits") else {}
        for inc in raw.get("include") or []:
            out.update(self.resolve(inc, _depth + 1))
        out.update({k: v for k, v in raw.items() if k not in _META_KEYS})
        self.cache[name] = out
        return out


def official_presets(paths: dict, settings: dict) -> dict:
    """The resolved official presets named by a project's settings."""
    pr = _Presets(paths.get("profiles"))
    return {"printer": pr.resolve(settings["printer_settings_id"]),
            "process": pr.resolve(settings["print_settings_id"]),
            "filaments": [pr.resolve(f) for f in settings["filament_settings_id"]]}


def _flat_values(v) -> list:
    items = v if isinstance(v, list) else [v]
    return [str(x).strip() for x in items]


_NUMBER = re.compile(r"-?[0-9]+(\.[0-9]+)?")


def _numbers(key: str, v, problems: list) -> list:
    """Every item of a temperature setting as a number; anything else is a problem."""
    if not isinstance(v, (list, str, int, float)) or isinstance(v, bool):
        problems.append(f"{key} is not a list of numbers")
        return []
    out = []
    for x in _flat_values(v):
        if not _NUMBER.fullmatch(x):
            problems.append(f"{key} holds {x[:20]!r}, not a plain number")
            return []
        out.append(float(x))
    return out


def _slots(key: str, values: list, n: int, problems: list) -> list:
    """Split a per-filament list (possibly expanded per nozzle variant) into n slots."""
    if n == 0 or not values or len(values) % n:
        if values:
            problems.append(f"{key} has {len(values)} values for {n} filaments")
        return []
    size = len(values) // n
    return [values[i * size:(i + 1) * size] for i in range(n)]


def _machine_safety_keys(mach: dict) -> list:
    return sorted(set(SAFETY_MACHINE_KEYS) | {k for k in mach if k.startswith("machine_max_")})


def _is_filament_safety_key(k: str) -> bool:
    return k.startswith(SAFETY_FILAMENT_PREFIXES)


def safety_problems(settings: dict, official: dict) -> list:
    """Printer limits, motion settings and temperatures that the official presets do not allow.

    Missing printer limits are filled in from the official printer preset (in place)."""
    problems = []
    mach = official["printer"]
    fils = official["filaments"]
    for k in _machine_safety_keys(mach):
        if k not in mach:
            if k in settings and _flat_values(settings[k]) not in (["0"], ["0.0"], []):
                problems.append(f"{k} is {json.dumps(settings[k])[:60]}, official 0")
            continue
        if k not in settings:
            settings[k] = mach[k]
        elif _flat_values(settings[k]) != _flat_values(mach[k]):
            problems.append(f"{k} is {json.dumps(settings[k])[:60]}, official {json.dumps(mach[k])[:60]}")
    for k in sorted(k for k in settings if _is_filament_safety_key(k)):
        concat = [x for d in fils for x in _flat_values(d.get(k, []))]
        have = _flat_values(settings[k])
        if concat and have != concat:
            problems.append(f"{k} is {json.dumps(settings[k])[:60]}, official {json.dumps(concat)[:60]}")
        elif not concat and any(x not in ("nil", "") for x in have):
            problems.append(f"{k} is {json.dumps(settings[k])[:60]}, not set in the official presets")
    n = len(fils)
    for k in ("nozzle_temperature", "nozzle_temperature_initial_layer"):
        if k not in settings:
            continue
        for i, slot in enumerate(_slots(k, _numbers(k, settings[k], problems), n, problems)):
            lo = _numbers("range_low", fils[i].get("nozzle_temperature_range_low", []), [])
            hi = _numbers("range_high", fils[i].get("nozzle_temperature_range_high", []), [])
            if not lo or not hi:
                continue
            bad = [t for t in slot if not min(lo) <= t <= max(hi)]
            if bad:
                problems.append(f"{k} {bad[0]:g} C for filament {i + 1} is outside its official "
                                f"range {min(lo):g}-{max(hi):g} C")
    hot = [k for k in settings if k.endswith("_plate_temp") or k.endswith("_plate_temp_initial_layer")
           or k == "chamber_temperatures"]
    for k in sorted(hot):
        for i, slot in enumerate(_slots(k, _numbers(k, settings[k], problems), n, problems)):
            ref = _numbers(k, fils[i].get(k, []), [])
            if not ref:
                continue
            bad = [t for t in slot if not 0 <= t <= max(ref) + TEMP_MARGIN_C]
            if bad:
                problems.append(f"{k} {bad[0]:g} C for filament {i + 1} is above the official {max(ref):g} C")
    return problems


def official_code_values(paths: dict, printer: str, process: str, filaments: list) -> dict:
    """Return the official value of every code key for these presets.

    Printer and process keys are plain values; filament keys ('filament_*') are lists with
    one entry per filament, as in a project file. post_process is always empty."""
    pr = _Presets(paths.get("profiles"))
    out = {}
    for name in (printer, process):
        for k, v in pr.resolve(name).items():
            if _is_code_key(k) and not k.startswith("filament_"):
                out[k] = v
    per_fil = [pr.resolve(f) for f in filaments]
    fil_keys = {k for d in per_fil for k in d if _is_code_key(k) and k.startswith("filament_")}
    for k in fil_keys:
        vals = []
        for d in per_fil:
            v = d.get(k, [""])
            vals.append(v[0] if isinstance(v, list) and v else (v if isinstance(v, str) else ""))
        out[k] = vals
    out["post_process"] = []
    return out


def code_key_differences(s: dict, flat: dict) -> list:
    """Code keys whose value in the settings is not the official one."""
    out = []
    for k in sorted(set(s) | set(flat)):
        if _is_code_key(k):
            new = flat.get(k, [] if k == "post_process" else "")
            if s.get(k) != new:
                out.append(k)
    return out


# --------------------------------------------------------------------------- templates

def _read_entry(z: zipfile.ZipFile, name: str) -> bytes:
    info = z.getinfo(name)
    if info.file_size > MAX_ENTRY_BYTES:
        raise UserError(f"{name} inside the template is too large ({info.file_size} bytes)")
    return z.read(name)


def project_origin(z: zipfile.ZipFile, settings: dict) -> dict:
    """Which program last saved a project, and for which printer.

    Bambu Studio writes `BambuStudio-<version>` in the Application metadata of
    3D/3dmodel.model. Its forks (QIDI Studio, OrcaSlicer, ...) open the same files and,
    when saving, write their own name and convert the project to their own printer."""
    app = None
    if MODEL_ENTRY in z.namelist():
        m = _APP_RE.search(_read_entry(z, MODEL_ENTRY).decode("utf-8", "replace"))
        app = m.group(1).strip() if m else None
    model = settings.get("printer_model")
    return {"application": app, "printer_model": model if isinstance(model, str) else None}


def origin_problem(path: pathlib.Path, origin: dict, fix: str) -> str | None:
    """Why a project was not saved by Bambu Studio for the X2D, or None if it was."""
    app, model = origin["application"], origin["printer_model"]
    if app and app.startswith("BambuStudio-") and model == X2D_MODEL:
        return None
    if app and not app.startswith("BambuStudio-"):
        why = (f"{path.name} was rewritten by another slicer ({app}, printer "
               f"{model or 'unknown'}), probably opened with a double click. Bambu Studio "
               "may crash on it or print with the wrong printer's settings.")
    elif not app:
        why = f"{path.name} was not saved by Bambu Studio (no Application metadata)."
    else:
        why = (f"{path.name} is set up for {model or 'an unknown printer'}, not the "
               f"{X2D_MODEL}.")
    return why + " " + fix


def read_template(path: pathlib.Path) -> dict:
    """Read only the settings of a Bambu Studio project. Geometry is ignored."""
    if not zipfile.is_zipfile(path):
        raise UserError(f"{path} is not a .3mf (zip) file")
    with zipfile.ZipFile(path) as z:
        if SETTINGS_ENTRY not in z.namelist():
            raise UserError(f"{path} has no Bambu Studio settings: save it from Bambu Studio")
        settings = json.loads(_read_entry(z, SETTINGS_ENTRY).decode("utf-8"))
        if not isinstance(settings, dict) or "printer_settings_id" not in settings:
            raise UserError(f"{path}: settings are not from Bambu Studio")
        problem = origin_problem(path, project_origin(z, settings), TEMPLATE_FIX)
    if problem:
        raise UserError(problem)
    return settings


def describe_template(settings: dict) -> dict:
    fil = settings.get("filament_settings_id", [])
    colours = settings.get("filament_colour", [])
    types = settings.get("filament_type", [])
    return {
        "printer": settings.get("printer_settings_id"),
        "process": settings.get("print_settings_id"),
        "plate": settings.get("curr_bed_type"),
        "nozzles": len(settings.get("nozzle_diameter", [])) or 1,
        "filaments": [
            {"number": i + 1, "colour": (colours[i] if i < len(colours) else "?"),
             "type": (types[i] if i < len(types) else "?"), "preset": name}
            for i, name in enumerate(fil)],
        "studio_version": settings.get("version"),
    }


def candidate_templates(paths: dict) -> list:
    """Projects Bambu Studio itself knows about: the open-project backup and recent files.

    Only two keys of BambuStudio.conf are read (recent_projects, app.last_backup_path).
    That file also holds account data and access codes, which are never read or printed.
    """
    out = []
    data = pathlib.Path(paths["data_dir"]) if paths.get("data_dir") else None
    conf = data / "BambuStudio.conf" if data else None
    if conf and conf.is_file():
        try:
            d = json.loads(conf.read_text(encoding="utf-8", errors="replace"))
        except ValueError:
            d = {}
        backup = (d.get("app") or {}).get("last_backup_path")
        if isinstance(backup, str):
            p = pathlib.Path(backup) / ".3mf"
            if p.is_file():
                out.append((p, "project open in Bambu Studio (backup copy)"))
        recent = d.get("recent_projects") or {}
        if isinstance(recent, dict):
            for _, v in sorted(recent.items()):
                if isinstance(v, str) and v.lower().endswith(".3mf") and pathlib.Path(v).is_file():
                    out.append((pathlib.Path(v), "recent project"))
    return out


# --------------------------------------------------------------------------- STL

def read_stl(path: pathlib.Path):
    """Return (vertices, triangles) with shared vertices merged."""
    size = path.stat().st_size
    if size > MAX_STL_BYTES:
        raise UserError(f"{path.name} is larger than {MAX_STL_BYTES // 2**20} MB")
    raw = path.read_bytes()
    tris = []
    if len(raw) >= 84:
        (n,) = struct.unpack_from("<I", raw, 80)
        if 84 + 50 * n == len(raw):
            for i in range(n):
                vals = struct.unpack_from("<12f", raw, 84 + 50 * i)
                if not all(math.isfinite(x) for x in vals[3:12]):
                    raise UserError(f"{path.name} has a vertex that is not a number")
                tris.append((vals[3:6], vals[6:9], vals[9:12]))
    if not tris:
        text = raw.decode("ascii", errors="replace")
        try:
            pts = [tuple(float(v) for v in m.groups()) for m in re.finditer(
                r"vertex\s+(\S+)\s+(\S+)\s+(\S+)", text)]
        except ValueError:
            raise UserError(f"{path.name} is not a readable STL") from None
        if not all(math.isfinite(c) for p in pts for c in p):
            raise UserError(f"{path.name} has a vertex that is not a number")
        if len(pts) % 3 or not pts:
            raise UserError(f"{path.name} is not a readable STL")
        tris = [tuple(pts[i:i + 3]) for i in range(0, len(pts), 3)]
    index, verts, faces = {}, [], []
    for tri in tris:
        f = []
        for v in tri:
            key = (round(v[0], 5), round(v[1], 5), round(v[2], 5))
            if key not in index:
                index[key] = len(verts)
                verts.append(key)
            f.append(index[key])
        if len(set(f)) == 3:
            faces.append(tuple(f))
    if not faces:
        raise UserError(f"{path.name} has no triangles")
    return verts, faces


def open_edges(faces) -> int:
    count = {}
    for a, b, c in faces:
        for e in ((a, b), (b, c), (c, a)):
            k = (min(e), max(e))
            count[k] = count.get(k, 0) + 1
    return sum(1 for v in count.values() if v != 2)


def bbox(verts):
    xs, ys, zs = zip(*verts)
    return (min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs))


# --------------------------------------------------------------------------- job

def load_job(path: pathlib.Path) -> dict:
    job = json.loads(path.read_text(encoding="utf-8"))
    base = path.parent
    if not isinstance(job, dict):
        raise UserError("job: the file must hold one JSON object")
    if not isinstance(job.get("objects"), list) or not job["objects"]:
        raise UserError("job: 'objects' must be a non-empty list")
    name = str(job.get("name", "")).strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", name):
        raise UserError("job: 'name' must be 1-64 letters, digits, dots, dashes or underscores")
    job["name"] = name
    job["_base"] = base
    for obj in job["objects"]:
        if not isinstance(obj, dict) or not isinstance(obj.get("parts"), list) or not obj["parts"]:
            name = obj.get("name") if isinstance(obj, dict) else obj
            raise UserError(f"object {name!r} has no parts")
        for part in obj["parts"]:
            if not isinstance(part, dict) or not isinstance(part.get("stl"), str):
                raise UserError("job: each part needs an 'stl' file name")
            if not isinstance(part.get("filament"), int) or part["filament"] < 1:
                raise UserError(f"part {part.get('stl')!r}: 'filament' must be a number from 1")
            p = (base / part["stl"]).resolve()
            if p.suffix.lower() != ".stl" or not p.is_file():
                raise UserError(f"part file not found or not .stl: {part['stl']}")
            part["_path"] = p
    return job


def nozzle_map(job: dict, settings: dict) -> list | None:
    """Per-filament nozzle ('1' left, '2' right) for dual-nozzle printers, else None."""
    n_fil = len(settings.get("filament_settings_id", []))
    if len(settings.get("nozzle_diameter", [])) < 2:
        return None
    spec = job.get("nozzles") or {}
    names = {"left": "1", "right": "2", "1": "1", "2": "2"}
    current = list(settings.get("filament_map") or [])
    out = []
    for i in range(n_fil):
        v = spec.get(str(i + 1))
        if v is None:
            v = current[i] if i < len(current) else "1"
        v = names.get(str(v).lower())
        if v is None:
            raise UserError(f"nozzles: filament {i + 1} must be 'left' or 'right'")
        out.append(v)
    return out


# --------------------------------------------------------------------------- writing

def _uid(tag: str) -> str:
    return str(uuid.uuid5(NS_UUID, tag))


def _num(v: float) -> str:
    s = f"{v:.5f}".rstrip("0").rstrip(".")
    return "0" if s in ("", "-0") else s


def place_objects(objects, settings, gap=10.0):
    """Centre the objects side by side on the bed, away from the prime tower."""
    area = settings.get("printable_area") or ["0x0", "256x0", "256x256", "0x256"]
    pts = [tuple(float(c) for c in p.split("x")) for p in area]
    bx0, by0 = min(p[0] for p in pts), min(p[1] for p in pts)
    bx1, by1 = max(p[0] for p in pts), max(p[1] for p in pts)
    widths = [o["_size"][0] for o in objects]
    total = sum(widths) + gap * (len(objects) - 1)
    depth = max(o["_size"][1] for o in objects)
    cy = (by0 + by1) / 2
    try:
        tower_y = float((settings.get("wipe_tower_y") or [None])[0])
    except (TypeError, ValueError):
        tower_y = None
    if tower_y is not None and cy + depth / 2 + 10 > tower_y:
        cy = max(by0 + depth / 2 + 10, tower_y - 10 - depth / 2)
    x = (bx0 + bx1) / 2 - total / 2
    if total > bx1 - bx0 - 10 or depth > by1 - by0 - 10:
        raise UserError(f"the objects ({total:.0f} x {depth:.0f} mm) do not fit on the bed")
    try:
        max_h = float(settings.get("printable_height") or 0)
    except (TypeError, ValueError):
        max_h = 0
    height = max(o["_size"][2] for o in objects)
    if max_h and height > max_h:
        raise UserError(f"the objects are {height:.0f} mm tall, the printer prints up to {max_h:.0f} mm")
    for o, w in zip(objects, widths):
        o["_place"] = (x + w / 2, cy, o["_size"][2] / 2)
        x += w + gap


def build_project(job: dict, settings: dict, flat: dict | None, report: dict,
                  official: dict | None = None) -> bytes:
    if official is not None:
        settings = dict(settings)
        safety_problems(settings, official)      # fills missing printer limits; checked below
    n_fil = len(settings.get("filament_settings_id", []))
    if n_fil == 0:
        raise UserError("template has no filaments")
    objects = []
    for oi, obj in enumerate(job["objects"]):
        parts = []
        for part in obj["parts"]:
            if part["filament"] > n_fil:
                raise UserError(f"{part['stl']}: filament {part['filament']} but the template has {n_fil}")
            verts, faces = read_stl(part["_path"])
            if open_edges(faces):
                report["warnings"].append(f"{part['_path'].name}: mesh has open edges; Bambu Studio may repair it")
            parts.append({"name": part["_path"].stem, "filament": part["filament"], "v": verts, "f": faces})
        lo = [min(bbox(p["v"])[0][k] for p in parts) for k in range(3)]
        hi = [max(bbox(p["v"])[1][k] for p in parts) for k in range(3)]
        if abs(lo[2]) > 0.05:
            report["warnings"].append(f"object {obj.get('name', oi + 1)}: lowest point is z={lo[2]:.2f}, moved to the bed")
        objects.append({"name": str(obj.get("name") or job["name"]), "parts": parts,
                        "_centre": [(lo[k] + hi[k]) / 2 for k in range(3)],
                        "_size": [hi[k] - lo[k] for k in range(3)]})
    place_objects(objects, settings)

    # settings: the template, code keys from the official presets, then the job's choices
    s = dict(settings)
    replaced = []
    if flat is not None:
        replaced = code_key_differences(s, flat)
        for k in sorted(set(s) | set(flat)):
            if _is_code_key(k):
                s[k] = flat.get(k, [] if k == "post_process" else "")
    else:
        for k in list(s):
            if _is_code_key(k) and s[k] not in ("", [], [""]):
                raise UserError("cannot verify the template's G-code without Bambu Studio")
    report["code_keys_replaced"] = replaced
    for k in HOST_KEYS:
        if s.get(k):
            s[k] = ""
            report["warnings"].append(f"template setting {k} was cleared")
    nm = nozzle_map(job, s)
    if nm is not None:
        s["filament_map"] = nm
        s["filament_map_mode"] = "Manual"
    process_changes = []
    for k, v in (job.get("settings") or {}).items():
        if _is_code_key(k):
            raise UserError(f"settings: '{k}' cannot be set from a job")
        if k not in s:
            raise UserError(f"settings: unknown key '{k}'")
        if type(v) is not type(s[k]):
            raise UserError(f"settings: '{k}' must look like {json.dumps(s[k])[:40]}")
        s[k] = v
        process_changes.append(k)
    diff = list(s.get("different_settings_to_system") or [""])
    if process_changes:
        have = [x for x in diff[0].split(";") if x]
        diff[0] = ";".join(sorted(set(have) | set(process_changes)))
        s["different_settings_to_system"] = diff
    if official is not None:
        problems = safety_problems(s, official)
        if problems:
            raise UserError("the template or the job changes printer limits, motion or temperatures "
                            "beyond the official presets: " + "; ".join(problems[:5]) + ". Save a new "
                            "template from your own Bambu Studio with unmodified system presets.")
    version = str(s.get("version") or "")
    if not re.fullmatch(r"[0-9.]{1,20}", version):
        raise UserError("template has no Bambu Studio version")

    files = {}
    # geometry: one sub-model with every mesh, components group them into objects
    sub = ['<?xml version="1.0" encoding="UTF-8"?>',
           f'<model unit="millimeter" xml:lang="en-US" xmlns="{NS_CORE}" '
           'xmlns:BambuStudio="http://schemas.bambulab.com/package/2021" '
           'xmlns:p="http://schemas.microsoft.com/3dmanufacturing/production/2015/06" requiredextensions="p">',
           ' <metadata name="BambuStudio:3mfVersion">1</metadata>', ' <resources>']
    main_res, build_items, cfg_objects, plate_inst, assemble = [], [], [], [], []
    mesh_id = 0
    jn = job["name"]
    for oi, o in enumerate(objects):
        oid = 1000 + oi
        comps, cfg_parts = [], []
        for pi, p in enumerate(o["parts"]):
            mesh_id += 1
            c = o["_centre"]
            sub.append(f'  <object id="{mesh_id}" p:UUID="{_uid(f"{jn}/{oi}/{pi}/mesh")}" type="model">')
            sub.append("   <mesh>\n    <vertices>")
            sub += [f'     <vertex x="{_num(x - c[0])}" y="{_num(y - c[1])}" z="{_num(z - c[2])}"/>'
                    for x, y, z in p["v"]]
            sub.append("    </vertices>\n    <triangles>")
            sub += [f'     <triangle v1="{a}" v2="{b}" v3="{cc}"/>' for a, b, cc in p["f"]]
            sub.append("    </triangles>\n   </mesh>\n  </object>")
            comps.append(f'    <component p:path="/3D/Objects/object_1.model" objectid="{mesh_id}" '
                         f'p:UUID="{_uid(f"{jn}/{oi}/{pi}/comp")}" transform="1 0 0 0 1 0 0 0 1 0 0 0"/>')
            cfg_parts.append(
                f'    <part id="{mesh_id}" subtype="normal_part">\n'
                f'      <metadata key="name" value={quoteattr(p["name"])}/>\n'
                '      <metadata key="matrix" value="1 0 0 0 0 1 0 0 0 0 1 0 0 0 0 1"/>\n'
                f'      <metadata key="extruder" value="{p["filament"]}"/>\n'
                f'      <mesh_stat face_count="{len(p["f"])}" edges_fixed="0" degenerate_facets="0" '
                'facets_removed="0" facets_reversed="0" backwards_edges="0"/>\n    </part>')
            assemble.append(f'   <assemble_item object_id="{oid}" volume_id="{pi}" '
                            'transform="1 0 0 0 1 0 0 0 1 0 0 0" />')
        x, y, z = (_num(v) for v in o["_place"])
        main_res.append(f'  <object id="{oid}" p:UUID="{_uid(f"{jn}/{oi}/object")}" type="model">\n'
                        '   <components>\n' + "\n".join(comps) + '\n   </components>\n  </object>')
        build_items.append(f'  <item objectid="{oid}" p:UUID="{_uid(f"{jn}/{oi}/item")}" '
                           f'transform="1 0 0 0 1 0 0 0 1 {x} {y} {z}" printable="1"/>')
        faces = sum(len(p["f"]) for p in o["parts"])
        cfg_objects.append(f'  <object id="{oid}">\n    <metadata key="name" value={quoteattr(o["name"])}/>\n'
                           f'    <metadata key="extruder" value="{o["parts"][0]["filament"]}"/>\n'
                           f'    <metadata face_count="{faces}"/>\n' + "\n".join(cfg_parts) + "\n  </object>")
        plate_inst.append(f'    <model_instance>\n      <metadata key="object_id" value="{oid}"/>\n'
                          f'      <metadata key="instance_id" value="0"/>\n'
                          f'      <metadata key="identify_id" value="{oid}"/>\n    </model_instance>')
        assemble.insert(0, f'   <assemble_item object_id="{oid}" instance_id="0" '
                           f'transform="1 0 0 0 1 0 0 0 1 {x} {y} {z}" offset="0 0 0" />')
    sub += [" </resources>", " <build/>", "</model>"]
    files["3D/Objects/object_1.model"] = "\n".join(sub) + "\n"
    title = escape(str(job.get("title") or job["name"]))
    files["3D/3dmodel.model"] = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<model unit="millimeter" xml:lang="en-US" xmlns="{NS_CORE}" '
        'xmlns:BambuStudio="http://schemas.bambulab.com/package/2021" '
        'xmlns:p="http://schemas.microsoft.com/3dmanufacturing/production/2015/06" requiredextensions="p">\n'
        f' <metadata name="Application">BambuStudio-{version}</metadata>\n'
        ' <metadata name="BambuStudio:3mfVersion">1</metadata>\n'
        f' <metadata name="Title">{title}</metadata>\n'
        ' <resources>\n' + "\n".join(main_res) + "\n </resources>\n"
        f' <build p:UUID="{_uid(job["name"] + "/build")}">\n' + "\n".join(build_items) + "\n </build>\n</model>\n")
    maps = " ".join(s["filament_map"]) if nm is not None else ""
    plate_meta = ('    <metadata key="plater_id" value="1"/>\n    <metadata key="plater_name" value=""/>\n'
                  '    <metadata key="locked" value="false"/>\n')
    if nm is not None:
        plate_meta += (f'    <metadata key="filament_map_mode" value="Manual"/>\n'
                       f'    <metadata key="filament_maps" value="{maps}"/>\n'
                       f'    <metadata key="filament_volume_maps" value="{" ".join("0" for _ in nm)}"/>\n')
    files["Metadata/model_settings.config"] = (
        '<?xml version="1.0" encoding="UTF-8"?>\n<config>\n' + "\n".join(cfg_objects) +
        "\n  <plate>\n" + plate_meta + '    <metadata key="gcode_file" value=""/>\n' +
        "\n".join(plate_inst) + "\n  </plate>\n  <assemble>\n" + "\n".join(assemble) + "\n  </assemble>\n</config>\n")
    files[SETTINGS_ENTRY] = json.dumps(s, indent=4, ensure_ascii=False)
    files["Metadata/slice_info.config"] = (
        '<?xml version="1.0" encoding="UTF-8"?>\n<config>\n  <header>\n'
        '    <header_item key="X-BBL-Client-Type" value="slicer"/>\n'
        f'    <header_item key="X-BBL-Client-Version" value="{version}"/>\n  </header>\n</config>\n')
    files["[Content_Types].xml"] = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">\n'
        ' <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>\n'
        ' <Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>\n'
        ' <Default Extension="png" ContentType="image/png"/>\n'
        ' <Default Extension="gcode" ContentType="text/x.gcode"/>\n</Types>\n')
    rel = ('<?xml version="1.0" encoding="UTF-8"?>\n'
           '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n'
           ' <Relationship Target="{}" Id="rel-1" '
           'Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>\n</Relationships>\n')
    files["_rels/.rels"] = rel.format("/3D/3dmodel.model")
    files["3D/_rels/3dmodel.model.rels"] = rel.format("/3D/Objects/object_1.model")
    for name, text in files.items():
        if name != SETTINGS_ENTRY:
            ET.fromstring(text.encode("utf-8"))      # stop here if any XML is broken

    report["objects"] = [{"name": o["name"], "size_mm": [round(v, 2) for v in o["_size"]],
                          "position_mm": [round(v, 1) for v in o["_place"][:2]],
                          "parts": [{"name": p["name"], "filament": p["filament"]} for p in o["parts"]]}
                         for o in objects]
    report["filament_map"] = nm
    report["settings_changed"] = process_changes
    report["template"] = describe_template(s)
    import io
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, text in files.items():
            z.writestr(name, text)
    return buf.getvalue()


# --------------------------------------------------------------------------- checking

def parse_gcode(path: pathlib.Path, filament_map) -> dict:
    """Filament changes per layer from the sliced G-code (M620 S<n> marks a change)."""
    layer, per_layer = 0, {}
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if line.startswith("; CHANGE_LAYER"):
                layer += 1
            m = re.match(r"M620 S(\d+)A", line)
            if m:
                per_layer.setdefault(layer, []).append(int(m.group(1)) + 1)
    seq = [(lay, f) for lay in sorted(per_layer) for f in per_layer[lay]]
    same_nozzle = nozzle_switch = 0
    swap_layers = set()
    for (_, a), (lay, b) in zip(seq, seq[1:]):
        if a == b:
            continue
        if filament_map and filament_map[a - 1] != filament_map[b - 1]:
            nozzle_switch += 1
        else:
            same_nozzle += 1
            swap_layers.add(lay)
    return {"layers": layer, "changes_per_layer": {str(k): v for k, v in sorted(per_layer.items())},
            "swaps_same_nozzle": same_nozzle, "nozzle_switches": nozzle_switch,
            "layers_with_swaps": len(swap_layers)}


def check_project(path: pathlib.Path, paths: dict) -> dict:
    """Slice the project with the local Bambu Studio and summarise colour use and waste."""
    if not paths.get("executable"):
        raise UserError("Bambu Studio is not installed: the check needs it")
    with zipfile.ZipFile(path) as z:
        if SETTINGS_ENTRY not in z.namelist():
            raise UserError(f"{path} has no Bambu Studio settings")
        settings = json.loads(_read_entry(z, SETTINGS_ENTRY).decode("utf-8"))
        if not isinstance(settings, dict) or "printer_settings_id" not in settings:
            raise UserError(f"{path}: settings are not from Bambu Studio")
        problem = origin_problem(path, project_origin(z, settings), PROJECT_FIX)
    if problem:
        raise UserError(problem)
    official = official_presets(paths, settings)
    flat = official_code_values(paths, settings["printer_settings_id"], settings["print_settings_id"],
                                list(settings["filament_settings_id"]))
    unofficial = code_key_differences(settings, flat)
    if unofficial:
        raise UserError("this project carries G-code that is not the official one ("
                        + ", ".join(unofficial[:6]) + "). Check only projects made with 'build'; "
                        "use a downloaded project only after rebuilding it with 'build'.")
    problems = safety_problems(dict(settings), official)
    if problems:
        raise UserError("this project changes printer limits, motion or temperatures: "
                        + "; ".join(problems[:5]))
    fmap = settings.get("filament_map") if len(settings.get("nozzle_diameter", [])) > 1 else None
    with tempfile.TemporaryDirectory() as tmp:
        src = pathlib.Path(tmp) / "in.3mf"
        with zipfile.ZipFile(path) as zin, zipfile.ZipFile(src, "w", zipfile.ZIP_DEFLATED) as zout:
            for name in CHECK_ENTRIES:
                if name in zin.namelist():
                    zout.writestr(name, _read_entry(zin, name))
        res = _run_studio(paths["executable"], ["--slice", "1", "--outputdir", str(pathlib.Path(tmp) / "out"), str(src)], tmp)
        rj = pathlib.Path(tmp) / "out" / "result.json"
        if not rj.is_file():
            raise UserError("Bambu Studio did not slice the file:\n" + res.stdout[-800:] + res.stderr[-800:])
        result = json.loads(rj.read_text(encoding="utf-8"))
        if result.get("return_code", 1) != 0:
            raise UserError(f"Bambu Studio refused to slice: {result.get('error_string')}")
        plate = result["sliced_plates"][0]
        gcode = next((pathlib.Path(tmp) / "out").glob("plate_*.gcode"), None)
        stats = parse_gcode(gcode, fmap) if gcode else {}
        time_line = ""
        if gcode:
            with open(gcode, encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    if "total estimated time" in line:
                        time_line = line.split("total estimated time:")[-1].strip()
                        break
    colours = settings.get("filament_colour", [])
    fil = []
    for f in plate.get("filaments", []):
        i = f["id"]
        fil.append({"filament": i, "colour": colours[i - 1] if i - 1 < len(colours) else "?",
                    "nozzle": (("left" if fmap[i - 1] == "1" else "right") if fmap else None),
                    "model_g": round(f.get("main_used_g", 0), 2),
                    "total_g": round(f.get("total_used_g", 0), 2)})
    model = sum(f["model_g"] for f in fil)
    total = sum(f["total_g"] for f in fil)
    report = {"ok": True, "estimated_time": time_line, "filament_changes": plate.get("filament_change_times"),
              "model_g": round(model, 1), "total_g": round(total, 1), "waste_g": round(total - model, 1),
              "filaments": fil, **stats, "advice": []}
    report["advice"] = colour_advice(report, settings, fmap)
    return report


def colour_advice(r: dict, settings: dict, fmap) -> list:
    """Plain-language warnings from the colour best practices (references/colour-best-practices.md)."""
    adv = []
    used = [f for f in r["filaments"] if f["total_g"] > 0]
    types = settings.get("filament_type", [])
    used_types = {types[f["filament"] - 1] for f in used if f["filament"] - 1 < len(types)}
    if len(used_types) > 1:
        adv.append(f"Different materials in one print ({', '.join(sorted(used_types))}): they may not stick to each other.")
    if len(used) > 1 and settings.get("enable_prime_tower") == "0":
        adv.append("Prime tower is off with several colours: turn it on unless you know why it is off.")
    layers = max(r.get("layers") or 1, 1)
    with_swaps = r.get("layers_with_swaps", 0)
    if r.get("swaps_same_nozzle", 0) and with_swaps > layers * 0.3:
        adv.append(f"Colours swap on the same nozzle in {with_swaps} of {layers} layers: every swap "
                   "cuts and purges filament. Keep extra colours to a few layers (the first or the last).")
    if r["waste_g"] > max(r["model_g"], 5):
        adv.append(f"Purge waste ({r['waste_g']} g) is more than the part itself ({r['model_g']} g). "
                   "Normal for a small part with several colours; to cut it, use fewer colours or fewer "
                   "layers with colour, or print several copies on one plate (they share the purges).")
    if fmap and used:
        heavy = max(used, key=lambda f: f["model_g"])
        shared = [f for f in used if f is not heavy and f["nozzle"] == heavy["nozzle"]]
        other = [f for f in used if f["nozzle"] != heavy["nozzle"]]
        if shared and len(other) == 0:
            adv.append(f"All colours use the {heavy['nozzle']} nozzle. Put the main colour "
                       f"(filament {heavy['filament']}) on the other nozzle: a nozzle switch costs no purge.")
    return adv


# --------------------------------------------------------------------------- CLI

def _print(obj):
    print(json.dumps(obj, indent=2, ensure_ascii=False, default=str))


def other_slicers(dirs=None) -> list:
    """Installed slicers other than Bambu Studio that can open, and rewrite, a .3mf."""
    if dirs is None:
        system = platform.system()
        if system == "Darwin":
            dirs = [pathlib.Path("/Applications"), pathlib.Path.home() / "Applications"]
        elif system == "Windows":
            dirs = [pathlib.Path(os.environ.get("ProgramFiles", r"C:\Program Files"))]
        else:
            dirs = []
    found = []
    for d in dirs:
        try:
            entries = sorted(pathlib.Path(d).iterdir())
        except OSError:
            continue
        for e in entries:
            key = re.sub(r"[^a-z]", "", e.name.lower())
            if "bambu" not in key and any(s in key for s in OTHER_SLICERS):
                found.append(e.name)
    return found


def cmd_studio(a):
    out = dict(studio_paths(a.studio))
    others = other_slicers()
    out["other_slicers"] = others
    if others:
        out["warning"] = ("Other slicers are installed (" + ", ".join(others) + "). A double "
                          "click on a .3mf may open it in one of them, which rewrites it for "
                          "another printer; Bambu Studio can then crash on Print. Open projects "
                          "from Bambu Studio with File, Open project.")
    _print(out)


def cmd_templates(a):
    paths = studio_paths(a.studio)
    items = [(pathlib.Path(p), "given") for p in a.paths] or candidate_templates(paths)
    out = []
    for p, origin in items:
        try:
            out.append({"path": str(p), "origin": origin, **describe_template(read_template(p))})
        except (UserError, ValueError, zipfile.BadZipFile) as e:
            out.append({"path": str(p), "origin": origin, "error": str(e)})
    _print(out)


def output_path(job: dict, value, template: pathlib.Path, force: bool) -> pathlib.Path:
    """Where the project goes: a .3mf inside the job's folder, never the template, and an
    existing file only with --force."""
    base = job["_base"].resolve()
    out = pathlib.Path(value or f"{job['name']}.3mf")
    if not out.is_absolute():
        out = base / out
    if out.suffix.lower() != ".3mf":
        raise UserError(f"output must end in .3mf: {out.name}")
    if out.is_symlink():
        raise UserError(f"{out} is a symbolic link; refusing to write through it")
    real = out.resolve()
    if real != base and base not in real.parents:
        raise UserError(f"output must stay inside the job's folder ({base})")
    if real == template.resolve() or (real.exists() and template.exists()
                                      and os.path.samefile(real, template)):
        raise UserError("output would overwrite the settings template")
    if real.exists() and not real.is_file():
        raise UserError(f"{real} exists and is not a file")
    if real.exists() and not force:
        raise UserError(f"{real.name} already exists: pass --force to replace it")
    return real


def cmd_build(a):
    job_path = pathlib.Path(a.job).resolve()
    job = load_job(job_path)
    tpl = pathlib.Path(a.template or job.get("template") or "")
    if not tpl.is_absolute():
        tpl = (job["_base"] / tpl).resolve()
    if not tpl.is_file():
        raise UserError("no settings template: pass --template or set 'template' in the job")
    settings = read_template(tpl)
    paths = studio_paths(a.studio)
    flat = official_code_values(paths, settings["printer_settings_id"], settings["print_settings_id"],
                                list(settings["filament_settings_id"]))
    official = official_presets(paths, settings)
    report = {"warnings": []}
    data = build_project(job, settings, flat, report, official)
    out = output_path(job, a.out or job.get("output"), tpl, a.force)
    out.parent.mkdir(parents=True, exist_ok=True)
    out = output_path(job, str(out), tpl, a.force)   # again, now that the folder exists
    out.write_bytes(data)
    report["output"] = str(out)
    report["template_path"] = str(tpl)
    if a.check:
        chk = check_project(out, paths)
        if len(job["objects"]) > 1 and chk.get("layers_with_swaps", 0) > max(chk.get("layers") or 1, 1) * 0.3:
            chk["advice"].insert(0, "Several objects share the plate and their colours alternate on the "
                                    "same nozzle in most layers. Print them on separate plates: one job "
                                    "and one 3MF per plate.")
        report["check"] = chk
    _print(report)


def cmd_check(a):
    _print(check_project(pathlib.Path(a.file).resolve(), studio_paths(a.studio)))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--studio", help="path to the Bambu Studio executable (else auto-detect)")
    sp = ap.add_subparsers(dest="cmd", required=True)
    sp.add_parser("studio", help="show where Bambu Studio and its profiles are").set_defaults(fn=cmd_studio)
    t = sp.add_parser("templates", help="list settings templates")
    t.add_argument("paths", nargs="*")
    t.set_defaults(fn=cmd_templates)
    b = sp.add_parser("build", help="write the project from a job file")
    b.add_argument("job")
    b.add_argument("--template")
    b.add_argument("--out")
    b.add_argument("--check", action="store_true", help="also slice it to check")
    b.add_argument("--force", action="store_true", help="replace an existing output file")
    b.set_defaults(fn=cmd_build)
    c = sp.add_parser("check", help="slice a project with Bambu Studio and report")
    c.add_argument("file")
    c.set_defaults(fn=cmd_check)
    a = ap.parse_args(argv)
    try:
        a.fn(a)
    except UserError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except (ValueError, KeyError, TypeError, AttributeError, RecursionError, OSError,
            zipfile.BadZipFile) as e:
        print(f"error: unreadable input ({type(e).__name__}: {str(e)[:200]})", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
