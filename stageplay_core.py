"""UI-independent media, timing and viewport rules for StagePlay V2."""
from __future__ import annotations

from pathlib import Path
from uuid import uuid4

VIDEO_EXTS = {'.mp4', '.mov', '.mkv', '.avi', '.webm', '.m4v', '.mpg', '.mpeg', '.wmv', '.ts', '.m2ts'}
IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.bmp', '.tif', '.tiff', '.webp'}
PDF_EXTS = {'.pdf'}
# PPT/X require a presentation rendering engine, and are not silently accepted as playable.
MEDIA_EXTS = VIDEO_EXTS | IMAGE_EXTS | PDF_EXTS
MODES = ('FIT', 'FILL', 'STRETCH', 'ORIGINAL')
LOOPS = ('OFF', 'ONE', 'ALL')


def media_kind(path: str) -> str | None:
    suffix = Path(path).suffix.lower()
    if suffix in VIDEO_EXTS:
        return 'video'
    if suffix in IMAGE_EXTS:
        return 'image'
    if suffix in PDF_EXTS:
        return 'pdf'
    return None


def default_settings() -> dict:
    return dict(mode='FIT', zoom=1.0, pan_x=0.0, pan_y=0.0,
                crop_l=0, crop_r=0, crop_t=0, crop_b=0,
                volume=100, in_ms=0, out_ms=0, still_seconds=0)


def create_entry(path: str) -> dict:
    return {'id': uuid4().hex, 'path': str(Path(path).resolve()),
            'kind': media_kind(path), 'settings': default_settings()}


def normalized_settings(legacy: dict | None) -> dict:
    s = default_settings()
    if isinstance(legacy, dict):
        s.update({k: v for k, v in legacy.items() if k in s})
        # V1 'zoom' and 'volume' values still load. Legacy VLC ratio/crop fields
        # were not reliably implemented and are deliberately not preserved.
    s['mode'] = s['mode'] if s['mode'] in MODES else 'FIT'
    s['zoom'] = max(.25, min(4.0, float(s['zoom'])))
    s['pan_x'] = max(-100, min(100, float(s['pan_x'])))
    s['pan_y'] = max(-100, min(100, float(s['pan_y'])))
    for k in ('crop_l', 'crop_r', 'crop_t', 'crop_b'):
        s[k] = max(0, min(45, int(s[k])))
    s['volume'] = max(0, min(100, int(s['volume'])))
    s['in_ms'] = max(0, int(s['in_ms']))
    s['out_ms'] = max(0, int(s['out_ms']))
    s['still_seconds'] = max(0, int(s['still_seconds']))
    return s


def display_time(ms: int) -> str:
    seconds = max(0, int(ms)) // 1000
    return f'{seconds//3600:02d}:{seconds//60%60:02d}:{seconds%60:02d}'


def crop_transform(source: tuple[int, int], viewport: tuple[int, int], settings: dict) -> dict:
    """Calculate physical pixel positions for video HWND and still-image rendering.

    The effective cropped source rectangle is fitted/filled into the viewport,
    then the full source is drawn behind a clipping rectangle. Cropping, zoom
    and pan are all geometric, not dependent on VLC crop/zoom plugins.
    Returns full source rectangle and clipping rectangle (x,y,w,h).
    """
    sw, sh = max(1., float(source[0])), max(1., float(source[1]))
    vw, vh = max(1., float(viewport[0])), max(1., float(viewport[1]))
    l = max(0., min(.45, float(settings.get('crop_l', 0))/100))
    r = max(0., min(.45, float(settings.get('crop_r', 0))/100))
    t = max(0., min(.45, float(settings.get('crop_t', 0))/100))
    b = max(0., min(.45, float(settings.get('crop_b', 0))/100))
    ew, eh = sw * (1-l-r), sh * (1-t-b)
    mode = settings.get('mode', 'FIT')
    if mode == 'FILL':
        scale = max(vw/ew, vh/eh)
        sx = sy = scale
    elif mode == 'STRETCH':
        sx, sy = vw/ew, vh/eh
    elif mode == 'ORIGINAL':
        sx = sy = 1.
    else:  # FIT
        sx = sy = min(vw/ew, vh/eh)
    z = max(.25, min(4., float(settings.get('zoom', 1))))
    sx *= z; sy *= z
    dx, dy = ew*sx, eh*sy
    pan_x = float(settings.get('pan_x', 0))*vw/100
    pan_y = float(settings.get('pan_y', 0))*vh/100
    ex = (vw-dx)/2 + pan_x
    ey = (vh-dy)/2 + pan_y
    fx, fy = ex-sw*l*sx, ey-sh*t*sy
    cx, cy = max(0., ex), max(0., ey)
    cr, cb = min(vw, ex+dx), min(vh, ey+dy)
    return {'full': (fx, fy, sw*sx, sh*sy),
            'clip': (cx, cy, max(0., cr-cx), max(0., cb-cy)),
            'effective': (ex, ey, dx, dy)}


def next_index(current: int, total: int, loop: str, auto_next: bool) -> int | None:
    if total == 0 or current < 0:
        return None
    if loop == 'ONE':
        return current
    if loop == 'ALL':
        return (current+1) % total
    if auto_next and current < total-1:
        return current+1
    return None


def media_path_for_save(path: str, show_path: str) -> str:
    import os
    try:
        return os.path.relpath(path, str(Path(show_path).resolve().parent))
    except ValueError:  # different Windows drives
        return str(path)


def resolve_saved_path(path: str, show_path: str) -> str:
    p = Path(path)
    return str(p if p.is_absolute() else (Path(show_path).resolve().parent / p).resolve())
