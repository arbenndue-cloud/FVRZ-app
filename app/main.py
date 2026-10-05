from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent.parent
DB = Path(os.getenv("MAX_DB_PATH", str(ROOT / "max_demo.db")))

app = FastAPI(title="MAX · FC Oberwinterthur Pilot", version="0.8.0")

FIXTURES = [
    ("Junioren D-9 a", "FC Witikon a", "2026-10-03 09:00", "Hegmatten", "Regional Cup"),
    ("1. Mannschaft", "FC Pfäffikon 1", "2026-10-03 16:30", "Hegmatten", "2. Liga · Gruppe 2"),
    ("Junioren D-9 c", "FC Zürich Mädchen U14 b", "2026-10-04 10:00", "Heerenschürli", "Trainingsspiel"),
    ("2. Mannschaft", "FC Dielsdorf 2", "2026-10-04 11:00", "Erlen", "4. Liga · Gruppe 6"),
    ("1. Mannschaft", "SC Veltheim 1", "2026-10-10 18:00", "Flüeli", "2. Liga · Gruppe 2"),
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
    c.commit()
    c.close()


@app.on_event("startup")
def startup():
    init()


class SponsorCampaign(BaseModel):
    sponsor_name: str
    club: str = "FC Oberwinterthur"
    match_id: int
    placement: str
    headline: str = ""
    coupon: str = ""


class ClubPost(BaseModel):
    title: str
    body: str
    post_type: Literal["club_info", "event", "one_off", "sponsor", "other"] = "one_off"


@app.get("/health")
def health():
    return {"status": "ok", "product": "MAX", "club": "FC Oberwinterthur", "version": "0.8.0"}


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
        (post.title, post.body, post.post_type, "premium"),
    )
    c.commit()
    pid = cur.lastrowid
    c.close()
    return {
        "ok": True,
        "post_id": pid,
        "outputs": ["WhatsApp Channel", "WhatsApp Status"],
        "note": "Demo: Content is prepared, not sent to Meta.",
    }


CLUB_HTML = """<!doctype html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>MAX Club · FC Oberwinterthur</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600;700;800&family=Space+Grotesk:wght@600;700&display=swap');
:root{--ink:#15202b;--muted:#6d7885;--line:#e7ebef;--soft:#f7f9fb;--mint:#4fe0bd;--blue:#3f78ff;--violet:#8a68ff;--yellow:#ffd817;--fco:#083b77;--good:#138a62;--warn:#b06a00;--bad:#b42318}
*{box-sizing:border-box}body{margin:0;background:#fff;color:var(--ink);font-family:Manrope,system-ui,sans-serif}button,input,textarea,select{font:inherit}button{cursor:pointer}.hidden{display:none!important}
.top{height:72px;border-bottom:1px solid var(--line);display:flex;align-items:center;justify-content:space-between;padding:0 4vw;position:sticky;top:0;background:#ffffffee;backdrop-filter:blur(14px);z-index:50}.brand{display:flex;gap:11px;align-items:center}.maxmark{width:42px;height:42px;border-radius:13px;background:#151b22;color:#fff;display:grid;place-items:center;font:700 12px Space Grotesk}.brand b{display:block}.brand span{font-size:10px;color:var(--muted)}.nav{display:flex;align-items:center;gap:8px}.nav a,.pill{border:1px solid var(--line);padding:9px 11px;border-radius:999px;color:var(--ink);text-decoration:none;font-size:10px;font-weight:800;background:#fff}.premium-pill{border-color:#dccfff;background:#f7f3ff;color:#6941c6}
.shell{width:min(1240px,93vw);margin:26px auto 70px}.hero{display:grid;grid-template-columns:1.18fr .82fr;gap:16px}.hero-main{min-height:390px;border:1px solid var(--line);border-radius:28px;padding:44px;position:relative;overflow:hidden;background:linear-gradient(135deg,#fff 0%,#fbfcff 65%,#f2eeff 100%)}.hero-main:after{content:"";position:absolute;width:320px;height:320px;border-radius:50%;right:-110px;top:-120px;background:linear-gradient(135deg,var(--mint),var(--blue),var(--violet));filter:blur(55px);opacity:.15}.eyebrow{font-size:10px;letter-spacing:.14em;font-weight:800;color:#687584;text-transform:uppercase}.hero h1{font:700 clamp(46px,5.7vw,76px)/.95 Space Grotesk;margin:14px 0 18px;letter-spacing:-.055em}.hero h1 span{background:linear-gradient(100deg,#25b99a,var(--blue),var(--violet));-webkit-background-clip:text;color:transparent}.hero p{max-width:650px;font-size:15px;line-height:1.7;color:var(--muted)}.hero-actions{display:flex;gap:8px;margin-top:25px;flex-wrap:wrap}.btn{border:0;border-radius:12px;padding:12px 14px;font-size:11px;font-weight:800;background:#151b22;color:#fff}.btn.alt{background:#fff;color:var(--ink);border:1px solid var(--line)}.hero-side{border-radius:28px;background:#fff;border:1px solid var(--line);padding:25px}.max-card{height:100%;display:flex;flex-direction:column}.avatar{width:74px;height:74px;border-radius:22px;background:#f8f2df;display:grid;place-items:center;font-size:32px;border:1px solid #eee4c5}.max-card h2{font:700 27px Space Grotesk;margin:15px 0 4px}.max-card p{font-size:11px;color:var(--muted);line-height:1.55}.task{padding:11px 0;border-top:1px solid var(--line);display:flex;justify-content:space-between;gap:10px}.task b{font-size:11px}.task span{font-size:9px;color:var(--good);font-weight:800}
.grid{display:grid;grid-template-columns:1.15fr .85fr;gap:16px;margin-top:16px}.card{border:1px solid var(--line);border-radius:22px;background:#fff;overflow:hidden}.card-head{padding:20px 22px;border-bottom:1px solid var(--line);display:flex;justify-content:space-between;align-items:end;gap:15px}.card-head h2{font:700 22px Space Grotesk;margin:4px 0 0}.card-head p{font-size:10px;color:var(--muted);margin:0}.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:9px;padding:18px}.stat{border:1px solid var(--line);background:var(--soft);border-radius:15px;padding:15px}.stat small{display:block;color:var(--muted);font-size:9px}.stat b{font:700 25px Space Grotesk;display:block;margin-top:4px}.stat em{font-style:normal;font-size:9px;color:var(--good)}
.reachbar{margin:0 18px 18px;border-radius:17px;background:#151b22;color:#fff;padding:19px;display:grid;grid-template-columns:1fr auto;gap:15px;align-items:end}.reachbar small{font-size:9px;color:#aab3bd}.reachbar strong{font:700 33px Space Grotesk}.reachbar span{font-size:10px;color:#76efd1}
.feed{padding:18px}.post{border:1px solid var(--line);border-radius:17px;overflow:hidden;margin-bottom:11px}.visual{height:190px;background:#fff;position:relative;display:grid;place-items:center;text-align:center;padding:20px;border-bottom:1px solid var(--line)}.visual:before{content:"";position:absolute;inset:14px;border-radius:15px;background:linear-gradient(145deg,#083b77,#0f5a99);z-index:0}.visual .inner{position:relative;z-index:2;color:#fff}.visual .type{font-size:11px;font-weight:900;color:var(--yellow);letter-spacing:.14em}.visual h3{font:700 29px Space Grotesk;margin:14px 0 3px}.visual p{font-size:10px;color:#dbe7f5}.share{display:flex;justify-content:space-between;padding:10px 13px;font-size:9px;color:var(--muted)}.share b{color:var(--ink)}.dual{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:8px}.out{background:var(--soft);border:1px solid var(--line);border-radius:11px;padding:9px 11px;font-size:9px}.out b{display:block;font-size:10px;margin-bottom:2px}
.approvals{padding:8px 18px 18px}.approval{display:grid;grid-template-columns:1fr auto;gap:12px;padding:13px 0;border-bottom:1px solid var(--line);align-items:center}.approval:last-child{border-bottom:0}.approval b{display:block;font-size:11px}.approval span{font-size:9px;color:var(--muted)}.approval-actions{display:flex;gap:5px}.mini{border:1px solid var(--line);background:#fff;border-radius:8px;padding:7px 8px;font-size:9px;font-weight:800}.mini.ok{background:#ecfdf5;border-color:#abefc6;color:#067647}.mini.no{background:#fff5f4;border-color:#fecdca;color:#b42318}
.plans{display:grid;grid-template-columns:1fr 1fr;gap:12px;padding:18px}.plan{border:1px solid var(--line);border-radius:17px;padding:18px;position:relative}.plan.premium{border:2px solid #cfc1ff;background:#fbf9ff}.plan h3{margin:6px 0 3px;font:700 20px Space Grotesk}.price{font:700 26px Space Grotesk;margin:10px 0}.price small{font:500 10px Manrope;color:var(--muted)}.plan ul{padding-left:17px;font-size:10px;color:#53606d;line-height:1.8}.tag{font-size:8px;font-weight:900;letter-spacing:.1em;color:#6941c6}
.lab{padding:18px}.prompt{width:100%;min-height:90px;border:1px solid var(--line);border-radius:14px;padding:13px;outline:none}.prompt:focus{border-color:#9b87ff;box-shadow:0 0 0 3px #eeeaff}.lab-actions{display:flex;gap:8px;margin-top:9px}.preview-design{margin-top:12px;border:1px solid var(--line);border-radius:16px;padding:16px;background:linear-gradient(135deg,#fff7d6,#eef4ff)}.preview-design b{font:700 17px Space Grotesk}.locknote{font-size:9px;color:var(--muted);margin-top:8px}
.form{padding:18px}.field{margin-bottom:10px}.field label{display:block;font-size:9px;font-weight:800;margin-bottom:5px}.field input,.field textarea,.field select{width:100%;border:1px solid var(--line);border-radius:11px;padding:10px 11px;background:#fff}.success{margin-top:10px;background:#ecfdf5;border:1px solid #abefc6;color:#05603a;border-radius:11px;padding:10px;font-size:10px}
.login{position:fixed;inset:0;background:#ffffffef;backdrop-filter:blur(10px);z-index:100;display:grid;place-items:center;padding:20px}.loginbox{width:min(430px,94vw);border:1px solid var(--line);border-radius:25px;padding:28px;background:#fff;box-shadow:0 25px 80px #10203018}.loginbox h2{font:700 31px Space Grotesk;margin:10px 0 7px}.loginbox p{font-size:11px;color:var(--muted);line-height:1.55}.loginbox input{width:100%;border:1px solid var(--line);border-radius:11px;padding:11px;margin:5px 0}
@media(max-width:980px){.hero,.grid{grid-template-columns:1fr}.stats{grid-template-columns:1fr 1fr}.hero-side{min-height:320px}}@media(max-width:650px){.shell{width:95vw}.hero-main{padding:30px 24px}.hero h1{font-size:48px}.stats,.plans,.dual{grid-template-columns:1fr}.nav a:not(:last-child){display:none}}
</style>
</head>
<body>
<div class="login" id="login">
  <div class="loginbox">
    <div class="maxmark">MAX</div>
    <div class="eyebrow">VEREINS-LOGIN · DEMO</div>
    <h2>Hallo FC Oberwinterthur.</h2>
    <p>MAX hat den Club bereits vorbereitet. Für die Demo sind keine echten Zugangsdaten nötig.</p>
    <input value="vorstand@fcoberwinterthur.ch">
    <input type="password" value="demo1234">
    <button class="btn" style="width:100%;margin-top:7px" onclick="document.getElementById('login').classList.add('hidden')">Demo öffnen</button>
  </div>
</div>

<header class="top">
  <div class="brand"><div class="maxmark">MAX</div><div><b>MAX Club</b><span>FC Oberwinterthur · Demo</span></div></div>
  <div class="nav"><a href="#growth">Reichweite</a><a href="#premium">Free / Premium</a><a href="#approvals">Sponsoren</a><a href="/sponsor">Sponsor-Login</a><span class="pill premium-pill">PREMIUM CHF 49</span></div>
</header>

<main class="shell">
  <section class="hero">
    <div class="hero-main">
      <div class="eyebrow">MEET MAX · YOUR CLUB'S HARDEST-WORKING FAN</div>
      <h1>Er baut eure <span>Audience.</span><br>Jedes Wochenende.</h1>
      <p>MAX liest den Spielplan, kuratiert relevante Clubmomente, erzeugt WhatsApp Channel- und Status-Versionen und lernt aus Views, Shares und neuen Followern. Sponsoring kommt danach — wenn die Reichweite da ist.</p>
      <div class="hero-actions"><button class="btn" onclick="document.getElementById('growth').scrollIntoView({behavior:'smooth'})">Growth Cockpit</button><button class="btn alt" onclick="document.getElementById('premium').scrollIntoView({behavior:'smooth'})">Premium ansehen</button></div>
    </div>
    <aside class="hero-side"><div class="max-card"><div class="avatar">🤓</div><h2>MAX arbeitet.</h2><p>Dicker Bauch, 3-Tage-Bart, Trucker-Cap — und beim FCO natürlich der grösste Oberi-Fan.</p><div style="margin-top:auto"><div class="task"><b>Weekend Recap</b><span>READY</span></div><div class="task"><b>Channel + Status</b><span>2 OUTPUTS</span></div><div class="task"><b>Share Potential</b><span>HIGH</span></div><div class="task"><b>Sponsor Approval</b><span>1 PENDING</span></div></div></div></aside>
  </section>

  <section class="grid" id="growth">
    <div class="card">
      <div class="card-head"><div><div class="eyebrow">AUDIENCE ENGINE</div><h2>Reichweite zuerst.</h2></div><p>Demo-Werte für den FCO-Pilot</p></div>
      <div class="stats">
        <div class="stat"><small>Channel Follower</small><b>500</b><em>+38 diese Woche</em></div>
        <div class="stat"><small>Ø direkte Views</small><b>372</b><em>74 % View Rate</em></div>
        <div class="stat"><small>Shares / Woche</small><b>61</b><em>Player Posts stark</em></div>
        <div class="stat"><small>Neue Follows</small><b>+27</b><em>aus Share-Loops</em></div>
      </div>
      <div class="reachbar"><div><small>MAX REACH · OWNED + EARNED + NETWORK</small><strong>1'840</strong></div><span>3.7× eigene Follower</span></div>
    </div>

    <div class="card">
      <div class="card-head"><div><div class="eyebrow">MAX LEARNS</div><h2>Was gerade funktioniert.</h2></div></div>
      <div style="padding:10px 20px 20px">
        <div class="task"><b>Player of the Day</b><span>2.4× Share Rate</span></div>
        <div class="task"><b>Junioren + persönliche Story</b><span>HIGH VIRALITY</span></div>
        <div class="task"><b>Weekend Recap</b><span>BEST UTILITY</span></div>
        <div class="task"><b>Opponent Shares</b><span>GROWING</span></div>
      </div>
    </div>
  </section>

  <section class="grid">
    <div class="card">
      <div class="card-head"><div><div class="eyebrow">CONTENT</div><h2>Ein Inhalt. Zwei WhatsApp-Outputs.</h2></div><p>Channel ist Hauptmedium · Status verstärkt Reichweite</p></div>
      <div class="feed">
        <div class="post">
          <div class="visual"><div class="inner"><div class="type">PLAYER OF THE DAY</div><h3>Oberi Moment.</h3><p>Persönlicher Content ist bewusst auf Shares optimiert.</p></div></div>
          <div class="share"><b>Expected Shareability: HIGH</b><span>↗ 22 Shares · +9 Follows</span></div>
        </div>
        <div class="dual"><div class="out"><b>WhatsApp Channel</b>vollständiger offizieller Clubpost</div><div class="out"><b>WhatsApp Status</b>9:16 · kürzer · grösser · share-ready</div></div>
      </div>
    </div>

    <div class="card" id="premium">
      <div class="card-head"><div><div class="eyebrow">FREEMIUM</div><h2>Free ist gut. Premium gibt Kontrolle.</h2></div></div>
      <div class="plans">
        <div class="plan"><div class="tag" style="color:#53606d">MAX FREE</div><h3>Standard</h3><div class="price">CHF 0 <small>/ Mt.</small></div><ul><li>Standarddesign</li><li>Kernposts automatisiert</li><li>Channel + Status Assets</li><li>Basis-Growth-Dashboard</li></ul></div>
        <div class="plan premium"><div class="tag">MAX PREMIUM</div><h3>Club Studio</h3><div class="price">CHF 49 <small>/ Mt.</small></div><ul><li>Design per Prompt</li><li>zusätzliche Auto-Posts</li><li>Einmalpostings</li><li>Club-Informationen</li><li>eigene Events / Hinweise</li></ul></div>
      </div>
    </div>
  </section>

  <section class="grid">
    <div class="card">
      <div class="card-head"><div><div class="eyebrow">PREMIUM · DESIGN LAB</div><h2>Design mit einfachen Prompts.</h2></div><p>LLM-ready Demo</p></div>
      <div class="lab">
        <textarea class="prompt" id="designPrompt">Mach den nächsten Matchday-Post ruhiger, hochwertiger und moderner. Mehr Weissraum, FCO Blau und Gelb nur als Akzent.</textarea>
        <div class="lab-actions"><button class="btn" onclick="applyDesign()">Design generieren</button><button class="btn alt" onclick="resetDesign()">Standard</button></div>
        <div class="preview-design" id="designPreview"><b>MAX Design Preview</b><div style="font-size:10px;color:#687584;margin-top:4px">Standard FCO Template · Free</div></div>
        <div class="locknote">Im produktiven System wird dieser Prompt an das gewählte LLM/Design-Modell gesendet. Die Demo simuliert die Designentscheidung ohne externe API-Kosten.</div>
      </div>
    </div>

    <div class="card">
      <div class="card-head"><div><div class="eyebrow">PREMIUM · CLUB POST</div><h2>Einmalposting erstellen.</h2></div><p>Clubinfo, Event, Hinweis</p></div>
      <div class="form">
        <div class="field"><label>Titel</label><input id="postTitle" value="Juniorenturnier am Sonntag"></div>
        <div class="field"><label>Typ</label><select id="postType"><option value="club_info">Club-Information</option><option value="event">Event</option><option value="one_off">Einmalposting</option></select></div>
        <div class="field"><label>Inhalt</label><textarea id="postBody" rows="4">Am Sonntag gehört Hegmatten unserem Nachwuchs. Kommt vorbei und unterstützt die Teams.</textarea></div>
        <button class="btn" onclick="createPost()">Channel + Status vorbereiten</button>
        <div id="postSuccess" class="success hidden"></div>
      </div>
    </div>
  </section>

  <section class="card" id="approvals" style="margin-top:16px">
    <div class="card-head"><div><div class="eyebrow">BRAND SAFETY</div><h2>Neue Sponsoren einmal freigeben.</h2></div><p>Danach kann die Brand innerhalb der Clubregeln selbst buchen.</p></div>
    <div class="approvals" id="approvalList"><div style="padding:14px 0;font-size:10px;color:#6d7885">Lade Sponsor-Anfragen …</div></div>
  </section>
</main>

<script>
async function loadApprovals(){
  const r=await fetch('/api/sponsors'); const rows=await r.json();
  const pending=rows.filter(x=>x.approval_status==='pending');
  const el=document.getElementById('approvalList');
  if(!pending.length){el.innerHTML='<div style="padding:14px 0;font-size:10px;color:#6d7885">Keine offenen Sponsor-Freigaben. Im Sponsor-Portal eine Demo-Buchung erstellen.</div>';return;}
  el.innerHTML=pending.map(x=>`<div class="approval"><div><b>${x.sponsor_name} · ${x.placement}</b><span>CHF ${x.sponsor_pays.toFixed(2)} · Club erhält CHF ${x.club_share.toFixed(2)} · neue Brand</span></div><div class="approval-actions"><button class="mini ok" onclick="approveSponsor(${x.id},'approve')">Freigeben</button><button class="mini no" onclick="approveSponsor(${x.id},'reject')">Ablehnen</button></div></div>`).join('');
}
async function approveSponsor(id,action){await fetch('/api/sponsor/'+id+'/'+action,{method:'POST'});loadApprovals()}
function applyDesign(){
 const text=document.getElementById('designPrompt').value.toLowerCase(); const p=document.getElementById('designPreview');
 if(text.includes('ruhig')||text.includes('weiss')){p.style.background='linear-gradient(135deg,#ffffff,#f3f6ff)';p.style.borderColor='#cbd9ee';p.innerHTML='<b style="color:#083b77">MATCHDAY · Premium Variant</b><div style="font-size:10px;color:#687584;margin-top:5px">mehr Weissraum · FCO Blau · Gelb als Akzent · reduzierte Typografie</div>'}
 else{p.style.background='linear-gradient(135deg,#fff3c4,#eef4ff)';p.innerHTML='<b>MAX Design Preview</b><div style="font-size:10px;color:#687584;margin-top:5px">Prompt interpretiert · Premium Variant</div>'}
}
function resetDesign(){const p=document.getElementById('designPreview');p.style.background='linear-gradient(135deg,#fff7d6,#eef4ff)';p.innerHTML='<b>MAX Design Preview</b><div style="font-size:10px;color:#687584;margin-top:4px">Standard FCO Template · Free</div>'}
async function createPost(){
 const payload={title:document.getElementById('postTitle').value,body:document.getElementById('postBody').value,post_type:document.getElementById('postType').value};
 const r=await fetch('/api/club/post',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(payload)});const j=await r.json();
 const el=document.getElementById('postSuccess');el.classList.remove('hidden');el.textContent='✓ Post #'+j.post_id+' vorbereitet · WhatsApp Channel + WhatsApp Status';
}
loadApprovals();
</script>
</body>
</html>"""


SPONSOR_HTML = """<!doctype html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>MAX Sponsor · FC Oberwinterthur</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600;700;800&family=Space+Grotesk:wght@600;700&display=swap');
:root{--ink:#16202a;--muted:#6d7885;--line:#e7ebef;--soft:#f7f9fb;--blue:#3f78ff;--violet:#8a68ff;--mint:#4fe0bd;--yellow:#ffd817;--fco:#083b77}
*{box-sizing:border-box}body{margin:0;background:#fff;color:var(--ink);font-family:Manrope,system-ui,sans-serif}button,input,select{font:inherit}.hidden{display:none!important}
.top{height:72px;border-bottom:1px solid var(--line);display:flex;align-items:center;justify-content:space-between;padding:0 4vw}.brand{display:flex;gap:11px;align-items:center}.mark{width:42px;height:42px;border-radius:13px;background:#151b22;color:#fff;display:grid;place-items:center;font:700 12px Space Grotesk}.brand b{display:block}.brand span{font-size:10px;color:var(--muted)}.top a{font-size:10px;font-weight:800;color:var(--ink);text-decoration:none;border:1px solid var(--line);padding:9px 11px;border-radius:999px}
.shell{width:min(1180px,93vw);margin:28px auto 70px}.hero{border:1px solid var(--line);border-radius:28px;padding:43px;background:linear-gradient(135deg,#fff,#f7fbff 60%,#f4f0ff);position:relative;overflow:hidden}.eyebrow{font-size:10px;letter-spacing:.14em;font-weight:800;color:#687584;text-transform:uppercase}.hero h1{font:700 clamp(45px,5.5vw,74px)/.96 Space Grotesk;margin:14px 0 15px;letter-spacing:-.055em}.hero h1 span{background:linear-gradient(100deg,#25b99a,var(--blue),var(--violet));-webkit-background-clip:text;color:transparent}.hero p{max-width:720px;color:var(--muted);font-size:14px;line-height:1.65}.chips{display:flex;gap:7px;flex-wrap:wrap;margin-top:22px}.chips span{border:1px solid var(--line);background:#fff;border-radius:999px;padding:8px 10px;font-size:9px;font-weight:800}
.layout{display:grid;grid-template-columns:1.08fr .92fr;gap:16px;margin-top:16px}.card{border:1px solid var(--line);border-radius:22px;background:#fff;overflow:hidden}.head{padding:20px 22px;border-bottom:1px solid var(--line)}.head h2{font:700 22px Space Grotesk;margin:4px 0 0}.body{padding:18px}.matches{display:grid;gap:8px}.match{border:1px solid var(--line);border-radius:14px;padding:13px;cursor:pointer}.match.active{border:2px solid var(--blue);background:#f7f9ff}.match b{font-size:11px;display:block}.match span{font-size:9px;color:var(--muted)}.placements{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:15px}.placement{border:1px solid var(--line);border-radius:14px;padding:13px;cursor:pointer}.placement.active{border:2px solid var(--violet);background:#faf8ff}.placement b{font-size:11px;display:block}.placement strong{font:700 21px Space Grotesk;display:block;margin-top:5px}.placement span{font-size:9px;color:var(--muted)}.field{margin-top:11px}.field label{display:block;font-size:9px;font-weight:800;margin-bottom:5px}.field input{width:100%;border:1px solid var(--line);border-radius:11px;padding:11px}.btn{width:100%;border:0;border-radius:12px;padding:13px;background:#151b22;color:#fff;font-size:11px;font-weight:800;margin-top:12px;cursor:pointer}.preview{position:sticky;top:18px}.phone{width:min(350px,100%);margin:auto;border:6px solid #151515;border-radius:42px;padding:7px;background:#151515}.screen{min-height:570px;background:#f2f4f7;border-radius:31px;overflow:hidden}.wahead{background:#fff;padding:22px 13px 11px;display:flex;gap:9px;align-items:center}.crest{width:39px;height:39px;border-radius:50%;background:var(--yellow);border:2px solid var(--fco);display:grid;place-items:center;font-size:9px;font-weight:900;color:var(--fco)}.wahead b{font-size:12px;display:block}.wahead span{font-size:8px;color:var(--muted)}.feed{padding:9px}.post{background:#fff;border-radius:11px;padding:5px}.art{height:280px;border-radius:8px;background:linear-gradient(145deg,#083b77,#0f5a99);color:#fff;display:grid;place-items:center;text-align:center;position:relative;padding:20px}.art .type{color:var(--yellow);font-size:11px;font-weight:900;letter-spacing:.13em}.art h3{font:700 28px Space Grotesk;margin:11px 0 3px}.sponsor{position:absolute;left:12px;right:12px;bottom:12px;background:#fff;border-radius:9px;color:#16202a;padding:9px;text-align:left}.sponsor b{font-size:9px;display:block}.sponsor span{font-size:8px;color:var(--muted)}.copy{font-size:9px;line-height:1.5;padding:9px}.summary{margin-top:15px;border-top:1px solid var(--line);padding-top:13px}.row{display:flex;justify-content:space-between;font-size:10px;padding:5px 0}.row.total{font-size:15px;font-weight:900;border-top:1px solid var(--line);margin-top:6px;padding-top:11px}.approval{background:#fff9e9;border:1px solid #fedf89;border-radius:11px;padding:10px;margin-top:10px;font-size:9px;color:#7a2e0e}.success{background:#ecfdf5;border:1px solid #abefc6;color:#05603a;border-radius:11px;padding:11px;margin-top:10px;font-size:10px}.login{position:fixed;inset:0;background:#ffffffef;backdrop-filter:blur(10px);z-index:50;display:grid;place-items:center;padding:20px}.loginbox{width:min(430px,94vw);border:1px solid var(--line);border-radius:25px;padding:28px;background:#fff;box-shadow:0 25px 80px #10203018}.loginbox h2{font:700 31px Space Grotesk;margin:10px 0 7px}.loginbox p{font-size:11px;color:var(--muted)}.loginbox input{width:100%;border:1px solid var(--line);border-radius:11px;padding:11px;margin:5px 0}
@media(max-width:900px){.layout{grid-template-columns:1fr}.preview{position:static}}@media(max-width:600px){.placements{grid-template-columns:1fr}.shell{width:95vw}.hero{padding:30px 24px}}
</style>
</head>
<body>
<div class="login" id="login"><div class="loginbox"><div class="mark">MAX</div><div class="eyebrow">SPONSOR-LOGIN · DEMO</div><h2>Lokale Reichweite buchen.</h2><p>Für die Demo sind keine echten Zugangsdaten nötig.</p><input value="marketing@beispiel.ch"><input type="password" value="demo1234"><button class="btn" onclick="document.getElementById('login').classList.add('hidden')">Demo öffnen</button></div></div>
<header class="top"><div class="brand"><div class="mark">MAX</div><div><b>MAX Sponsor</b><span>Self-Service Marketplace</span></div></div><a href="/club">Vereins-Login</a></header>
<main class="shell">
  <section class="hero"><div class="eyebrow">MAX FOR BRANDS</div><h1>Deine Marke im <span>echten Sportmoment.</span></h1><p>Spiel auswählen, Placement wählen, Brand hinterlegen. Neue Sponsoren werden einmalig vom Verein freigegeben. Danach kann innerhalb der Clubregeln automatisiert gebucht werden.</p><div class="chips"><span>ab CHF 20</span><span>75 % an den Club</span><span>25 % MAX</span><span>MAXSTART25 Welcome Credit</span></div></section>

  <section class="layout">
    <div class="card">
      <div class="head"><div class="eyebrow">1 · SPIEL</div><h2>Wo willst du sichtbar sein?</h2></div>
      <div class="body">
        <div class="matches" id="matches"></div>
        <div style="margin-top:18px" class="eyebrow">2 · PLACEMENT</div>
        <div class="placements">
          <div class="placement active" data-name="Matchday" data-price="25" onclick="choosePlacement(this)"><b>Matchday</b><strong>CHF 25</strong><span>Vor dem Spiel</span></div>
          <div class="placement" data-name="Kickoff" data-price="20" onclick="choosePlacement(this)"><b>Kickoff</b><strong>CHF 20</strong><span>Zum Anpfiff</span></div>
          <div class="placement" data-name="Full Time" data-price="30" onclick="choosePlacement(this)"><b>Full Time</b><strong>CHF 30</strong><span>Resultat & Moment</span></div>
          <div class="placement" data-name="Player of the Day" data-price="35" onclick="choosePlacement(this)"><b>Player of the Day</b><strong>CHF 35</strong><span>höchste Shareability</span></div>
        </div>
        <div class="field"><label>Unternehmen</label><input id="sponsorName" value="Garage Keller AG" oninput="refresh()"></div>
        <div class="field"><label>Claim</label><input id="headline" value="Mobilität für Winterthur." oninput="refresh()"></div>
        <div class="field"><label>Coupon / MAX Credit</label><input id="coupon" placeholder="z.B. MAXSTART25" oninput="refresh()"></div>
      </div>
    </div>

    <aside class="card preview">
      <div class="head"><div class="eyebrow">LIVE PREVIEW</div><h2>So erscheint deine Marke.</h2></div>
      <div class="body">
        <div class="phone"><div class="screen"><div class="wahead"><div class="crest">FCO</div><div><b>FC Oberwinterthur</b><span>WhatsApp Channel</span></div></div><div class="feed"><div class="post"><div class="art"><div><div class="type" id="previewType">MATCHDAY</div><h3 id="previewOpponent">vs FC Pfäffikon</h3><div style="font-size:9px;color:#d9e6f5" id="previewWhen">Hegmatten · 16:30</div></div><div class="sponsor"><b id="previewSponsor">Garage Keller AG</b><span id="previewClaim">Mobilität für Winterthur.</span></div></div><div class="copy">MAX erstellt aus demselben Content zusätzlich eine 9:16 Status-Version. Share-ready und auf neue Follower optimiert.</div></div></div></div>
        <div class="summary"><div class="row"><span>Listenpreis</span><b id="listPrice">CHF 25.00</b></div><div class="row"><span>Club-Anteil 75 %</span><b id="clubShare">CHF 18.75</b></div><div class="row"><span>MAX Anteil</span><b id="maxShare">CHF 6.25</b></div><div class="row" id="discountRow" style="display:none"><span>MAX Welcome Credit</span><b id="discount">- CHF 6.25</b></div><div class="row total"><span>Du zahlst</span><span id="total">CHF 25.00</span></div></div>
        <div class="approval">Neue Brands werden zuerst vom Verein freigegeben. Die Demo belastet keine Zahlung.</div>
        <button class="btn" onclick="book()">Zur Club-Freigabe senden</button>
        <div class="success hidden" id="success"></div>
      </div>
    </aside>
  </section>
</main>
<script>
let matchId=null, placement='Matchday', price=25, matchData=null;
async function loadMatches(){
 const r=await fetch('/api/matches');const rows=await r.json();const el=document.getElementById('matches');
 el.innerHTML=rows.map((m,i)=>`<div class="match ${i===1?'active':''}" data-id="${m.id}" onclick='chooseMatch(this,${JSON.stringify(m).replace(/'/g,"&apos;")})'><b>${m.team} · FC Oberwinterthur vs ${m.opponent}</b><span>${m.kickoff} · ${m.venue} · ${m.competition}</span></div>`).join('');
 matchData=rows[1]||rows[0];matchId=matchData.id;refresh();
}
function chooseMatch(el,m){document.querySelectorAll('.match').forEach(x=>x.classList.remove('active'));el.classList.add('active');matchData=m;matchId=m.id;refresh()}
function choosePlacement(el){document.querySelectorAll('.placement').forEach(x=>x.classList.remove('active'));el.classList.add('active');placement=el.dataset.name;price=+el.dataset.price;refresh()}
function money(v){return 'CHF '+Number(v).toFixed(2)}
function refresh(){
 document.getElementById('previewType').textContent=placement.toUpperCase();document.getElementById('previewSponsor').textContent=document.getElementById('sponsorName').value||'Dein Unternehmen';document.getElementById('previewClaim').textContent=document.getElementById('headline').value||'Dein Claim';
 if(matchData){document.getElementById('previewOpponent').textContent='vs '+matchData.opponent;document.getElementById('previewWhen').textContent=matchData.venue+' · '+matchData.kickoff.slice(11,16)}
 const club=price*.75,max=price*.25,c=document.getElementById('coupon').value.trim().toUpperCase(),has=['MAXSTART25','FCO25'].includes(c),discount=has?max:0;
 document.getElementById('listPrice').textContent=money(price);document.getElementById('clubShare').textContent=money(club);document.getElementById('maxShare').textContent=money(max-discount);document.getElementById('discount').textContent='- '+money(discount);document.getElementById('discountRow').style.display=has?'flex':'none';document.getElementById('total').textContent=money(price-discount);
}
async function book(){
 if(!matchId)return;
 const payload={sponsor_name:document.getElementById('sponsorName').value||'Demo Sponsor',club:'FC Oberwinterthur',match_id:matchId,placement,headline:document.getElementById('headline').value,coupon:document.getElementById('coupon').value};
 const r=await fetch('/api/sponsor/campaign',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(payload)});const j=await r.json();
 const el=document.getElementById('success');el.classList.remove('hidden');el.textContent='✓ Anfrage #'+j.campaign_id+' erstellt · Status: wartet auf Club-Freigabe · Club erhält CHF '+j.club_share.toFixed(2);
}
loadMatches();
</script>
</body>
</html>"""


@app.get("/club", response_class=HTMLResponse)
def club_portal():
    return HTMLResponse(CLUB_HTML)


@app.get("/sponsor", response_class=HTMLResponse)
def sponsor_portal():
    return HTMLResponse(SPONSOR_HTML)
