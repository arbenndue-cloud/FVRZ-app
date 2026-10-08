"""Behaviour checks for the fictional demo; uses a disposable database."""
import tempfile
import unittest
from collections import Counter
from datetime import date
from pathlib import Path
from fastapi.testclient import TestClient
from app import main

class DemoTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        main.DB = Path(self.temp.name) / 'test.db'
        main.init()
        self.client = TestClient(main.app)
    def tearDown(self):
        self.temp.cleanup()
    def test_autopilot_budget_and_weekly_cap(self):
        payload = dict(budget=300,start='2026-10-08',end='2026-10-31',frequency_cap=2,region='Winterthur',featured=True)
        r=self.client.post('/api/autopilot/plan',json=payload)
        self.assertEqual(r.status_code,200)
        data=r.json()
        self.assertEqual(data['planned']+data['remaining'],300)
        self.assertEqual(sum(s['price'] for s in data['slots']),data['planned'])
        counts=Counter(date.fromisoformat(s['kickoff'][:10]).isocalendar()[:2] for s in data['slots'])
        self.assertTrue(all(c<=2 for c in counts.values()))
        self.assertEqual(self.client.get('/api/sponsors').json(),[])
        payload['budget']=20
        self.assertEqual(self.client.post('/api/autopilot/plan',json=payload).json()['planned'],0)
        payload['end']='2026-10-01'
        self.assertEqual(self.client.post('/api/autopilot/plan',json=payload).status_code,422)
    def test_empty_inventory_keeps_budget(self):
        data=self.client.post('/api/autopilot/plan',json=dict(budget=500,start='2027-01-01',end='2027-01-31',frequency_cap=2,region='Schweiz')).json()
        self.assertEqual(data['slots'],[])
        self.assertEqual(data['remaining'],500)
    def test_sponsor_credit_and_review(self):
        data=self.client.post('/api/sponsor/campaign',json=dict(sponsor_name='Testpartner',match_id=1,placement='Matchday',coupon='MAXSTART25')).json()
        self.assertEqual(data['club_share'],18.75)
        self.assertEqual(data['sponsor_pays'],18.75)
        result=self.client.post(f"/api/sponsor/{data['campaign_id']}/approve").json()
        self.assertEqual(result['status'],'approved')
    def test_player_requires_consent_and_review(self):
        payload=dict(player='Demo Spieler',team='Junioren U17',body='Dies ist eine fiktive Teamgeschichte.',rights_confirmed=False)
        self.assertEqual(self.client.post('/api/player/moment',json=payload).status_code,400)
        payload['rights_confirmed']=True
        data=self.client.post('/api/player/moment',json=payload).json()
        self.assertEqual(data['status'],'pending')
        self.assertEqual(self.client.post(f"/api/player/moment/{data['id']}/approve").json()['status'],'approved')
    def test_seed_idempotent_and_routes(self):
        main.init()
        self.assertEqual(len(self.client.get('/api/matches').json()),9)
        for path in ['/club','/sponsor','/player','/website','/static/matchday.png']:
            self.assertEqual(self.client.get(path).status_code,200)
if __name__=='__main__': unittest.main()
