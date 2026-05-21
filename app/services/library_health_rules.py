"""Conservative library health rules.

These helpers intentionally reduce noisy health warnings. A health card should
point to actionable work, not every technically-missing sidecar file.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

from app.scrapers.tagger import read_existing_tags, read_sidecar_lyrics

AUDIO_EXTENSIONS = {".flac", ".ape", ".wav", ".wv", ".m4a", ".mp3", ".aac", ".ogg", ".opus", ".aiff", ".dsf", ".dff"}

_INSTRUMENTAL_RE = re.compile(
    r"(instrumental|inst\.?|karaoke|off\s*vocal|backing\s*track|伴奏|纯音乐|器乐|无人声|卡拉ok|钢琴版|吉他版|演奏版|配乐|ost|bgm|original\s*soundtrack|soundtrack|score)",
    re.IGNORECASE,
)
_CLASSICAL_RE = re.compile(
    r"(classical|古典|交响|协奏|奏鸣曲|sonata|symphony|concerto|prelude|etude|nocturne|waltz|piano|orchestra|quartet|quintet|violin|cello|巴赫|莫扎特|贝多芬|肖邦)",
    re.IGNORECASE,
)
_NON_SONG_RE = re.compile(
    r"(podcast|播客|有声书|audiobook|广播剧|相声|评书|lecture|访谈|interview|demo|intro|outro|skit|interlude)",
    re.IGNORECASE,
)
_LYRIC_SIDECAR_SUFFIXES = (".lrc", ".krc", ".qrc", ".txt", ".ass", ".srt")


@dataclass(frozen=True)
class CueInfo:
    path: Path
    audio_file: str = ""
    track_count: int = 0


def _joined(*parts: object) -> str:
    return " ".join(str(p or "") for p in parts).strip()


def _non_empty_text_file(path: Path, *, min_size: int = 12) -> bool:
    try:
        return path.exists() and path.is_file() and path.stat().st_size >= min_size
    except Exception:
        return False


def has_lyrics(file_path: str | None) -> bool:
    """Return true when lyrics are present as sidecar or embedded tag."""
    if not file_path:
        return False
    try:
        if read_sidecar_lyrics(file_path):
            return True
        p = Path(file_path)
        # Imported libraries may use non-.lrc lyric sidecars; count only non-empty files.
        for suffix in _LYRIC_SIDECAR_SUFFIXES:
            if suffix == ".lrc":
                continue
            if _non_empty_text_file(p.with_suffix(suffix), min_size=20):
                return True
        tags = read_existing_tags(file_path)
        return bool(tags.get("lyrics"))
    except Exception:
        return False


def should_expect_lyrics(*, title: str = "", artist: str = "", album: str = "", genre: str = "", duration: float | int | None = None, scraped: bool | None = None) -> bool:
    """Heuristic: only flag missing lyrics for likely vocal songs.

    False positives were high when every local audio file without .lrc was counted:
    instrumentals, OST/BGM, classical pieces, short clips, podcasts, and unknown rows
    are usually not useful lyric work items.
    """
    text = _joined(title, artist, album, genre)
    if not (title and (artist or album)):
        return False
    if scraped is False and not artist:
        return False
    try:
        dur = float(duration or 0)
    except Exception:
        dur = 0
    if dur and (dur < 75 or dur > 15 * 60):
        return False
    if _NON_SONG_RE.search(text):
        return False
    if _INSTRUMENTAL_RE.search(text):
        return False
    if _CLASSICAL_RE.search(text):
        return False
    return True


def is_missing_lyrics_candidate(file_path: str | None, *, title: str = "", artist: str = "", album: str = "", genre: str = "", duration: float | int | None = None, scraped: bool | None = None) -> bool:
    if not should_expect_lyrics(title=title, artist=artist, album=album, genre=genre, duration=duration, scraped=scraped):
        return False
    return not has_lyrics(file_path)


def _parse_cue_info(cue_path: Path) -> CueInfo | None:
    encodings = ("utf-8", "utf-8-sig", "gb18030", "big5", "shift_jis", "latin-1")
    text = ""
    for enc in encodings:
        try:
            text = cue_path.read_text(encoding=enc)
            break
        except UnicodeDecodeError:
            continue
        except Exception:
            return None
    if not text:
        return None
    audio_file = ""
    track_count = 0
    for raw_line in text.splitlines():
        line = raw_line.strip()
        upper = line.upper()
        if upper.startswith("FILE ") and not audio_file:
            m = re.match(r'FILE\s+"([^"]+)"', line, re.IGNORECASE) or re.match(r"FILE\s+(\S+)", line, re.IGNORECASE)
            if m:
                audio_file = m.group(1).strip()
        elif upper.startswith("TRACK "):
            track_count += 1
    return CueInfo(path=cue_path, audio_file=audio_file, track_count=track_count)


def _audio_files_in_dir(directory: Path) -> list[Path]:
    try:
        return [p for p in directory.iterdir() if p.is_file() and p.suffix.lower() in AUDIO_EXTENSIONS]
    except Exception:
        return []


def _cue_matches_audio(cue: CueInfo, audio_path: Path) -> bool:
    if cue.audio_file:
        return Path(cue.audio_file).name == audio_path.name
    return cue.path.stem == audio_path.stem


def cue_split_candidate(file_path: str | None, *, duration: float | int | None = None) -> bool:
    """Return true only for likely single-image audio + usable local CUE.

    Old logic treated every audio file in a folder as a CUE candidate whenever the
    folder had exactly one .cue. That mislabels already-split albums. We now require:
    - real local audio file and CUE with at least 2 tracks;
    - long enough source audio;
    - an explicit FILE/same-stem match, or the only audio file in the folder.
    """
    if not file_path:
        return False
    path = Path(file_path)
    if not path.exists() or not path.is_file() or path.suffix.lower() not in AUDIO_EXTENSIONS:
        return False
    try:
        dur = float(duration or 0)
    except Exception:
        dur = 0
    if dur and dur < 12 * 60:
        return False

    cue_paths: list[Path] = []
    same_stem = path.with_suffix(".cue")
    if same_stem.exists() and same_stem.is_file():
        cue_paths.append(same_stem)
    try:
        cue_paths.extend(p for p in path.parent.glob("*.cue") if p.is_file() and p not in cue_paths)
    except Exception:
        pass
    if not cue_paths:
        return False

    audio_files = _audio_files_in_dir(path.parent)
    single_audio_folder = len(audio_files) == 1 and audio_files[0].resolve() == path.resolve()

    for cue_path in cue_paths:
        cue = _parse_cue_info(cue_path)
        if not cue or cue.track_count < 2:
            continue
        if cue.audio_file:
            if Path(cue.audio_file).name != path.name:
                continue
            return True
        if cue.path.stem == path.stem:
            return True
        if single_audio_folder:
            return True
    return False
