from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from datetime import date, timedelta
from pydantic import Field, model_validator
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent.parent
DB = Path(os.getenv("MAX_DB_PATH", str(ROOT / "max_demo.db")))

app = FastAPI(title="MAX · FC Mockup Pilot", version="1.0.0")

FIXTURES = [
    ("1. Mannschaft", "FC Riverside", "2026-10-10 18:00", "MAX Arena", "Regional-Liga · Derby"),
    ("Frauen", "FC Lakeside", "2026-10-11 14:00", "MAX Arena", "Regional-Liga"),
    ("Junioren U17", "FC Riverside U17", "2026-10-14 18:30", "MAX Arena", "Junioren-Liga"),
    ("1. Mannschaft", "FC Nordstadt", "2026-10-17 16:00", "MAX Arena", "Regional-Liga"),
    ("Frauen", "FC Westpark", "2026-10-18 14:00", "MAX Arena", "Regional-Liga"),
    ("Junioren U17", "FC Lakeside U17", "2026-10-21 18:30", "MAX Arena", "Junioren-Liga"),
    ("1. Mannschaft", "FC Lakeside", "2026-10-24 18:00", "MAX Arena", "Regional-Liga"),
    ("Frauen", "FC Nordstadt", "2026-10-25 14:00", "MAX Arena", "Regional-Liga"),
    ("1. Mannschaft", "FC Riverside", "2026-10-31 18:00", "MAX Arena", "Regional-Liga · Derby"),
]

PLACEMENTS = {
    "Matchday": 25,
    "Kickoff": 20,
    "Full Time": 30,
    "Player of the Day": 35,
}


def conn():
    DB.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c


def init():
    c = conn()
    c.executescript(
        """
        CREATE TABLE IF NOT EXISTS matches(
            id INTEGER PRIMARY KEY,
            team TEXT NOT NULL,
            opponent TEXT NOT NULL,
            kickoff TEXT NOT NULL,
            venue TEXT NOT NULL,
            competition TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sponsor_campaigns(
            id INTEGER PRIMARY KEY,
            sponsor_name TEXT NOT NULL,
            club TEXT NOT NULL,
            match_id INTEGER,
            placement TEXT NOT NULL,
            list_price REAL NOT NULL,
            sponsor_pays REAL NOT NULL,
            club_share REAL NOT NULL,
            max_share REAL NOT NULL,
            headline TEXT DEFAULT '',
            coupon TEXT DEFAULT '',
            approval_status TEXT DEFAULT 'pending',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS club_posts(
            id INTEGER PRIMARY KEY,
            title TEXT NOT NULL,
            body TEXT NOT NULL,
            post_type TEXT NOT NULL,
            plan TEXT DEFAULT 'premium',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    if c.execute("SELECT COUNT(*) FROM matches").fetchone()[0] == 0:
        c.executemany(
            "INSERT INTO matches(team,opponent,kickoff,venue,competition) VALUES(?,?,?,?,?)",
            FIXTURES,
        )
    c.execute("CREATE TABLE IF NOT EXISTS demo_meta(key TEXT PRIMARY KEY, value TEXT)")
    if not c.execute("SELECT 1 FROM demo_meta WHERE key='mockup_v1'").fetchone():
        legacy = c.execute("SELECT COUNT(*) FROM matches WHERE venue IN ('Hegmatten','Heerenschürli','Erlen','Flüeli')").fetchone()[0]
        if legacy:
            for i, fixture in enumerate(FIXTURES[:5], 1):
                c.execute("UPDATE matches SET team=?,opponent=?,kickoff=?,venue=?,competition=? WHERE id=? AND venue IN ('Hegmatten','Heerenschürli','Erlen','Flüeli')", (*fixture, i))
            c.executemany("INSERT INTO matches(team,opponent,kickoff,venue,competition) VALUES(?,?,?,?,?)", FIXTURES[5:])
        c.execute("UPDATE sponsor_campaigns SET club='FC Mockup' WHERE club='FC Oberwinterthur'")
        c.execute("INSERT INTO demo_meta VALUES('mockup_v1','done')")
    c.execute("CREATE TABLE IF NOT EXISTS player_moments(id INTEGER PRIMARY KEY, player TEXT, team TEXT, body TEXT, status TEXT DEFAULT 'pending', created_at TEXT DEFAULT CURRENT_TIMESTAMP)")
    c.commit()
    c.close()


@app.on_event("startup")
def startup():
    init()


class SponsorCampaign(BaseModel):
    sponsor_name: str = Field(min_length=1, max_length=100)
    club: str = "FC Mockup"
    match_id: int
    placement: str
    headline: str = Field(default="", max_length=200)
    coupon: str = Field(default="", max_length=50)


class ClubPost(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=4000)
    post_type: Literal["club_info", "event", "one_off", "sponsor", "other"] = "one_off"


@app.get("/health")
def health():
    return {"status": "ok", "product": "MAX", "club": "FC Mockup", "version": "1.0.0"}


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse("/club")


@app.get("/api/matches")
def api_matches():
    c = conn()
    rows = [dict(x) for x in c.execute("SELECT * FROM matches ORDER BY kickoff").fetchall()]
    c.close()
    return rows


@app.get("/api/sponsors")
def api_sponsors():
    c = conn()
    rows = [
        dict(x)
        for x in c.execute(
            "SELECT * FROM sponsor_campaigns ORDER BY id DESC LIMIT 30"
        ).fetchall()
    ]
    c.close()
    return rows


@app.post("/api/sponsor/campaign")
def create_sponsor_campaign(campaign: SponsorCampaign):
    if campaign.placement not in PLACEMENTS:
        raise HTTPException(400, "Unknown placement")
    c = conn()
    match = c.execute("SELECT * FROM matches WHERE id=?", (campaign.match_id,)).fetchone()
    if not match:
        c.close()
        raise HTTPException(404, "Match not found")

    list_price = float(PLACEMENTS[campaign.placement])
    club_share = round(list_price * 0.75, 2)
    max_share = round(list_price * 0.25, 2)
    coupon = campaign.coupon.strip().upper()
    discount = max_share if coupon in {"MAXSTART25", "FCO25"} else 0.0
    sponsor_pays = round(list_price - discount, 2)
    max_net = round(max_share - discount, 2)

    cur = c.execute(
        """
        INSERT INTO sponsor_campaigns(
            sponsor_name,club,match_id,placement,list_price,sponsor_pays,
            club_share,max_share,headline,coupon,approval_status
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            campaign.sponsor_name,
            campaign.club,
            campaign.match_id,
            campaign.placement,
            list_price,
            sponsor_pays,
            club_share,
            max_net,
            campaign.headline,
            coupon,
            "pending",
        ),
    )
    c.commit()
    campaign_id = cur.lastrowid
    c.close()
    return {
        "ok": True,
        "campaign_id": campaign_id,
        "approval_status": "pending",
        "list_price": list_price,
        "sponsor_pays": sponsor_pays,
        "club_share": club_share,
        "max_share": max_net,
        "coupon_applied": bool(discount),
    }


@app.post("/api/sponsor/{campaign_id}/{action}")
def sponsor_approval(campaign_id: int, action: str):
    if action not in {"approve", "reject"}:
        raise HTTPException(400, "Action must be approve or reject")
    status = "approved" if action == "approve" else "rejected"
    c = conn()
    row = c.execute("SELECT id FROM sponsor_campaigns WHERE id=?", (campaign_id,)).fetchone()
    if not row:
        c.close()
        raise HTTPException(404, "Campaign not found")
    c.execute(
        "UPDATE sponsor_campaigns SET approval_status=? WHERE id=?",
        (status, campaign_id),
    )
    c.commit()
    c.close()
    return {"ok": True, "status": status}


@app.post("/api/club/post")
def create_club_post(post: ClubPost):
    c = conn()
    cur = c.execute(
        "INSERT INTO club_posts(title,body,post_type,plan) VALUES(?,?,?,?)",
        (post.title, post.body, post.post_type, "free"),
    )
    c.commit()
    pid = cur.lastrowid
    c.close()
    return {
        "ok": True,
        "post_id": pid,
        "outputs": ["WhatsApp Channel", "WhatsApp Status", "Instagram", "Facebook", "TikTok storyboard"],
        "note": "Demo: Content is prepared, not sent to Meta.",
    }



app.mount("/static", StaticFiles(directory=ROOT / "app/static"), name="static")

@app.get("/club", response_class=HTMLResponse)
@app.get("/sponsor", response_class=HTMLResponse)
@app.get("/player", response_class=HTMLResponse)
def portal():
    return HTMLResponse((ROOT / "app/pages/portal.html").read_text())

@app.get("/website", response_class=HTMLResponse)
def website():
    return HTMLResponse((ROOT / "max-site/index.html").read_text().replace('src="assets/', 'src="/site-assets/'))

app.mount("/site-assets", StaticFiles(directory=ROOT / "max-site/assets"), name="site-assets")

class AutopilotRequest(BaseModel):
    budget: int = Field(default=300, ge=20, le=100000)
    start: date
    end: date
    frequency_cap: int = Field(default=2, ge=1, le=4)
    region: Literal["Winterthur", "Zürich", "Schweiz"] = "Winterthur"
    featured: bool = False

    @model_validator(mode="after")
    def dates_valid(self):
        if self.end < self.start or (self.end-self.start).days > 365:
            raise ValueError("Bitte einen Zeitraum von maximal 365 Tagen wählen.")
        return self

@app.post("/api/autopilot/plan")
def autopilot_plan(request: AutopilotRequest):
    # Demo inventory only. No booking, payment, API distribution or audience tracking.
    matches = [m for m in api_matches() if request.start <= date.fromisoformat(m['kickoff'][:10]) <= request.end]
    remaining = request.budget
    slots = []
    weeks = {}
    for m in matches:
        week = date.fromisoformat(m['kickoff'][:10]).isocalendar()[:2]
        for placement, price in [("Matchday",25),("Full Time",30)]:
            if weeks.get(week,0) >= request.frequency_cap or price > remaining:
                continue
            slots.append({"match_id":m['id'], "team":m['team'], "opponent":m['opponent'], "kickoff":m['kickoff'], "placement":placement, "price":price})
            weeks[week] = weeks.get(week,0)+1
            remaining -= price
    return {"demo":True, "slots":slots, "planned":request.budget-remaining, "remaining":remaining,
        "club_share":round((request.budget-remaining)*.75,2),
        "note":"Frequency Cap: Platzierungen pro Kalenderwoche in diesem Demo-Verein. Personenübergreifende Kontaktfrequenz ist ohne Plattformdaten nicht messbar.",
        "suggestion": "Mehr Vereine in der Region anfragen oder Laufzeit verlängern. Restbudget bleibt unverplant." if remaining else "Budget vollständig innerhalb des Limits planbar.",
        "region_note":"Aktuell ist nur FC Mockup als Demo-Inventar verfügbar; eine grössere Region fügt noch keine Vereine hinzu.",
        "featured_note":"Derby-Sponsoring als Zusatzanfrage vormerken; Verfügbarkeit, Exklusivität und Preis müssen bestätigt werden." if request.featured else ""}

class PlayerMoment(BaseModel):
    player: str = Field(min_length=2, max_length=70)
    team: Literal["1. Mannschaft", "Frauen", "Junioren U17"]
    body: str = Field(min_length=10, max_length=1200)
    rights_confirmed: bool

@app.post("/api/player/moment")
def player_moment(moment: PlayerMoment):
    if not moment.rights_confirmed:
        raise HTTPException(400, "Bitte die nötigen Einwilligungen bestätigen.")
    c=conn()
    cur=c.execute("INSERT INTO player_moments(player,team,body) VALUES(?,?,?)", (moment.player, moment.team, moment.body))
    c.commit()
    result={"id":cur.lastrowid, "status":"pending", "note":"Zur Vereinsprüfung eingereicht. Keine automatische Veröffentlichung."}
    c.close()
    return result

@app.get("/api/player/moments")
def moments():
    c=conn()
    rows=[dict(x) for x in c.execute("SELECT * FROM player_moments ORDER BY id DESC LIMIT 30")]
    c.close()
    return rows

@app.post("/api/player/moment/{moment_id}/{action}")
def review_moment(moment_id: int, action: Literal['approve','reject']):
    c=conn()
    status='approved' if action=='approve' else 'rejected'
    count=c.execute("UPDATE player_moments SET status=? WHERE id=?", (status,moment_id)).rowcount
    c.commit()
    c.close()
    if not count:
        raise HTTPException(404, 'Moment not found')
    return {"status":status}
