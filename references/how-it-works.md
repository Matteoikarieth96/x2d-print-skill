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
| `Metadata/x2d_print.json` | a marker: "built by x2d-print, a project to print, not a template". Bambu Studio ignores it and drops it when it saves the file again; `templates` and `build` warn when a template still carries it |

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
   per filament, from the job's `nozzles`: keys `"1"` to `"N"`, values `left` or `right`,
   anything else refused) with `filament_map_mode` set to `Manual`, which Bambu Studio
   02.09's window calls **Custom Mode**; and the process overrides in `settings`. A job
   may not set G-code keys, host keys, or the keys that say which printer, presets or
   filaments the project is for (`*_settings_id`, `inherits`, `printer_model`, `version`,
   `compatible_*`, `different_settings_to_system`, `filament_type`, `filament_colour`,
   `filament_map`, ...). Values must be shaped like the template's: same type, same
   number of items, numbers where the template has numbers, `sparse_infill_density` a
   percentage from 0% to 100%, wall and shell counts whole numbers, layer heights within
   the printer's `min_layer_height` and `max_layer_height`. Custom Mode avoids the
   automatic grouping, which on dual-nozzle printers
   has open bugs that can put two filaments on the auxiliary nozzle (Bambu Studio issues
   #12915 and #13020, both still open in 02.09.01.70, November 2026).

## Placement

Each object is centred on its own bounding box, laid on the bed (lowest point at z = 0)
and placed in a row across the printable area, away from the prime tower position. If the
row does not fit, the build stops and says so: split the job into plates.

Placement uses the whole plate's printable area. The X2D's right nozzle has a smaller
one (it cannot reach the 20.5 mm at the left edge and prints 5 mm lower); a part on that
nozzle placed in the strip makes the check fail with Bambu Studio's out-of-area message.

## The check

Before anything else, `check` (like `templates` and `build` for a template) reads which
program last saved the file (`Application` in `3D/3dmodel.model`) and its
`printer_model`. Bambu Studio's forks (QIDI Studio, OrcaSlicer and others) open the same
`.3mf` and, on save, write their own name and convert it to their own printer; Bambu
Studio still slices such a file but can crash when sending it. Anything other than
`BambuStudio-<version>` and `Bambu Lab X2D` is refused with the fix: rebuild with
`build --force`, open from Bambu Studio with File, Open project. `studio` lists such
slicers when they are installed, since a double click may open the file in one of them.

`--check` (or `check FILE.3mf`) copies the project into a temporary folder and runs
`BambuStudio --slice 1 --outputdir ...`. From `result.json` (first entry of
`sliced_plates`) it takes grams per filament (`main_used_g` for the model,
`total_used_g` with purge: the difference is flush plus prime tower, which Bambu
Studio's Preview panel shows apart), `filament_change_times`, `total_predication`
(seconds), the `Flush` and `Prime tower` seconds of `feature_type_times`, and
`warning_message`, reported as `studio_warnings`. From the G-code header it takes the
time text (`total estimated time`) and the length per filament (`; filament:` with
`; total filament length [mm]`); cost is the template's `filament_cost` (per kg) times
the grams. In the G-code body it counts `M620 S<n>` lines per layer to tell nozzle
switches (free) from same-nozzle swaps (each one flushes). The sliced G-code is deleted
with the folder: the person slices again in Bambu Studio before printing.

With `build --check` the project is first written to a hidden temporary file in the
output folder, checked, and only then moved over the output name. If the check fails the
temporary file is deleted and an older output stays as it was; the error lists the job
settings that differ from the template.

The design comparison: when the job has a `design` block, `build` warns when the
project's `layer_height` (after the job's settings), the `filament_type` of the
filaments used, or `nozzle_diameter` differ from `design.layer_mm`, `design.material`,
`design.nozzle_mm`, and when a filament sits on the other nozzle than
`design.suggested_nozzles` says (keyed by STL name in job format 1, by colour in
format 2).

## Variants

Job format 2 may list `variants`: `name` (same rule as the job name, no duplicates),
`about`, `settings` applied on top of the job's, `stl` replacing some of the job's STLs
(paths relative to the job file), and the design skill's `estimate`. `build --variants`
reads the template and resolves the official presets once, builds every version in
memory and checks every output path before writing anything, then writes (and with
`--check` slices) them one after another, as `<output stem>-<name>.3mf`. A variant whose
slice fails gets no file and the command exits with code 1. The comparison puts real
time, grams, metres, cost and changes next to the estimate: grams against total grams
(the design's estimate counts purge), minutes against the estimated range.

Validated on Bambu Studio 2.9.1 with an X2D template: the script's project sliced to the
same layer count, changes, grams and time as the same parts set up by hand in the GUI.

## Limits

- One plate per 3MF. For two plates, two job files.
- Each job object is placed once, in a row. To fill the plate, the person adds copies in
  Bambu Studio (`+`, then Arrange with `A`); the check's numbers are for the job as built.
- STL only (binary or ASCII); one STL per colour. Painted single-mesh models are not
  supported.
- Parts keep the position they have in their STL relative to each other, so export all
  parts of one object from the same CAD file without moving them.
- The template's flush volumes are kept; Bambu Studio recalculates them on Sync.
