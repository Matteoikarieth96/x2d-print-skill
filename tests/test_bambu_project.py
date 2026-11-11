"""Unit tests that need no Bambu Studio: python3 -m unittest discover -s tests"""
import io
import json
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
                                "change_filament_gcode": "", "gcode_flavor": "marlin"},
        "machine/Printer tpl start.json": {"name": "Printer tpl start", "instantiation": "false",
                                           "machine_start_gcode": "OFFICIAL START"},
        "machine/Printer tpl change.json": {"name": "Printer tpl change", "instantiation": "false",
                                            "change_filament_gcode": "M620 S[next_extruder]A"},
        "machine/Printer 0.4.json": {"name": "Printer 0.4", "inherits": "common",
                                     "include": ["Printer tpl start", "Printer tpl change"]},
        "process/proc.json": {"name": "proc", "filename_format": "{input_filename_base}.gcode",
                              "wall_loops": "2"},
        "filament/fil base.json": {"name": "fil base", "filament_start_gcode": ["; start base"],
                                   "filament_end_gcode": ["; end"]},
        "filament/PLA A.json": {"name": "PLA A", "inherits": "fil base"},
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
        "filament_settings_id": ["PLA A", "PLA B"], "filament_colour": ["#FFFFFF", "#000000"],
        "filament_type": ["PLA", "PLA"], "nozzle_diameter": ["0.4", "0.4"],
        "filament_map": ["1", "1"], "printable_area": ["0x0", "256x0", "256x256", "0x256"],
        "wipe_tower_y": ["220"], "curr_bed_type": "Textured PEI Plate", "version": "2.9.1.70",
        "wall_loops": "2", "different_settings_to_system": ["", "", "", ""],
        # hostile values a downloaded template could carry
        "machine_start_gcode": "M104 S999 ; tampered", "post_process": ["/tmp/evil.sh"],
        "filament_start_gcode": ["tampered", "tampered"], "filename_format": "../../x",
    }
    s.update(extra)
    return s


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
        with zipfile.ZipFile(tpl, "w") as z:
            z.writestr(bp.SETTINGS_ENTRY, json.dumps(template_settings()))
        self.job(template="tpl.3mf", output="out/tag.3mf")
        with mock.patch.object(bp, "studio_paths", return_value=self.paths), \
                redirect_stdout(io.StringIO()):
            self.assertEqual(bp.main(["build", str(self.dir / "job.json")]), 0)
        self.assertTrue(zipfile.is_zipfile(self.dir / "out" / "tag.3mf"))

    def test_symlink_output_refused(self):
        tpl = self.dir / "tpl.3mf"
        with zipfile.ZipFile(tpl, "w") as z:
            z.writestr(bp.SETTINGS_ENTRY, json.dumps(template_settings()))
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


if __name__ == "__main__":
    unittest.main()
