"""HTTP integration tests against the isolated *_test database only."""
from __future__ import annotations

import http.client
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
import uuid

from psycopg.conninfo import conninfo_to_dict, make_conninfo

from auction_lab.db import connect, disposable_guard, dsn_for, install
from auction_lab.fixtures import create_auction
from auction_lab.web import create_server
from auction_lab.web_service import AuctionWebService


class WebIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.owner = dsn_for('test')
        disposable_guard(cls.owner, 'test')
        install(cls.owner, reset=True, purpose='test')
        source = os.getenv('APP_DATABASE_URL')
        cls.app = make_conninfo(source, dbname=conninfo_to_dict(cls.owner)['dbname']) if source else cls.owner
        cls.temp = tempfile.TemporaryDirectory()
        root = Path(cls.temp.name)
        (root / 'index.html').write_text('<!doctype html><title>HTTP test</title>', encoding='utf-8')
        cls.service = AuctionWebService(app_dsn=cls.app, test_dsn=cls.owner, web_root=root)
        cls.service.health()
        cls.server = create_server(port=0, service=cls.service)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)
        cls.temp.cleanup()

    def setUp(self):
        self.auction = create_auction(self.owner)

    def request(self, method, path, body=None, headers=None, raw=False):
        connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=30)
        supplied = dict(headers or {})
        if body is not None and not raw:
            body = json.dumps(body).encode('utf-8')
            supplied.setdefault('Content-Type', 'application/json')
        connection.request(method, path, body=body, headers=supplied)
        response = connection.getresponse()
        content = response.read()
        status, returned_headers = response.status, dict(response.getheaders())
        connection.close()
        if 'application/json' in returned_headers.get('Content-Type', '') and content:
            content = json.loads(content)
        return status, content, returned_headers

    def post(self, path, body, **kwargs):
        return self.request('POST', path, body, headers={'X-Auction-Token': self.service.csrf_token, **kwargs})

    def bid_payload(self, **changes):
        return {'bidder_id': 2, 'amount': '100', 'request_id': str(uuid.uuid4()), 'strategy': 'row_lock', **changes}

    def test_01_health_and_static_headers(self):
        status, response, _ = self.request('GET', '/api/health')
        self.assertEqual(status, 200)
        self.assertEqual(response['data']['application'], 'auction19')
        status, content, headers = self.request('GET', '/')
        self.assertEqual(status, 200)
        self.assertIn(b'HTTP test', content)
        self.assertEqual(headers['X-Content-Type-Options'], 'nosniff')
        self.assertIn("frame-ancestors 'none'", headers['Content-Security-Policy'])
        self.assertEqual(self.request('HEAD', '/')[0], 200)

    def test_02_bootstrap_has_actual_summary_and_token(self):
        status, body, _ = self.request('GET', '/api/bootstrap')
        self.assertEqual(status, 200)
        data = body['data']
        self.assertEqual(data['csrf_token'], self.service.csrf_token)
        self.assertTrue(data['users'])
        with connect(self.owner) as conn:
            count = conn.execute('SELECT count(*) n FROM auction.auctions').fetchone()['n']
        self.assertEqual(data['summary']['total_auctions'], count)

    def test_03_list_filters_search_and_unknown_sort(self):
        status, body, _ = self.request('GET', '/api/auctions?state=LIVE&kind=ARTWORK&sort=price')
        self.assertEqual(status, 200)
        self.assertTrue(body['data']['items'])
        self.assertTrue(all(x['state'] == 'LIVE' and x['kind'] == 'ARTWORK' for x in body['data']['items']))
        status, body, _ = self.request('GET', '/api/auctions?search=%27%3B%20DROP%20TABLE%20auction.users%3B--')
        self.assertEqual(status, 200)
        self.assertEqual(body['data']['items'], [])
        self.assertEqual(self.request('GET', '/api/auctions?sort=id;DROP')[0], 400)

    def test_04_detail_counts_do_not_multiply(self):
        self.post(f'/api/auctions/{self.auction}/bids', self.bid_payload())
        self.post(f'/api/auctions/{self.auction}/bids', self.bid_payload(bidder_id=3, amount='110'))
        status, body, _ = self.request('GET', f'/api/auctions/{self.auction}')
        self.assertEqual(status, 200)
        data = body['data']
        self.assertEqual(data['auction']['bid_count'], 2)
        self.assertEqual(data['auction']['participant_count'], 20)
        self.assertEqual(len(data['bids']), 2)
        self.assertEqual(data['bids'][0]['amount'], '110.00')
        self.assertEqual(data['auction']['current_price'], '110.00')
        self.assertEqual(data['auction']['minimum_bid'], '120.00')

    def test_05_missing_and_invalid_ids(self):
        self.assertEqual(self.request('GET', '/api/auctions/9223372036854775807')[0], 404)
        self.assertEqual(self.request('GET', '/api/auctions/0')[0], 400)
        self.assertEqual(self.request('GET', '/api/auctions/999999999999999999999999')[0], 400)

    def test_06_bid_replay_and_payload_conflict_use_existing_function(self):
        payload = self.bid_payload()
        status, first, _ = self.post(f'/api/auctions/{self.auction}/bids', payload)
        self.assertEqual((status, first['data']['status']), (200, 'ACCEPTED'))
        _, second, _ = self.post(f'/api/auctions/{self.auction}/bids', payload)
        self.assertEqual(second['data']['status'], 'REPLAYED')
        self.assertEqual(first['data']['bid_id'], second['data']['bid_id'])
        _, conflict, _ = self.post(f'/api/auctions/{self.auction}/bids', {**payload, 'amount': '110'})
        self.assertEqual(conflict['data']['code'], 'IDEMPOTENCY_CONFLICT')

    def test_07_business_rejection_is_not_http_server_failure(self):
        status, body, _ = self.post(f'/api/auctions/{self.auction}/bids', self.bid_payload(amount='99'))
        self.assertEqual(status, 200)
        self.assertTrue(body['ok'])
        self.assertEqual(body['data']['status'], 'REJECTED')
        self.assertEqual(body['data']['code'], 'BID_TOO_LOW')

    def test_08_close_early_then_closed_and_replayed(self):
        _, body, _ = self.post(f'/api/auctions/{self.auction}/close', {'strategy': 'row_lock'})
        self.assertEqual(body['data']['code'], 'TOO_EARLY')
        with connect(self.owner) as conn:
            conn.execute('UPDATE auction.auctions SET closes_at=clock_timestamp() WHERE id=%s', (self.auction,))
        _, closed, _ = self.post(f'/api/auctions/{self.auction}/close', {'strategy': 'row_lock'})
        self.assertEqual(closed['data']['status'], 'CLOSED')
        self.assertIsNone(closed['data']['winning_bid_id'])
        _, again, _ = self.post(f'/api/auctions/{self.auction}/close', {'strategy': 'row_lock'})
        self.assertEqual(again['data']['status'], 'REPLAYED')

    def test_09_csrf_missing_invalid_and_cross_origin_are_rejected(self):
        path = f'/api/auctions/{self.auction}/bids'
        self.assertEqual(self.request('POST', path, self.bid_payload())[0], 403)
        self.assertEqual(self.request('POST', path, self.bid_payload(), headers={'X-Auction-Token': 'wrong'})[0], 403)
        self.assertEqual(self.post(path, self.bid_payload(), Origin='https://example.com')[0], 403)
        self.assertEqual(self.request('GET', '/api/bootstrap', headers={'Host': 'example.com'})[0], 403)

    def test_10_json_validation_and_body_limit(self):
        path = f'/api/auctions/{self.auction}/bids'
        token = {'X-Auction-Token': self.service.csrf_token, 'Content-Type': 'application/json'}
        self.assertEqual(self.request('POST', path, b'{broken', token, raw=True)[0], 400)
        self.assertEqual(self.request('POST', path, b'[]', token, raw=True)[0], 400)
        self.assertEqual(self.request('POST', path, b'x' * 33000, token, raw=True)[0], 413)
        self.assertEqual(self.post(path, self.bid_payload(amount=100))[0], 400)
        self.assertEqual(self.post(path, self.bid_payload(bidder_id=True))[0], 400)
        self.assertEqual(self.post(path, self.bid_payload(request_id='invalid'))[0], 400)
        self.assertEqual(self.post(path, self.bid_payload(amount='NaN'))[0], 400)
        self.assertEqual(self.post(path, self.bid_payload(amount='1e999999999999999999999'))[0], 400)

    def test_11_static_traversal_and_private_file_denied(self):
        for path in ('/../.env', '/%2e%2e/.env', '/%5c..%5c.env', '/.env', '/auction_lab/db.py'):
            self.assertIn(self.request('GET', path)[0], (403, 404), path)

    def test_12_money_above_javascript_safe_integer_stays_string(self):
        large = create_auction(self.owner, start_price='9007199254740993.00', bid_step='0.01')
        _, body, _ = self.request('GET', f'/api/auctions/{large}')
        self.assertEqual(body['data']['auction']['start_price'], '9007199254740993.00')
        payload = self.bid_payload(amount='9007199254740993.01')
        _, placed, _ = self.post(f'/api/auctions/{large}/bids', payload)
        self.assertEqual(placed['data']['amount'], '9007199254740993.01')
        _, replay, _ = self.post(f'/api/auctions/{large}/bids', payload)
        self.assertEqual(replay['data']['amount'], '9007199254740993.01')
        with connect(self.owner) as conn:
            conn.execute('UPDATE auction.auctions SET closes_at=clock_timestamp() WHERE id=%s', (large,))
        _, closed, _ = self.post(f'/api/auctions/{large}/close', {'strategy': 'row_lock'})
        self.assertEqual(closed['data']['winning_price'], '9007199254740993.01')

    def test_13_real_equal_price_experiments_both_protocols(self):
        for strategy in ('row_lock', 'serializable'):
            with self.subTest(strategy=strategy):
                status, body, _ = self.post('/api/experiments/race', {'strategy': strategy, 'workers': 4})
                self.assertEqual(status, 200, body)
                data = body['data']
                self.assertEqual((data['accepted'], data['rejected']), (1, 3))
                self.assertTrue(data['database'].endswith('_test'))
                self.assertTrue(all(c['passed'] for c in data['checks']))

    def test_14_experiment_guard_and_busy_state(self):
        self.assertEqual(self.post('/api/experiments/race', {'workers': 100})[0], 400)
        self.service.experiment_lock.acquire()
        try:
            status, body, _ = self.post('/api/experiments/race', {'workers': 2})
            self.assertEqual(status, 409)
            self.assertEqual(body['error']['code'], 'EXPERIMENT_BUSY')
        finally:
            self.service.experiment_lock.release()

    def test_15_checks_and_saved_metrics_are_real(self):
        status, body, _ = self.request('GET', '/api/checks')
        self.assertEqual(status, 200)
        self.assertEqual(len(body['data']['checks']), 8)
        self.assertTrue(all(c['passed'] for c in body['data']['checks']))
        status, body, _ = self.request('GET', '/api/experiments/latest')
        self.assertEqual(status, 200)
        if body['data']['tests'] is not None:
            source = json.loads((self.service.result_root / 'test-results.json').read_text(encoding='utf-8-sig'))
            self.assertEqual(body['data']['tests']['tests_run'], source['tests_run'])
        self.assertNotIn('samples', body['data'].get('benchmark') or {})

    def test_16_serializable_http_path(self):
        status, body, _ = self.post(f'/api/auctions/{self.auction}/bids', self.bid_payload(strategy='serializable'))
        self.assertEqual((status, body['data']['status']), (200, 'ACCEPTED'))
        self.assertGreaterEqual(body['data']['attempts'], 1)

    def test_17_owned_server_can_stop_without_database_connection(self):
        unavailable = AuctionWebService(
            app_dsn='postgresql://unavailable@127.0.0.1:1/missing_database',
            web_root=self.service.web_root,
        )
        server = create_server(port=0, service=unavailable)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        connection = http.client.HTTPConnection('127.0.0.1', server.server_address[1], timeout=5)
        try:
            connection.request('GET', '/api/health')
            response = connection.getresponse()
            health = json.loads(response.read())
            self.assertEqual(response.status, 200)
            token = health['data']['csrf_token']
            self.assertEqual(health['data']['application'], 'auction19')
            connection.request('POST', '/api/system/stop', body=b'{}', headers={
                'Content-Type': 'application/json', 'X-Auction-Token': token,
            })
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            self.assertEqual(json.loads(response.read())['data']['status'], 'STOPPING')
            thread.join(timeout=5)
            self.assertFalse(thread.is_alive(), 'Máy chủ phải dừng cả khi PostgreSQL không kết nối được')
        finally:
            connection.close()
            if thread.is_alive():
                server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__ == '__main__':
    unittest.main(verbosity=2)
