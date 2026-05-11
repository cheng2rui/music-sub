"""Library API routes."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.db import get_db
from app.models import MusicFile

router = APIRouter()


@router.get("/")
def list_library(artist: str = "", album: str = "", limit: int = 50,
                 db: Session = Depends(get_db)):
    """Browse music library."""
    q = db.query(MusicFile).order_by(MusicFile.created_at.desc())
    if artist:
        q = q.filter(MusicFile.artist.ilike(f"%{artist}%"))
    if album:
        q = q.filter(MusicFile.album.ilike(f"%{album}%"))
    files = q.limit(limit).all()
    return [
        {
            "id": f.id,
            "file_path": f.file_path,
            "artist": f.artist,
            "album": f.album,
            "title": f.title,
            "year": f.year,
            "format": f.format,
            "scraped": f.scraped,
        }
        for f in files
    ]


@router.get("/stats")
def library_stats(db: Session = Depends(get_db)):
    """Get library statistics."""
    total = db.query(MusicFile).count()
    scraped = db.query(MusicFile).filter(MusicFile.scraped == True).count()
    artists = db.query(MusicFile.artist).distinct().count()
    albums = db.query(MusicFile.album).distinct().count()
    return {
        "total_files": total,
        "scraped": scraped,
        "unscraped": total - scraped,
        "artists": artists,
        "albums": albums,
    }
