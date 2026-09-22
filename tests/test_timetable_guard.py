import json
import unittest
from unittest.mock import patch

from src.timetable import DEFAULT_CACHE
from src.timetable_guard import ground_request, query_trains, render_grounded

AT = '2026-09-22T10:00:00+08:00'


class TimetableGuardTests(unittest.TestCase):
    def test_exact_report_and_new_example(self):
        for question in ('A1到A13我要搭普通車是幾點', '台北車站到第二航廈，下一班普通車幾點？'):
            with self.subTest(question=question):
                output = ground_request(question, {}, AT)
                self.assertEqual([t['departure'][11:16] for t in output['result']['next_trains']], ['10:08', '10:23'])
                self.assertEqual(output['result']['requested_train_type'], '普通車')
                self.assertIn('都會停靠 A13', output['answer'])

    def test_every_station_has_local_service_in_both_directions_at_daytime(self):
        stations = json.loads(DEFAULT_CACHE.read_text(encoding='utf-8'))['stations']
        for station in stations:
            if station == 'A1':
                continue
            for origin, destination in (('A1', station), (station, 'A1')):
                with self.subTest(origin=origin, destination=destination):
                    result = query_trains(origin, destination, AT, '普通車')
                    self.assertEqual(result['status'], 'ok')
                    self.assertTrue(all('普通車' in r['train_type'] for r in result['next_trains']))

    def test_filter_scans_past_first_two_and_recounts_before_limit(self):
        base = {'status':'ok','next_trains':[], 'query_time':AT, 'origin':'A1','destination':'A13'}
        rows = [{'service_code':code,'departure':f'2026-09-22T{hm}:00+08:00',
                 'train_type':kind,'terminal_station_id':'A22'} for code, hm, kind in
                [('des01','10:04','直達車'),('des02','10:05','尖峰增停直達車'),
                 ('des03','10:08','普通車'),('des03','10:23','普通車'),('des03','10:38','普通車')]]
        with patch('src.timetable_guard.get_next_trains', return_value=base), patch(
                'src.timetable_guard.query_direct_trains', return_value={'status':'ok','next_departures':rows}) as query:
            result = query_trains('A1','A13',AT,'普通車')
            self.assertGreater(query.call_args.kwargs['limit'], 2)
            self.assertEqual(result['remaining_departures'], 3)
            self.assertEqual([r['departure'][11:16] for r in result['next_trains']], ['10:08','10:23'])

    def test_three_minute_rule_and_filter_do_not_mix_train_types(self):
        result = query_trains('A1','A13','2026-09-22T10:05:00+08:00','普通車')
        self.assertEqual(result['imminent_departures'], ['2026-09-22T10:08:00+08:00'])
        self.assertEqual([r['departure'][11:16] for r in result['next_trains']], ['10:23','10:38'])
        result = query_trains('A1','A13',AT,'普通車')
        self.assertEqual(result['imminent_departures'], [])  # 10:00 express is irrelevant.

    def test_no_express_does_not_mean_no_local(self):
        result = query_trains('A9','A1',AT,'直達車')
        self.assertEqual(result['status'], 'no_direct_departures_remaining')
        self.assertEqual(result['remaining_departures'], 0)
        self.assertIn('不代表這個站沒有普通車服務', render_grounded(result))
        self.assertEqual(query_trains('A9','A1',AT,'普通車')['status'], 'ok')

    def test_after_last_local_and_missing_day_do_not_invent_trains(self):
        result = query_trains('A1','A13','2026-09-23T01:00:00+08:00','普通車')
        self.assertEqual(result['status'], 'no_direct_departures_remaining')
        self.assertIn('只限本次日期', render_grounded(result))
        result = query_trains('A1','A13','2030-01-01T10:00:00+08:00','普通車')
        self.assertEqual(result['status'], 'date_not_cached')
        self.assertFalse(result['next_trains'])

    def test_time_phrase_and_type_followup_keep_verified_route_and_time(self):
        first = ground_request('我9/22早上10點要從A1到A12可以搭哪班車', {}, '2026-09-22T20:44:00+08:00')
        self.assertEqual(first['result']['query_time'], AT)
        second = ground_request('那普通車呢', {}, '2026-09-22T20:44:00+08:00', first['context'])
        self.assertEqual(second['result']['query_time'], AT)
        self.assertEqual(second['result']['destination'], 'A12')
        third = ground_request('有普通車', {}, '2026-09-22T20:44:00+08:00', second['context'])
        self.assertEqual(third['result'], second['result'])

    def test_ambiguity_negation_and_unrecognized_time_do_not_get_silent_defaults(self):
        for text in ('A1到A13普通車還是直達車', '不是A1到A13普通車',
                     'A1台北車站到A13第一航廈普通車', '明天早上A1到A13普通車',
                     'A1到A13十點普通車', 'A1到A13我9/31搭普通車'):
            with self.subTest(text=text):
                self.assertNotIn('result', ground_request(text, {}, AT))
        result = ground_request('A1到機場普通車', {}, AT)
        self.assertEqual(result['candidates'], ['A12','A13'])
        resolved = ground_request('A13', {}, AT, result['context'])
        self.assertEqual(resolved['result']['destination'], 'A13')
        self.assertEqual(resolved['result']['requested_train_type'], '普通車')


if __name__ == '__main__':
    unittest.main()
