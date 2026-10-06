import asyncio
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'neco'))
from machine import _battery
spec = importlib.util.spec_from_file_location('vitals_filter', ROOT / 'openwebui/functions/senses.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class VitalsTests(unittest.TestCase):
    def test_battery_reading(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            device = root / 'BAT0'; device.mkdir()
            for name, value in [('type', 'Battery'), ('capacity', '59'), ('status', 'Discharging')]:
                (device / name).write_text(value)
            result = _battery(root)['batteries'][0]
            self.assertEqual(result['percent'], 59)
            self.assertEqual(result['status'], 'Discharging')
            self.assertIn('59%', module._format_vitals({'battery': _battery(root)}))

    def test_missing_and_invalid_battery(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertIsNone(_battery(root))
            device = root / 'BAT0'; device.mkdir()
            (device / 'type').write_text('Battery')
            (device / 'capacity').write_text('999')
            self.assertIsNone(_battery(root)['batteries'][0]['percent'])
            (device / 'capacity').write_text('unknown')
            self.assertIsNone(_battery(root)['batteries'][0]['percent'])

    def context(self, path):
        with patch.object(module, 'SNAPSHOT', path):
            body = {'messages': [{'role': 'user', 'content': 'battery and RAM usage?'}]}
            return asyncio.run(module.Filter().inlet(body))['messages'][0]['content']

    def test_missing_snapshot_is_explicit(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertIn('unavailable', self.context(Path(directory) / 'missing'))

    def test_stale_snapshot_not_live(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'snapshot'
            path.write_text(json.dumps({'sampled_at': '2000-01-01T00:00:00+00:00', 'cpu_temp_c': 99}))
            text = self.context(path)
            self.assertIn('stale', text)
            self.assertNotIn('99', text)

    def test_fresh_snapshot_reports_host_values(self):
        from datetime import datetime, timezone
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'snapshot'
            path.write_text(json.dumps({'sampled_at': datetime.now(timezone.utc).isoformat(), 'cpu_temp_c': 53,
                'memory': {'used_gib': 6.02, 'total_gib': 7.45, 'used_percent': 80.9}}))
            text = self.context(path)
            self.assertIn('53', text)
            self.assertIn('6.02', text)
            self.assertIn('host machine', text)

if __name__ == '__main__': unittest.main()
