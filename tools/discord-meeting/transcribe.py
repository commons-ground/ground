#!/usr/bin/env python3
"""録った通話を文字にする（discord-meeting の2段目）。

record.mjs が書いた segments/<開始ミリ秒>_<ユーザーID>.ogg を、話した順に faster-whisper で文字にし、
「[分:秒] 名前：話した内容」の transcript.md にする。話す人ごとに音が分かれているので、
誰が話したかは推測しなくてよい。

中身はログに出さない（公開リポジトリの Actions で動くため）。

usage: transcribe.py REC_DIR [--model large-v3-turbo] [--language ja]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path

import numpy as np
from faster_whisper import WhisperModel

ap = argparse.ArgumentParser()
ap.add_argument("rec")
ap.add_argument("--model", default="large-v3-turbo")
ap.add_argument("--language", default="ja")
a = ap.parse_args()

rec = Path(a.rec)
meta = json.loads((rec / "meta.json").read_text())
names: dict[str, str] = meta.get("names", {})
t0 = time.time()
model = WhisperModel(a.model, device="cpu", compute_type="int8", cpu_threads=0)


def pcm16k(path: Path) -> np.ndarray:
    raw = subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-i", str(path), "-ac", "1", "-ar", "16000", "-f", "s16le", "-"],
        capture_output=True,
        check=True,
    ).stdout
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0


def mmss(ms: float) -> str:
    s = int(ms // 1000)
    return f"{s // 3600}:{s // 60 % 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60:02d}:{s % 60:02d}"


lines, spoken, skipped = [], 0.0, 0
for f in sorted((rec / "segments").glob("*.ogg")):
    offset_ms, user_id = f.stem.split("_", 1)
    try:
        audio = pcm16k(f)
    except subprocess.CalledProcessError:
        skipped += 1
        continue
    if len(audio) < 16000 * 0.6:  # 0.6秒未満（咳・相づちの切れ端）は飛ばす
        skipped += 1
        continue
    spoken += len(audio) / 16000
    segs, _ = model.transcribe(
        audio,
        language=None if a.language == "auto" else a.language,
        beam_size=1,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 500},
        condition_on_previous_text=False,
    )
    text = "".join(s.text.strip() for s in segs).strip()
    if text:
        lines.append(f"[{mmss(int(offset_ms))}] {names.get(user_id, '参加者')}：{text}")

header = (
    f"# 通話の文字起こし：{meta.get('channel_name', '')}\n\n"
    f"- 日時：{meta.get('started_at', '')} 〜 {meta.get('ended_at', '')}（UTC）\n"
    f"- 参加者：{'、'.join(sorted(set(names.values()))) or '不明'}\n"
    "- 機械の文字起こしなので、聞き間違い（人名・製品名・専門用語）がある\n\n"
)
(rec / "transcript.md").write_text(header + "\n".join(lines) + "\n")
print(f"文字起こし：発言 {len(lines)} 件、話した時間 {spoken / 60:.1f} 分、飛ばした {skipped} 件、{time.time() - t0:.0f} 秒")
