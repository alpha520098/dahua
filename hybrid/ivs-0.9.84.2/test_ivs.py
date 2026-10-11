"""Replay tests for the IVS candidate; no Home Assistant server is contacted.

Selected real methods are loaded through AST with small HA/network stand-ins.
These tests verify replay behavior, not live hardware or a full HA runtime.
"""
import ast
import asyncio
import importlib.util
import json
import logging
import hashlib
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parent
ORIGINAL = ROOT / "test_baseline"


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


ivs = module("hybrid_ivs", ROOT / "dahua" / "ivs.py")
utils = module("hybrid_utils", ROOT / "dahua" / "dahua_utils.py")


def selected_class(filename, classname, methods, namespace):
    tree = ast.parse((ROOT / "dahua" / filename).read_text())
    source = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == classname)
    selected = ast.ClassDef(
        name=classname, bases=[], keywords=[],
        body=[node for node in source.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in methods],
        decorator_list=[],
    )
    future = ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0)
    compiled = ast.fix_missing_locations(ast.Module(body=[future, selected], type_ignores=[]))
    exec(compile(compiled, filename, "exec"), namespace)
    return namespace[classname]


def flat_row(identity, index=0, channel=0, kind="CrossLineDetection", **extras):
    row = {"Id": identity, "Name": f"Gate {identity}", "Class": "Normal", "Enable": "true", "Type": kind}
    row.update(extras)
    prefix = f"table.VideoAnalyseRule[{channel}][{index}]"
    return {prefix + "." + key: value for key, value in row.items()}


def event(identity=9, code="CrossLineDetection", action="Start", **payload):
    data = {"Class": "Normal", "RuleID": identity, "Object": {"ObjectType": "Human"}}
    data.update(payload)
    return {"Code": code, "action": action, "index": "0", "data": data}


def tracker():
    return ivs.IVSRuleTracker(ivs.rules_from_flat({
        **flat_row(9), **flat_row(7, index=1),
        **flat_row(8, index=2, kind="CrossRegionDetection"),
    }, 0))


class DiscoveryTests(unittest.TestCase):
    def test_selects_only_requested_channel(self):
        table = {**flat_row(9), **flat_row(9, channel=1)}
        self.assertEqual([row["channel"] for row in ivs.rules_from_flat(table, 1)], [1])

    def test_id_zero_is_valid(self):
        self.assertEqual(ivs.rules_from_flat(flat_row(0), 0)[0]["id"], "0")

    def test_duplicate_ids_are_refused(self):
        self.assertEqual(ivs.rules_from_flat({**flat_row(9), **flat_row("9", index=1)}, 0), [])

    def test_duplicate_id_in_other_class_is_still_ambiguous(self):
        table = {**flat_row(9), **flat_row(9, index=1, Class="HumanTrait")}
        self.assertEqual(ivs.rules_from_flat(table, 0), [])

    def test_incomplete_and_nonnormal_rows_are_skipped(self):
        for extra in ({"Class": "HumanTrait"}, {"Id": None}, {"Id": []}, {"Id": True}, {"Type": None}, {"Enable": None}):
            with self.subTest(extra=extra):
                self.assertEqual(ivs.rules_from_flat(flat_row(9, **extra), 0), [])

    def test_disabled_rule_still_has_sensor(self):
        self.assertEqual(len(ivs.rules_from_flat(flat_row(9, Enable="false"), 0)), 1)

    def test_remote_bool_enable_and_channel_index(self):
        rows = [{"Id": 17, "Class": "Normal", "Enable": True, "Name": "Driveway", "Type": "CrossLineDetection"}]
        result = ivs.rules_from_remote(rows, 3)
        self.assertEqual((result[0]["id"], result[0]["channel"], result[0]["source"]), ("17", 3, "RemoteVideoAnalyseRule"))

    def test_bad_remote_table_is_refused(self):
        for value in ({}, [None], "bad"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                ivs.rules_from_remote(value, 0)


class EventTests(unittest.TestCase):
    def test_only_matching_rule_activates(self):
        state = tracker()
        self.assertEqual(state.apply(event(9)), ["9"])
        self.assertEqual(state.states, {"9": True, "7": False, "8": False})

    def test_lowercase_ruleid_variant(self):
        state = tracker()
        value = event(9)
        value["data"]["RuleId"] = value["data"].pop("RuleID")
        self.assertEqual(state.apply(value), ["9"])

    def test_unknown_id_never_matches_by_name(self):
        state = tracker()
        self.assertEqual(state.apply(event(77, Name="Gate 9")), [])
        self.assertFalse(any(state.states.values()))
        self.assertEqual(state.unmatched_count, 1)

    def test_wrong_type_cannot_activate_same_id(self):
        state = tracker()
        self.assertEqual(state.apply(event(9, code="CrossRegionDetection")), [])
        self.assertFalse(any(state.states.values()))

    def test_non_normal_events_do_not_activate(self):
        state = tracker()
        self.assertEqual(state.apply(event(9, Class="HumanTrait")), [])

    def test_one_stop_clears_concurrent_rules_for_its_code(self):
        state = tracker()
        state.apply(event(9, Direction="LeftToRight"))
        state.apply(event(7, Direction="RightToLeft"))
        state.apply(event(8, code="CrossRegionDetection"))
        self.assertEqual(state.apply(event(9, action="Stop")), ["7", "9"])
        self.assertTrue(state.states["8"])
        self.assertEqual(state.details["7"]["direction"], "RightToLeft")

    def test_stop_with_no_payload_clears_rules(self):
        state = tracker()
        state.apply(event(9))
        self.assertEqual(state.apply({"Code": "CrossLineDetection", "action": "Stop"}), ["9"])

    def test_malformed_payload_does_not_raise(self):
        state = tracker()
        for value in (None, [], "bad"):
            self.assertEqual(state.apply({"Code": "CrossLineDetection", "action": "Start", "data": value}), [])
        self.assertEqual(state.apply(event(9, Object=None)), ["9"])


class ReplayTests(unittest.TestCase):
    def setUp(self):
        namespace = {"parse_event": utils.parse_event, "time": __import__("time"), "_LOGGER": logging.getLogger("replay")}
        methods = {"on_receive", "translate_event_code", "get_event_key", "get_event_timestamp", "_handle_ivs_rule_event", "add_ivs_rule_listener"}
        klass = selected_class("__init__.py", "DahuaDataUpdateCoordinator", methods, namespace)
        self.subject = klass()
        self.subject._channel = 0
        self.subject._address = "test-nvr"
        self.subject._dahua_event_timestamp = {}
        self.subject._dahua_event_listeners = {}
        self.subject._ivs_tracker = tracker()
        self.subject._ivs_rule_listeners = {}
        self.subject.get_device_name = lambda: "Driveway"
        self.subject.get_address = lambda: "test-nvr"
        self.subject._handle_anpr_plate = Mock()
        self.subject.hass = SimpleNamespace(bus=SimpleNamespace(fire=Mock()))

    def send(self, value, channel=0):
        raw = "--myboundary\nContent-Type: text/plain\nContent-Length: 999\n\nCode={};action={};index={};data={}".format(
            value["Code"], value["action"], channel, json.dumps(value.get("data", {})))
        self.subject.on_receive(raw.encode(), channel)

    def test_raw_human_event_keeps_aggregate_and_rule_sensors(self):
        motion = Mock()
        cross = Mock()
        rule = Mock()
        self.subject._dahua_event_listeners = {"SmartMotionHuman-0": motion, "CrossLineDetection-0": cross}
        self.subject.add_ivs_rule_listener("9", rule)
        self.send(event(9))
        motion.assert_called_once()
        cross.assert_called_once()
        rule.assert_called_once()
        self.assertGreater(self.subject.get_event_timestamp("SmartMotionHuman"), 0)
        self.send(event(9, action="Stop"))
        self.assertEqual(self.subject.get_event_timestamp("SmartMotionHuman"), 0)
        self.assertFalse(self.subject._ivs_tracker.states["9"])

    def test_vehicle_translation_remains(self):
        vehicle = Mock()
        self.subject._dahua_event_listeners["SmartMotionVehicle-0"] = vehicle
        self.send(event(9, Object={"ObjectType": "Vehicle"}))
        vehicle.assert_called_once()

    def test_other_channel_is_not_dispatched(self):
        self.send(event(9), channel=1)
        self.assertFalse(any(self.subject._ivs_tracker.states.values()))
        self.subject.hass.bus.fire.assert_not_called()

    def test_ivsfailure_does_not_block_legacy_detection(self):
        self.subject._ivs_tracker = SimpleNamespace(unmatched_count=0, apply=Mock(side_effect=RuntimeError("broken optional feature")))
        motion = Mock()
        self.subject._dahua_event_listeners["SmartMotionHuman-0"] = motion
        with self.assertLogs("replay", level="ERROR"):
            self.send(event(9))
        motion.assert_called_once()

    def test_original_raw_event_bus_and_anpr_callback_are_retained(self):
        value = event(9, code="Traffic")
        self.send(value)
        self.subject._handle_anpr_plate.assert_called_once()
        args = self.subject.hass.bus.fire.call_args.args
        self.assertEqual(args[0], "dahua_event_received")
        self.assertEqual(args[1]["Code"], "Traffic")

    def test_new_rule_callback_is_removed_on_unload(self):
        listener = Mock()
        unsubscribe = self.subject.add_ivs_rule_listener("9", listener)
        unsubscribe()
        self.send(event(9))
        listener.assert_not_called()


class ReadOnlyRpcTests(unittest.IsolatedAsyncioTestCase):
    async def test_request_uses_authoritative_channel_and_no_write(self):
        calls = []
        class Session:
            async def __aenter__(self): return self
            async def __aexit__(self, *args): pass
        class Rpc:
            def __init__(self, *args): pass
            async def login(self): calls.append("login")
            async def request(self, method, params):
                calls.append((method, params))
                return {"params": {"table": [{"Id": 9}]}}
            async def logout(self): calls.append("logout")
        namespace = {"asyncio": asyncio, "DahuaRpc2Client": Rpc, "_IVS_DISCOVERY_LOCKS": {}, "TIMEOUT_SECONDS": 1, "_LOGGER": logging.getLogger("rpc")}
        klass = selected_class("client.py", "DahuaClient", {"async_get_remote_ivs_rules"}, namespace)
        client = klass()
        client._base = "http://test-nvr"
        client._username = "test"
        client._password = "test"
        client._address = "test-nvr"
        client._port = 80
        client._rtsp_port = 554
        client._new_rpc2_session = Session
        original_session = client._session = object()
        self.assertEqual(await client.async_get_remote_ivs_rules(3), [{"Id": 9}])
        self.assertEqual(calls, ["login", ("configManager.getConfig", {"name": "RemoteVideoAnalyseRule", "onlyLocal": False, "channel": 3}), "logout"])
        self.assertIs(client._session, original_session)


class StartupTests(unittest.IsolatedAsyncioTestCase):
    async def test_existing_entities_added_before_optional_discovery_completes(self):
        ready = asyncio.Event()
        added = []
        tasks = []
        class Coordinator:
            def get_event_list(self): return ["SmartMotionHuman", "FaceDetection", "Traffic"]
            def is_doorbell(self): return False
            async def async_discover_ivs_rules(self):
                await ready.wait()
                return [{"id": "9"}]
        def entity(*args): return args[-1] if isinstance(args[-1], str) else "ANPR"
        namespace = {
            "DOMAIN": "dahua", "DahuaDataUpdateCoordinator": Coordinator,
            "DahuaEventSensor": entity, "DahuaAuthorizedVehicleBinarySensor": entity,
            "DahuaIVSRuleBinarySensor": lambda *args: "IVS",
            "_LOGGER": logging.getLogger("startup"),
        }
        tree = ast.parse((ROOT / "dahua" / "binary_sensor.py").read_text())
        function = next(node for node in tree.body if isinstance(node, ast.AsyncFunctionDef) and node.name == "async_setup_entry")
        future = ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0)
        exec(compile(ast.fix_missing_locations(ast.Module(body=[future, function], type_ignores=[])), "binary_sensor.py", "exec"), namespace)
        def background(hass, target, name, eager_start):
            self.assertFalse(eager_start)
            task = asyncio.create_task(target)
            tasks.append(task)
            return task
        entry = SimpleNamespace(entry_id="camera", async_create_background_task=background)
        hass = SimpleNamespace(data={"dahua": {"camera": Coordinator()}})
        await namespace["async_setup_entry"](hass, entry, added.extend)
        self.assertEqual(added, ["SmartMotionHuman", "FaceDetection", "Traffic", "ANPR"])
        await asyncio.sleep(0)
        self.assertEqual(len(added), 4)
        ready.set()
        await asyncio.gather(*tasks)
        self.assertEqual(added[-1], "IVS")


class PreservationTests(unittest.TestCase):
    def test_legacy_detection_and_anpr_methods_are_identical(self):
        if not ORIGINAL.exists():
            self.skipTest("Original source unavailable for AST comparison")
        targets = {
            "__init__.py": {"translate_event_code", "get_event_timestamp", "add_dahua_event_listener", "_async_stream_events", "_handle_anpr_plate", "is_plate_authorized"},
            "client.py": {"stream_events"},
            "binary_sensor.py": {"DahuaEventSensor", "DahuaAuthorizedVehicleBinarySensor"},
        }
        for filename, names in targets.items():
            def lookup(path):
                return {node.name: ast.dump(node) for node in ast.walk(ast.parse(path.read_text()))
                        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name in names}
            self.assertEqual(lookup(ORIGINAL / filename), lookup(ROOT / "dahua" / filename), filename)

    def test_configuration_flow_is_byte_identical(self):
        if not ORIGINAL.exists():
            self.skipTest("Original source unavailable")
        self.assertEqual((ORIGINAL / "config_flow.py").read_bytes(), (ROOT / "dahua" / "config_flow.py").read_bytes())


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.config = self.base / "config"
        self.target = self.config / "custom_components" / "dahua"
        shutil.copytree(ORIGINAL, self.target)
        storage = self.config / ".storage"
        storage.mkdir()
        (storage / "core.config_entries").write_text("REGISTRIES MUST BE RETAINED")
        self.bin = self.base / "bin"
        self.bin.mkdir()
        (self.bin / "ha").write_text('#!/bin/bash\nprintf "%s\\n" "$*" >> "$DAHUA_CONFIG_DIR/ha_calls"\n')
        (self.bin / "ha").chmod(0o755)
        self.env = {**os.environ, "DAHUA_CONFIG_DIR": str(self.config), "PATH": str(self.bin) + os.pathsep + os.environ["PATH"]}

    def run_script(self, script, *args):
        return subprocess.run(["bash", str(script), *args], env=self.env, capture_output=True, text=True)

    def version(self):
        return json.loads((self.target / "manifest.json").read_text())["version"]

    def test_check_does_not_stop_core_or_change_files(self):
        result = self.run_script(ROOT / "install_ivs.sh", "--check")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.version(), "0.9.84.1")
        self.assertFalse((self.config / "ha_calls").exists())

    def test_apply_and_rollback_preserve_registries_and_original_code(self):
        result = self.run_script(ROOT / "install_ivs.sh", "--apply")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.version(), "0.9.84.2")
        backup = next((self.config / "dahua_backups").glob("ivs_candidate_*"))
        self.assertEqual((backup / "dahua_original" / "binary_sensor.py").read_bytes(), (ORIGINAL / "binary_sensor.py").read_bytes())
        self.assertEqual((backup / "storage_before" / "core.config_entries").read_text(), "REGISTRIES MUST BE RETAINED")
        result = self.run_script(backup / "rollback_ivs.sh")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.version(), "0.9.84.1")
        self.assertEqual((self.config / ".storage" / "core.config_entries").read_text(), "REGISTRIES MUST BE RETAINED")
        self.assertEqual((self.config / "ha_calls").read_text().splitlines(), ["core stop", "core start", "core stop", "core start"])

    def test_modified_hybrid_is_refused_before_stopping_core(self):
        with (self.target / "binary_sensor.py").open("a") as output:
            output.write("\n# unknown local change\n")
        result = self.run_script(ROOT / "install_ivs.sh", "--apply")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.config / "ha_calls").exists())

    def test_version_120_is_refused(self):
        manifest = self.target / "manifest.json"
        manifest.write_text(manifest.read_text().replace("0.9.84.1", "1.2.0"))
        result = self.run_script(ROOT / "install_ivs.sh", "--apply")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.version(), "1.2.0")
        self.assertFalse((self.config / "ha_calls").exists())

    def test_failed_file_swap_restores_original_and_starts_core(self):
        real_mv = shutil.which("mv")
        wrapper = self.bin / "mv"
        wrapper.write_text('#!/bin/bash\ncase "$1" in */stage) exit 1 ;; esac\nexec ' + real_mv + ' "$@"\n')
        wrapper.chmod(0o755)
        result = self.run_script(ROOT / "install_ivs.sh", "--apply")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.version(), "0.9.84.1")
        self.assertEqual((self.config / "ha_calls").read_text().splitlines(), ["core stop", "core start"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
