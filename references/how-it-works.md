# How the script works

`scripts/bambu_project.py`, standard library only. It writes files and runs the local
Bambu Studio in a temporary folder; it opens no network connection.

## The 3MF it writes

A Bambu Studio project is a zip:

| Entry | Content |
|---|---|
| `3D/3dmodel.model` | one object per job object, made of components; build items placed on the plate |
| `3D/Objects/object_1.model` | the meshes, one per STL part |
| `Metadata/model_settings.config` | each part's filament number (`extruder`), the plate, `filament_map_mode` and `filament_maps` |
| `Metadata/project_settings.config` | every setting, flat JSON: the template's, see below |
| `Metadata/slice_info.config`, `[Content_Types].xml`, `_rels/` | the boilerplate Bambu Studio expects |

Every XML entry is parsed back before the zip is written.

## Where the settings come from

1. **The template**, a `.3mf` saved by the person's own Bambu Studio: printer, nozzle,
   plate type, process, filament presets and the colours synced from the AMS, plus all
   vectors already sized for the number of filaments and nozzles. This is why there is no
   hand-written settings file in this repository: the person's install knows the current
   profiles, and Bambu's profiles are AGPL-3.0 and change with each release.
2. **Official code values.** Every key that holds code or names output files (`*_gcode`,
   `gcode_flavor`, `post_process`, `filename_format`) is replaced with the value of the
   system preset of the same name, read from the local install
   (`<Bambu Studio data>/system/BBL`). The resolver follows each preset's `inherits` chain
   and its `include` list, as Bambu Studio does. The X2D's start, layer change and filament
   change G-code live in separate "template" files reached only through `include`; Bambu
   Studio's own `--export-settings` skips them and returns a generic start G-code, which
   is why the script does not use it. If a preset is not a system preset, the build stops.
   The printer limits and motion settings (plate area and height, nozzle, z offset, clearances, the printer's maximum speeds and accelerations, and the retraction, z hop and flow limits of each filament) must match the official
   presets, each filament's nozzle temperature must stay in that filament's official range,
   and bed and chamber temperatures within 10 C of its official value. This is checked on
   the final settings, after the job's overrides, so a job cannot undo it; otherwise the
   build stops. Network host settings (`print_host`, `printhost_apikey` and similar) are
   cleared.
3. **The job's choices:** `filament_map` (left nozzle `"1"`, right nozzle `"2"`, one entry
   per filament) with `filament_map_mode` set to `Manual`, and the process overrides in
   `settings`. Manual mode avoids the automatic grouping, which on dual-nozzle printers
   has open bugs that can put two filaments on the auxiliary nozzle.

## Placement

Each object is centred on its own bounding box, laid on the bed (lowest point at z = 0)
and placed in a row across the printable area, away from the prime tower position. If the
row does not fit, the build stops and says so: split the job into plates.

## The check

`--check` (or `check FILE.3mf`) copies the project into a temporary folder and runs
`BambuStudio --slice 1 --outputdir ...`. From `result.json` it takes grams per filament
(model and total, the difference is purge and prime tower) and the number of changes;
from the G-code it counts `M620 S<n>` lines per layer to tell nozzle switches (free)
from same-nozzle swaps (each one flushes). The sliced G-code is deleted with the folder:
the person slices again in Bambu Studio before printing.

Validated on Bambu Studio 2.9.1 with an X2D template: the script's project sliced to the
same layer count, changes, grams and time as the same parts set up by hand in the GUI.

## Limits

- One plate per 3MF. For two plates, two job files.
- STL only (binary or ASCII); one STL per colour. Painted single-mesh models are not
  supported.
- Parts keep the position they have in their STL relative to each other, so export all
  parts of one object from the same CAD file without moving them.
- The template's flush volumes are kept; Bambu Studio recalculates them on Sync.
