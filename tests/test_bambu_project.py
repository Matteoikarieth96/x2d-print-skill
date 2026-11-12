"""Unit tests that need no Bambu Studio: python3 -m unittest discover -s tests"""
import io
import json
import os
import pathlib
import struct
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))
import bambu_project as bp  # noqa: E402


def write_box_stl(path, x0, y0, z0, x1, y1, z1):
    """A closed box as a binary STL."""
    v = [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
         (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]
    tris = [(0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7), (0, 1, 5), (0, 5, 4),
            (1, 2, 6), (1, 6, 5), (2, 3, 7), (2, 7, 6), (3, 0, 4), (3, 4, 7)]
    with open(path, "wb") as fh:
        fh.write(b"\0" * 80 + struct.pack("<I", len(tris)))
        for t in tris:
            fh.write(struct.pack("<3f", 0, 0, 0))
            for i in t:
                fh.write(struct.pack("<3f", *v[i]))
            fh.write(b"\0\0")


def fake_profiles(root):
    """A tiny system/BBL tree with inherits and include, like Bambu Studio's."""
    bbl = root / "system" / "BBL"
    for sub in ("machine", "process", "filament"):
        (bbl / sub).mkdir(parents=True)
    presets = {
        "machine/common.json": {"name": "common", "machine_start_gcode": "GENERIC",
                                "change_filament_gcode": "", "gcode_flavor": "marlin",
                                "printable_area": ["0x0", "256x0", "256x256", "0x256 "],
                                "printable_height": "250", "nozzle_diameter": ["0.4", "0.4"],
                                "printer_model": "Bambu Lab X2D",
                                "machine_max_speed_z": ["12", "12"]},
        "machine/Printer tpl start.json": {"name": "Printer tpl start", "instantiation": "false",
                                           "machine_start_gcode": "OFFICIAL START"},
        "machine/Printer tpl change.json": {"name": "Printer tpl change", "instantiation": "false",
                                            "change_filament_gcode": "M620 S[next_extruder]A"},
        "machine/Printer 0.4.json": {"name": "Printer 0.4", "inherits": "common",
                                     "include": ["Printer tpl start", "Printer tpl change"]},
        "process/proc.json": {"name": "proc", "filename_format": "{input_filename_base}.gcode",
                              "wall_loops": "2"},
        "filament/fil base.json": {"name": "fil base", "filament_start_gcode": ["; start base"],
                                   "filament_end_gcode": ["; end"],
                                   "nozzle_temperature_range_low": ["190"],
                                   "nozzle_temperature_range_high": ["240"],
                                   "textured_plate_temp": ["55"],
                                   "filament_retraction_length": ["0.8"]},
        "filament/PLA A.json": {"name": "PLA A", "inherits": "fil base"},
        "filament/PC C.json": {"name": "PC C", "inherits": "fil base",
                               "nozzle_temperature_range_low": ["260"],
                               "nozzle_temperature_range_high": ["300"]},
        "filament/PLA B.json": {"name": "PLA B", "inherits": "fil base",
                                "filament_start_gcode": ["; start B"]},
    }
    index = {"machine_model_list": [], "machine_list": [], "process_list": [], "filament_list": []}
    for rel, data in presets.items():
        (bbl / rel).write_text(json.dumps(data))
        key = {"machine": "machine_list", "process": "process_list", "filament": "filament_list"}[rel.split("/")[0]]
        index[key].append({"name": data["name"], "sub_path": rel})
    (root / "system" / "BBL.json").write_text(json.dumps(index))
    return {"profiles": str(bbl), "executable": None}


def template_settings(**extra):
    s = {
        "printer_settings_id": "Printer 0.4", "print_settings_id": "proc",
        "printer_model": "Bambu Lab X2D",
        "filament_settings_id": ["PLA A", "PLA B"], "filament_colour": ["#FFFFFF", "#000000"],
        "filament_type": ["PLA", "PLA"], "nozzle_diameter": ["0.4", "0.4"],
        "filament_map": ["1", "1"], "printable_area": ["0x0", "256x0", "256x256", "0x256"],
        "wipe_tower_y": ["220"], "curr_bed_type": "Textured PEI Plate", "version": "2.9.1.70",
        "wall_loops": "2", "different_settings_to_system": ["", "", "", ""],
        "nozzle_temperature": ["220", "220", "220", "220"], "textured_plate_temp": ["55", "60"],
        "filament_retraction_length": ["0.8", "0.8"],
        # hostile values a downloaded template could carry
        "machine_start_gcode": "M104 S999 ; tampered", "post_process": ["/tmp/evil.sh"],
        "filament_start_gcode": ["tampered", "tampered"], "filename_format": "../../x",
    }
    s.update(extra)
    return s


def write_3mf(path, settings, app="BambuStudio-02.09.01.70"):
    """A project as Bambu Studio (or, with another app, a different slicer) saves it."""
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(bp.SETTINGS_ENTRY, json.dumps(settings))
        if app is not None:
            z.writestr(bp.MODEL_ENTRY, '<?xml version="1.0" encoding="UTF-8"?>\n<model>\n'
                       f' <metadata name="Application">{app}</metadata>\n</model>\n')
    return path


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = pathlib.Path(self.tmp.name)
        self.paths = fake_profiles(self.dir)
        write_box_stl(self.dir / "base.stl", 0, 0, 0, 40, 20, 3)
        write_box_stl(self.dir / "inlay.stl", 10, 5, 0, 20, 15, 0.8)

    def tearDown(self):
        self.tmp.cleanup()

    def job(self, **extra):
        j = {"name": "test-job", "objects": [{"name": "tag", "parts": [
            {"stl": "base.stl", "filament": 2}, {"stl": "inlay.stl", "filament": 1}]}],
            "nozzles": {"1": "left", "2": "right"}}
        j.update(extra)
        p = self.dir / "job.json"
        p.write_text(json.dumps(j))
        return bp.load_job(p)


class TestStl(Base):
    def test_read_and_closed(self):
        v, f = bp.read_stl(self.dir / "base.stl")
        self.assertEqual(len(v), 8)
        self.assertEqual(len(f), 12)
        self.assertEqual(bp.open_edges(f), 0)
        lo, hi = bp.bbox(v)
        self.assertEqual([round(x, 3) for x in hi], [40, 20, 3])


class TestPresets(Base):
    def test_include_wins_over_inherits(self):
        off = bp.official_code_values(self.paths, "Printer 0.4", "proc", ["PLA A", "PLA B"])
        self.assertEqual(off["machine_start_gcode"], "OFFICIAL START")
        self.assertEqual(off["change_filament_gcode"], "M620 S[next_extruder]A")
        self.assertEqual(off["filament_start_gcode"], ["; start base", "; start B"])
        self.assertEqual(off["post_process"], [])
        self.assertEqual(off["filename_format"], "{input_filename_base}.gcode")

    def test_unknown_preset_refused(self):
        with self.assertRaises(bp.UserError):
            bp.official_code_values(self.paths, "My custom printer", "proc", ["PLA A"])


class TestJob(Base):
    def test_bad_name(self):
        with self.assertRaises(bp.UserError):
            self.job(name="../evil")

    def test_bad_filament(self):
        with self.assertRaises(bp.UserError):
            self.job(objects=[{"name": "x", "parts": [{"stl": "base.stl", "filament": 0}]}])

    def test_missing_stl(self):
        with self.assertRaises(bp.UserError):
            self.job(objects=[{"name": "x", "parts": [{"stl": "nope.stl", "filament": 1}]}])

    def test_nozzle_names(self):
        self.assertEqual(bp.nozzle_map(self.job(), template_settings()), ["1", "2"])
        with self.assertRaises(bp.UserError):
            bp.nozzle_map(self.job(nozzles={"1": "middle"}), template_settings())


class TestBuild(Base):
    def build(self, job, settings=None):
        s = settings or template_settings()
        flat = bp.official_code_values(self.paths, s["printer_settings_id"], s["print_settings_id"],
                                       s["filament_settings_id"])
        report = {"warnings": []}
        data = bp.build_project(job, s, flat, report)
        return zipfile.ZipFile(io.BytesIO(data)), report

    def test_project_contents(self):
        z, report = self.build(self.job(settings={"wall_loops": "3"}))
        for name in z.namelist():
            if name.endswith((".model", ".rels", ".xml")) or name.endswith("model_settings.config"):
                ET.fromstring(z.read(name))
        s = json.loads(z.read(bp.SETTINGS_ENTRY))
        self.assertEqual(s["machine_start_gcode"], "OFFICIAL START")
        self.assertEqual(s["post_process"], [])
        self.assertEqual(s["filament_start_gcode"], ["; start base", "; start B"])
        self.assertEqual(s["filename_format"], "{input_filename_base}.gcode")
        self.assertEqual(s["filament_map"], ["1", "2"])
        self.assertEqual(s["filament_map_mode"], "Manual")
        self.assertEqual(s["wall_loops"], "3")
        self.assertIn("machine_start_gcode", report["code_keys_replaced"])
        ms = z.read("Metadata/model_settings.config").decode()
        self.assertIn('key="extruder" value="2"', ms)
        self.assertIn('key="extruder" value="1"', ms)

    def test_code_key_from_job_refused(self):
        with self.assertRaises(bp.UserError):
            self.build(self.job(settings={"machine_start_gcode": "G28"}))

    def test_wrong_type_refused(self):
        with self.assertRaises(bp.UserError):
            self.build(self.job(settings={"wall_loops": 3}))

    def test_filament_beyond_template(self):
        job = self.job(objects=[{"name": "x", "parts": [{"stl": "base.stl", "filament": 3}]}])
        with self.assertRaises(bp.UserError):
            self.build(job)

    def test_too_big_for_bed(self):
        write_box_stl(self.dir / "huge.stl", 0, 0, 0, 300, 20, 3)
        job = self.job(objects=[{"name": "x", "parts": [{"stl": "huge.stl", "filament": 1}]}])
        with self.assertRaises(bp.UserError):
            self.build(job)


class TestGcode(Base):
    def test_swaps_and_switches(self):
        g = self.dir / "p.gcode"
        g.write_text("M620 S1A\n; CHANGE_LAYER\nM620 S0A\nM620 S1A\nM620 S2A\n; CHANGE_LAYER\nM620 S2A\n")
        r = bp.parse_gcode(g, ["1", "1", "2"])
        self.assertEqual(r["layers"], 2)
        self.assertEqual(r["swaps_same_nozzle"], 2)   # 2->1 and 1->2, same nozzle
        self.assertEqual(r["nozzle_switches"], 1)     # 2->3
        self.assertEqual(r["layers_with_swaps"], 1)

    def test_advice(self):
        r = {"filaments": [{"filament": 1, "model_g": 10, "total_g": 15, "nozzle": "left"},
                           {"filament": 2, "model_g": 1, "total_g": 5, "nozzle": "left"}],
             "layers": 10, "layers_with_swaps": 8, "swaps_same_nozzle": 8, "model_g": 11, "waste_g": 9}
        adv = " ".join(bp.colour_advice(r, template_settings(enable_prime_tower="0"), ["1", "1"]))
        self.assertIn("8 of 10 layers", adv)
        self.assertIn("Prime tower is off", adv)
        self.assertIn("other nozzle", adv)


class TestCli(Base):
    def test_build_writes_file(self):
        tpl = self.dir / "tpl.3mf"
        write_3mf(tpl, template_settings())
        self.job(template="tpl.3mf", output="out/tag.3mf")
        with mock.patch.object(bp, "studio_paths", return_value=self.paths), \
                redirect_stdout(io.StringIO()):
            self.assertEqual(bp.main(["build", str(self.dir / "job.json")]), 0)
        self.assertTrue(zipfile.is_zipfile(self.dir / "out" / "tag.3mf"))

    def test_symlink_output_refused(self):
        tpl = self.dir / "tpl.3mf"
        write_3mf(tpl, template_settings())
        target = self.dir / "elsewhere.3mf"
        target.write_text("keep")
        (self.dir / "out.3mf").symlink_to(target)
        self.job(template="tpl.3mf", output="out.3mf")
        err = io.StringIO()
        with mock.patch.object(bp, "studio_paths", return_value=self.paths), \
                redirect_stderr(err), redirect_stdout(io.StringIO()):
            code = bp.main(["build", str(self.dir / "job.json")])
        self.assertEqual(code, 2)
        self.assertIn("symbolic link", err.getvalue())
        self.assertEqual(target.read_text(), "keep")

    def test_template_not_zip(self):
        bad = self.dir / "bad.3mf"
        bad.write_text("not a zip")
        with self.assertRaises(bp.UserError):
            bp.read_template(bad)


class TestSafety(Base):
    """Regression tests for the release review (hostile templates and projects)."""

    def write_template(self, settings, name="tpl.3mf"):
        return write_3mf(self.dir / name, settings)

    def run_main(self, argv):
        err = io.StringIO()
        with mock.patch.object(bp, "studio_paths", return_value=self.paths), \
                redirect_stderr(err), redirect_stdout(io.StringIO()):
            code = bp.main(argv)
        return code, err.getvalue()

    def test_official_template_passes_and_limits_filled(self):
        s = template_settings()
        self.assertEqual(bp.safety_problems(s, bp.official_presets(self.paths, s)), [])
        self.assertEqual(s["printable_height"], "250")

    def test_hostile_limits_and_temperatures_found(self):
        s = template_settings(printable_height="999", nozzle_temperature=["320", "220"],
                              textured_plate_temp=["110", "55"],
                              printable_area=["-50x-50", "400x-50", "400x400", "-50x400"])
        found = " ".join(bp.safety_problems(s, bp.official_presets(self.paths, s)))
        for key in ("printable_height", "printable_area", "nozzle_temperature", "textured_plate_temp"):
            self.assertIn(key, found)

    def test_build_refuses_hostile_template(self):
        self.write_template(template_settings(nozzle_temperature=["320", "220"]))
        self.job(template="tpl.3mf")
        code, err = self.run_main(["build", str(self.dir / "job.json")])
        self.assertEqual(code, 2)
        self.assertIn("printer limits, motion or temperatures", err)
        self.assertFalse((self.dir / "test-job.3mf").exists())

    def test_host_keys_cleared(self):
        self.write_template(template_settings(print_host="http://192.0.2.1", printhost_apikey="k"))
        self.job(template="tpl.3mf")
        self.assertEqual(self.run_main(["build", str(self.dir / "job.json")])[0], 0)
        with zipfile.ZipFile(self.dir / "test-job.3mf") as z:
            s = json.loads(z.read(bp.SETTINGS_ENTRY))
        self.assertEqual(s["print_host"], "")
        self.assertEqual(s["printhost_apikey"], "")

    def test_check_refuses_unofficial_gcode(self):
        hostile = self.write_template(template_settings(), "downloaded.3mf")
        paths = dict(self.paths, executable="/nonexistent/slicer")
        with mock.patch.object(bp, "_run_studio", side_effect=AssertionError("slicer started")):
            with self.assertRaises(bp.UserError) as ctx:
                bp.check_project(hostile, paths)
        self.assertIn("not the official one", str(ctx.exception))

    def test_check_slices_built_project(self):
        self.write_template(template_settings())
        self.job(template="tpl.3mf")
        self.assertEqual(self.run_main(["build", str(self.dir / "job.json")])[0], 0)
        paths = dict(self.paths, executable="/nonexistent/slicer")
        with mock.patch.object(bp, "_run_studio", side_effect=bp.UserError("slicer reached")):
            with self.assertRaises(bp.UserError) as ctx:
                bp.check_project(self.dir / "test-job.3mf", paths)
        self.assertEqual(str(ctx.exception), "slicer reached")

    def test_output_rules(self):
        self.write_template(template_settings())
        (self.dir / "victim.txt").write_text("keep")
        other = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(lambda: [f.unlink() for f in other.iterdir()] and None or other.rmdir())
        (self.dir / "linked").symlink_to(other, target_is_directory=True)
        for output, expected in (("../escape.3mf", "inside the job"), ("victim.txt", ".3mf"),
                                 ("tpl.3mf", "template"), ("linked/x.3mf", "inside the job")):
            self.job(template="tpl.3mf", output=output)
            code, err = self.run_main(["build", str(self.dir / "job.json")])
            self.assertEqual(code, 2, output)
            self.assertIn(expected, err, output)
        self.assertEqual((self.dir / "victim.txt").read_text(), "keep")
        self.assertEqual(list(other.iterdir()), [])

    def test_existing_output_needs_force(self):
        self.write_template(template_settings())
        self.job(template="tpl.3mf")
        job = str(self.dir / "job.json")
        self.assertEqual(self.run_main(["build", job])[0], 0)
        code, err = self.run_main(["build", job])
        self.assertEqual(code, 2)
        self.assertIn("--force", err)
        self.assertEqual(self.run_main(["build", job, "--force"])[0], 0)

    def test_too_tall_refused(self):
        write_box_stl(self.dir / "tall.stl", 0, 0, 0, 20, 20, 300)
        self.write_template(template_settings())
        self.job(template="tpl.3mf", objects=[{"name": "t", "parts": [{"stl": "tall.stl", "filament": 1}]}])
        code, err = self.run_main(["build", str(self.dir / "job.json")])
        self.assertEqual(code, 2)
        self.assertIn("tall", err)

    def test_nan_vertex_refused(self):
        with open(self.dir / "nan.stl", "wb") as fh:
            fh.write(b"\0" * 80 + struct.pack("<I", 1) + struct.pack("<12f", *([0.0] * 3 + [float("nan")] * 9)) + b"\0\0")
        with self.assertRaises(bp.UserError):
            bp.read_stl(self.dir / "nan.stl")

    def test_job_cannot_undo_safety(self):
        self.write_template(template_settings())
        self.job(template="tpl.3mf", settings={"nozzle_temperature": ["400", "400", "400", "400"]})
        code, err = self.run_main(["build", str(self.dir / "job.json")])
        self.assertEqual(code, 2)
        self.assertIn("nozzle_temperature", err)
        self.assertFalse((self.dir / "test-job.3mf").exists())

    def problems(self, **extra):
        s = template_settings(**extra)
        return " ".join(bp.safety_problems(s, bp.official_presets(self.paths, s)))

    def test_non_numeric_temperatures_refused(self):
        for bad in (["300abc", "220"], ["350,350", "220"], ["350 ;", "220"], {"a": 1}):
            self.assertIn("nozzle_temperature", self.problems(nozzle_temperature=bad), bad)
        self.assertIn("textured_plate_temp", self.problems(textured_plate_temp=["130x", "55"]))

    def test_motion_and_offset_keys_checked(self):
        self.assertIn("z_offset", self.problems(z_offset="-5"))
        self.assertEqual(self.problems(z_offset="0"), "")
        self.assertIn("machine_max_speed_z", self.problems(machine_max_speed_z=["99", "99"]))
        self.assertIn("filament_retraction_length", self.problems(filament_retraction_length=["50", "0.8"]))
        self.assertIn("filament_z_hop", self.problems(filament_z_hop=["40", "40"]))

    def test_nozzle_range_per_filament(self):
        # 280 C is fine for the PC in slot 2, not for the PLA in slot 1
        found = self.problems(filament_settings_id=["PLA A", "PC C"], nozzle_temperature=["280", "280"])
        self.assertIn("filament 1", found)
        self.assertNotIn("filament 2", found)

    def test_force_never_overwrites_template_through_a_link(self):
        tpl = self.write_template(template_settings())
        os.link(tpl, self.dir / "hard.3mf")
        before = tpl.read_bytes()
        self.job(template="tpl.3mf", output="hard.3mf")
        code, err = self.run_main(["build", str(self.dir / "job.json"), "--force"])
        self.assertEqual(code, 2)
        self.assertIn("template", err)
        self.assertEqual(tpl.read_bytes(), before)

    def test_check_passes_only_expected_entries(self):
        self.write_template(template_settings())
        self.job(template="tpl.3mf")
        self.assertEqual(self.run_main(["build", str(self.dir / "job.json")])[0], 0)
        out = self.dir / "test-job.3mf"
        with zipfile.ZipFile(out, "a") as z:
            z.writestr("Metadata/custom_gcode_per_layer.xml", "<custom_gcodes_per_layer/>")
        seen = {}

        def fake_run(exe, args, cwd):
            with zipfile.ZipFile(args[-1]) as z:
                seen["names"] = z.namelist()
            raise bp.UserError("slicer reached")
        with mock.patch.object(bp, "_run_studio", side_effect=fake_run):
            with self.assertRaises(bp.UserError):
                bp.check_project(out, dict(self.paths, executable="/nonexistent/slicer"))
        self.assertIn(bp.SETTINGS_ENTRY, seen["names"])
        self.assertNotIn("Metadata/custom_gcode_per_layer.xml", seen["names"])

    def test_bad_input_gives_error_not_traceback(self):
        (self.dir / "job.json").write_text('{"name": "x", "objects": [1]}')
        code, err = self.run_main(["build", str(self.dir / "job.json")])
        self.assertEqual(code, 2)
        (self.dir / "job.json").write_text("[[[[" * 100000)
        code, err = self.run_main(["build", str(self.dir / "job.json")])
        self.assertEqual(code, 2)
        self.assertIn("error", err)


class TestSlicerOrigin(Base):
    """Incident 2026-11-12: a double click opened a built project in QIDI Studio, which
    rewrote it for a Qidi Q1 Pro; Bambu Studio then crashed on Print."""

    QIDI = dict(printer_model="Q1 Pro", printer_settings_id="Q1 Pro 0.4 nozzle")

    def run_main(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(bp, "studio_paths", return_value=self.paths), \
                redirect_stderr(err), redirect_stdout(out):
            code = bp.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_template_from_other_slicer_refused(self):
        tpl = write_3mf(self.dir / "t.3mf", template_settings(**self.QIDI), "QIDIStudio-02.07.02.60")
        with self.assertRaises(bp.UserError) as ctx:
            bp.read_template(tpl)
        msg = str(ctx.exception)
        self.assertIn("another slicer", msg)
        self.assertIn("QIDIStudio-02.07.02.60", msg)
        self.assertIn("Save Project As", msg)

    def test_template_for_other_printer_refused(self):
        tpl = write_3mf(self.dir / "t.3mf", template_settings(printer_model="Bambu Lab P2S"))
        with self.assertRaises(bp.UserError) as ctx:
            bp.read_template(tpl)
        self.assertIn("Bambu Lab P2S", str(ctx.exception))
        self.assertIn("not the Bambu Lab X2D", str(ctx.exception))

    def test_template_without_application_refused(self):
        tpl = write_3mf(self.dir / "t.3mf", template_settings(), app=None)
        with self.assertRaises(bp.UserError) as ctx:
            bp.read_template(tpl)
        self.assertIn("not saved by Bambu Studio", str(ctx.exception))

    def test_templates_listing_reports_rewritten_file(self):
        good = write_3mf(self.dir / "good.3mf", template_settings())
        bad = write_3mf(self.dir / "bad.3mf", template_settings(**self.QIDI), "OrcaSlicer-2.3.0")
        code, out, _ = self.run_main(["templates", str(good), str(bad)])
        self.assertEqual(code, 0)
        rows = json.loads(out)
        self.assertNotIn("error", rows[0])
        self.assertIn("another slicer", rows[1]["error"])

    def test_build_refuses_rewritten_template(self):
        write_3mf(self.dir / "tpl.3mf", template_settings(**self.QIDI), "QIDIStudio-02.07.02.60")
        self.job(template="tpl.3mf")
        code, _, err = self.run_main(["build", str(self.dir / "job.json")])
        self.assertEqual(code, 2)
        self.assertIn("another slicer", err)
        self.assertFalse((self.dir / "test-job.3mf").exists())

    def built_then_rewritten(self, app, **settings):
        """Build a project, then rewrite it the way another slicer would."""
        write_3mf(self.dir / "tpl.3mf", template_settings())
        self.job(template="tpl.3mf")
        self.assertEqual(self.run_main(["build", str(self.dir / "job.json")])[0], 0)
        built = self.dir / "test-job.3mf"
        with zipfile.ZipFile(built) as z:
            entries = {n: z.read(n) for n in z.namelist()}
        self.assertIn(b"BambuStudio-", entries[bp.MODEL_ENTRY])
        s = json.loads(entries[bp.SETTINGS_ENTRY])
        s.update(settings)
        entries[bp.SETTINGS_ENTRY] = json.dumps(s).encode()
        entries[bp.MODEL_ENTRY] = entries[bp.MODEL_ENTRY].replace(
            b"BambuStudio-2.9.1.70", app.encode())
        with zipfile.ZipFile(built, "w") as z:
            for n, data in entries.items():
                z.writestr(n, data)
        return built

    def test_check_refuses_project_rewritten_by_another_slicer(self):
        built = self.built_then_rewritten("QIDIStudio-02.07.02.60", **self.QIDI)
        paths = dict(self.paths, executable="/nonexistent/slicer")
        with mock.patch.object(bp, "_run_studio", side_effect=AssertionError("slicer started")):
            with self.assertRaises(bp.UserError) as ctx:
                bp.check_project(built, paths)
        msg = str(ctx.exception)
        self.assertIn("another slicer (QIDIStudio-02.07.02.60, printer Q1 Pro)", msg)
        self.assertIn("--force", msg)
        self.assertIn("File, Open project", msg)

    def test_check_refuses_other_printer_model(self):
        built = self.built_then_rewritten("BambuStudio-2.9.1.70", printer_model="Bambu Lab H2D")
        paths = dict(self.paths, executable="/nonexistent/slicer")
        with mock.patch.object(bp, "_run_studio", side_effect=AssertionError("slicer started")):
            with self.assertRaises(bp.UserError) as ctx:
                bp.check_project(built, paths)
        self.assertIn("Bambu Lab H2D", str(ctx.exception))

    def test_other_slicers_found(self):
        apps = self.dir / "Applications"
        for name in ("BambuStudio.app", "QIDIStudio.app", "OrcaSlicer.app", "Safari.app",
                     "UltiMaker Cura.app", "Accurate Notes.app"):
            (apps / name).mkdir(parents=True)
        found = bp.other_slicers([apps, self.dir / "missing"])
        self.assertEqual(found, ["OrcaSlicer.app", "QIDIStudio.app", "UltiMaker Cura.app"])

    def test_studio_warns_about_other_slicers(self):
        with mock.patch.object(bp, "other_slicers", return_value=["QIDIStudio.app"]):
            code, out, _ = self.run_main(["studio"])
        self.assertEqual(code, 0)
        r = json.loads(out)
        self.assertEqual(r["other_slicers"], ["QIDIStudio.app"])
        self.assertIn("File, Open project", r["warning"])
        with mock.patch.object(bp, "other_slicers", return_value=[]):
            r = json.loads(self.run_main(["studio"])[1])
        self.assertNotIn("warning", r)


if __name__ == "__main__":
    unittest.main()
