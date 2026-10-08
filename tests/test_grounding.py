import asyncio
import importlib.util
import os
import sqlite3
import sys
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'neco'))
import hostfacts

spec = importlib.util.spec_from_file_location('grounding_filter', ROOT / 'openwebui/functions/grounding.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

FACTS = {
    'host': {'distro': 'CachyOS', 'kernel': '6.17.1-cachyos', 'terminals': ['kitty'],
             'packages': {'manager': 'pacman', 'count': 1200, 'aur_helper': 'paru'},
             'utc_offset_minutes': 180, 'timezone': 'Asia/Riyadh'},
    'self': {'model': 'deepseek-flash', 'model_location': 'external API',
             'persona_mode': 'full', 'memory_enabled': True,
             'memories_recalled_per_reply': 6, 'idle_interval_minutes': [20, 45]},
}


class HostFactsTests(unittest.TestCase):
    def test_os_release_parsing(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'os-release'
            path.write_text('NAME="CachyOS Linux"\nPRETTY_NAME="CachyOS"\nID=cachyos\n')
            self.assertEqual(hostfacts.os_release(path)['ID'], 'cachyos')

    def test_describe_contains_host_and_self(self):
        now = datetime(2026, 10, 8, 23, 30, tzinfo=timezone.utc)
        text = hostfacts.describe(FACTS, memory_count=42, now=now)
        for expected in ('CachyOS', 'kitty', 'paru', 'deepseek-flash', 'external API', '42 active records'):
            self.assertIn(expected, text)
        self.assertIn('Friday 02:30', text)  # 23:30 UTC + 3h crosses midnight

    def test_missing_facts_are_left_out(self):
        text = hostfacts.describe({'host': {}, 'self': {'model': 'x', 'memory_enabled': False}})
        self.assertNotIn('distro:', text)
        self.assertIn('disabled', text)

    def test_provider_override(self):
        info = hostfacts.collect_self({'NECO_MODEL': 'm', 'NECO_MODEL_PROVIDER': 'DeepSeek API',
                                       'NECO_CONTEXT_TOKENS': '65536'})
        self.assertEqual(info['model_location'], 'DeepSeek API')
        self.assertEqual(info['context_window_tokens'], 65536)

    def test_memory_count(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / 'm.sqlite3'
            db = sqlite3.connect(db_path)
            db.execute('CREATE TABLE memories (id INTEGER, status TEXT)')
            db.executemany('INSERT INTO memories VALUES (?, ?)', [(1, 'active'), (2, 'archived'), (3, 'active')])
            db.commit(); db.close()
            self.assertEqual(hostfacts.memory_count(db_path), 2)
            self.assertIsNone(hostfacts.memory_count(Path(directory) / 'missing'))


class GroundingFilterTests(unittest.TestCase):
    def run_filter(self, path):
        with patch.object(module, 'GROUNDING', path):
            body = {'messages': [{'role': 'system', 'content': 'persona'},
                                 {'role': 'user', 'content': 'hey'}]}
            return asyncio.run(module.Filter().inlet(body))['messages']

    def test_always_injected_without_trigger_words(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'grounding.txt'
            path.write_text(hostfacts.describe(FACTS))
            messages = self.run_filter(path)
            self.assertIn('deepseek-flash', messages[0]['content'])
            self.assertEqual(len(messages), 2)

    def test_missing_file_changes_nothing(self):
        with tempfile.TemporaryDirectory() as directory:
            messages = self.run_filter(Path(directory) / 'missing')
            self.assertEqual(messages[0]['content'], 'persona')

    def test_old_file_is_flagged(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'grounding.txt'
            path.write_text('distro: CachyOS')
            old = time.time() - 3600
            os.utime(path, (old, old))
            self.assertIn('out of date', self.run_filter(path)[0]['content'])


if __name__ == '__main__':
    unittest.main()
