# DBS — Instagram Reel

A 30-second vertical reel (1080×1920, 30 fps, H.264 + AAC) that introduces DBS to Django
developers. It opens on a real, reproducible result: 10,000 random bytes flipped in a
backup, the database deleted, and every row restored.

| File | What it is |
|---|---|
| `dbs-reel.mp4` | The reel, ready to upload |
| `cover.png` | The cover frame (the hook), for the Reel's cover and the profile grid |
| `reel.html` | The composition: every frame is `render(t)` at a given second |
| `render.cjs` | Steps Chromium through the composition and encodes the frames |
| `music.py` | The soundtrack, synthesized with numpy and timed from the composition's cues |
| `build.sh` | Builds `dbs-reel.mp4` and `cover.png` from the three files above |
| `stress-run-10000.txt` | The run the hook is based on |
| `fonts/` | JetBrains Mono (SIL Open Font License 1.1, `fonts/OFL.txt`) |

## Rebuild

Needs Node with Playwright and Chromium, Python 3 with numpy, ffmpeg, and the Inter Display
font (`apt install fonts-inter`).

```bash
promo/instagram-reel/build.sh            # writes dbs-reel.mp4 and cover.png
node promo/instagram-reel/render.cjs stills 0,5,10 /tmp   # preview single frames
```

## Storyboard

| Time | Beat | On screen |
|---|---|---|
| 0.0–3.5 | Hook | "I flipped **10,000** random bytes in my Django backup." over a hex dump turning red. "Then I restored it." |
| 3.5–9.5 | Proof | The stress script's real output; the hex dump heals green. "Every row came back. 31,140 records · every hash matches" |
| 9.5–12.5 | Reveal | "Meet DBS — Django Backup Solution. Backups that heal themselves." (the beat drops) |
| 12.5–18.5 | How | One `.dbs` file: copy A, copy B 64 blocks later, Reed-Solomon parity; blocks are damaged, then healed |
| 18.5–22.5 | Start | "Add one app. Run one command." `pip install django-dbs`, `dbs backup`, and the command's real success line |
| 22.5–26.5 | Also in the box | Nine features, one per eighth note |
| 26.5–30.0 | Call to action | `pip install django-dbs` · Free and open source · MIT · "Save it for your next deploy" |

## Where every claim comes from

| On screen | Source |
|---|---|
| 10,000 bytes flipped, 28 blocks repaired, 31,140 records, "counts, hashes, samples and aggregates all equal" | `DBS_STRESS_FLIPS=10000 python scripts/stress_roundtrip.py`, transcript in `stress-run-10000.txt` |
| 3,917,816-byte backup | The same run |
| Two copies, 64 blocks apart; Reed-Solomon parity; AES-256-GCM; Argon2id | README, "How it heals" |
| "Wrote backup.dbs (… bytes), verified, two redundant copies + Reed-Solomon parity." | `dbs/management/commands/dbs_backup.py` |
| Passphrase derived from `SECRET_KEY` | README, "Take, check and restore a backup" |
| Verified end to end, never overwrites, dry-run restores, panel, audit trail, SSH pulls, MCP | README |
| Django 4.2 to 6.x, Python 3.9+, MIT | `pyproject.toml` |

Keep the number at 10,000 unless a new run proves a larger one. A run with 50,000 flipped
bytes went past the parity budget: block 11 could not be repaired, and DBS refused to restore
and named the block, as the README says it does.

## Caption

```text
I flipped 10,000 random bytes in a Django backup, deleted the database, and restored it.
All 31,140 records came back. Every hash matched. 🧬

That's DBS, an open-source backup library for Django:
→ rows, relations and files in one encrypted file
→ every block stored twice, plus Reed-Solomon parity
→ damage is found and repaired on restore
→ AES-256-GCM, with the key derived through Argon2id

pip install django-dbs

Run the same test yourself from the repo:
DBS_STRESS_FLIPS=10000 python scripts/stress_roundtrip.py

🔖 Save this for your next deploy. Link in bio.

#django #python #djangodeveloper #backend #devops #opensource #database #webdevelopment
```

First comment, pinned: `pip install django-dbs` and the repository link.

## Other hooks to test

Swap the three hook lines in `reel.html` (scene `s1`) to A/B test:

- "This backup file heals itself."
- "POV: you corrupt your own backup on purpose."
- "What happens when a backup gets corrupted? Watch."

## Posting

- Upload `dbs-reel.mp4` as a Reel and pick `cover.png` as the cover. Its text sits inside
  the 3:4 crop the profile grid shows.
- The text is burned in, so the reel works muted. The soundtrack is original and
  loudness-normalized to −14 LUFS. To use a trending sound instead, add it in Instagram and
  lower the original audio.
- Text stays clear of the caption and the action buttons: nothing important sits in the
  bottom 420 px or behind the right-hand icons.
