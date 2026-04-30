#!/usr/bin/env python3
"""
YouTube Live Recorder via RSS Feed — macOS
-------------------------------------------
- Polls the top entry of a YouTube RSS feed
- Confirms it is actively live via yt-dlp
- Records stream + internal audio in parallel
- On Ctrl+C: gracefully stops, muxes, and saves .mp4

Requirements:
    pip install yt-dlp requests
    brew install ffmpeg
    brew install blackhole-2ch
    (Set BlackHole 2ch as system output in Audio MIDI Setup for internal audio)
"""

import subprocess
import sys
import os
import re
import signal
import time
import requests
import xml.etree.ElementTree as ET
from datetime import datetime

# ─────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────

RSS_FEED_URL = "https://www.youtube.com/feeds/videos.xml?playlist_id=UULVuBYl17rgxG2hRZXbSQ-ecQ"

OUTPUT_DIR = os.path.expanduser("~/Downloads/LiveRecordings")

# 0 = record until Ctrl+C, otherwise seconds
RECORD_DURATION_SECONDS = 0

# BlackHole virtual audio device name
# Find yours: ffmpeg -f avfoundation -list_devices true -i ""
AUDIO_DEVICE = "BlackHole 2ch"

# Seconds between feed polls when waiting
POLL_INTERVAL = 30

# ─────────────────────────────────────────────

NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "yt":   "http://www.youtube.com/xml/schemas/2015",
}

# Global process handles so signal handler can reach them
_ytdlp_proc  = None
_ffmpeg_proc = None


def check_dependencies():
    missing = []
    for tool in ["yt-dlp", "ffmpeg"]:
        if subprocess.run(["which", tool], capture_output=True).returncode != 0:
            missing.append(tool)
    if missing:
        print(f"[ERROR] Missing tools: {', '.join(missing)}")
        if "yt-dlp"  in missing: print("  pip install yt-dlp")
        if "ffmpeg"  in missing: print("  brew install ffmpeg")
        sys.exit(1)


def fetch_top_entry(feed_url: str) -> dict | None:
    try:
        resp = requests.get(feed_url, timeout=15)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"[ERROR] Could not fetch RSS feed: {e}")
        return None

    root    = ET.fromstring(resp.content)
    entries = root.findall("atom:entry", NS)
    if not entries:
        return None

    entry       = entries[0]
    video_id_el = entry.find("yt:videoId", NS)
    title_el    = entry.find("atom:title",  NS)
    link_el     = entry.find("atom:link",   NS)

    if video_id_el is None or title_el is None:
        return None

    video_id = video_id_el.text.strip()
    title    = title_el.text.strip()
    url      = (link_el.attrib.get("href")
                if link_el is not None
                else f"https://www.youtube.com/watch?v={video_id}")

    return {"id": video_id, "title": title, "url": url}


def is_currently_live(video_url: str) -> bool:
    try:
        result = subprocess.run(
            ["yt-dlp", "--no-playlist", "--print", "%(is_live)s", video_url],
            capture_output=True, text=True, timeout=20
        )
        return result.stdout.strip().lower() == "true"
    except Exception:
        return False


def get_live_entry(feed_url: str) -> dict | None:
    entry = fetch_top_entry(feed_url)
    if not entry:
        return None
    print(f"[INFO] Top entry : {entry['title'][:70]}")
    if is_currently_live(entry["url"]):
        return entry
    print("[INFO] Not live right now.")
    return None


def sanitize_filename(name: str) -> str:
    name = re.sub(r'[^\w\s\-]', "", name, flags=re.UNICODE)
    name = name.strip().replace(" ", "_")
    return name[:80] or "live_stream"


def stop_processes():
    """Gracefully stop both recording processes."""
    global _ytdlp_proc, _ffmpeg_proc
    for name, proc in [("yt-dlp", _ytdlp_proc), ("ffmpeg", _ffmpeg_proc)]:
        if proc and proc.poll() is None:
            print(f"[INFO] Stopping {name}...")
            proc.send_signal(signal.SIGINT)
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()


def mux_and_save(temp_video: str, temp_audio: str, output_path: str):
    """Mux recorded video and internal audio into the final .mp4."""
    has_video = os.path.exists(temp_video) and os.path.getsize(temp_video) > 0
    has_audio = os.path.exists(temp_audio) and os.path.getsize(temp_audio) > 0

    if not has_video:
        print("[ERROR] No video file found — nothing to save.")
        return

    if has_video and has_audio:
        print("\n[INFO] Muxing stream video + internal audio...")
        cmd = [
            "ffmpeg", "-y",
            "-i", temp_video,
            "-i", temp_audio,
            "-filter_complex", "[0:a][1:a]amix=inputs=2:duration=first[aout]",
            "-map", "0:v",
            "-map", "[aout]",
            "-c:v", "copy",
            "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart",
            output_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"[WARN] Mux failed, saving stream-only video. ffmpeg error:\n{result.stderr[-300:]}")
            os.rename(temp_video, output_path)
        else:
            os.remove(temp_video)
    else:
        print("[WARN] No internal audio captured — saving stream audio/video only.")
        os.rename(temp_video, output_path)

    # Clean up temp audio
    if has_audio and os.path.exists(temp_audio):
        os.remove(temp_audio)

    if os.path.exists(output_path):
        size_mb = os.path.getsize(output_path) / (1024 * 1024)
        print(f"\n[DONE] Saved: {output_path} ({size_mb:.1f} MB)")
    else:
        print("[ERROR] Final output file missing.")


def record_stream(stream_info: dict, output_dir: str, duration: int, audio_device: str):
    global _ytdlp_proc, _ffmpeg_proc

    os.makedirs(output_dir, exist_ok=True)

    title        = stream_info.get("title", "live_stream")
    stream_url   = stream_info["url"]
    timestamp    = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_title   = sanitize_filename(title)
    output_path  = os.path.join(output_dir, f"{safe_title}_{timestamp}.mp4")
    temp_video   = os.path.join(output_dir, f"{safe_title}_{timestamp}_video_tmp.mp4")
    temp_audio   = os.path.join(output_dir, f"{safe_title}_{timestamp}_audio_tmp.aac")

    print(f"\n{'─'*55}")
    print(f"  LIVE STREAM DETECTED")
    print(f"  Title  : {title}")
    print(f"  URL    : {stream_url}")
    print(f"  Output : {output_path}")
    print(f"{'─'*55}\n")

    # ── yt-dlp: record stream to temp video file ──
    ytdlp_cmd = [
        "yt-dlp",
        "-f", "bestvideo+bestaudio/best",
        "--merge-output-format", "mp4",
        "--no-playlist",
        "--no-part",                   # write directly, no .part files
        "--hls-use-mpegts",            # write mpeg-ts chunks as they arrive
        "-o", temp_video,
        stream_url,
    ]
    if duration > 0:
        ytdlp_cmd += ["--download-sections", f"*0-{duration}"]

    # ── ffmpeg: capture internal (BlackHole) audio to temp aac file ──
    ffmpeg_cmd = [
        "ffmpeg", "-y",
        "-f", "avfoundation",
        "-i", f"none:{audio_device}",
        "-c:a", "aac", "-b:a", "192k",
        temp_audio,
    ]
    if duration > 0:
        ffmpeg_cmd = ffmpeg_cmd[:3] + ["-t", str(duration)] + ffmpeg_cmd[3:]

    print("[INFO] Recording started. Press Ctrl+C to stop and save.\n")

    try:
        _ytdlp_proc  = subprocess.Popen(ytdlp_cmd)
        _ffmpeg_proc = subprocess.Popen(
            ffmpeg_cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )

        if duration > 0:
            # Wait for duration then stop automatically
            time.sleep(duration + 5)
            stop_processes()
        else:
            # Wait until user presses Ctrl+C
            _ytdlp_proc.wait()

    except KeyboardInterrupt:
        print("\n[INFO] Ctrl+C received — stopping and saving...")
        stop_processes()

    # Give processes a moment to flush buffers
    time.sleep(2)

    mux_and_save(temp_video, temp_audio, output_path)


def main():
    print("=" * 55)
    print("  YouTube Live Recorder — RSS Feed Mode (macOS)")
    print("=" * 55)

    check_dependencies()

    print(f"\n[INFO] RSS Feed : {RSS_FEED_URL}")
    print(f"[INFO] Output   : {OUTPUT_DIR}")

    stream_info = get_live_entry(RSS_FEED_URL)

    if not stream_info:
        print(f"\n[INFO] Not live right now. Checking every {POLL_INTERVAL}s... Press Ctrl+C to quit.\n")
        while not stream_info:
            time.sleep(POLL_INTERVAL)
            now = datetime.now().strftime("%H:%M:%S")
            print(f"[{now}] Checking...")
            stream_info = get_live_entry(RSS_FEED_URL)

    record_stream(
        stream_info=stream_info,
        output_dir=OUTPUT_DIR,
        duration=RECORD_DURATION_SECONDS,
        audio_device=AUDIO_DEVICE,
    )


if __name__ == "__main__":
    main()