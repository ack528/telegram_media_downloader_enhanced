"""Optional metadata-based download limits."""

import math


def validate_limits(limits):
    """Validate inclusive bounds; zero or a missing bound means unlimited."""
    if not isinstance(limits, dict):
        raise ValueError("download_limits must be a mapping")
    for key in ("min_size_mb", "max_size_mb", "min_video_resolution", "max_video_resolution"):
        value = limits.get(key, 0)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise ValueError(f"download_limits.{key} must be a non-negative number")
    for low, high in (("min_size_mb", "max_size_mb"), ("min_video_resolution", "max_video_resolution")):
        if limits.get(low, 0) and limits.get(high, 0) and limits[low] > limits[high]:
            raise ValueError(f"download_limits.{low} exceeds {high}")


def allowed_media(media, media_type, limits):
    """Return false for out-of-range or unknown metadata when limited."""
    def in_range(value, low, high):
        return not (low or high) or bool(value and (not low or value >= low) and (not high or value <= high))

    size = getattr(media, "file_size", None)
    if not in_range(size, limits.get("min_size_mb", 0) * 1048576, limits.get("max_size_mb", 0) * 1048576):
        return False
    if media_type in ("video", "video_note"):
        width = getattr(media, "width", None) or getattr(media, "length", None)
        height = getattr(media, "height", None) or getattr(media, "length", None)
        resolution = min(width, height) if width and height else None
        return in_range(resolution, limits.get("min_video_resolution", 0), limits.get("max_video_resolution", 0))
    return True
