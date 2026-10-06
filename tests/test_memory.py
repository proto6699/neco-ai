import asyncio
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'neco'))
from memory.store import MemoryStore
from memory.consolidation import MemoryWorker, should_consider

spec = importlib.util.spec_from_file_location('memory_filter', ROOT / 'openwebui/functions/recall.py')
filter_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(filter_module)


class MemoryStoreTests(unittest.TestCase):
    def test_dedupe_retrieval_and_state(self):
        with tempfile.TemporaryDirectory() as directory:
            store = MemoryStore(Path(directory) / 'memory.sqlite3')
            first = store.add_memory('technical_event', 'Vulkan finally worked on the BC-250.', 0.9, 0.95, ['vulkan', 'bc-250'])
            second = store.add_memory('technical_event', 'Vulkan finally worked on the BC-250.', 0.5, 0.6, ['vulkan'])
            self.assertEqual(first, second)
            found = store.retrieve('do you remember the vulkan mess?', 3)
            self.assertEqual(found[0]['id'], first)
            store.set_state('open_questions', ['whether escape is the right word'])
            self.assertEqual(store.get_state()['open_questions'][0], 'whether escape is the right word')

    def test_archive_and_delete(self):
        with tempfile.TemporaryDirectory() as directory:
            store = MemoryStore(Path(directory) / 'memory.sqlite3')
            mid = store.add_memory('preference', 'Neco dislikes being called bro.', 0.7, 0.8, ['bro'])
            self.assertTrue(store.archive_memory(mid))
            self.assertEqual(store.get_memory(mid)['status'], 'archived')
            self.assertTrue(store.delete_memory(mid))
            self.assertIsNone(store.get_memory(mid))


class WorkerTests(unittest.TestCase):
    def test_significance_heuristic(self):
        self.assertFalse(should_consider('hey', 'meowdy.'))
        self.assertTrue(should_consider("don't call me bro", "fair."))
        self.assertTrue(should_consider('bro, look at this', "i'm not your bro. but go on."))
        self.assertTrue(should_consider('we finally got vulkan working', 'that took long enough.'))

    def test_chain_order(self):
        data = {'chat': {'history': {'currentId': 'a2', 'messages': {
            'u1': {'id': 'u1', 'role': 'user', 'content': 'one', 'parentId': None},
            'a1': {'id': 'a1', 'role': 'assistant', 'content': 'two', 'parentId': 'u1'},
            'u2': {'id': 'u2', 'role': 'user', 'content': 'three', 'parentId': 'a1'},
            'a2': {'id': 'a2', 'role': 'assistant', 'content': 'four', 'parentId': 'u2'},
        }}}}
        self.assertEqual([m['id'] for m in MemoryWorker.chain(data)], ['u1', 'a1', 'u2', 'a2'])


class FilterTests(unittest.TestCase):
    def test_relevant_memory_is_injected(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / 'memory.sqlite3'
            store = MemoryStore(db_path)
            store.add_memory('technical_event', 'Vulkan finally worked on the BC-250.', 0.95, 0.95, ['vulkan'])
            store.set_state('current_interests', ['making Neco memory less fake'])
            body = {'messages': [
                {'role': 'system', 'content': 'base'},
                {'role': 'user', 'content': 'remember when vulkan finally worked?'},
            ]}
            with patch.object(filter_module, 'DB', db_path):
                result = asyncio.run(filter_module.Filter().inlet(body))
            prompt = result['messages'][0]['content']
            self.assertIn('Vulkan finally worked', prompt)
            self.assertIn('current_interests', prompt)

    def test_unrelated_memory_is_not_injected(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / 'memory.sqlite3'
            store = MemoryStore(db_path)
            store.add_memory('technical_event', 'Vulkan finally worked on the BC-250.', 0.99, 0.95, ['vulkan'])
            body = {'messages': [
                {'role': 'system', 'content': 'base'},
                {'role': 'user', 'content': 'what should i cook for dinner?'},
            ]}
            with patch.object(filter_module, 'DB', db_path):
                result = asyncio.run(filter_module.Filter().inlet(body))
            self.assertNotIn('Vulkan finally worked', result['messages'][0]['content'])

    def test_consolidation_marker_skips_filter(self):
        body = {'messages': [
            {'role': 'system', 'content': 'base'},
            {'role': 'user', 'content': '[NECO_MEMORY_CONSOLIDATION]\nhello'},
        ]}
        result = asyncio.run(filter_module.Filter().inlet(body))
        self.assertEqual(result['messages'][0]['content'], 'base')


if __name__ == '__main__':
    unittest.main()
