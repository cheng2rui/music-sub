# Music Sub library orphan dry-run report

Date: 2026-05-16 Asia/Shanghai
Mode: dry-run only; no files deleted or moved.
Current version observed: v0.5.7

## Summary

DB currently tracks 2 real library audio files:

1. `data/library/周杰伦林俊杰/稻香 - 周杰伦、林俊杰/稻香 - 周杰伦、林俊杰.mp3`
2. `data/library/林俊杰/I AM 世界巡回演唱会/江南 (Live) - 林俊杰.mp3`

API library stats:

- total_files: 2
- scraped: 2
- unscraped: 0
- artists: 2
- albums: 1

Found 3 orphan album directories containing audio files that are not referenced by `music_files`.
These appear to be leftovers from earlier simulated/test tasks that were removed from the DB.

## Orphan candidates

| Directory | Files | Bytes | Reason |
|---|---:|---:|---|
| `data/library/sim-complete/sim-complete` | 2 | 10,315 | simulated test task residue |
| `data/library/周杰伦/魔杰座` | 4 | 172,168 | old test/simulated 稻香 task residue; DB row removed |
| `data/library/周杰倫/为心爱的人唱一首歌` | 2 | 10,231 | old test/simulated 稻香 task residue; DB row removed |

## Detailed file list

### `data/library/sim-complete/sim-complete`

- `album.nfo`
- `周杰伦 - 青花瓷.mp3`

### `data/library/周杰伦/魔杰座`

- `album.nfo`
- `cover.jpg`
- `周杰伦 - 稻香.lrc`
- `周杰伦 - 稻香.mp3`

### `data/library/周杰倫/为心爱的人唱一首歌`

- `album.nfo`
- `周杰伦 - 稻香.mp3`

## Recommended cleanup

Move these three directories to a recoverable trash/staging folder instead of deleting permanently:

`data/.trash/library-orphans-20260516/`

Recommended command pattern:

```bash
mkdir -p data/.trash/library-orphans-20260516
mv data/library/sim-complete data/.trash/library-orphans-20260516/
mv data/library/周杰伦/魔杰座 data/.trash/library-orphans-20260516/周杰伦-魔杰座
mv data/library/周杰倫 data/.trash/library-orphans-20260516/
find data/library -type d -empty -delete
```

Do not touch the two real tracked library folders:

- `data/library/周杰伦林俊杰/稻香 - 周杰伦、林俊杰/`
- `data/library/林俊杰/I AM 世界巡回演唱会/`

No cleanup has been executed yet.

## Cleanup executed

Executed at: 2026-05-16 15:31 Asia/Shanghai

Moved orphan directories to recoverable trash folder:

`data/.trash/library-orphans-20260516/`

Moved items:

- `data/library/sim-complete` → `data/.trash/library-orphans-20260516/sim-complete`
- `data/library/周杰伦/魔杰座` → `data/.trash/library-orphans-20260516/周杰伦-魔杰座`
- `data/library/周杰倫` → `data/.trash/library-orphans-20260516/周杰倫`

Verification after cleanup:

- Live library physical files now only contain the two real tracked folders:
  - `data/library/周杰伦林俊杰/稻香 - 周杰伦、林俊杰/`
  - `data/library/林俊杰/I AM 世界巡回演唱会/`
- DB `music_files`: 2 rows remain.
- `/api/library/stats`: `total_files=2`, `scraped=2`, `unscraped=0`.
- `/api/tasks/cleanup/preview`: candidate_count=0.

No files were permanently deleted.
