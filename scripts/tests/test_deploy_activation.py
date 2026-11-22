import importlib.util
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch


SCRIPT = Path(__file__).resolve().parents[1] / "deploy" / "activate-release.py"
SPEC = importlib.util.spec_from_file_location("activate_release", SCRIPT)
activation = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(activation)


class DeployActivationTests(unittest.TestCase):
    def setUp(self):
        scratch = TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.root = Path(scratch.name).resolve()
        self.state = self.root / "state"
        self.state.mkdir()
        (self.state / "backups").mkdir()
        (self.root / "instances").mkdir()
        self.current = self.state / "current"
        self.previous, self.candidate = (
            self.root / "releases" / (digit * 40 + "-1") for digit in "12"
        )
        for release in (self.previous, self.candidate):
            (release / "backend").mkdir(parents=True)
            for frontend in activation.SITES.values():
                (release / frontend).mkdir()
                (release / frontend / "index.html").write_text(frontend, encoding="utf-8")

        upstream = self.root / "upstream.conf"
        upstream.write_text("server 127.0.0.1:18081;\n", encoding="utf-8")
        self.units = "project1-v2-api@18081.service\nproject1-v2-scheduler.service\n"
        self.maintenance = Mock()
        self.systemctl = Mock()
        config = patch.multiple(
            activation, ROOT=self.root, UPSTREAM=upstream,
            run=Mock(side_effect=lambda *command, **kwargs: {
                "upstream": upstream.read_text(encoding="utf-8"), "units": self.units,
            }.get(command[-1])),
            systemctl=self.systemctl, maintenance=self.maintenance,
            smoke=Mock(side_effect=lambda url, host=None:
                       activation.SITES[host] if url.endswith("/") else '{"status":"UP","message":"hello"}'),
        )
        config.start()
        self.addCleanup(config.stop)

    def test_first_release_sets_static_and_instance_links(self):
        activation.activate(self.candidate, self.state)

        self.assertEqual(self.current.resolve(), self.candidate)
        self.assertEqual((self.root / "instances/18081").resolve(), self.candidate)
        self.assertEqual([call.args[1] for call in self.maintenance.call_args_list], ["backup", "migrate"])

    def test_backup_failure_restores_previous_without_migrating(self):
        activation.activate(self.previous, self.state)
        self.maintenance.reset_mock()
        self.maintenance.side_effect = RuntimeError("backup unavailable")

        with self.assertRaisesRegex(RuntimeError, "backup unavailable"):
            activation.activate(self.candidate, self.state)

        self.assertEqual(self.current.resolve(), self.previous)
        self.assertEqual((self.root / "instances/18081").resolve(), self.previous)
        self.assertEqual([call.args[1] for call in self.maintenance.call_args_list], ["backup"])

    def test_candidate_failure_checks_database_before_restoring(self):
        activation.activate(self.previous, self.state)
        self.maintenance.reset_mock()
        self.systemctl.reset_mock()

        def fail_candidate(action, unit):
            if action == "start":
                raise RuntimeError("candidate startup unavailable")

        def fail_validation(release, command, config, *args):
            if command == "validate":
                raise RuntimeError("incompatible schema")

        self.systemctl.side_effect = fail_candidate
        self.maintenance.side_effect = fail_validation
        with self.assertRaisesRegex(RuntimeError, "incompatible schema"):
            activation.activate(self.candidate, self.state)

        self.assertEqual(self.current.resolve(), self.previous)
        self.assertEqual([call.args[1] for call in self.maintenance.call_args_list],
                         ["backup", "migrate", "validate"])
        self.assertEqual(sum(call.args[0] == "start" for call in self.systemctl.call_args_list), 1)


if __name__ == "__main__":
    unittest.main()
