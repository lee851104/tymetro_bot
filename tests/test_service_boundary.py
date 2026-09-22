"""First/last queries must preserve service dates, stops and boarding safety."""

import unittest
from unittest.mock import patch

from src.timetable_guard import ground_request, query_service_boundary, render_grounded
from tests.test_qwen_chat import make_service


AT = '2026-09-22T22:00:00+08:00'


class ServiceBoundaryTests(unittest.TestCase):
    def test_user_question_and_common_wording(self):
        for text in ('A12到A18末班車幾點', 'A12到A18的末班車幾點？',
                     '請問A12到A18最後一班普通車是幾點', 'A12到A18最晚幾點發車',
                     '第一航廈到高鐵桃園末班車幾點'):
            with self.subTest(text=text):
                output = ground_request(text, {}, AT)
                result = output['result']
                self.assertEqual((result['origin'], result['destination']), ('A12', 'A18'))
                self.assertEqual(result['query_mode'], 'last')
                self.assertEqual(result['next_trains'][0]['departure'], '2026-09-22T23:58:00+08:00')
                self.assertIn('末班車', output['answer'])
                self.assertNotIn('尚未提供', output['answer'])

    def test_airport_short_turn_is_not_a_train_to_hsr(self):
        airport = query_service_boundary('A12', 'A13', AT, 'last')
        hsr = query_service_boundary('A12', 'A18', AT, 'last')
        self.assertEqual(airport['next_trains'][0]['departure'], '2026-09-23T00:28:00+08:00')
        self.assertEqual(airport['next_trains'][0]['terminal'], 'A13')
        self.assertEqual(hsr['next_trains'][0]['departure'], '2026-09-22T23:58:00+08:00')
        self.assertEqual(hsr['next_trains'][0]['terminal'], 'A22')
        self.assertIn('隔日凌晨', render_grounded(airport))

    def test_explicit_date_names_service_day_even_with_after_midnight_clock(self):
        at = '2026-09-23T00:10:00+08:00'
        implied = ground_request('A12到A13末班車幾點', {}, at)['result']
        explicit = ground_request('9/23 A12到A13末班車幾點', {}, at)['result']
        today = ground_request('今天A12到A13末班車幾點', {}, at)['result']
        self.assertEqual(implied['service_date'], '2026-09-22')
        self.assertEqual(explicit['service_date'], '2026-09-23')
        self.assertEqual(explicit['next_trains'][0]['departure'], '2026-09-24T00:28:00+08:00')
        self.assertEqual(today, explicit)

    def test_last_is_retained_within_three_minutes_and_after_departure(self):
        for at, state in [('2026-09-22T23:55:00+08:00', 'imminent'),
                          ('2026-09-22T23:58:00+08:00', 'imminent'),
                          ('2026-09-23T00:10:00+08:00', 'passed')]:
            with self.subTest(at=at):
                result = query_service_boundary('A12', 'A18', at, 'last')
                self.assertEqual(result['status'], 'ok')
                self.assertEqual(result['departure_state'], state)
                self.assertEqual(result['next_trains'][0]['departure'], '2026-09-22T23:58:00+08:00')
                answer = render_grounded(result)
                self.assertIn('沒有更晚', answer)
                self.assertNotIn('改搭', answer)
                self.assertIn('不建議趕車' if state == 'imminent' else '時間已過', answer)

    def test_first_is_not_replaced_by_the_next_departure(self):
        for at in (AT, '2026-09-22T05:55:00+08:00'):
            with self.subTest(at=at):
                result = ground_request('A12到A18首班車幾點', {}, at)['result']
                self.assertEqual(result['query_mode'], 'first')
                self.assertEqual(result['next_trains'][0]['departure'], '2026-09-22T05:57:00+08:00')

    def test_type_filter_applies_before_selecting_last(self):
        ordinary = query_service_boundary('A1', 'A13', AT, 'last', '普通車')
        express = query_service_boundary('A1', 'A13', AT, 'last', '直達車')
        self.assertEqual(ordinary['next_trains'][0]['departure'][11:16], '23:38')
        self.assertEqual(express['next_trains'][0]['departure'][11:16], '23:00')
        empty = query_service_boundary('A9', 'A1', AT, 'last', '直達車')
        self.assertEqual(empty['status'], 'no_matching_departures')
        self.assertFalse(empty['next_trains'])
        self.assertIn('只限本次日期', render_grounded(empty))

    def test_unavailable_date_same_station_and_bad_rules_do_not_invent_last(self):
        result = query_service_boundary('A12', 'A18', '2030-01-01T22:00:00+08:00', 'last')
        self.assertEqual(result['status'], 'date_not_cached')
        self.assertIn('2030-01-01', render_grounded(result))
        same = query_service_boundary('A12', 'A12', AT, 'last')
        self.assertEqual(same['status'], 'same_station')
        raw = {'status': 'service_rules_unavailable', 'station_id': 'A12', 'destination_id': 'A18'}
        with patch('src.timetable_guard.query_direct_trains', return_value=raw):
            unknown = query_service_boundary('A12', 'A18', AT, 'last')
        self.assertEqual(unknown['status'], 'service_rules_unavailable')
        self.assertFalse(unknown['next_trains'])

    def test_boundary_followups_and_form_reset(self):
        first = ground_request('A12到A18', {}, AT)
        last = ground_request('那末班呢', {}, AT, first['context'])
        self.assertEqual(last['result']['query_mode'], 'last')
        kind = ground_request('那普通車呢', {}, AT, last['context'])
        self.assertEqual(kind['result']['query_mode'], 'last')
        self.assertEqual(kind['result']['requested_train_type'], '普通車')
        next_train = ground_request('那下一班呢', {}, AT, kind['context'])
        self.assertNotIn('query_mode', next_train['result'])
        selected = ground_request('unused', {'route': {'origin': 'A1', 'destination': 'A13'}}, AT, last['context'])
        self.assertNotIn('query_mode', selected['result'])
        self.assertEqual(selected['result']['origin'], 'A1')

    def test_pending_station_preserves_boundary_and_date(self):
        at = '2026-09-23T00:10:00+08:00'
        pending = ground_request('9/23 A1到機場末班車幾點', {}, at)
        self.assertEqual(pending['candidates'], ['A12', 'A13'])
        resolved = ground_request('A13', {}, at, pending['context'])
        self.assertEqual(resolved['result']['query_mode'], 'last')
        self.assertEqual(resolved['result']['service_date'], '2026-09-23')

    def test_mixed_unsupported_and_ambiguous_constraints_are_not_discarded(self):
        for text in ('A12到A18末班車幾點抵達', 'A12到A18末班車票價',
                     'A12到A18首班末班幾點', 'A12到A18不要普通車末班',
                     'A12到A18再到A22末班', '9/31 A12到A18末班',
                     'A12到A18十點末班', 'A12到A18末班普通車還是直達車'):
            with self.subTest(text=text):
                self.assertNotIn('result', ground_request(text, {}, AT))

    def test_qwen_runs_but_unsupported_model_claim_is_replaced(self):
        seen = []
        service = make_service(lambda messages, tools: seen.append(messages[-1]['content']) or '首末班尚未提供。')
        question = 'A12到A18末班車幾點'
        response = service.chat({'message': question, 'at': AT})
        self.assertEqual(seen, [question])
        self.assertEqual(response['answer_source'], 'timetable')
        self.assertEqual(response['confirmed_query']['query_mode'], 'last')
        self.assertEqual(response['confirmed_query']['service_date'], '2026-09-22')
        self.assertIn('23:58', response['answer']['zh'])
        self.assertNotIn('尚未提供', response['answer']['zh'])
        self.assertIn('尚未提供', response['raw_output']['first_output'])
        self.assertEqual(response['actual_call']['name'], 'get_service_boundary')


if __name__ == '__main__':
    unittest.main()
