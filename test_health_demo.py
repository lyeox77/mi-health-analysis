import copy
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from zipfile import ZipFile
from health_demo import aggregate, demo_payload, write_outputs

A, B = date(2026, 10, 1), date(2026, 10, 14)


class HealthDemoTests(unittest.TestCase):
    def test_missing_and_duplicates(self):
        r = aggregate(demo_payload(), A, B)
        self.assertEqual(r['quality']['duplicates_removed'], 1)
        self.assertIsNone(r['daily'][6]['sleep_minutes'])
        self.assertIsNone(r['daily'][9]['steps'])
        self.assertEqual(r['summary']['sleep_minutes']['days'], 13)
        self.assertIsNone(r['daily'][4]['sleep_score'])

    def test_wake_date_and_timezone(self):
        p = demo_payload()
        p['records']['sleep'] = [{'start_at': '2026-09-30T16:30:00Z',
            'end_at': '2026-09-30T23:30:00Z', 'time_asleep_minutes': 400}]
        r = aggregate(p, A, A)
        self.assertEqual(r['daily'][0]['sleep_minutes'], 400)
        self.assertEqual(r['daily'][0]['sleep_start'], '2026-10-01T00:30:00+08:00')

    def test_conflicting_activity_and_main_sleep(self):
        p = demo_payload()
        p['records']['daily_activity'].append({**p['records']['daily_activity'][0], 'steps': 99})
        s = copy.deepcopy(p['records']['sleep'][0])
        s['time_asleep_minutes'] = 100
        p['records']['sleep'].append(s)
        r = aggregate(p, A, A)
        self.assertIsNone(r['daily'][0]['steps'])
        self.assertEqual(r['quality']['activity_conflicts'], 1)
        self.assertEqual(r['quality']['extra_main_sleep_candidates'], 1)
        self.assertGreater(r['daily'][0]['sleep_minutes'], 100)

    def test_invalid_rows_not_zero_filled(self):
        p = {'schema_version': '1.0', 'records': {'sleep': [
            {'start_at': '2026-10-01T00:00:00', 'end_at': '2026-10-01T08:00:00',
             'time_asleep_minutes': 400}], 'heart_rate': [{'timestamp': 'bad', 'bpm': 0}]}}
        r = aggregate(p, A, A)
        self.assertEqual(r['quality']['invalid_records'], 2)
        self.assertIsNone(r['daily'][0]['sleep_minutes'])
        self.assertIsNone(r['daily'][0]['heart_rate_sample_mean_bpm'])

    def test_single_account(self):
        p = demo_payload()
        p['records']['heart_rate'][0]['user_id'] = 'OTHER'
        with self.assertRaises(ValueError):
            aggregate(p, A, B)

    def test_allowlist_and_archive(self):
        p = demo_payload()
        p['records']['sleep'][0].update(passToken='SECRET_TOKEN', address='PRIVATE_ADDRESS')
        p['records']['workout_gps'] = [{'latitude': 1, 'longitude': 2}]
        r = aggregate(p, A, B)
        with tempfile.TemporaryDirectory() as d:
            out = Path(d)/'out'
            write_outputs(r, out)
            with ZipFile(out/'submit_to_chatgpt.zip') as z:
                self.assertEqual(set(z.namelist()), {'analysis_packet.json', 'daily.csv', 'analysis_request.txt'})
                text = '\n'.join(z.read(n).decode('utf-8-sig') for n in z.namelist())
                for secret in ('SECRET_TOKEN', 'PRIVATE_ADDRESS', 'SYNTHETIC_ACCOUNT', 'latitude', 'device_id'):
                    self.assertNotIn(secret, text)
                self.assertTrue(json.loads(z.read('analysis_packet.json'))['synthetic'])
            with self.assertRaises(ValueError):
                write_outputs(r, out)


if __name__ == '__main__':
    unittest.main()
