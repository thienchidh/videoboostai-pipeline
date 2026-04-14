"""
modules/media/subtitle_srt.py — SRT subtitle file generation from word timestamps.

SRT format:
1
00:00:00,000 --> 00:00:00,500
Word1 Word2

2
00:00:00,500 --> 00:00:01,000
Word3 Word4
"""

from pathlib import Path
from typing import List, Dict


def format_timestamp(seconds: float) -> str:
    """Format seconds as HH:MM:SS,mmm for SRT."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def generate_srt(timestamps: List[Dict[str, float]],
                  max_words_per_line: int = 1,
                  max_duration_sec: float = 0.3) -> str:
    """Convert word timestamps to SRT subtitle entries.

    Groups consecutive words into subtitle lines, respecting
    max_words_per_line and max_duration_sec limits.
    """
    if not timestamps:
        return ""

    entries = []
    entry_idx = 1

    i = 0
    while i < len(timestamps):
        group_words = []
        group_start = timestamps[i]["start"]
        group_end = timestamps[i]["end"]

        while i < len(timestamps):
            w = timestamps[i]
            proposed_end = w["end"]

            duration = proposed_end - group_start
            if (len(group_words) >= max_words_per_line or
                    duration >= max_duration_sec) and group_words:
                break

            group_words.append(w["word"])
            group_end = w["end"]
            i += 1

        if not group_words:
            break

        text = " ".join(group_words)
        entries.append(f"{entry_idx}\n{format_timestamp(group_start)} --> {format_timestamp(group_end)}\n{text}")
        entry_idx += 1

    return "\n\n".join(entries) + "\n"


def save_srt(timestamps: List[Dict[str, float]], output_path: str,
             max_words_per_line: int = 8, max_duration_sec: float = 5.0) -> str:
    """Generate SRT and save to file. Returns the output path."""
    srt_content = generate_srt(timestamps, max_words_per_line, max_duration_sec)
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(srt_content)
    return output_path


if __name__ == "__main__":
    import json
    import sys

    if len(sys.argv) > 1:
        with open(sys.argv[1], encoding="utf-8") as f:
            timestamps = json.load(f)
    else:
        timestamps = [
            {"word": "Xin", "start": 0.0, "end": 0.3},
            {"word": "chào", "start": 0.3, "end": 0.7},
        ]

    print(generate_srt(timestamps))