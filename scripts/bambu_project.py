#!/usr/bin/env python3
"""Build a ready-to-print Bambu Studio project (.3mf) from STL parts, then check it.

Standard library only (Python 3.9+). It never contacts a printer: it writes a file,
and optionally asks the locally installed Bambu Studio to slice that file in a
temporary folder to prove it slices and to count colour changes.

Subcommands
  studio                 where Bambu Studio, its command line and its profiles are
  templates [PATH ...]   list settings templates (.3mf saved by Bambu Studio)
  build JOB.json         write the project described by JOB.json (--variants: also
                         each version listed in the job, with a comparison table)
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
import unicodedata
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
# Job and variant names: safe as file names.
NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
# Job formats written by the 3d-print-design skill (format 1 keys suggested_nozzles by STL,
# format 2 by colour name and adds settings, variants and estimates).
JOB_FORMATS = (1, 2)
# Zip entry that marks a project written by `build`. Bambu Studio ignores it on open and
# drops it on save, so a project saved again from Bambu Studio no longer carries it.
BUILT_ENTRY = "Metadata/x2d_print.json"
BUILT_NOTE = ("{name} is a project built by x2d-print, not a clean template: its settings "
              "carry an earlier job's choices (nozzles, walls, infill). Better: save a template "
              "from Bambu Studio as in SKILL.md Step 3.")
# Settings that say which printer, presets or loaded filaments a project is for. They come
# from the template (the person's own Bambu Studio) and a job may never set them.
IDENTITY_KEYS = frozenset((
    "inherits", "printer_model", "printer_variant", "printer_technology", "printer_structure",
    "version", "different_settings_to_system", "name", "from", "setting_id", "host_type",
    "default_print_profile", "default_filament_profile", "filament_type", "filament_colour",
    "filament_vendor", "filament_ids", "filament_map", "filament_map_mode", "filament_nozzle_map",
    "filament_volume_map"))
# Settings that must be a whole number.
INT_KEYS = frozenset(("wall_loops", "top_shell_layers", "bottom_shell_layers"))
_PERCENT = re.compile(r"-?[0-9]+(\.[0-9]+)?%")


# Copies of each object placed on the plate when the design asks for several (design.quantity).
MAX_COPIES = 50
MAX_COPY_FACES = 1_000_000      # above this many triangles in all, one copy is placed
# Placement: (margin from the bed edges, margin from the front edge where the purge line
# runs, gap between objects). The roomy spacing first, then a tight one before giving up.
SPACINGS = ((5.0, 10.0, 10.0), (3.0, 5.0, 5.0))
TOWER_MM = 10.0             # objects stay this far in front of the prime tower when they can
# Where the X2D's right nozzle reaches, when the template does not say (extruder_printable_area).
X2D_RIGHT_REACH_X = 20.5
# Strings read from a template or project (possibly a downloaded file) are printed into the
# agent's context: they are cut to this length and stripped of control characters.
TEXT_LIMIT = 80
_COLOUR = re.compile(r"#[0-9A-Fa-f]{6}(?:[0-9A-Fa-f]{2})?")


class UserError(Exception):
    """A problem the person can fix; printed without a traceback."""


def safe_text(v, limit: int = TEXT_LIMIT):
    """A value from an untrusted file, safe to print: control and invisible characters
    become spaces, runs of spaces one, and at most `limit` characters are kept."""
    if v is None:
        return None
    if not isinstance(v, str):
        v = json.dumps(v, ensure_ascii=False, default=str)
    v = "".join(" " if unicodedata.category(ch) in ("Cc", "Cf", "Cs", "Co", "Zl", "Zp") else ch
                for ch in v)
    v = re.sub(r"\s+", " ", v).strip()
    return v if len(v) <= limit else v[:limit - 3] + "..."


def safe_colour(v) -> str:
    """A colour from an untrusted file: only #RRGGBB or #RRGGBBAA, else '?'."""
    return v if isinstance(v, str) and _COLOUR.fullmatch(v) else "?"


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
            raise UserError(f"preset chain too deep at '{safe_text(name)}'")
        path = self.index.get(name)
        if path is None or not path.is_file():
            raise UserError(
                f"'{safe_text(name)}' is not an official Bambu preset on this computer. Save the template "
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
    # both strings come from the file itself: printed only cut and cleaned
    name, app_s, model_s = safe_text(path.name, 120), safe_text(app), safe_text(model)
    if app and not app.startswith("BambuStudio-"):
        why = (f"{name} was rewritten by another slicer ({app_s}, printer "
               f"{model_s or 'unknown'}), probably opened with a double click. Bambu Studio "
               "may crash on it or print with the wrong printer's settings.")
    elif not app:
        why = f"{name} was not saved by Bambu Studio (no Application metadata)."
    else:
        why = (f"{name} is set up for {model_s or 'an unknown printer'}, not the "
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


def built_project_note(path: pathlib.Path) -> str | None:
    """A warning when a .3mf was written by this script's `build` (not a clean template)."""
    try:
        with zipfile.ZipFile(path) as z:
            if BUILT_ENTRY in z.namelist():
                return BUILT_NOTE.format(name=path.name)
    except (OSError, zipfile.BadZipFile):
        pass
    return None


def _list(v) -> list:
    return v if isinstance(v, list) else []


def describe_template(settings: dict) -> dict:
    """The template's printer, plate and filaments, for the person to confirm. Every string
    comes from the file (possibly a downloaded one): cut and cleaned before printing."""
    fil = _list(settings.get("filament_settings_id"))
    colours = _list(settings.get("filament_colour"))
    types = _list(settings.get("filament_type"))
    return {
        "printer": safe_text(settings.get("printer_settings_id")),
        "process": safe_text(settings.get("print_settings_id")),
        "plate": safe_text(settings.get("curr_bed_type")),
        "layer_height": safe_text(settings.get("layer_height")),
        "nozzles": len(_list(settings.get("nozzle_diameter"))) or 1,
        "filaments": [
            {"number": i + 1, "colour": safe_colour(colours[i] if i < len(colours) else None),
             "type": safe_text(types[i]) if i < len(types) else "?", "preset": safe_text(name)}
            for i, name in enumerate(fil)],
        # A template records colours and materials, not where each spool sits.
        "where_loaded": ("unknown: the template does not record which AMS slot or external "
                         "spool holds each filament. Ask the person."),
        "studio_version": safe_text(settings.get("version")),
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

def _job_name(value, what: str) -> str:
    name = str(value if value is not None else "").strip()
    if not NAME_RE.fullmatch(name):
        raise UserError(f"{what}: 'name' must be 1-64 letters, digits, dots, dashes or underscores, "
                        "starting with a letter or digit")
    return name


def _stl_path(base: pathlib.Path, rel, what: str) -> pathlib.Path:
    if not isinstance(rel, str) or not rel.strip():
        raise UserError(f"{what}: needs an 'stl' file name")
    p = (base / rel).resolve()
    if p.suffix.lower() != ".stl" or not p.is_file():
        raise UserError(f"{what}: file not found or not .stl: {rel}")
    return p


def _settings_dict(value, what: str) -> dict:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise UserError(f"{what}: 'settings' must be an object such as {{\"wall_loops\": \"3\"}}")
    return value


def load_job(path: pathlib.Path) -> dict:
    """Read a job file, format 1 or 2 (see SKILL.md Step 4), and check its shape."""
    job = json.loads(path.read_text(encoding="utf-8"))
    base = path.parent
    if not isinstance(job, dict):
        raise UserError("job: the file must hold one JSON object")
    if not isinstance(job.get("objects"), list) or not job["objects"]:
        raise UserError("job: 'objects' must be a non-empty list")
    job["name"] = _job_name(job.get("name"), "job")
    job["_base"] = base
    job["_warnings"] = []
    design = job.get("design")
    if design is not None and not isinstance(design, dict):
        raise UserError("job: 'design' must be an object")
    fmt = (design or {}).get("format")
    if fmt is not None and fmt not in JOB_FORMATS:
        job["_warnings"].append(f"the job says design format {fmt!r}; this skill knows formats "
                                f"{', '.join(str(f) for f in JOB_FORMATS)}: update x2d-print if "
                                "something is missing")
    q = (design or {}).get("quantity")
    if q is None:
        q = 1
    if not isinstance(q, int) or isinstance(q, bool) or not 1 <= q <= MAX_COPIES:
        raise UserError(f"job: design.quantity must be a whole number from 1 to {MAX_COPIES}")
    job["_quantity"] = q
    job["settings"] = _settings_dict(job.get("settings"), "job")
    if job.get("nozzles") is not None and not isinstance(job["nozzles"], dict):
        raise UserError('job: \'nozzles\' must be an object such as {"1": "left", "2": "right"}')
    stls = set()
    for obj in job["objects"]:
        if not isinstance(obj, dict) or not isinstance(obj.get("parts"), list) or not obj["parts"]:
            name = obj.get("name") if isinstance(obj, dict) else obj
            raise UserError(f"object {name!r} has no parts")
        for part in obj["parts"]:
            if not isinstance(part, dict) or not isinstance(part.get("stl"), str):
                raise UserError("job: each part needs an 'stl' file name")
            fil = part.get("filament")
            if fil is None:
                colour = f" ({part['colour']})" if isinstance(part.get("colour"), str) else ""
                raise UserError(f"part {part['stl']!r}{colour}: 'filament' is still empty. Set it to "
                                "the number of the template filament with that colour (see `templates`).")
            if not isinstance(fil, int) or isinstance(fil, bool) or fil < 1:
                raise UserError(f"part {part.get('stl')!r}: 'filament' must be a number from 1")
            part["_path"] = _stl_path(base, part["stl"], f"part {part['stl']!r}")
            stls.add(part["stl"])
    variants = job.get("variants")
    if variants is None:
        variants = []
    if not isinstance(variants, list):
        raise UserError("job: 'variants' must be a list")
    seen = set()
    for v in variants:
        if not isinstance(v, dict):
            raise UserError("job: each variant must be an object with a 'name'")
        v["name"] = _job_name(v.get("name"), "variant")
        if v["name"] in seen:
            raise UserError(f"variant {v['name']!r} is listed twice: variant names must differ")
        seen.add(v["name"])
        what = f"variant {v['name']!r}"
        v["settings"] = _settings_dict(v.get("settings"), what)
        repl = v.get("stl") or {}
        if not isinstance(repl, dict):
            raise UserError(f"{what}: 'stl' must map a job STL to its replacement")
        v["_stl_paths"] = {}
        for old, new in repl.items():
            if old not in stls:
                raise UserError(f"{what}: 'stl' replaces {old!r}, which no part of the job uses")
            v["_stl_paths"][old] = _stl_path(base, new, what)
        if v.get("estimate") is not None and not isinstance(v["estimate"], dict):
            raise UserError(f"{what}: 'estimate' must be an object")
    job["variants"] = variants
    return job


def variant_job(job: dict, v: dict) -> dict:
    """The job for one variant: its settings on top of the job's, its STL replacements,
    the same filament numbers and nozzles."""
    vj = dict(job)
    vj["name"] = f"{job['name']}-{v['name']}"
    vj["settings"] = {**job.get("settings", {}), **v.get("settings", {})}
    vj["objects"] = [dict(o, parts=[dict(p, _path=v["_stl_paths"].get(p["stl"], p["_path"]))
                                    for p in o["parts"]]) for o in job["objects"]]
    return vj


def nozzle_map(job: dict, settings: dict) -> list | None:
    """Per-filament nozzle ('1' left, '2' right) for dual-nozzle printers, else None.

    The job's `nozzles` keys are template filament numbers ("1".."N") and the values
    "left" or "right"; anything else is refused, never silently ignored."""
    n_fil = len(settings.get("filament_settings_id", []))
    spec = job.get("nozzles") or {}
    if not isinstance(spec, dict):
        raise UserError('nozzles: must be an object such as {"1": "left", "2": "right"}')
    bad = [k for k in spec if k not in {str(i + 1) for i in range(n_fil)}]
    if bad:
        raise UserError(f"nozzles: {', '.join(repr(k) for k in bad[:5])} is not a filament number. "
                        f"The keys are the template's filament numbers as strings, \"1\" to "
                        f"\"{n_fil}\", not STL or colour names (those go in design.suggested_nozzles).")
    for k, v in spec.items():
        if not isinstance(v, str) or v.strip().lower() not in ("left", "right"):
            raise UserError(f"nozzles: filament {k} is {json.dumps(v)[:30]}: use \"left\" or \"right\"")
    if len(settings.get("nozzle_diameter", [])) < 2:
        return None
    names = {"left": "1", "right": "2", "1": "1", "2": "2"}
    current = list(settings.get("filament_map") or [])
    out = []
    for i in range(n_fil):
        v = spec.get(str(i + 1))
        if v is None:
            v = current[i] if i < len(current) else "1"
        v = names.get(str(v).strip().lower())
        if v is None:
            raise UserError(f"the template's filament_map for filament {i + 1} is not left or right")
        out.append(v)
    return out


def _value_shape_problem(k: str, v, current) -> str | None:
    """Why a job value does not look like the template's value, or None."""
    if isinstance(current, list):
        if len(v) != len(current):
            return f"'{k}' must have {len(current)} values, like {json.dumps(current)[:40]}"
        for x, c in zip(v, current):
            if not isinstance(x, str):
                return f"'{k}' values must be strings, like {json.dumps(current)[:40]}"
            why = _value_shape_problem(k, x, c) if isinstance(c, str) else None
            if why:
                return why
        return None
    x = v.strip()
    if k == "sparse_infill_density":
        if not _PERCENT.fullmatch(x) or not 0 <= float(x[:-1]) <= 100:
            return "'sparse_infill_density' must be a percentage from 0% to 100%, such as \"15%\""
        return None
    if k in INT_KEYS and not re.fullmatch(r"[0-9]{1,3}", x):
        return f"'{k}' must be a whole number written as a string, such as \"3\""
    c = current.strip()
    if (_NUMBER.fullmatch(c) or _PERCENT.fullmatch(c)) and not (_NUMBER.fullmatch(x) or _PERCENT.fullmatch(x)):
        return f"'{k}' must be a number written as a string, like {json.dumps(current)[:40]}"
    return None


def job_setting_problem(k: str, v, s: dict) -> str | None:
    """Why a job may not set `k` to `v` on top of the settings `s`, or None."""
    if _is_code_key(k):
        return f"'{k}' holds G-code or file names and cannot be set from a job"
    if k in ("filament_map", "filament_map_mode"):
        return f"'{k}' comes from the job's 'nozzles' (filament number to left or right), not 'settings'"
    if (k in IDENTITY_KEYS or k in HOST_KEYS or k.endswith("_settings_id") or "compatible" in k
            or "extruder_variant" in k):
        return (f"'{k}' says which printer, presets or loaded filaments the project is for. It comes "
                "from the template saved in your Bambu Studio and cannot be set from a job.")
    if k not in s:
        return f"unknown key '{k}'"
    if type(v) is not type(s[k]):
        return f"'{k}' must look like {json.dumps(s[k])[:40]}"
    why = _value_shape_problem(k, v, s[k])
    if why:
        return why
    if k in ("layer_height", "initial_layer_print_height"):
        if not _NUMBER.fullmatch(v.strip()):
            return f"'{k}' must be a height in mm written as a string, such as \"0.2\""
        h = float(v)
        lo = [float(x) for x in _flat_values(s.get("min_layer_height", [])) if _NUMBER.fullmatch(x)]
        hi = [float(x) for x in _flat_values(s.get("max_layer_height", [])) if _NUMBER.fullmatch(x)]
        if h <= 0 or (lo and h < max(lo)) or (hi and h > min(hi)):
            span = f" (this printer: {max(lo):g} to {min(hi):g} mm)" if lo and hi else ""
            return f"'{k}' {v} mm is outside the layer heights the nozzle can print{span}"
    return None


def design_warnings(job: dict, s: dict, nm) -> list:
    """Where the design (x2d-job.json `design`) and the project disagree."""
    d = job.get("design") if isinstance(job.get("design"), dict) else {}
    out = []

    def num(x):
        try:
            return float(x)
        except (TypeError, ValueError):
            return None
    used = sorted({p["filament"] for o in job["objects"] for p in o["parts"]})
    want, have = num(d.get("layer_mm")), num(s.get("layer_height"))
    if want and have and abs(want - have) > 1e-6:
        out.append(f"The design was made for {want:g} mm layers but the project prints {have:g} mm "
                   f"layers. Set settings.layer_height to \"{want:g}\" unless the change is wanted.")
    mat = d.get("material")
    types = s.get("filament_type", [])
    if isinstance(mat, str) and mat.strip():
        other = [f"{i} ({types[i - 1]})" for i in used
                 if i - 1 < len(types) and str(types[i - 1]).strip().upper() != mat.strip().upper()]
        if other:
            out.append(f"The design is for {mat.strip()}, but template filament {', '.join(other)} "
                       "is another material. Check the spools, then sync and save the template again.")
    want = num(d.get("nozzle_mm"))
    sizes = [num(x) for x in _flat_values(s.get("nozzle_diameter", []))]
    if want and any(x is not None and abs(x - want) > 1e-6 for x in sizes):
        out.append(f"The design was made for a {want:g} mm nozzle but the template has "
                   f"{', '.join(_flat_values(s.get('nozzle_diameter', [])))} mm nozzles.")
    sug = d.get("suggested_nozzles")
    if isinstance(sug, dict) and sug and nm is not None:
        for o in job["objects"]:
            for p in o["parts"]:
                # format 1 keys by STL name, format 2 by colour name
                key = p["stl"] if p["stl"] in sug else p.get("colour")
                w = sug.get(key) if isinstance(key, str) else None
                if w not in ("left", "right"):
                    continue
                h = "left" if nm[p["filament"] - 1] == "1" else "right"
                if h != w:
                    where = ("the external spool holder (right nozzle)" if w == "right"
                             else "the AMS (left nozzle)")
                    msg = (f"Advice: the design suggested the {w} nozzle for {key} because its plan "
                           f"prints faster that way; here filament {p['filament']} is on the {h} "
                           f"nozzle. Keep yours if {where} is not available for that colour; "
                           f"otherwise set nozzles \"{p['filament']}\": \"{w}\" and rebuild.")
                    if msg not in out:
                        out.append(msg)
    return out


# --------------------------------------------------------------------------- writing

def _uid(tag: str) -> str:
    return str(uuid.uuid5(NS_UUID, tag))


def _num(v: float) -> str:
    s = f"{v:.5f}".rstrip("0").rstrip(".")
    return "0" if s in ("", "-0") else s


def _corners(text) -> list:
    """'0x0,256x0,...' or ['0x0', '256x0', ...] as (x, y) points; [] when unreadable."""
    items = text.split(",") if isinstance(text, str) else (text if isinstance(text, list) else [])
    pts = []
    for p in items:
        try:
            x, y = (float(c) for c in str(p).strip().split("x"))
        except ValueError:
            return []
        if not (math.isfinite(x) and math.isfinite(y)):
            return []
        pts.append((x, y))
    return pts


def _inner_box(pts) -> tuple:
    """A rectangle inside a four-corner area (the area itself when it is a rectangle)."""
    xs, ys = sorted(p[0] for p in pts), sorted(p[1] for p in pts)
    if len(pts) >= 4:
        return xs[1], ys[1], xs[-2], ys[-2]
    return xs[0], ys[0], xs[-1], ys[-1]


def nozzle_reach(settings: dict, n_nozzles: int) -> list:
    """Per nozzle, the rectangle of the bed it can print on, from extruder_printable_area.
    Without it a two-nozzle X2D gets the right nozzle's known limit (x from 20.5 mm)."""
    bed = _corners(settings.get("printable_area")) or _corners(["0x0", "256x0", "256x256", "0x256"])
    bed_box = _inner_box(bed)
    areas = settings.get("extruder_printable_area")
    out = []
    for i in range(n_nozzles):
        pts = _corners(areas[i]) if isinstance(areas, list) and i < len(areas) else []
        if pts:
            out.append(_inner_box(pts))
        elif i == 1:
            out.append((max(bed_box[0], X2D_RIGHT_REACH_X),) + bed_box[1:])
        else:
            out.append(bed_box)
    return out


def _row_start(row: list, centre: float, gap: float):
    """Left edge of a row of objects (in this order) closest to `centre` that keeps each
    object inside its own x limits, or None when no left edge does."""
    lo, hi, off = -math.inf, math.inf, 0.0
    for o in row:
        w = o["_size"][0]
        lo, hi = max(lo, o["_xlim"][0] - off), min(hi, o["_xlim"][1] - off - w)
        off += w + gap
    if lo > hi + 1e-9:
        return None
    return min(max(centre - (off - gap) / 2, lo), hi)


def _shelves(objects: list, y0: float, y1: float, cx: float, cy: float, gap: float) -> bool:
    """Shelf packing: objects, deepest first, go left to right in a row; when the next one
    does not fit, a new row starts behind it. The rows are centred on (cx, cy) as far as
    the y range [y0, y1] and each object's x limits allow. Sets `_place`; False if it
    does not fit."""
    order = sorted(objects, key=lambda o: (-o["_size"][1], -o["_size"][0]))
    rows, cur = [], []
    for o in order:
        cand = sorted(cur + [o], key=lambda q: q["_xlim"][0])    # right-nozzle parts to the right
        if _row_start(cand, cx, gap) is not None:
            cur = cand
            continue
        if not cur or _row_start([o], cx, gap) is None:
            return False
        rows.append(cur)
        cur = [o]
    rows.append(cur)
    depths = [max(o["_size"][1] for o in r) for r in rows]
    total = sum(depths) + gap * (len(rows) - 1)
    if total > y1 - y0 + 1e-9:
        return False
    y = min(max(cy - total / 2, y0), y1 - total)
    for r, d in zip(rows, depths):
        x = _row_start(r, cx, gap)
        for o in r:
            o["_place"] = (x + o["_size"][0] / 2, y + d / 2, o["_size"][2] / 2)
            x += o["_size"][0] + gap
        y += d + gap
    return True


def place_objects(objects, settings, nm=None) -> list:
    """Lay the objects on the bed in rows, centred, in front of the prime tower, each inside
    the reach of the nozzles its parts print with. Returns notes for the report; raises
    UserError when they do not fit on one plate."""
    reach = nozzle_reach(settings, 2 if nm is not None else 1)
    bed = _inner_box(_corners(settings.get("printable_area")) or _corners(["0x0", "256x0", "256x256", "0x256"]))
    per_noz_h = [float(x) for x in _flat_values(settings.get("extruder_printable_height") or [])
                 if _NUMBER.fullmatch(x)]
    try:
        max_h = float(settings.get("printable_height") or 0)
    except (TypeError, ValueError):
        max_h = 0
    for o in objects:
        nozzles = sorted({int(nm[p["filament"] - 1]) - 1 for p in o["parts"]}) if nm else [0]
        box = list(bed)
        for i in nozzles:
            r = reach[min(i, len(reach) - 1)]
            box = [max(box[0], r[0]), max(box[1], r[1]), min(box[2], r[2]), min(box[3], r[3])]
        o["_box"] = box
        o["_right"] = 1 in nozzles and box[0] > bed[0]
        hs = [per_noz_h[i] for i in nozzles if i < len(per_noz_h)] if nm else []
        limit = min(hs) if hs else max_h
        if limit and o["_size"][2] > limit:
            on = " with the right nozzle" if hs and 1 in nozzles and limit < max_h else ""
            raise UserError(f"the objects are {o['_size'][2]:.0f} mm tall, the printer prints up to "
                            f"{limit:.0f} mm{on}")
    cx, cy = (bed[0] + bed[2]) / 2, (bed[1] + bed[3]) / 2
    try:
        tower_y = float((settings.get("wipe_tower_y") or [None])[0])
    except (TypeError, ValueError):
        tower_y = None
    for edge, front, gap in SPACINGS:
        for o in objects:
            b = o["_box"]
            o["_xlim"] = (b[0] + edge, b[2] - edge)
        y0 = max(o["_box"][1] for o in objects) + front
        y1 = min(o["_box"][3] for o in objects) - edge
        alone = [o for o in objects
                 if o["_size"][0] > o["_xlim"][1] - o["_xlim"][0] or o["_size"][1] > y1 - y0]
        if alone:
            if (edge, front, gap) != SPACINGS[-1]:
                continue
            o = alone[0]
            within = (f" within the right nozzle's reach (from x = {o['_box'][0]:g} mm)"
                      if o["_right"] else "")
            raise UserError(f"object {safe_text(o['name'])!r} is {o['_size'][0]:.0f} x {o['_size'][1]:.0f} "
                            f"mm and does not fit on the bed{within}. Scale it down or split it "
                            "into smaller parts.")
        if (tower_y is not None and math.isfinite(tower_y) and y0 < tower_y - TOWER_MM < y1
                and _shelves(objects, y0, tower_y - TOWER_MM, cx, cy, gap)):
            return []
        if _shelves(objects, y0, y1, cx, cy, gap):
            if tower_y is not None and math.isfinite(tower_y) and max(
                    o["_place"][1] + o["_size"][1] / 2 for o in objects) > tower_y - TOWER_MM:
                return ["the objects reach back to the prime tower's position: Bambu Studio may move "
                        "the tower or warn about it; check it in Preview"]
            return []
    sizes = ", ".join(f"{o['_size'][0]:.0f} x {o['_size'][1]:.0f}" for o in objects[:8])
    raise UserError(f"the {len(objects)} objects ({sizes} mm) do not fit on one plate, even in rows. "
                    "Split them into one 3MF per plate (one job per plate), or build fewer objects "
                    "and arrange them in Bambu Studio (Arrange, A).")


def place_copies(objects: list, quantity: int, settings: dict, nm, report: dict) -> list:
    """Place `quantity` copies of each object when they fit on the plate, else one copy and
    a warning that says how to add the others. Sets report['copies']."""
    if quantity > 1:
        faces = sum(len(p["f"]) for o in objects for p in o["parts"]) * quantity
        many = [dict(o, name=o["name"] if c == 0 else f"{o['name']} ({c + 1})")
                for o in objects for c in range(quantity)]
        why = None
        if faces > MAX_COPY_FACES:
            why = f"{quantity} copies would make the project too large ({faces} triangles)"
        else:
            try:
                report["warnings"].extend(place_objects(many, settings, nm))
                report["copies"] = {"per_object": quantity, "design_quantity": quantity}
                return many
            except UserError:
                why = f"{quantity} copies of each object do not fit on one plate"
        report["warnings"].append(
            f"design.quantity is {quantity}, but {why}: the project holds one copy of each object. "
            f"In Bambu Studio select the object, add {quantity - 1} copies with + and press Arrange (A); "
            "print the copies that do not fit as a second plate. The design's estimate is for "
            f"{quantity} copies, so the comparison uses it per copy (estimate / {quantity}).")
    report["warnings"].extend(place_objects(objects, settings, nm))
    report["copies"] = {"per_object": 1, "design_quantity": quantity}
    return objects


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
    process_changes, differ = [], []
    for k, v in (job.get("settings") or {}).items():
        why = job_setting_problem(k, v, s)
        if why:
            raise UserError(f"settings: {why}")
        if s[k] != v:
            differ.append(k)
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
    objects = place_copies(objects, job.get("_quantity", 1), s, nm, report)
    report["warnings"].extend(w for w in design_warnings(job, s, nm) if w not in report["warnings"])

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
    files[BUILT_ENTRY] = json.dumps({"built_by": "x2d-print", "job": job["name"],
                                     "note": "a project to print, not a settings template"}, indent=2)
    for name, text in files.items():
        if name not in (SETTINGS_ENTRY, BUILT_ENTRY):
            ET.fromstring(text.encode("utf-8"))      # stop here if any XML is broken

    report["objects"] = [{"name": o["name"], "size_mm": [round(v, 2) for v in o["_size"]],
                          "position_mm": [round(v, 1) for v in o["_place"][:2]],
                          "parts": [{"name": p["name"], "filament": p["filament"]} for p in o["parts"]]}
                         for o in objects]
    report["filament_map"] = nm
    report["settings_changed"] = differ
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


def check_project(path: pathlib.Path, paths: dict, presets: tuple | None = None) -> dict:
    """Slice the project with the local Bambu Studio and summarise colour use and waste.

    `presets` is (official, flat) already resolved for the same printer, process and
    filament presets (build resolves them once for every version); else they are read."""
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
    if presets is None:
        official = official_presets(paths, settings)
        flat = official_code_values(paths, settings["printer_settings_id"], settings["print_settings_id"],
                                    list(settings["filament_settings_id"]))
    else:
        official, flat = presets
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
            raise UserError("Bambu Studio did not slice the file:\n" + (res.stdout or "")[-800:]
                            + (res.stderr or "")[-800:])
        result = json.loads(rj.read_text(encoding="utf-8"))
        if result.get("return_code", 1) != 0:
            raise UserError(f"Bambu Studio refused to slice: {result.get('error_string')}")
        gcode = next((pathlib.Path(tmp) / "out").glob("plate_*.gcode"), None)
        return summarise_slice(result, gcode, settings, fmap)


def gcode_header(path: pathlib.Path) -> dict:
    """Time text and filament length per filament from the header Bambu Studio writes:
    '; total estimated time: 38m 12s', '; filament: 1,5', '; total filament length [mm] : a,b'."""
    out = {"time": "", "lengths_mm": {}}
    ids, lengths = [], []
    with open(path, encoding="utf-8", errors="replace") as fh:
        for n, line in enumerate(fh):
            if n > 400 or line.startswith("; HEADER_BLOCK_END"):
                break
            if "total estimated time:" in line:
                out["time"] = line.split("total estimated time:")[-1].strip()
            elif line.startswith("; filament:"):
                ids = [int(x) for x in re.findall(r"[0-9]+", line.split(":", 1)[1])]
            elif line.startswith("; total filament length [mm]"):
                lengths = [float(x) for x in re.findall(r"[0-9]+(?:\.[0-9]+)?", line.split(":", 1)[1])]
    if ids and len(ids) == len(lengths):
        out["lengths_mm"] = dict(zip(ids, lengths))
    return out


def studio_warnings(value) -> list:
    """Bambu Studio's warning_message, a string or a list, as short plain lines."""
    items = value if isinstance(value, list) else [value]
    out = []
    for it in items:
        if isinstance(it, dict):
            it = it.get("msg") or it.get("message") or it.get("text") or json.dumps(it)
        if isinstance(it, str):
            out += [ln.strip()[:300] for ln in it.splitlines() if ln.strip()]
    return out[:10]


def _seconds(v):
    return round(float(v)) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def summarise_slice(result: dict, gcode, settings: dict, fmap) -> dict:
    """The check report from Bambu Studio's result.json and the sliced G-code."""
    plate = result["sliced_plates"][0]
    stats = parse_gcode(gcode, fmap) if gcode else {}
    header = gcode_header(gcode) if gcode else {"time": "", "lengths_mm": {}}
    colours = settings.get("filament_colour", [])
    costs = settings.get("filament_cost", [])
    fil = []
    for f in plate.get("filaments", []):
        i = f["id"]
        total_g = round(f.get("total_used_g", 0), 2)
        mm = header["lengths_mm"].get(i)
        try:
            per_kg = float(costs[i - 1])
        except (IndexError, TypeError, ValueError):
            per_kg = None
        fil.append({"filament": i, "colour": safe_colour(colours[i - 1] if i - 1 < len(colours) else None),
                    "nozzle": (("left" if fmap[i - 1] == "1" else "right") if fmap else None),
                    "model_g": round(f.get("main_used_g", 0), 2), "total_g": total_g,
                    "length_m": round(mm / 1000, 2) if mm is not None else None,
                    "cost": round(total_g / 1000 * per_kg, 2) if per_kg is not None else None})
    model = sum(f["model_g"] for f in fil)
    total = sum(f["total_g"] for f in fil)
    lengths = [f["length_m"] for f in fil]
    prices = [f["cost"] for f in fil]
    ftt = plate.get("feature_type_times") if isinstance(plate.get("feature_type_times"), dict) else {}
    warnings = studio_warnings(plate.get("warning_message")) + studio_warnings(result.get("warning_message"))
    report = {"ok": True, "estimated_time": header["time"], "time_s": _seconds(plate.get("total_predication")),
              "flush_time_s": _seconds(ftt.get("Flush")), "prime_tower_time_s": _seconds(ftt.get("Prime tower")),
              "filament_changes": plate.get("filament_change_times"),
              "model_g": round(model, 1), "total_g": round(total, 1), "waste_g": round(total - model, 1),
              "metres": round(sum(lengths), 2) if fil and None not in lengths else None,
              "cost": round(sum(prices), 2) if fil and None not in prices else None,
              "filaments": fil, **stats, "studio_warnings": warnings, "advice": []}
    report["advice"] = colour_advice(report, settings, fmap)
    return report


def many_swap_layers(r: dict) -> bool:
    """True when same-nozzle colour swaps happen in more than 30 % of the layers."""
    layers = max(r.get("layers") or 1, 1)
    return bool(r.get("swaps_same_nozzle", 0)) and r.get("layers_with_swaps", 0) > layers * 0.3


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
    many = many_swap_layers(r)
    with_swaps, layers = r.get("layers_with_swaps", 0), max(r.get("layers") or 1, 1)
    if many:
        adv.append(f"Colours swap on the same nozzle in {with_swaps} of {layers} layers: every swap "
                   "cuts and purges filament. Keep extra colours to a few layers (the first or the last).")
    if r["waste_g"] > max(r["model_g"], 5):
        adv.append(f"Purge waste ({r['waste_g']} g) is more than the part itself ({r['model_g']} g). "
                   "Normal for a small part with several colours; to cut it, use fewer colours or fewer "
                   "layers with colour, or print several copies on one plate (they share the purges).")
    # Only when colours meet on one nozzle in many layers. When they change only by height
    # (few layers with swaps) everything stays on the left nozzle: colour rule 2.
    if fmap and used and many:
        heavy = max(used, key=lambda f: f["model_g"])
        shared = [f for f in used if f is not heavy and f["nozzle"] == heavy["nozzle"]]
        other = [f for f in used if f["nozzle"] != heavy["nozzle"]]
        if shared and len(other) == 0:
            adv.append(f"All colours use the {heavy['nozzle']} nozzle. If the other nozzle is free "
                       f"(for the right one, the external spool holder), put the main colour (filament "
                       f"{heavy['filament']}) there: a nozzle switch costs no purge.")
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
    # the rule holds even with no other slicer installed (one may be installed later)
    out["open_projects"] = "from Bambu Studio with File, Open project, never by double-clicking them"
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
        shown = safe_text(str(p), 300)
        try:
            row = {"path": shown, "origin": origin, **describe_template(read_template(p))}
            note = built_project_note(p)
            if note:
                row["warning"] = safe_text(note, 400)
            out.append(row)
        except (UserError, ValueError, zipfile.BadZipFile) as e:
            out.append({"path": shown, "origin": origin, "error": safe_text(str(e), 600)})
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


def write_project(out: pathlib.Path, data: bytes, check, settings_changed: list):
    """Write `data` to a temporary file next to `out`, check it when `check` is a callable
    (path -> report), then move it into place. On any failure the temporary file is
    deleted and `out` is left as it was."""
    fd, tmp = tempfile.mkstemp(prefix=f".{out.stem}-", suffix=".tmp.3mf", dir=str(out.parent))
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.chmod(tmp, 0o644)
        report = check(pathlib.Path(tmp)) if check else None
        os.replace(tmp, out)
        return report
    except BaseException as e:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        if isinstance(e, UserError) and settings_changed:
            raise UserError(f"{e}\nNo file was written. The job changes these settings from the "
                            f"template: {', '.join(settings_changed)}. One of them may be the "
                            "cause: build again without it to see.") from e
        if isinstance(e, UserError):
            raise UserError(f"{e}\nNo file was written.") from e
        raise


def _minutes_range(est: dict):
    m = est.get("minutes")
    if isinstance(m, list) and len(m) == 2 and all(isinstance(x, (int, float)) for x in m):
        return [min(m), max(m)]
    r = est.get("minutes_range")
    if isinstance(r, list) and len(r) == 2 and all(isinstance(x, (int, float)) for x in r):
        return [min(r), max(r)]
    if isinstance(m, (int, float)) and not isinstance(m, bool):
        return [m, m]
    return None


def _drift(real, est):
    if real is None or not isinstance(est, (int, float)) or isinstance(est, bool) or est <= 0:
        return None
    return round((real - est) / est * 100)


def scaled_estimate(est: dict, factor: float) -> dict:
    """The estimate's grams, metres and minutes times `factor` (copies placed / design.quantity)."""
    out = {}
    for k in ("grams", "model_g", "metres"):
        v = est.get(k)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            out[k] = round(v * factor, 2)
    rng = _minutes_range(est)
    if rng:
        out["minutes"] = [round(rng[0] * factor, 1), round(rng[1] * factor, 1)]
    return out


def comparison_row(name: str, about, output: str, est, chk, copies: int = 1, quantity: int = 1) -> dict:
    """One version: real numbers from the check next to the design's estimate.

    The design's `grams` count model plus purge (3d-print-design estimate.py), so they are
    compared with total_g; `model_g` with model_g. Minutes are a range: the drift is 0 inside
    it, else measured from the nearest end. The estimate is for `quantity` copies
    (design.quantity); when the project holds a different number of `copies`, it is scaled
    to them (per copy when only one is placed), so the drift is not an artefact."""
    chk = chk or {}
    est = est if isinstance(est, dict) else {}
    row = {"version": name, "about": about if isinstance(about, str) else "", "output": output,
           "time": chk.get("estimated_time"), "time_s": chk.get("time_s"), "model_g": chk.get("model_g"),
           "purge_g": chk.get("waste_g"), "total_g": chk.get("total_g"), "metres": chk.get("metres"),
           "cost": chk.get("cost"), "filament_changes": chk.get("filament_changes"), "estimate": est,
           "copies": copies, "drift_pct": {}}
    if quantity > 1 and copies != quantity and est:
        est = scaled_estimate(est, copies / quantity)
        row["estimate_compared"] = est
        row["compared_as"] = (f"design estimate for {quantity} copies, scaled to the {copies} "
                              f"cop{'y' if copies == 1 else 'ies'} on the plate")
    rng = _minutes_range(est)
    if rng and chk.get("time_s") is not None:
        real = chk["time_s"] / 60
        row["minutes_in_range"] = rng[0] <= real <= rng[1]
        edge = rng[0] if real < rng[0] else (rng[1] if real > rng[1] else None)
        row["drift_pct"]["minutes"] = 0 if edge is None else _drift(real, edge)
    for key, real in (("grams", chk.get("total_g")), ("model_g", chk.get("model_g")),
                      ("metres", chk.get("metres"))):
        d = _drift(real, est.get(key))
        if d is not None:
            row["drift_pct"][key] = d
    return row


def comparison_table(rows: list) -> str:
    """The comparison as a short plain-text table."""
    def cell(v, fmt="{:g}"):
        return "?" if v is None else fmt.format(v)

    def pct(v):
        return "" if v is None else f"{v:+d}%"
    head = ["version", "copies", "time", "model g", "purge g", "total g", "metres", "cost", "changes",
            "design g", "design min", "drift g", "drift min"]
    lines = []
    for r in rows:
        e = r.get("estimate_compared", r["estimate"])
        rng = _minutes_range(e)
        lines.append([r["version"], cell(r.get("copies", 1)), r["time"] or "?", cell(r["model_g"]), cell(r["purge_g"]),
                      cell(r["total_g"]), cell(r["metres"]), cell(r["cost"], "{:.2f}"),
                      cell(r["filament_changes"]), cell(e.get("grams")),
                      "" if not rng else (f"{rng[0]:g}" if rng[0] == rng[1] else f"{rng[0]:g}-{rng[1]:g}"),
                      pct(r["drift_pct"].get("grams")),
                      "in range" if r.get("minutes_in_range") else pct(r["drift_pct"].get("minutes"))])
    widths = [max(len(str(x)) for x in col) for col in zip(head, *lines)]
    return "\n".join("  ".join(str(x).ljust(w) for x, w in zip(row, widths)).rstrip()
                     for row in [head] + lines)


def cmd_build(a):
    job_path = pathlib.Path(a.job).resolve()
    job = load_job(job_path)
    tpl = pathlib.Path(a.template or job.get("template") or "")
    if not tpl.is_absolute():
        tpl = (job["_base"] / tpl).resolve()
    if not tpl.is_file():
        raise UserError("no settings template: pass --template or set 'template' in the job")
    settings = read_template(tpl)
    tpl_note = built_project_note(tpl)
    paths = studio_paths(a.studio)
    # resolved once: every version uses the template's printer, process and filament presets
    flat = official_code_values(paths, settings["printer_settings_id"], settings["print_settings_id"],
                                list(settings["filament_settings_id"]))
    official = official_presets(paths, settings)
    if a.variants and not job["variants"]:
        raise UserError("--variants: the job lists no 'variants'")
    versions = [(None, job)] + ([(v, variant_job(job, v)) for v in job["variants"]] if a.variants else [])
    main_out = output_path(job, a.out or job.get("output"), tpl, a.force)

    # build every version in memory and check every output path before writing anything
    planned = []
    for v, vj in versions:
        report = {"warnings": list(job["_warnings"]) + ([tpl_note] if tpl_note else [])}
        try:
            data = build_project(vj, settings, flat, report, official)
        except UserError as e:
            raise UserError(f"variant {v['name']!r}: {e}" if v else str(e)) from e
        out = main_out if v is None else main_out.with_name(f"{main_out.stem}-{v['name']}.3mf")
        planned.append((v, vj, data, output_path(job, str(out), tpl, a.force), report))
    if job["variants"] and not a.variants:
        planned[0][4]["warnings"].append(
            f"the job lists {len(job['variants'])} other version(s) ("
            + ", ".join(v["name"] for v in job["variants"]) + "): add --variants to build and compare them")

    def check_fn(vj):
        def run(path):
            chk = check_project(path, paths, (official, flat))
            if len(vj["objects"]) > 1 and many_swap_layers(chk):
                chk["advice"].insert(0, "Several objects share the plate and their colours alternate on "
                                        "the same nozzle in most layers. Print them on separate plates: "
                                        "one job and one 3MF per plate.")
            return chk
        return run

    failed, rows = [], []
    for v, vj, data, out, report in planned:
        out.parent.mkdir(parents=True, exist_ok=True)
        out = output_path(job, str(out), tpl, a.force)   # again, now that the folder exists
        try:
            chk = write_project(out, data, check_fn(vj) if a.check else None, report["settings_changed"])
        except UserError as e:
            if v is None:
                raise
            report["error"] = str(e)
            failed.append(v["name"])
            chk = None
        else:
            report["output"] = str(out)
        if chk is not None:
            report["check"] = chk
        design = job.get("design") if isinstance(job.get("design"), dict) else {}
        if v is None:
            label = design.get("variant") if isinstance(design.get("variant"), str) else "chosen"
            name, est, about = f"{label} (chosen)", design.get("estimate"), "the version in the job's top level"
        else:
            name, est, about = v["name"], v.get("estimate"), v.get("about")
        if a.variants or (a.check and isinstance(est, dict)):
            copies = report.get("copies") or {}
            rows.append(comparison_row(name, about, report.get("output", ""), est, chk,
                                       copies.get("per_object", 1), job.get("_quantity", 1)))
    result = planned[0][4]
    result["template_path"] = str(tpl)
    if a.variants:
        result["variants"] = [{"name": v["name"], "about": v.get("about"),
                               **{k: x for k, x in r.items() if k not in ("template", "code_keys_replaced")}}
                              for v, _, _, _, r in planned[1:]]
    if failed:
        result["failed_variants"] = failed
    if rows:
        result["comparison"] = rows
        result["table"] = comparison_table(rows)
    _print(result)
    if rows:
        print(result["table"], file=sys.stderr)
    return 1 if failed else 0


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
    b.add_argument("--variants", action="store_true",
                   help="also build each version in the job's 'variants' as <output>-<name>.3mf")
    b.set_defaults(fn=cmd_build)
    c = sp.add_parser("check", help="slice a project with Bambu Studio and report")
    c.add_argument("file")
    c.set_defaults(fn=cmd_check)
    a = ap.parse_args(argv)
    try:
        code = a.fn(a)
    except UserError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except (ValueError, KeyError, TypeError, AttributeError, RecursionError, OSError,
            zipfile.BadZipFile) as e:
        print(f"error: unreadable input ({type(e).__name__}: {str(e)[:200]})", file=sys.stderr)
        return 2
    return code or 0


if __name__ == "__main__":
    sys.exit(main())
