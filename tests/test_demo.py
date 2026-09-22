"""Acceptance checks for UI data, bilingual routing and timetable boundaries."""

import json
import threading
import unittest
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from scripts.serve_demo import Handler
from src.demo_chat import bootstrap, chat
from src.timetable import TAIPEI
from datetime import datetime

AT = '2026-09-22T10:05:00+08:00'


class DemoTests(unittest.TestCase):
    def ask(self, message='', **kwargs):
        return chat({'message': message, 'at': AT, **kwargs})

    def test_bilingual_queries_return_identical_facts(self):
        zh = self.ask('北車到二航')
        en = self.ask('Taipei Main Station to Terminal 2')
        self.assertEqual(zh['result'], en['result'])
        self.assertEqual(en['result']['destination'], 'A13')
        self.assertTrue(all(ord(c) < 128 for c in en['answer']['en']))

    def test_every_english_station_name_maps_to_the_same_code(self):
        for station in bootstrap()['stations']:
            with self.subTest(station=station['code']):
                result = self.ask(route={'origin': station['en'], 'destination': station['code']})
                self.assertEqual(result['result']['status'], 'same_station')

    def test_approved_aliases_without_reasking(self):
        result = self.ask('我在體大，要去一航')
        self.assertEqual(result['result']['origin'], 'A7')
        self.assertEqual(result['result']['destination'], 'A12')
        self.assertNotIn('state', result['result'])

    def test_ambiguous_airport_and_followup_preserve_origin(self):
        first = self.ask('Taipei Main Station to airport')
        self.assertEqual(first['candidates'], ['A12', 'A13'])
        self.assertNotIn('result', first)
        second = self.ask('Terminal 1', state=first['state'])
        self.assertEqual(second['result']['origin'], 'A1')
        self.assertEqual(second['result']['destination'], 'A12')

    def test_ambiguous_or_conflicting_station_is_not_guessed(self):
        for message in ('北車到棒球那站', '北車到新莊', 'A8 林口站到二航', 'Taipei Main Station to Xinzhuang'):
            with self.subTest(message=message):
                self.assertNotIn('result', self.ask(message))

    def test_unknown_station_is_not_a_substring_match(self):
        self.assertNotIn('result', self.ask('near Taipei Main Station to Terminal 2'))
        self.assertNotIn('result', self.ask('A14 到 A13'))

    def test_explicit_time_or_constraint_never_silently_ignored(self):
        for message in ('A1 to A13 tomorrow', 'A1 到 A13 18:00', 'A1 到 A13 明天',
                        'A1 to A13 express', 'A1到A13末班', 'A1 到 A13 下午五點'):
            with self.subTest(message=message):
                self.assertNotIn('result', self.ask(message))

    def test_exact_three_minutes_not_recommended(self):
        result = self.ask('A1 to A13')['result']
        self.assertEqual(result['next_trains'][0]['departure'][11:16], '10:15')
        self.assertEqual(result['imminent_departures'][0][11:16], '10:08')

    def test_imminent_last_train_and_uncached_day(self):
        last = self.ask('A1 to A13', at='2026-09-22T23:35:00+08:00')
        self.assertEqual(last['result']['status'], 'only_imminent_departures_remaining')
        self.assertEqual(last['result']['next_trains'], [])
        self.assertIn('no later trains', last['answer']['en'])
        missing = self.ask('A1 to A13', at='2027-01-01T10:00:00+08:00')
        self.assertEqual(missing['result']['status'], 'date_not_cached')
        self.assertEqual(missing['result']['next_trains'], [])

    def test_timezone_required_and_non_taiwan_offset_converted(self):
        self.assertNotIn('result', self.ask('A1 to A13', at='2026-09-22T10:05:00'))
        result = self.ask('A1 to A13', at='2026-09-22T02:05:00+00:00')['result']
        self.assertEqual(result['query_time'], AT)

    def test_demo_does_not_claim_model_inference(self):
        self.assertEqual(bootstrap()['engine'], 'timetable')
        self.assertFalse(bootstrap()['model_loaded'])

    def test_user_report_destination_before_origin(self):
        for question in ('我要去A9我在A1', '我要去 A9，我在 A1', '我想去A9,目前在A1',
                         '我要到A9，從A1出發', '我在A1我要去A9', '我在A1，要到A9',
                         "I want to go to A9, I'm at A1", "I am at A1, I want to go to A9"):
            with self.subTest(question=question):
                result = self.ask(question)['result']
                self.assertEqual((result['origin'], result['destination']), ('A1', 'A9'))
                self.assertEqual(result, self.ask('A1到A9')['result'])

    def test_common_route_question_wrappers(self):
        questions = ('我要從A1到A9', '請問A1到A9下一班幾點', '從A1到A9的下一班車',
                     'A1站到A9站', 'Ａ１到Ａ９', 'A1-A9', '請幫我查一下 A1 到 A9 的班次',
                     'a1 至 a9', '我想從A1到A9怎麼坐', '請問一下，從A1到A9的下一班車呢？',
                     'Could you tell me when is the next train from A1 to A9?',
                     'Station A1 to Station A9')
        for question in questions:
            with self.subTest(question=question):
                result = self.ask(question)['result']
                self.assertEqual((result['origin'], result['destination']), ('A1', 'A9'))

    def test_unsupported_fares_and_duration_are_not_bad_station_errors(self):
        for question, intent in (('A1到A9要多久', 'duration'), ('A1到A9多少錢', 'fare'),
                                 ('How long does it take from A1 to A9?', 'duration')):
            with self.subTest(question=question):
                result = self.ask(question)
                self.assertEqual(result['unsupported_intents'], [intent])
                self.assertNotIn('state', result)
                self.assertNotIn('result', result)
                self.assertIn('A1', result['answer']['zh'])
                self.assertIn('A9', result['answer']['zh'])

    def test_now_uses_actual_time_instead_of_old_form_value(self):
        before = datetime.now(TAIPEI)
        result = self.ask('A1到A9現在有車嗎')
        self.assertEqual(result['time_source'], 'current')
        used_time = datetime.fromisoformat(result['result']['query_time'])
        self.assertLess(abs((before-used_time).total_seconds()), 5)
        self.assertEqual((result['result']['origin'], result['result']['destination']), ('A1', 'A9'))

    def test_no_guessing_from_codes_with_extra_stops_or_negation(self):
        for question in ('A1到A9再到A12', '我要去A9不是A1', '不要去A9我在A1',
                         '我要去A9我在A8林口站', '我在A1附近要去A9', '我要去新莊我在A1'):
            with self.subTest(question=question):
                self.assertNotIn('result', self.ask(question))


class HTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f'http://127.0.0.1:{cls.server.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def test_http_contract_and_private_files_not_served(self):
        for path in ('/', '/app.js', '/style.css', '/favicon.svg', '/api/bootstrap'):
            with urlopen(self.url + path) as response:
                self.assertEqual(response.status, 200)
        body = json.dumps({'message': 'A1 to A13', 'at': AT}).encode()
        with urlopen(Request(self.url + '/api/chat', data=body, headers={'Content-Type': 'application/json'})) as response:
            self.assertEqual(json.load(response)['result']['destination'], 'A13')
        for path in ('/../README.md', '/data/training/train.jsonl'):
            with self.assertRaises(HTTPError) as error:
                urlopen(self.url + path)
            self.assertEqual(error.exception.code, 404)
        with self.assertRaises(HTTPError) as error:
            urlopen(Request(self.url + '/api/chat', data=body, headers={'Origin':'https://example.com'}))
        self.assertEqual(error.exception.code, 403)


if __name__ == '__main__':
    unittest.main()
