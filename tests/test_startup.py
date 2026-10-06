"""Exercise existing-install migration without touching the host's systemd."""

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ServiceMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        directory = Path(self.temporary.name)
        self.install = directory / 'den % with spaces'
        (self.install / 'scripts').mkdir(parents=True)
        (self.install / 'neco/.venv/bin').mkdir(parents=True)
        (self.install / '.runtime').mkdir()
        shutil.copy2(ROOT / 'scripts/start-neco.sh', self.install / 'scripts/start-neco.sh')
        (self.install / 'neco/heartbeat.py').write_text('# entry point\n')
        executable = self.install / 'neco/.venv/bin/python'
        executable.write_text('#!/bin/sh\nexit 0\n')
        executable.chmod(0o755)
        (self.install / '.runtime/neco_token').write_text('test-token')
        self.settings = self.install / '.env'
        self.settings.write_text('NECO_MODEL=existing-model\n')
        self.database = self.install / '.runtime/neco-memory.sqlite3'
        self.database.write_bytes(b'existing persistent record')
        self.config = directory / 'config'
        self.log = directory / 'commands'
        bin_path = directory / 'bin'
        bin_path.mkdir()
        systemctl = bin_path / 'systemctl'
        systemctl.write_text(
            '#!/bin/sh\n'
            'printf "%s\\n" "$*" >> "$NECO_TEST_LOG"\n'
            'case "$*" in\n'
            '  *--property=WorkingDirectory*) printf "%s\\n" "$NECO_TEST_WORKDIR" ;;\n'
            'esac\n'
        )
        systemctl.chmod(0o755)
        self.environment = dict(
            os.environ,
            PATH=str(bin_path) + os.pathsep + os.environ['PATH'],
            XDG_CONFIG_HOME=str(self.config),
            NECO_TEST_WORKDIR=str(self.install / 'neco'),
            NECO_TEST_LOG=str(self.log),
        )
        self.dropin = self.config / 'systemd/user/neco-ai.service.d/heartbeat.conf'

    def start(self, *arguments):
        return subprocess.run(
            ['bash', str(self.install / 'scripts/start-neco.sh'), *arguments],
            env=self.environment, capture_output=True, text=True,
        )

    def test_configure_only_preserves_data_and_service_state(self):
        for _ in range(2):
            result = self.start('--configure-only')
            self.assertEqual(result.returncode, 0, result.stderr)
        content = self.dropin.read_text()
        self.assertIn('ExecStart=\nExecStart="', content)
        self.assertIn('/den %% with spaces/neco/heartbeat.py"', content)
        self.assertNotIn('runtime.py', content)
        self.assertNotIn('restart', self.log.read_text())
        self.assertNotIn('enable', self.log.read_text())
        self.assertEqual(self.settings.read_text(), 'NECO_MODEL=existing-model\n')
        self.assertEqual(self.database.read_bytes(), b'existing persistent record')

    def test_normal_start_reloads_before_restarting(self):
        result = self.start()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.dropin.is_file())
        calls = self.log.read_text().splitlines()
        self.assertEqual(calls.count('--user daemon-reload'), 2)
        self.assertLess(
            max(i for i, call in enumerate(calls) if call == '--user daemon-reload'),
            calls.index('--user restart neco-ai.service'),
        )

    def test_other_installation_is_not_reconfigured(self):
        self.environment['NECO_TEST_WORKDIR'] = '/another/den/neco'
        result = self.start()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('belongs to another directory', result.stderr)
        self.assertFalse(self.dropin.exists())
        self.assertNotIn('restart', self.log.read_text())


if __name__ == '__main__':
    unittest.main()
