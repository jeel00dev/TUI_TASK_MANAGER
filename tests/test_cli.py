import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class CLITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name)
        self.env = dict(os.environ, HOME=str(self.home), XDG_DATA_HOME=str(self.home / "data"), XDG_CONFIG_HOME=str(self.home / "config"), XDG_STATE_HOME=str(self.home / "state"))

    def tearDown(self):
        self.temp.cleanup()

    def command(self, *args, expected=0):
        result = subprocess.run([sys.executable, "-m", "taskcal", *args], cwd=ROOT, env=self.env, capture_output=True, text=True, timeout=8)
        self.assertEqual(expected, result.returncode, result.stderr)
        return result.stdout + result.stderr

    def test_cli_capture_schedule_filters_and_undo(self):
        self.assertIn("Added 1 to Inbox", self.command("add", "Redis", "--tags", "backend", "--notes", "persistence"))
        self.assertIn("Redis", self.command("list", "--view", "inbox"))
        self.command("move", "1", "tomorrow")
        self.assertNotIn("Redis", self.command("list", "--view", "inbox"))
        self.command("start", "1")
        self.assertIn("ongoing", self.command("show", "1"))
        self.command("done", "1")
        self.assertIn("Redis", self.command("list", "--view", "history"))
        self.command("delete", "1")
        self.assertEqual("", self.command("list", "--search", "persistence"))
        self.command("undo")
        self.assertIn("Redis", self.command("list", "--search", "#backend persistence"))

    def test_recurrence_cli_requires_occurrence_reference(self):
        self.command("add", "DSA", "--start", "2026-10-01 17:00", "--repeat", "daily")
        self.assertIn("occurrence reference", self.command("done", "1", expected=1))
        self.command("done", "1@2026-10-01")
        self.assertIn("pending", self.command("show", "1@2026-10-02"))

    def test_year_listing_includes_tasks_across_month_and_year_boundaries(self):
        self.command("add", "Annual project", "--start", "2027-12-01", "--end", "2029-02-01")
        self.command("add", "Leap day review", "--start", "2028-02-29 09:00")
        self.command("add", "Outside year", "--start", "2029-03-01")
        output = self.command("list", "--view", "year", "--date", "2028-06-01")
        self.assertIn("Annual project", output)
        self.assertIn("Leap day review", output)
        self.assertNotIn("Outside year", output)

    def test_invalid_schedule_and_nonterminal_fail_cleanly(self):
        self.assertIn("End must be after", self.command("add", "Invalid", "--start", "2026-10-04", "--end", "2026-10-02", expected=1))
        self.assertIn("interactive terminal", self.command(expected=1))

    def test_install_can_run_independent_of_checkout(self):
        output = self.command("install", "--no-autostart")
        self.assertIn("Installed", output)
        launcher = self.home / ".local/bin/task"
        result = subprocess.run([str(launcher), "add", "Installed capture"], cwd="/", env=self.env, capture_output=True, text=True, timeout=3)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("Installed capture", self.command("list", "--view", "inbox"))

    def test_install_does_not_replace_another_task_program(self):
        launcher = self.home / ".local/bin/task"
        launcher.parent.mkdir(parents=True)
        launcher.write_text("existing user's program")
        self.assertIn("left unchanged", self.command("install", "--no-autostart", expected=1))
        self.assertEqual("existing user's program", launcher.read_text())

    def test_user_only_database_permissions(self):
        self.command("add", "Private")
        database = self.home / "data/task-calendar/tasks.sqlite3"
        self.assertEqual(0o600, database.stat().st_mode & 0o777)

    def test_i3_without_dex_gets_idempotent_direct_startup(self):
        from taskcal.integration import install
        config = self.home / "config/i3/config"
        config.parent.mkdir(parents=True)
        config.write_text("# Existing personal config\nset $mod Mod4\n")
        with patch.dict(os.environ, self.env), patch("taskcal.integration.shutil.which", return_value=None):
            install()
            install()
        self.assertEqual(1, config.read_text().count('include "'))
        self.assertIn("set $mod Mod4", config.read_text())
        startup = self.home / "config/task-calendar/i3-startup.conf"
        self.assertIn("exec --no-startup-id", startup.read_text())
        self.assertIn("task reminders", startup.read_text())


if __name__ == "__main__":
    unittest.main()
