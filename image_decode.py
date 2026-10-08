"""Decode downloaded asset bytes into PIL images, including RAW and HEIC."""

import rawpy
from PIL import Image, UnidentifiedImageError

# RAW extensions sent straight to rawpy. Not exhaustive: a camera missing here
# is still caught by the rawpy fallback in open_asset().
RAW_SUFFIXES = (
    '.raw',
    '.dng',
    '.arw',
    '.cr2',
    '.cr3',
    '.nef',
    '.nrw',
    '.orf',
    '.raf',
    '.rw2',
    '.pef',
    '.srw',
    '.sr2',
    '.3fr',
    '.erf',
    '.iiq',
)


def _open_raw(data):
    """A PIL image from RAW bytes, whatever the file is called."""
    data.seek(0)
    with rawpy.imread(data) as raw:
        return Image.fromarray(raw.postprocess(use_camera_wb=True, use_auto_wb=False))


def open_asset(data, original_path):
    """A fully decoded PIL image from downloaded bytes.

    Raises ValueError naming the file when neither PIL nor rawpy can read it,
    and OSError for a truncated or damaged file.
    """
    lowered = (original_path or '').lower()
    if lowered.endswith(RAW_SUFFIXES):
        return _open_raw(data)
    if lowered.endswith('.heic'):
        return Image.open(data).convert('RGB')
    try:
        image = Image.open(data)
    except UnidentifiedImageError:
        # PIL names the BytesIO, not the file. The usual cause is a RAW file
        # from a camera not in RAW_SUFFIXES, so try rawpy before giving up.
        try:
            return _open_raw(data)
        except Exception as error:
            raise ValueError(f'Unsupported image format: {original_path or "unknown file"}') from error
    # Image.open reads only the header; load() makes a truncated file fail here,
    # where the caller can fall back to the preview, not mid-pipeline.
    image.load()
    return image


def open_preview(data):
    """A fully decoded PIL image from Immich's preview rendering."""
    image = Image.open(data)
    image.load()
    return image
