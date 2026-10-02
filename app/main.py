from __future__ import annotations
import os, sqlite3
from datetime import datetime
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

ROOT=Path(__file__).resolve().parent.parent
DB=Path(os.getenv("CLUBFLOW_DB_PATH", str(ROOT/"clubflow.db")))
app=FastAPI(title="FVRZ App · FC Oberwinterthur Pilot", version="0.3.0")

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

@app.get("/health")
def health(): return {"status":"ok","club":"FC Oberwinterthur","version":"0.3.0"}

@app.get("/",response_class=HTMLResponse)
def home():
    c=conn()
    matches=[dict(x) for x in c.execute("select * from matches order by kickoff").fetchall()]
    items=[dict(x) for x in c.execute("""select content.*,matches.team,matches.opponent,matches.kickoff
       from content join matches on matches.id=content.match_id
       order by case content.status when 'draft' then 0 when 'approved' then 1 else 2 end, content.id desc""").fetchall()]
    c.close()
    cards="".join(f"""<article class='card'><div class='visual'><span>{x['channel'].upper()}</span><b>{'FULL TIME' if x['kind']=='result' else 'MATCHDAY'}</b><h3>FC OBERWINTERTHUR</h3><em>vs</em><h3>{x['opponent']}</h3><small>PRESENTED BY · DEMO PARTNER</small></div>
    <div class='body'><div class='row'><strong>{x['team']}</strong><i class='status {x['status']}'>{x['status']}</i></div>
    <pre>{x['caption']}</pre><div class='actions'>
    {f"<button onclick=\"act({x['id']},'approve')\">Freigeben</button>" if x['status']=='draft' else ""}
    {f"<button onclick=\"act({x['id']},'publish')\">Publizieren</button>" if x['status']=='approved' else ""}
    {f"<button class='done'>Publiziert</button>" if x['status']=='published' else ""}
    </div></div></article>""" for x in items)
    games="".join(f"""<div class='game'><div><b>{m['kickoff'][5:16]}</b><span>{m['team']}</span></div><div><strong>FC Oberwinterthur – {m['opponent']}</strong><small>{m['competition']} · {m['venue']}</small></div><div>{f"<b class='score'>{m['gf']}:{m['ga']}</b>" if m['status']=='finished' else f"<button class='link' onclick='finish({m['id']})'>Resultat setzen</button>"}</div></div>""" for m in matches)
    return HTMLResponse(f"""<!doctype html><html lang='de'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>ClubFlow · FC Oberwinterthur</title>
<style>
:root{{--y:#ffd400;--b:#123a70;--bg:#f5f7fa;--line:#e5e7eb}}*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);font-family:Inter,Arial,sans-serif;color:#111827}}header{{background:#fff;border-bottom:1px solid var(--line);padding:16px 5vw;display:flex;justify-content:space-between;align-items:center;position:sticky;top:0;z-index:3}}header h1{{font-size:18px;margin:2px 0}}.eyebrow{{font-size:10px;letter-spacing:.14em;font-weight:900;color:#667085}}.mode{{background:#ecfdf3;color:#067647;padding:8px 10px;border-radius:999px;font-size:11px;font-weight:800}}main{{width:min(1180px,92vw);margin:26px auto}}.hero{{background:var(--b);color:white;border-radius:24px;padding:44px;display:flex;justify-content:space-between;gap:25px}}.hero h2{{font-size:54px;line-height:.96;margin:12px 0}}.hero p{{max-width:650px;color:#d0d9e7;line-height:1.55}}.facts{{display:flex;gap:8px;flex-wrap:wrap;margin-top:22px}}.facts span{{background:#ffffff14;border:1px solid #ffffff24;border-radius:999px;padding:8px 10px;font-size:11px}}section{{margin-top:32px}}.head{{display:flex;justify-content:space-between;align-items:end;margin-bottom:14px}}.head h2{{margin:4px 0}}.grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}}.card{{background:white;border:1px solid var(--line);border-radius:18px;overflow:hidden}}.visual{{background:var(--y);color:var(--b);height:300px;padding:25px;position:relative;display:flex;flex-direction:column;justify-content:center;text-align:center}}.visual span{{position:absolute;top:18px;left:18px;font-size:10px;font-weight:900;background:#fff9;padding:6px 8px;border-radius:999px}}.visual b{{font-size:30px}}.visual h3{{margin:16px 0;font-size:23px}}.visual em{{font-style:normal;opacity:.5;font-weight:900}}.visual small{{position:absolute;bottom:18px;left:0;right:0;font-weight:800}}.body{{padding:18px}}.row{{display:flex;justify-content:space-between;gap:10px}}.status{{font-style:normal;font-size:10px;border-radius:999px;padding:5px 8px;background:#f2f4f7}}.approved{{background:#fffaeb;color:#b54708}}.published{{background:#ecfdf3;color:#067647}}pre{{font:12px/1.45 Inter,Arial;white-space:pre-wrap;color:#475467;background:#fafafa;padding:12px;border-radius:10px;min-height:135px}}button{{border:0;border-radius:10px;padding:10px 12px;background:var(--b);color:white;font-weight:800;cursor:pointer}}button.done{{background:#12b76a}}.panel{{background:#fff;border:1px solid var(--line);border-radius:18px;overflow:hidden}}.game{{display:grid;grid-template-columns:145px 1fr auto;gap:18px;align-items:center;padding:16px;border-bottom:1px solid var(--line)}}.game span,.game small{{display:block;color:#667085;margin-top:4px;font-size:11px}}.link{{background:none;color:#175cd3;padding:0}}.score{{font-size:23px;color:var(--b)}}footer{{padding:26px 0;color:#667085;font-size:11px}}@media(max-width:900px){{.grid{{grid-template-columns:1fr 1fr}}.hero{{display:block}}}}@media(max-width:620px){{.grid{{grid-template-columns:1fr}}.hero h2{{font-size:42px}}.game{{grid-template-columns:90px 1fr}}.game>div:last-child{{grid-column:2}}}}
</style></head><body><header><div><div class='eyebrow'>FVRZ APP · PILOT</div><h1>FC Oberwinterthur</h1></div><div class='mode'>● Approval Mode</div></header>
<main><div class='hero'><div><div class='eyebrow' style='color:#ffd400'>DIGITAL CLUB ENGINE</div><h2>Ein Spiel.<br>Alle Kanäle.</h2><p>Aus Matchdaten entstehen automatisch Inhalte für WhatsApp, Instagram und Facebook – inklusive Freigabe-Workflow und digitaler Sponsor-Platzierung.</p><div class='facts'><span>24 Teams</span><span>Gelb / Blau</span><span>Hegmatten</span><span>seit 1934</span></div></div></div>
<section><div class='head'><div><div class='eyebrow'>CONTENT QUEUE</div><h2>Automatisch erstellt</h2></div></div><div class='grid'>{cards}</div></section>
<section><div class='head'><div><div class='eyebrow'>MATCH FEED</div><h2>Spiele</h2></div></div><div class='panel'>{games}</div></section>
<footer>Datenquelle Pilot: öffentlich sichtbare FVRZ-/Clubinformationen. Für einen produktiven kommerziellen Einsatz ist ein offizieller bzw. lizenzierter Datenzugang vorgesehen.</footer></main>
<script>
async function act(id,a){{await fetch('/api/content/'+id+'/'+a,{{method:'POST'}});location.reload()}}
async function finish(id){{let s=prompt('Resultat aus Sicht FC Oberwinterthur, z.B. 3:1');if(!s)return;let p=s.split(':');await fetch('/api/matches/'+id+'/finish',{{method:'POST',headers:{{'content-type':'application/json'}},body:JSON.stringify({{goals_for:+p[0],goals_against:+p[1]}})}});location.reload()}}
</script></body></html>""")
