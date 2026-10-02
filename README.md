# ClubFlow MVP · FC Oberwinterthur Pilot

A working prototype for an automated amateur-football content and sponsorship platform configured around FC Oberwinterthur.

## What it does
- FC Oberwinterthur-branded dashboard
- FVRZ match/event demo feed
- Matchday content automation
- Full-Time content after result entry
- WhatsApp, Instagram and Facebook copy
- Sponsor inventory assignment
- Approval workflow
- Simulated publish flow
- Shareable SVG artwork
- SQLite persistence

## Run
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000

## Render
The repository includes render.yaml and a /health endpoint.
