# MAX demo update — 8 October 2026

This update replaces the FC Oberwinterthur demo identity with **FC Mockup** and aligns the demonstrations with the latest project direction.

## Experiences

- `max-site/index.html`: public MAX concept, responsive process graphic, simple club/sponsor journeys, free club model, all three portal links.
- `/club`: forward-looking editorial examples, original four-card Mockup series, sponsor and player-moment reviews, free club-post drafts.
- `/sponsor`: Autopilot first; large monthly calendar second; editable placement preview, original logo upload and enquiry form below.
- `/player`: fictional player profile, original cards for download, channel sharing, text-moment submission with consent confirmation and club review.

## Graphics

The four original FC MAX Mockup/fitality cards supplied in the project are reused unchanged. The dynamic sponsor layout follows their white/navy/blue direction and uses the matchday art as a backdrop. It accepts an original logo locally; no replacement fitality logo is generated. Static reference cards keep their original embedded names, scores and sponsor. The editor clearly distinguishes them from editable previews.

## What works

- Autopilot proposes demo inventory within budget, dates and a per-club weekly placement cap, with unspent budget preserved.
- Changing region never invents available clubs. Featured sponsorship produces an additional enquiry suggestion, not a guaranteed placement.
- Individual sponsor requests are stored in SQLite and reviewed in the club portal.
- Player text moments require explicit rights confirmation, are stored and can be approved/rejected by the club.
- Club drafts are stored. Original static PNG assets can be downloaded.
- All user-provided text is escaped before insertion into the DOM.

## Demo boundaries

This remains a public fictional demonstration, not a production account system. There is no authentication or role isolation. Do not enter personal or confidential information. The banner states this on every portal.

No actual sports-data feed, social publisher, payment service, automated moderation, cross-channel person-level frequency tracking or analytics source is connected. TikTok is a planned video/storyboard output. Dynamic preview/logo upload is local and not stored as a renderable publication. Autopilot is an explainable deterministic planner, not an activated recurring campaign. Stored approvals do not publish content.

SQLite uses `MAX_DB_PATH` or `max_demo.db`; Render ephemeral storage can reset demo inputs on redeploy. No new paid services, disks or infrastructure are introduced.

## Verification

Run `python -m unittest test_demo -v` after installing requirements and `httpx`.
The tests cover budget and frequency caps, invalid ranges, empty inventory, sponsor credit and approval, player consent and review, idempotent fixture seeding, portal and asset responses.

Existing fixture migration only replaces rows matching the old bundled venue names and preserves their IDs so campaign references remain intact. Other historical rows are retained.
