import json
import sys
import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from catzoom.jev import parse_answer
from catzoom.server import Workbench, defaults, make_server, score, validate_configs


class WorkbenchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.path = Path(self.tmp.name)
        rows = []
        for i in range(12):
            rows.append({'listing': {'id': str(i), 'transaction': 'rent', 'collected_at': f'2026-09-26T{i:02d}:00:00Z',
                                      'title': f'Apartment {i}', 'description': 'Cats welcome. Quiet office and balcony.',
                                      'features': [], 'price': {'value': 600}, 'location': {'city': 'București'}}, 'jev': None})
        (self.path / 'listings.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in rows))
        self.calls = []
        def fake_evaluator(listing, key, questions, model):
            self.calls.append((listing['id'], tuple(questions)))
            chosen = {'pets': 'allowed', 'workspace': 'unspecified', 'noise': 'quiet_claim', 'balcony': 'private'}
            signals = {}
            for name, q in questions.items():
                if q['type'] == 'choice':
                    value = chosen.get(name) or next(iter(q['criteria']))
                    signals[name] = {'value': value, 'candidate': value, 'probability': .9}
                else:
                    signals[name] = {'value': 'yes', 'probability': .9}
            return {'model': model, 'signals': signals, 'usage': {}}
        self.workbench = Workbench(self.path, 'fake-key', fake_evaluator)

    def tearDown(self):
        self.tmp.cleanup()

    def test_only_requested_page_and_cache_reused(self):
        ids = [x['id'] for x in self.workbench.snapshot()['listings'][:9]]
        result = self.workbench.classify(ids)
        self.assertEqual(result['classified'], 9)
        self.assertEqual(len(self.calls), 9)
        self.assertEqual(len(result['state']['listings']), 12)
        self.assertTrue(all(len(q) == 4 for _, q in self.calls))
        self.assertEqual(self.workbench.classify(ids)['classified'], 0)
        self.assertEqual(len(self.calls), 9)
        self.assertTrue((self.path / 'classifications.json').exists())
        self.workbench.configs[0]['weight'] = 0
        self.assertEqual(self.workbench.classify(ids)['classified'], 0)
        self.assertLess(self.workbench.snapshot()['listings'][0]['score'], 100)
        with self.assertRaises(ValueError):
            self.workbench.classify([str(i) for i in range(10)])
        with self.assertRaises(ValueError):
            self.workbench.classify(['rent:999'])

    def test_custom_classifier_and_removed_preset(self):
        custom = {'name': 'Solar exposure', 'kind': 'noul', 'question': 'Does the text explicitly claim ample direct sunlight?',
                  'preferred': 'yes', 'weight': 2}
        state = self.workbench.configure([defaults()[0], custom])
        self.assertEqual(len(state['classifiers']), 2)
        self.assertTrue(state['classifiers'][1]['id'].startswith('custom-'))
        self.workbench.classify(['rent:11'])
        self.assertEqual(set(self.calls[0][1]), {'pets', state['classifiers'][1]['id']})
        reloaded = Workbench(self.path, 'fake-key', self.workbench.evaluator)
        self.assertEqual(len(reloaded.configs), 2)
        self.assertEqual(reloaded.classify(['rent:11'])['classified'], 0)
        with self.assertRaises(ValueError):
            validate_configs([{**custom, 'question': 'x' * 301}])

    def test_question_change_invalidates_cache_but_weight_does_not(self):
        choice = {'name': 'Kitchen style', 'kind': 'choice', 'question': 'Which kitchen arrangement is explicitly stated?', 'weight': 2,
                  'options': [{'key': 'separate', 'description': 'Separate kitchen', 'value': 1},
                              {'key': 'open', 'description': 'Open-plan kitchen', 'value': 0},
                              {'key': 'unknown', 'description': 'Not stated', 'value': 0}]}
        config = self.workbench.configure([choice])['classifiers'][0]
        self.workbench.classify(['rent:11'])
        self.assertEqual(len(self.calls), 1)
        config['weight'] = 4
        self.workbench.configure([config])
        self.assertEqual(self.workbench.classify(['rent:11'])['classified'], 0)
        config['question'] = 'Is the kitchen separate, open plan, or unspecified in the listing?'
        self.workbench.configure([config])
        self.assertEqual(self.workbench.classify(['rent:11'])['classified'], 1)
        self.assertEqual(len(self.calls), 2)

    def test_newest_pool_is_bounded_to_100(self):
        rows = []
        for i in range(105):
            rows.append({'listing': {'id': str(i), 'transaction': 'rent', 'collected_at': f'2026-09-26T{i:03d}:00:00Z',
                                      'title': f'Apartment {i}', 'description': ''}, 'jev': None})
        (self.path / 'listings.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in rows))
        bounded = Workbench(self.path, 'fake-key', self.workbench.evaluator)
        self.assertEqual(len(bounded.records), 100)
        self.assertIn('rent:104', bounded.records)
        self.assertNotIn('rent:0', bounded.records)

    def test_ordered_score_question_and_weighted_result(self):
        config = validate_configs([{'name': 'Sunlight', 'kind': 'score', 'question': 'How strongly does the text support natural light?',
                                    'weight': 2, 'levels': ['No evidence', 'Some evidence', 'Explicit bright sunlight']}])[0]
        answer = parse_answer({'answers': {config['id']: {'type': 'score', 'score': 1.5, 'confidence': .9}}},
                              {config['id']: {'type': 'score', 'criteria': config['levels']}})['signals'][config['id']]
        self.assertEqual(score({}, [config], {config['id']: answer}), 75)
        with self.assertRaises(ValueError):
            validate_configs([{**config, 'levels': ['Only one']}], [config])

    def test_http_origin_and_no_key_leak(self):
        server = make_server(self.path, 0, 'fake-key', self.workbench.evaluator)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f'http://127.0.0.1:{server.server_port}'
        try:
            with urlopen(base + '/api/state') as response:
                body = response.read().decode()
            self.assertNotIn('fake-key', body)
            self.assertEqual(len(json.loads(body)['listings']), 12)
            with urlopen(base + '/app.js') as response:
                self.assertIn(b'classifyPage', response.read())
            data = json.dumps({'classifiers': []}).encode()
            request = Request(base + '/api/classifiers', data=data, headers={'Content-Type': 'application/json',
                              'X-Catzoom-Request': '1', 'Origin': 'https://bad.example'}, method='POST')
            with self.assertRaises(HTTPError) as caught:
                urlopen(request)
            self.assertEqual(caught.exception.code, 403)
            request = Request(base + '/api/classifiers', data=data, headers={'Content-Type': 'application/json',
                              'X-Catzoom-Request': '1', 'Origin': base}, method='POST')
            with urlopen(request) as response:
                self.assertEqual(json.load(response)['classifiers'], [])
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == '__main__':
    unittest.main()
