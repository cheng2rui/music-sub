# Music Sub cleanup dry-run report

Date: 2026-05-16 Asia/Shanghai
Version observed: music-sub:0.5.4
Mode: dry-run only; no data deleted or modified.

## Summary

- Download tasks in DB: 8
- Music file records: 4
- qB-backed hashes found in DB: 4 task rows / 3 unique hashes
- qB states returned: 3 unique hashes
- Clear cleanup candidates: 7 task rows
- Keep candidate: 1 task row

## Cleanup candidates

### A. Mis-added M-Team video/concert tasks, paused in qB

These are qB-backed, paused/stopped, progress 0%, and look like video/MV/concert results. They are safe candidates to remove from qB and DB if confirmed.

| id | task name | hash | qB name/content | qB state | amount_left |
|---:|---|---|---|---|---:|
| 1 | 周杰伦-《前世情人》 MV | 68090ddaa08c945187591f8ab41395b7ec2176ff | /downloads/music/周杰伦-《now you see me》.mp4 | stoppedDL | 46,298,308 |
| 2 | Jay Chou Incomparable Live Concert 2004 Upscaled 2160P 60FPS H264 AC3 | 4f432ee33b5ced51631f76f29677b367c204d8e9 | /downloads/music/周杰伦-《前世情人》.mp4 | stoppedDL | 74,658,992 |
| 3 | Jay.Chou.Incomparable.Live.Concert.2004.DVDRip.x264.AC3.2Audios-CMCT | 5793c2e358ad1f76a553bce43940747a2c0f783c | /downloads/music/周杰伦2004无与伦比演唱会.2004.简繁中字￡CMCT小鱼 | stoppedDL | 5,114,217,967 |
| 8 | Jay Chou Incomparable Live Concert 2004 DVDrip Repair 4K 60FPS@zyl2012 | 5793c2e358ad1f76a553bce43940747a2c0f783c | /downloads/music/周杰伦2004无与伦比演唱会.2004.简繁中字￡CMCT小鱼 | stoppedDL | 5,114,217,967 |

Notes:
- IDs 3 and 8 share the same torrent hash, so qB deletion should happen once for hash `5793c2e358ad1f76a553bce43940747a2c0f783c`.
- Recommended cleanup action: delete qB torrents with `delete_files=false` first, then delete DB rows 1,2,3,8.
- Since progress is 0%, there should be no meaningful downloaded data, but use `delete_files=false` to stay conservative.

### B. Local simulated/test rows

These use synthetic hashes and appear to be development/test data. They are safe DB-only cleanup candidates if the goal is to remove historical dirty task rows.

| id | task name | hash | status | issue |
|---:|---|---|---|---|
| 4 | 周杰伦 - 青花瓷 | SIMULATED_HASH_001 | scraped | simulated hash; completed_at is null |
| 5 | 周杰伦 - 稻香 | SIMULATED_HASH_002 | scraped | simulated hash; completed_at is null |
| 6 | 周杰伦 - 稻香 lyrics | SIMULATED_HASH_LYRICS | scraped | simulated hash |

Recommended cleanup action: delete DB rows 4,5,6 only. Do not touch library files automatically unless separately reviewed.

## Keep

| id | task name | hash | site | status | reason |
|---:|---|---|---|---|---|
| 7 | 稻香 | online:0783f96dec8b4c529024c32b23e22026 | kugou | scraped | real online download validation; completed_at present |

## Proposed next step

If approved, run a conservative cleanup:

1. Backup SQLite DB: `data/music_sub.db` → timestamped `.bak`.
2. Delete qB torrents for unique hashes from IDs 1,2,3/8 with `delete_files=false`.
3. Delete DB rows 1,2,3,4,5,6,8.
4. Keep row 7.
5. Verify `/api/tasks/` only returns the real online task and qB no longer has the bad video torrents.

No cleanup has been executed yet.

## Cleanup executed

Executed at: 2026-05-16 14:10 Asia/Shanghai

Actions performed:

1. Backed up SQLite DB to `data/music_sub.db.bak.20260516-141043`.
2. Deleted qB torrents with `delete_files=false`:
   - `68090ddaa08c945187591f8ab41395b7ec2176ff`
   - `4f432ee33b5ced51631f76f29677b367c204d8e9`
   - `5793c2e358ad1f76a553bce43940747a2c0f783c`
3. Deleted DB task rows: `1,2,3,4,5,6,8`.
4. Deleted associated DB `music_files` rows for removed tasks: 3 rows.
5. Preserved real online download task row: `7`.

Verification:

- DB `download_tasks`: 1 row remains, status `scraped`.
- DB `music_files`: 1 row remains.
- qB lookup for removed hashes returned `{}`.
- `/api/tasks/` returns only task `7` (`稻香`, `kugou`, `scraped`).
- `/api/health` returns `{"status":"ok","version":"0.5.4"}`.
