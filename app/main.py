from __future__ import annotations
import os, sqlite3
from datetime import datetime
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

ROOT=Path(__file__).resolve().parent.parent
DB=Path(os.getenv("CLUBFLOW_DB_PATH", str(ROOT/"clubflow.db")))
app=FastAPI(title="FVRZ App · FC Oberwinterthur Pilot", version="0.5.0")

FIXTURES=[
("1. Mannschaft","FC Niederweningen 1","2026-09-26 18:00","Huebwis, Niederweningen","2. Liga · Gruppe 2",2,2,"finished"),
("Senioren 40+","FC Greifensee","2026-10-02 20:15","Hegmatten, Winterthur","Senioren 40+ · Gruppe 5",None,None,"scheduled"),
("Junioren D-9 a","FC Witikon a","2026-10-03 09:00","Hegmatten · Kunstrasen","Regional Cup Junioren D",None,None,"scheduled"),
("1. Mannschaft","FC Pfäffikon 1","2026-10-03 16:30","Hegmatten, Winterthur","2. Liga · Gruppe 2",None,None,"scheduled"),
("Junioren D-9 c","FC Zürich Mädchen U14 b","2026-10-04 10:00","Heerenschürli, Zürich","Trainingsspiel",None,None,"scheduled"),
("2. Mannschaft","FC Dielsdorf 2","2026-10-04 11:00","Erlen, Dielsdorf","4. Liga · Gruppe 6",None,None,"scheduled"),
("1. Mannschaft","SC Veltheim 1","2026-10-10 18:00","Flüeli, Winterthur","2. Liga · Gruppe 2",None,None,"scheduled"),
]

def conn():
    DB.parent.mkdir(parents=True, exist_ok=True)
    c=sqlite3.connect(DB); c.row_factory=sqlite3.Row; return c

def init():
    c=conn()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS matches(
      id INTEGER PRIMARY KEY, team TEXT, opponent TEXT, kickoff TEXT, venue TEXT,
      competition TEXT, gf INTEGER, ga INTEGER, status TEXT);
    CREATE TABLE IF NOT EXISTS content(
      id INTEGER PRIMARY KEY, match_id INTEGER, channel TEXT, kind TEXT, caption TEXT, status TEXT DEFAULT 'draft');
    CREATE TABLE IF NOT EXISTS sponsor_campaigns(
      id INTEGER PRIMARY KEY, sponsor_name TEXT, club TEXT, package TEXT, price INTEGER,
      headline TEXT, status TEXT DEFAULT 'booked', created_at TEXT DEFAULT CURRENT_TIMESTAMP);
    """)
    if c.execute("select count(*) from matches").fetchone()[0]==0:
        c.executemany("insert into matches(team,opponent,kickoff,venue,competition,gf,ga,status) values(?,?,?,?,?,?,?,?)",FIXTURES)
        c.commit()
        for m in c.execute("select * from matches").fetchall():
            kind="result" if m["status"]=="finished" else "matchday"
            for ch in ("whatsapp","instagram","facebook"):
                c.execute("insert into content(match_id,channel,kind,caption,status) values(?,?,?,?,?)",
                    (m["id"],ch,kind,caption(m,kind,ch),"draft"))
        c.commit()
    c.close()

def caption(m,kind,ch):
    if kind=="result":
        txt=f"FULL TIME 💛💙\n\nFC Oberwinterthur {m['gf']}:{m['ga']} {m['opponent']}\n\nHopp Oberi!"
    else:
        txt=f"MATCHDAY 💛💙\n\nFC Oberwinterthur 🆚 {m['opponent']}\n🗓 {m['kickoff']}\n📍 {m['venue']}\n🏆 {m['competition']}\n\nHopp Oberi!"
    if ch=="whatsapp": txt=txt.replace("MATCHDAY","⚽ *MATCHDAY*").replace("FULL TIME","🏁 *SCHLUSS*")
    return txt

@app.on_event("startup")
def startup(): init()

class Result(BaseModel):
    goals_for:int
    goals_against:int

@app.post("/api/matches/{mid}/finish")
def finish(mid:int,r:Result):
    c=conn(); m=c.execute("select * from matches where id=?",(mid,)).fetchone()
    if not m: raise HTTPException(404)
    c.execute("update matches set gf=?,ga=?,status='finished' where id=?",(r.goals_for,r.goals_against,mid))
    c.execute("delete from content where match_id=?",(mid,))
    m=dict(m); m["gf"]=r.goals_for; m["ga"]=r.goals_against; m["status"]="finished"
    for ch in ("whatsapp","instagram","facebook"):
        c.execute("insert into content(match_id,channel,kind,caption,status) values(?,?,?,?,?)",(mid,ch,"result",caption(m,"result",ch),"draft"))
    c.commit(); c.close(); return {"ok":True}

@app.post("/api/content/{cid}/{action}")
def content_action(cid:int,action:str):
    if action not in ("approve","publish"): raise HTTPException(400)
    c=conn(); row=c.execute("select * from content where id=?",(cid,)).fetchone()
    if not row: raise HTTPException(404)
    status="approved" if action=="approve" else "published"
    c.execute("update content set status=? where id=?",(status,cid)); c.commit(); c.close()
    return {"ok":True,"status":status}


class SponsorCampaign(BaseModel):
    sponsor_name:str
    club:str
    package:str
    price:int
    headline:str=""

@app.post("/api/sponsor/campaign")
def create_sponsor_campaign(campaign:SponsorCampaign):
    c=conn()
    cur=c.execute(
        "insert into sponsor_campaigns(sponsor_name,club,package,price,headline,status) values(?,?,?,?,?,?)",
        (campaign.sponsor_name,campaign.club,campaign.package,campaign.price,campaign.headline,"booked")
    )
    c.commit()
    cid=cur.lastrowid
    c.close()
    return {"ok":True,"campaign_id":cid,"status":"booked"}

@app.get("/health")
def health(): return {"status":"ok","club":"FC Oberwinterthur","version":"0.5.0"}

@app.get("/",response_class=HTMLResponse)
def home():
    c=conn()
    matches=[dict(x) for x in c.execute("select * from matches order by kickoff").fetchall()]
    items=[dict(x) for x in c.execute("""select content.*,matches.team,matches.opponent,matches.kickoff,matches.venue,matches.competition
       from content join matches on matches.id=content.match_id
       order by case content.status when 'draft' then 0 when 'approved' then 1 else 2 end, content.id desc""").fetchall()]
    c.close()

    wa_items=[x for x in items if x["channel"]=="whatsapp"]
    preview=wa_items[:3]
    upcoming=next((m for m in matches if m["status"]!="finished" and "Pfäffikon" in m["opponent"]), next((m for m in matches if m["status"]!="finished"), matches[0]))
    finished=next((m for m in matches if m["status"]=="finished"), None)

    def post_visual(x, compact=False):
        if x["kind"]=="result":
            score="3:1" if "Pfäffikon" in x["opponent"] else "2:2"
            return f"""<div class='post-art result-art'>
              <div class='paint paint-a'></div><div class='paint paint-b'></div>
              <span class='micro'>FULL TIME</span>
              <div class='versus'>
                <div><div class='crest mini'>FCO</div><small>FC Oberwinterthur</small></div>
                <div class='score-big'>{score}</div>
                <div><div class='opp-crest'>FC</div><small>{x['opponent'].replace(" 1","")}</small></div>
              </div>
              <strong>+3 Punkte</strong>
              <em>Hopp Oberi 💛💙</em>
              <div class='sponsor-strip'>RESULT PRESENTED BY · DEMO PARTNER</div>
            </div>"""
        return f"""<div class='post-art match-art'>
          <div class='paint paint-a'></div><div class='paint paint-b'></div>
          <span class='micro'>MATCHDAY</span>
          <div class='match-title'>FC Oberwinterthur</div>
          <div class='vs'>VS</div>
          <div class='match-title'>{x['opponent'].replace(" 1","")}</div>
          <div class='match-meta'>📅 {x['kickoff'][8:10]}.{x['kickoff'][5:7]}.{x['kickoff'][:4]} · {x['kickoff'][11:16]} &nbsp; 📍 {x['venue'].split(",")[0]}</div>
          <div class='sponsor-strip'>PRESENTED BY · DEMO PARTNER</div>
        </div>"""

    phone_posts=""
    if preview:
        for i,x in enumerate(preview):
            phone_posts += f"""<div class='wa-post'>
              {post_visual(x)}
              <div class='wa-copy'>{x['caption'].replace(chr(10),'<br>')}</div>
              <div class='wa-meta'><span>💛 💙 👍 {42+i*13}</span><span>{'08:12' if i==0 else '18:22' if i==1 else '20:14'} ↗</span></div>
            </div>"""
    phone_posts += """<div class='wa-post recap'>
      <div class='recap-card'>
        <b>Wochenend-Update</b>
        <div>⚽ 1. Mannschaft <strong>✅ 3:1</strong></div>
        <div>⚽ 2. Mannschaft <strong>🤝 2:2</strong></div>
        <div>👥 Junioren D-9 a <strong>✅ 4:0</strong></div>
        <div>👥 Senioren 40+ <strong>❌ 1:2</strong></div>
      </div>
      <div class='wa-copy'>Alle Resultate auf einen Blick.</div>
      <div class='wa-meta'><span>💛 💙 👍 36</span><span>20:14 ↗</span></div>
    </div>"""

    queue_rows=""
    for x in items[:8]:
        kind="Resultat" if x["kind"]=="result" else "Matchday"
        channel_icon={"whatsapp":"◉","instagram":"◎","facebook":"f"}.get(x["channel"],"•")
        action=(f"<button onclick=\\\"act({x['id']},'approve')\\\">Freigeben</button>" if x["status"]=="draft"
                else f"<button onclick=\\\"act({x['id']},'publish')\\\">Publizieren</button>" if x["status"]=="approved"
                else "<span class='done-chip'>Publiziert ✓</span>")
        queue_rows += f"""<div class='queue-row'>
          <div class='channel-dot {x['channel']}'>{channel_icon}</div>
          <div class='queue-main'><b>{kind} · {x['team']}</b><span>{x['channel'].title()} · {x['opponent']}</span></div>
          <span class='state {x['status']}'>{x['status']}</span>{action}
        </div>"""

    games=""
    for m in matches:
        result=f"<b class='score'>{m['gf']}:{m['ga']}</b>" if m["status"]=="finished" else f"<button class='text-btn' onclick='finish({m['id']})'>Resultat setzen</button>"
        games += f"""<div class='game'>
          <div class='game-date'><b>{m['kickoff'][8:10]}.{m['kickoff'][5:7]}</b><span>{m['kickoff'][11:16]}</span></div>
          <div><b>{m['team']}</b><strong>FC Oberwinterthur – {m['opponent']}</strong><small>{m['competition']} · {m['venue']}</small></div>
          <div>{result}</div>
        </div>"""

    next_label=f"{upcoming['kickoff'][8:10]}.{upcoming['kickoff'][5:7]}. · {upcoming['kickoff'][11:16]}"
    return HTMLResponse(f"""<!doctype html>
<html lang='de'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>FVRZ App · FC Oberwinterthur</title>
<style>
:root{{--yellow:#ffd817;--blue:#092e66;--blue2:#0e427f;--ink:#0d1828;--muted:#667085;--bg:#f2f4f7;--line:#e4e7ec;--green:#25d366}}
*{{box-sizing:border-box}}html{{scroll-behavior:smooth}}body{{margin:0;background:var(--bg);font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:var(--ink)}}button{{font:inherit}}
.topbar{{height:66px;background:#fff;border-bottom:1px solid var(--line);display:flex;align-items:center;justify-content:space-between;padding:0 4vw;position:sticky;top:0;z-index:20}}
.brand{{display:flex;align-items:center;gap:12px}}.brandmark{{width:38px;height:38px;border-radius:50%;background:var(--yellow);border:3px solid var(--blue);display:grid;place-items:center;color:var(--blue);font-weight:1000;font-size:12px}}.brand b{{display:block}}.brand span{{font-size:11px;color:var(--muted)}}
.live{{display:flex;align-items:center;gap:8px;font-size:12px;font-weight:800;color:#067647;background:#ecfdf3;padding:8px 11px;border-radius:999px}}.dot{{width:8px;height:8px;background:#12b76a;border-radius:50%}}
.wrap{{width:min(1240px,92vw);margin:28px auto 60px}}
.hero{{display:grid;grid-template-columns:1.05fr .95fr;gap:28px;background:linear-gradient(135deg,#061f49 0%,#0d3b75 72%,#103968 100%);border-radius:30px;min-height:680px;overflow:hidden;box-shadow:0 24px 70px #0b234218}}
.hero-copy{{padding:64px 20px 54px 58px;color:#fff;display:flex;flex-direction:column;justify-content:center}}
.kicker{{font-size:11px;letter-spacing:.16em;font-weight:900;color:var(--yellow)}}.hero h1{{font-size:68px;line-height:.94;letter-spacing:-.055em;margin:16px 0 20px;max-width:650px}}.hero p{{font-size:17px;line-height:1.6;color:#ced9e8;max-width:600px}}
.chips{{display:flex;gap:8px;flex-wrap:wrap;margin-top:24px}}.chips span{{font-size:11px;font-weight:800;padding:9px 11px;border:1px solid #ffffff24;background:#ffffff0d;border-radius:999px}}
.flow{{display:flex;align-items:center;gap:7px;flex-wrap:wrap;margin-top:38px}}.flow b{{font-size:12px;background:#fff;color:var(--blue);padding:9px 11px;border-radius:9px}}.flow i{{font-style:normal;color:#7da0cc}}
.phone-zone{{position:relative;display:flex;align-items:center;justify-content:center;padding:34px 44px 34px 14px}}.glow{{position:absolute;width:440px;height:440px;border-radius:50%;background:var(--yellow);filter:blur(90px);opacity:.12}}
.phone{{width:min(390px,100%);height:620px;background:#111;border:7px solid #161616;border-radius:45px;padding:7px;box-shadow:0 30px 70px #0008;position:relative;z-index:2}}
.screen{{height:100%;background:#efeae2;border-radius:33px;overflow:hidden;display:flex;flex-direction:column}}.notch{{position:absolute;top:12px;left:50%;transform:translateX(-50%);width:98px;height:25px;background:#111;border-radius:0 0 18px 18px;z-index:5}}
.wa-head{{background:#fff;padding:24px 15px 10px;display:flex;gap:10px;align-items:center;border-bottom:1px solid #ececec}}.wa-logo{{width:42px;height:42px;border-radius:50%;background:var(--yellow);border:2px solid var(--blue);display:grid;place-items:center;color:var(--blue);font-weight:1000;font-size:11px}}.wa-title{{flex:1}}.wa-title b{{font-size:15px;display:block}}.wa-title span{{font-size:11px;color:#667085}}.wa-menu{{font-size:20px;color:#344054}}
.wa-tabs{{background:#fff;display:flex;gap:3px;padding:0 10px 9px}}.wa-tabs span{{flex:1;text-align:center;font-size:11px;padding:7px;border-radius:999px}}.wa-tabs .active{{background:#e7f5ee;color:#176b4e;font-weight:800}}
.wa-feed{{padding:8px 7px 18px;overflow:auto;scrollbar-width:none}}.wa-feed::-webkit-scrollbar{{display:none}}.wa-post{{background:#fff;border-radius:12px;margin-bottom:8px;padding:5px;box-shadow:0 1px 2px #00000012}}
.post-art{{height:185px;border-radius:9px;overflow:hidden;position:relative;padding:18px;text-align:center;color:white;display:flex;flex-direction:column;align-items:center;justify-content:center;background:linear-gradient(145deg,#082b60,#0d4e8c)}}.paint{{position:absolute;background:var(--yellow);opacity:.96;transform:rotate(-8deg)}}.paint-a{{width:240px;height:32px;left:-80px;top:5px}}.paint-b{{width:250px;height:18px;right:-80px;bottom:18px}}.micro{{position:absolute;top:12px;left:14px;font-size:18px;font-weight:1000;font-style:italic;color:var(--yellow);letter-spacing:.02em}}.match-title{{font-size:18px;font-weight:900;position:relative}}.vs{{font-size:12px;color:var(--yellow);font-weight:1000;margin:5px}}.match-meta{{font-size:10px;margin-top:15px;color:#e6edf7;position:relative}}.sponsor-strip{{position:absolute;right:12px;bottom:6px;font-size:7px;color:#142d50;font-weight:900;background:var(--yellow);padding:3px 6px;border-radius:3px}}
.versus{{width:100%;display:grid;grid-template-columns:1fr auto 1fr;align-items:center;gap:8px;position:relative}}.crest,.opp-crest{{margin:auto;width:42px;height:42px;border-radius:50%;display:grid;place-items:center;font-size:11px;font-weight:1000}}.crest{{background:var(--yellow);color:var(--blue);border:2px solid #fff}}.opp-crest{{background:#fff;color:#8b1d2c;border:3px solid #8b1d2c}}.versus small{{font-size:8px;display:block;margin-top:5px}}.score-big{{font-size:46px;font-weight:1000;color:var(--yellow);letter-spacing:-.06em}}.result-art>strong{{font-size:15px;color:var(--yellow);margin-top:6px}}.result-art>em{{font-style:normal;font-size:10px;margin-top:3px}}.wa-copy{{font-size:11px;line-height:1.45;padding:8px 8px 4px}}.wa-meta{{display:flex;justify-content:space-between;align-items:center;color:#7c8490;font-size:9px;padding:2px 8px 6px}}.wa-meta span:first-child{{background:#f2f4f7;border-radius:999px;padding:4px 7px}}
.recap-card{{background:#f9fbfd;border:1px solid #e2e8f0;border-radius:9px;padding:13px;color:var(--blue);background-image:linear-gradient(120deg,#fff 70%,#fff5a8)}}.recap-card>b{{font-size:19px;display:block;margin-bottom:9px}}.recap-card div{{display:flex;justify-content:space-between;font-size:10px;padding:2px 0}}.recap-card strong{{color:var(--blue)}}
.section{{margin-top:30px}}.section-head{{display:flex;align-items:end;justify-content:space-between;margin-bottom:13px}}.section-head h2{{margin:4px 0 0;font-size:27px;letter-spacing:-.03em}}.section-head p{{font-size:12px;color:var(--muted);margin:0}}
.dashboard{{display:grid;grid-template-columns:1.1fr .9fr;gap:18px}}.panel{{background:#fff;border:1px solid var(--line);border-radius:20px;overflow:hidden;box-shadow:0 10px 30px #10182808}}.panel-title{{padding:18px 20px;border-bottom:1px solid var(--line);display:flex;align-items:center;justify-content:space-between}}.panel-title b{{font-size:15px}}.panel-title span{{font-size:10px;color:#667085}}
.queue-row{{display:grid;grid-template-columns:34px 1fr auto auto;gap:11px;align-items:center;padding:13px 18px;border-bottom:1px solid #f0f2f5}}.channel-dot{{width:30px;height:30px;border-radius:50%;display:grid;place-items:center;color:white;font-weight:900}}.channel-dot.whatsapp{{background:#25d366}}.channel-dot.instagram{{background:#ad438e}}.channel-dot.facebook{{background:#1877f2}}.queue-main b,.queue-main span{{display:block}}.queue-main b{{font-size:12px}}.queue-main span{{font-size:10px;color:var(--muted);margin-top:3px}}.state{{font-size:9px;border-radius:999px;background:#f2f4f7;padding:5px 7px;color:#475467}}.state.approved{{background:#fffaeb;color:#b54708}}.state.published{{background:#ecfdf3;color:#067647}}.queue-row button{{border:0;background:var(--blue);color:white;border-radius:8px;padding:8px 9px;font-size:10px;font-weight:800;cursor:pointer}}.done-chip{{font-size:10px;color:#067647;font-weight:800}}
.stats{{padding:18px;display:grid;grid-template-columns:1fr 1fr;gap:10px}}.stat{{background:#f8fafc;border:1px solid #edf0f3;border-radius:14px;padding:16px}}.stat small{{display:block;color:var(--muted);font-size:10px}}.stat b{{display:block;font-size:27px;margin-top:3px;color:var(--blue)}}.sponsor-demo{{margin:0 18px 18px;border-radius:14px;background:var(--yellow);padding:20px;color:var(--blue)}}.sponsor-demo small{{font-size:9px;font-weight:900;letter-spacing:.12em}}.sponsor-demo b{{display:block;font-size:22px;margin:6px 0 4px}}.sponsor-demo p{{font-size:11px;margin:0;opacity:.75}}
.games-panel{{background:#fff;border:1px solid var(--line);border-radius:20px;overflow:hidden}}.game{{display:grid;grid-template-columns:70px 1fr auto;gap:15px;align-items:center;padding:15px 18px;border-bottom:1px solid #f1f3f5}}.game:last-child{{border:0}}.game-date b,.game-date span{{display:block}}.game-date b{{font-size:17px;color:var(--blue)}}.game-date span{{font-size:10px;color:var(--muted)}}.game>div:nth-child(2)>b{{font-size:9px;text-transform:uppercase;color:#98a2b3;display:block;margin-bottom:3px}}.game strong{{font-size:12px;display:block}}.game small{{font-size:10px;color:var(--muted);display:block;margin-top:3px}}.text-btn{{border:0;background:none;color:#175cd3;font-size:10px;font-weight:800;cursor:pointer}}.score{{font-size:20px;color:var(--blue)}}.foot{{font-size:10px;color:#98a2b3;padding:25px 0;text-align:center}}
@media(max-width:960px){{.hero{{grid-template-columns:1fr;min-height:auto}}.hero-copy{{padding:46px 38px 16px}}.phone-zone{{padding:20px 20px 42px}}.dashboard{{grid-template-columns:1fr}}}}
@media(max-width:620px){{.wrap{{width:94vw;margin-top:14px}}.hero{{border-radius:22px}}.hero-copy{{padding:36px 24px 10px}}.hero h1{{font-size:48px}}.phone{{width:340px;height:590px}}.queue-row{{grid-template-columns:32px 1fr auto}}.queue-row>button,.done-chip{{grid-column:2/4;justify-self:start}}.state{{grid-column:3}}.game{{grid-template-columns:58px 1fr}}.game>div:last-child{{grid-column:2}}.topbar{{padding:0 3vw}}}}
</style></head>
<body>
<div class='topbar'><div class='brand'><div class='brandmark'>FCO</div><div><b>FVRZ App</b><span>FC Oberwinterthur · Pilot</span></div></div><div style='display:flex;gap:10px;align-items:center'><a href='/sponsor' style='font-size:11px;font-weight:900;color:#092e66;text-decoration:none;background:#ffd817;padding:9px 11px;border-radius:999px'>Sponsor Portal</a><div class='live'><i class='dot'></i> Live Demo</div></div></div>
<main class='wrap'>
<section class='hero'>
  <div class='hero-copy'>
    <div class='kicker'>DIGITAL CLUB ENGINE</div>
    <h1>Ein Spiel.<br>Alle Kanäle.</h1>
    <p>Die App verwandelt Matchdaten automatisch in fertige Club-Kommunikation – mit Fokus auf WhatsApp, Sponsor-Platzierung und einem einfachen Freigabe-Workflow.</p>
    <div class='chips'><span>WhatsApp first</span><span>Instagram</span><span>Facebook</span><span>Sponsoring</span><span>Approval Mode</span></div>
    <div class='flow'><b>FVRZ Match</b><i>→</i><b>Automation</b><i>→</i><b>Content</b><i>→</i><b>Freigabe</b><i>→</i><b>Live</b></div>
  </div>
  <div class='phone-zone'><div class='glow'></div>
    <div class='phone'><div class='notch'></div><div class='screen'>
      <div class='wa-head'><div class='wa-logo'>FCO</div><div class='wa-title'><b>FC Oberwinterthur</b><span>WhatsApp Channel Preview</span></div><div class='wa-menu'>⋮</div></div>
      <div class='wa-tabs'><span class='active'>Updates</span><span>Links</span><span>Medien</span></div>
      <div class='wa-feed'>{phone_posts}</div>
    </div></div>
  </div>
</section>

<section class='section'>
  <div class='section-head'><div><div class='kicker' style='color:#175cd3'>AUTOMATION CONTROL</div><h2>Content Queue</h2></div><p>Nächster Match-Trigger: {next_label}</p></div>
  <div class='dashboard'>
    <div class='panel'><div class='panel-title'><b>Bereit zur Freigabe</b><span>WhatsApp · Instagram · Facebook</span></div>{queue_rows}</div>
    <div class='panel'><div class='panel-title'><b>Pilot-Cockpit</b><span>FC Oberwinterthur</span></div>
      <div class='stats'><div class='stat'><small>Teams</small><b>24</b></div><div class='stat'><small>Kanäle</small><b>3</b></div><div class='stat'><small>Automationen</small><b>4</b></div><div class='stat'><small>Manueller Aufwand</small><b>&lt; 1 min</b></div></div>
      <div class='sponsor-demo'><small>DIGITAL SPONSOR INVENTORY</small><b>Demo Partner</b><p>Matchday · Result · Weekend Recap · WhatsApp + Social</p></div>
    </div>
  </div>
</section>

<section class='section'>
  <div class='section-head'><div><div class='kicker' style='color:#175cd3'>MATCH FEED</div><h2>Spiele & Trigger</h2></div><p>Resultat setzen → Content wird neu erzeugt</p></div>
  <div class='games-panel'>{games}</div>
</section>
<div class='foot'>Pilot-Demo mit öffentlich sichtbaren Club-/FVRZ-Informationen. Für kommerziellen Betrieb ist ein offizieller bzw. lizenzierter Datenzugang vorgesehen.</div>
</main>
<script>
async function act(id,a){{await fetch('/api/content/'+id+'/'+a,{{method:'POST'}});location.reload()}}
async function finish(id){{let s=prompt('Resultat aus Sicht FC Oberwinterthur, z.B. 3:1');if(!s)return;let p=s.split(':');if(p.length!==2)return;await fetch('/api/matches/'+id+'/finish',{{method:'POST',headers:{{'content-type':'application/json'}},body:JSON.stringify({{goals_for:+p[0],goals_against:+p[1]}})}});location.reload()}}
</script>
</body></html>""")


@app.get("/sponsor",response_class=HTMLResponse)
def sponsor_portal():
    return HTMLResponse("""<!doctype html>
<html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sponsor Portal · FVRZ App</title>
<style>
:root{--navy:#071c3d;--blue:#0b3c78;--yellow:#ffd817;--green:#25d366;--bg:#f4f6f8;--line:#e4e7ec;--muted:#667085;--ink:#101828;--white:#fff}
*{box-sizing:border-box}body{margin:0;font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:var(--bg);color:var(--ink)}
button,input,textarea{font:inherit}.hidden{display:none!important}.top{height:68px;background:#fff;border-bottom:1px solid var(--line);display:flex;align-items:center;justify-content:space-between;padding:0 4vw;position:sticky;top:0;z-index:30}
.brand{display:flex;align-items:center;gap:11px}.mark{width:38px;height:38px;border-radius:11px;background:var(--navy);color:var(--yellow);display:grid;place-items:center;font-weight:1000}.brand b{display:block}.brand span{font-size:11px;color:var(--muted)}
.user{display:flex;align-items:center;gap:10px;font-size:12px}.avatar{width:32px;height:32px;border-radius:50%;background:#eef2f6;display:grid;place-items:center;font-weight:900;color:var(--blue)}
.shell{width:min(1250px,94vw);margin:24px auto 60px}.hero{background:linear-gradient(135deg,#071c3d,#0b3c78);color:#fff;border-radius:26px;padding:44px 48px;display:flex;justify-content:space-between;align-items:end;gap:24px}.hero small{color:var(--yellow);font-weight:900;letter-spacing:.14em}.hero h1{font-size:48px;line-height:1;margin:9px 0 12px;letter-spacing:-.04em}.hero p{margin:0;color:#cbd5e1;max-width:680px;line-height:1.5}.steps{display:flex;gap:6px;flex-wrap:wrap}.steps span{font-size:10px;padding:8px 10px;border-radius:999px;background:#ffffff12;border:1px solid #ffffff1f}
.layout{display:grid;grid-template-columns:1.08fr .92fr;gap:18px;margin-top:20px}.card{background:#fff;border:1px solid var(--line);border-radius:20px;box-shadow:0 8px 24px #10182808}.pad{padding:22px}.section-title{display:flex;justify-content:space-between;align-items:end;margin-bottom:14px}.section-title h2{margin:4px 0 0;font-size:22px}.eyebrow{font-size:10px;font-weight:900;letter-spacing:.13em;color:#175cd3}.muted{font-size:11px;color:var(--muted)}
.club-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}.club{border:1px solid var(--line);border-radius:14px;padding:14px;cursor:pointer;transition:.16s;background:#fff}.club:hover{border-color:#9db6d3}.club.active{border:2px solid var(--blue);background:#f4f8fd}.club-logo{width:40px;height:40px;border-radius:50%;display:grid;place-items:center;background:var(--yellow);border:2px solid var(--blue);color:var(--blue);font-weight:1000;font-size:10px;margin-bottom:10px}.club b{font-size:12px;display:block}.club span{font-size:10px;color:var(--muted)}
.packages{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-top:14px}.pkg{border:1px solid var(--line);border-radius:15px;padding:16px;cursor:pointer;position:relative;min-height:190px}.pkg.active{border:2px solid var(--blue);background:#f7faff}.pkg.popular:before{content:"BELIEBT";position:absolute;top:-9px;right:10px;background:var(--yellow);color:var(--navy);font-size:8px;font-weight:1000;padding:4px 6px;border-radius:999px}.pkg h3{font-size:14px;margin:0 0 4px}.price{font-size:25px;font-weight:1000;color:var(--blue)}.price small{font-size:9px;color:var(--muted);font-weight:600}.pkg ul{padding-left:17px;margin:10px 0 0;font-size:10px;line-height:1.7;color:#475467}
.form-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px}.field label{display:block;font-size:10px;font-weight:800;margin-bottom:6px}.field input,.field textarea{width:100%;border:1px solid #d0d5dd;border-radius:10px;padding:11px 12px;background:#fff;outline:none}.field input:focus,.field textarea:focus{border-color:#6b9bd1;box-shadow:0 0 0 3px #dbeafe}.field.full{grid-column:1/-1}.upload{border:1.5px dashed #cbd5e1;border-radius:13px;padding:14px;background:#f8fafc}.upload input{font-size:10px;padding:0;border:0}.upload .hint{font-size:9px;color:var(--muted);margin-top:5px}
.preview-wrap{position:sticky;top:88px}.tabs{display:flex;gap:5px;margin-bottom:10px}.tabs button{border:0;background:#eef2f6;border-radius:999px;padding:8px 10px;font-size:10px;font-weight:800;cursor:pointer}.tabs button.active{background:var(--navy);color:#fff}.phone{width:min(360px,100%);margin:auto;background:#121212;border:6px solid #151515;border-radius:42px;padding:7px;box-shadow:0 24px 55px #0f172a22}.screen{background:#efeae2;border-radius:31px;overflow:hidden;min-height:600px}.wa-head{background:#fff;padding:23px 13px 10px;display:flex;gap:9px;align-items:center}.fco{width:38px;height:38px;border-radius:50%;background:var(--yellow);border:2px solid var(--blue);display:grid;place-items:center;color:var(--blue);font-size:10px;font-weight:1000}.wa-head b{font-size:13px;display:block}.wa-head span{font-size:9px;color:var(--muted)}.wa-feed{padding:9px}.wa-post{background:#fff;border-radius:11px;padding:5px;box-shadow:0 1px 2px #0002}.art{height:250px;background:linear-gradient(145deg,#062552,#0b4a8b);border-radius:8px;color:#fff;position:relative;overflow:hidden;display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;padding:20px}.slash{position:absolute;background:var(--yellow);width:280px;height:30px;transform:rotate(-8deg);top:5px;left:-75px}.slash.two{top:auto;bottom:18px;left:auto;right:-95px;height:17px}.art .type{position:absolute;top:15px;left:15px;color:var(--yellow);font-size:24px;font-weight:1000;font-style:italic}.art .clubname{font-size:21px;font-weight:1000}.art .vs{color:var(--yellow);font-size:11px;font-weight:900;margin:5px}.art .opp{font-size:18px;font-weight:900}.art .when{font-size:10px;color:#d6e0ed;margin-top:14px}.sponsor-brand{position:absolute;bottom:10px;left:12px;right:12px;background:#fff;border-radius:8px;padding:8px 10px;color:#102a4f;display:flex;align-items:center;gap:9px;text-align:left}.logo-slot{width:42px;height:30px;border-radius:6px;background:#f2f4f7;display:grid;place-items:center;overflow:hidden;font-size:8px;font-weight:900}.logo-slot img{width:100%;height:100%;object-fit:contain}.sponsor-brand b{font-size:9px;display:block}.sponsor-brand span{font-size:8px;color:#667085}.copy{font-size:10px;line-height:1.45;padding:8px 7px}.reactions{display:flex;justify-content:space-between;color:#7d8590;font-size:9px;padding:0 7px 6px}.reaction-pill{background:#f2f4f7;border-radius:999px;padding:4px 6px}
.order{margin-top:14px;border-top:1px solid var(--line);padding-top:14px}.order-row{display:flex;justify-content:space-between;font-size:11px;padding:5px 0}.order-row.total{font-size:15px;font-weight:900;border-top:1px solid var(--line);margin-top:7px;padding-top:11px}.cta{width:100%;border:0;background:var(--navy);color:#fff;padding:13px 15px;border-radius:11px;font-weight:900;cursor:pointer;margin-top:12px}.cta:hover{background:#0d356e}.subcta{width:100%;border:1px solid var(--line);background:#fff;padding:10px;border-radius:10px;font-weight:800;cursor:pointer;margin-top:8px}
.success{background:#ecfdf3;border:1px solid #abefc6;color:#05603a;border-radius:14px;padding:15px;margin-top:12px;font-size:11px}.success b{display:block;font-size:14px;margin-bottom:3px}
.login-overlay{position:fixed;inset:0;background:linear-gradient(135deg,#04152eeb,#0b3c78ef);z-index:100;display:grid;place-items:center;padding:20px}.login{width:min(430px,95vw);background:#fff;border-radius:24px;padding:30px;box-shadow:0 30px 90px #0006}.login-mark{width:48px;height:48px;border-radius:14px;background:var(--navy);color:var(--yellow);display:grid;place-items:center;font-weight:1000;margin-bottom:20px}.login h2{font-size:28px;margin:0 0 8px}.login p{color:var(--muted);font-size:12px;line-height:1.5}.login input{width:100%;padding:12px;border:1px solid #d0d5dd;border-radius:10px;margin-top:8px}.demo-note{background:#fffaeb;color:#7a2e0e;border-radius:10px;padding:10px;font-size:10px;margin-top:12px}
@media(max-width:950px){.layout{grid-template-columns:1fr}.preview-wrap{position:static}.hero{display:block}.steps{margin-top:20px}}@media(max-width:640px){.shell{width:96vw}.hero{padding:32px 24px}.hero h1{font-size:38px}.club-grid,.packages{grid-template-columns:1fr}.form-grid{grid-template-columns:1fr}.field.full{grid-column:auto}.phone{width:330px}.top{padding:0 3vw}}
</style></head>
<body>
<div class="login-overlay" id="loginOverlay">
  <div class="login">
    <div class="login-mark">SP</div>
    <div class="eyebrow">SPONSOR PORTAL</div>
    <h2>Willkommen zurück</h2>
    <p>Wähle deinen Verein, buche digitale Sponsoring-Flächen und sieh bereits vor der Buchung, wie deine Marke im Club-Content erscheint.</p>
    <input id="loginEmail" value="marketing@garage-keller.ch" placeholder="E-Mail">
    <input type="password" value="demo1234" placeholder="Passwort">
    <button class="cta" onclick="loginDemo()">Demo-Zugang öffnen</button>
    <div class="demo-note">Demo-Login: keine echten Zugangsdaten erforderlich.</div>
  </div>
</div>

<div class="top">
  <div class="brand"><div class="mark">SP</div><div><b>Sponsor Portal</b><span>FVRZ App · Self Service</span></div></div>
  <div class="user"><span id="topSponsor">Garage Keller AG</span><div class="avatar">GK</div></div>
</div>

<main class="shell">
  <section class="hero">
    <div><small>SPONSOR SELF-SERVICE</small><h1>Deine Marke.<br>Direkt im Spiel.</h1><p>Verein auswählen, Paket buchen, Logo hochladen und den fertigen Post sofort als Vorschau sehen. Der Club muss nur noch freigeben.</p></div>
    <div class="steps"><span>1 Verein</span><span>2 Paket</span><span>3 Branding</span><span>4 Preview</span><span>5 Buchen</span></div>
  </section>

  <div class="layout">
    <div>
      <section class="card pad">
        <div class="section-title"><div><div class="eyebrow">1 · VEREIN</div><h2>Wo willst du sichtbar sein?</h2></div><div class="muted">Demo-Auswahl</div></div>
        <div class="club-grid">
          <div class="club active" data-club="FC Oberwinterthur" onclick="selectClub(this)"><div class="club-logo">FCO</div><b>FC Oberwinterthur</b><span>Winterthur · Demo</span></div>
          <div class="club" data-club="FC Seuzach" onclick="selectClub(this)"><div class="club-logo">FCS</div><b>FC Seuzach</b><span>Region Winterthur · Demo</span></div>
          <div class="club" data-club="FC Töss" onclick="selectClub(this)"><div class="club-logo">FCT</div><b>FC Töss</b><span>Winterthur · Demo</span></div>
        </div>
      </section>

      <section class="card pad" style="margin-top:14px">
        <div class="section-title"><div><div class="eyebrow">2 · PAKET</div><h2>Wähle dein Sponsoring</h2></div><div class="muted">Preise nur Demo</div></div>
        <div class="packages">
          <div class="pkg" data-name="Matchday Partner" data-price="590" onclick="selectPackage(this)">
            <h3>Matchday Partner</h3><div class="price">CHF 590 <small>/ Saison</small></div>
            <ul><li>Matchday Posts</li><li>WhatsApp + Instagram</li><li>Logo im Footer</li><li>Basis-Reporting</li></ul>
          </div>
          <div class="pkg active popular" data-name="Digital Partner" data-price="1490" onclick="selectPackage(this)">
            <h3>Digital Partner</h3><div class="price">CHF 1'490 <small>/ Saison</small></div>
            <ul><li>Matchday + Result</li><li>Weekend Recap</li><li>WhatsApp + Social</li><li>Logo + Claim</li><li>Monatsreport</li></ul>
          </div>
          <div class="pkg" data-name="Season Partner" data-price="3900" onclick="selectPackage(this)">
            <h3>Season Partner</h3><div class="price">CHF 3'900 <small>/ Saison</small></div>
            <ul><li>Alle Digital-Formate</li><li>Exklusive Placements</li><li>Kampagnen-Content</li><li>Priority Slot</li><li>Reporting Dashboard</li></ul>
          </div>
        </div>
      </section>

      <section class="card pad" style="margin-top:14px">
        <div class="section-title"><div><div class="eyebrow">3 · BRANDING</div><h2>Deine Inhalte</h2></div><div class="muted">Live in der Vorschau</div></div>
        <div class="form-grid">
          <div class="field"><label>Unternehmen</label><input id="sponsorName" value="Garage Keller AG" oninput="updatePreview()"></div>
          <div class="field"><label>Claim / Kurztext</label><input id="headline" value="Mobilität für Winterthur." oninput="updatePreview()"></div>
          <div class="field full"><label>Logo</label><div class="upload"><input type="file" id="logoInput" accept="image/*" onchange="loadLogo(event)"><div class="hint">PNG, JPG oder SVG · Vorschau erscheint sofort</div></div></div>
          <div class="field full"><label>Eigener Kampagnen-Content</label><div class="upload"><input type="file" id="assetInput" accept="image/*,video/*,.pdf" onchange="assetChosen(event)"><div class="hint" id="assetHint">Optional: Bild, Video oder PDF hochladen</div></div></div>
          <div class="field full"><label>Begleittext</label><textarea id="copyText" rows="3" oninput="updatePreview()">Heute mit uns zum Heimspiel – Hopp Oberi! 💛💙</textarea></div>
        </div>
      </section>
    </div>

    <aside class="preview-wrap">
      <section class="card pad">
        <div class="section-title"><div><div class="eyebrow">4 · LIVE PREVIEW</div><h2>So sieht dein Placement aus</h2></div><div class="muted">Mockup</div></div>
        <div class="tabs"><button class="active">WhatsApp</button><button onclick="alert('Instagram-Preview kommt als nächster Schritt.')">Instagram</button><button onclick="alert('Facebook-Preview kommt als nächster Schritt.')">Facebook</button></div>
        <div class="phone"><div class="screen">
          <div class="wa-head"><div class="fco" id="clubLogo">FCO</div><div><b id="waClub">FC Oberwinterthur</b><span>WhatsApp Channel</span></div></div>
          <div class="wa-feed"><div class="wa-post">
            <div class="art"><div class="slash"></div><div class="slash two"></div><div class="type">MATCHDAY</div>
              <div class="clubname" id="artClub">FC Oberwinterthur</div><div class="vs">VS</div><div class="opp">FC Pfäffikon</div>
              <div class="when">Sa, 03.10.2026 · 16:30 · Hegmatten</div>
              <div class="sponsor-brand"><div class="logo-slot" id="logoSlot">LOGO</div><div><b id="previewSponsor">Garage Keller AG</b><span id="previewClaim">Mobilität für Winterthur.</span></div></div>
            </div>
            <div class="copy"><b>⚽ MATCHDAY</b><br><span id="copyClub">FC Oberwinterthur</span> vs FC Pfäffikon<br>🕓 16:30 Uhr · 📍 Hegmatten<br><br><span id="previewCopy">Heute mit uns zum Heimspiel – Hopp Oberi! 💛💙</span></div>
            <div class="reactions"><span class="reaction-pill">💛 💙 👍 42</span><span>08:12 ↗</span></div>
          </div></div>
        </div></div>

        <div class="order">
          <div class="order-row"><span>Verein</span><b id="orderClub">FC Oberwinterthur</b></div>
          <div class="order-row"><span>Paket</span><b id="orderPackage">Digital Partner</b></div>
          <div class="order-row"><span>Setup</span><b>CHF 0</b></div>
          <div class="order-row total"><span>Gesamt</span><span id="orderPrice">CHF 1'490</span></div>
          <button class="cta" onclick="bookCampaign()">Kampagne buchen</button>
          <button class="subcta" onclick="window.location='/'">Zur Club-Demo</button>
          <div class="success hidden" id="successBox"><b>Kampagne gebucht</b><span id="successText"></span></div>
        </div>
      </section>
    </aside>
  </div>
</main>

<script>
let selectedClub="FC Oberwinterthur", selectedPackage="Digital Partner", selectedPrice=1490, logoData=null;
function loginDemo(){document.getElementById('loginOverlay').classList.add('hidden')}
function selectClub(el){
 document.querySelectorAll('.club').forEach(x=>x.classList.remove('active'));el.classList.add('active');
 selectedClub=el.dataset.club; document.getElementById('orderClub').textContent=selectedClub;
 document.getElementById('waClub').textContent=selectedClub; document.getElementById('artClub').textContent=selectedClub;document.getElementById('copyClub').textContent=selectedClub;
 const abbr=selectedClub.split(' ').map(x=>x[0]).join('').slice(0,3).toUpperCase();document.getElementById('clubLogo').textContent=abbr; updatePreview();
}
function selectPackage(el){
 document.querySelectorAll('.pkg').forEach(x=>x.classList.remove('active'));el.classList.add('active');
 selectedPackage=el.dataset.name;selectedPrice=+el.dataset.price;
 document.getElementById('orderPackage').textContent=selectedPackage;document.getElementById('orderPrice').textContent="CHF "+selectedPrice.toLocaleString("de-CH");
}
function updatePreview(){
 const name=document.getElementById('sponsorName').value||"Dein Unternehmen";
 const claim=document.getElementById('headline').value||"Dein Claim";
 const copy=document.getElementById('copyText').value||"";
 document.getElementById('previewSponsor').textContent=name;document.getElementById('previewClaim').textContent=claim;document.getElementById('previewCopy').textContent=copy;
 document.getElementById('topSponsor').textContent=name;
}
function loadLogo(e){
 const file=e.target.files[0];if(!file)return;const r=new FileReader();r.onload=ev=>{logoData=ev.target.result;document.getElementById('logoSlot').innerHTML='<img src="'+logoData+'" alt="Sponsor logo">'};r.readAsDataURL(file)
}
function assetChosen(e){const f=e.target.files[0];if(f)document.getElementById('assetHint').textContent="✓ "+f.name+" bereit für die Kampagne"}
async function bookCampaign(){
 const payload={sponsor_name:document.getElementById('sponsorName').value||"Demo Sponsor",club:selectedClub,package:selectedPackage,price:selectedPrice,headline:document.getElementById('headline').value||""};
 const r=await fetch('/api/sponsor/campaign',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(payload)});
 const j=await r.json();const box=document.getElementById('successBox');box.classList.remove('hidden');document.getElementById('successText').textContent=" Buchungs-ID #"+j.campaign_id+" · "+selectedClub+" · "+selectedPackage+". Für die Demo wurde keine Zahlung ausgelöst.";
}
</script></body></html>""")

