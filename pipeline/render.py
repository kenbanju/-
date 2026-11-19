"""episode.json から縦型ショート動画（1080x1920）を自動生成するスクリプト。

流れ: VOICEVOX で場面ごとの音声 → Gemini API で場面イラスト → 字幕を重ねて ffmpeg で結合。

使い方:
  python pipeline/render.py episodes/001-sleep-hours
  python pipeline/render.py episodes/001-sleep-hours --mock   # API を使わず動作確認

環境変数:
  GEMINI_API_KEY    Gemini API キー（--mock のときは不要）
  GEMINI_IMAGE_MODEL  画像生成モデル（既定: gemini-3.1-flash-image）
  VOICEVOX_URL      VOICEVOX エンジンの URL（既定: http://localhost:50021）
"""
import argparse
import base64
import glob
import json
import os
import subprocess
import sys
import textwrap
import time
import urllib.error
import urllib.parse
import urllib.request

from PIL import Image, ImageDraw, ImageFont

W, H = 1080, 1920
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHANNEL = os.path.join(ROOT, "channel.json")
CHARACTER = os.path.join(ROOT, "assets", "character.png")
VOICEVOX_URL = os.environ.get("VOICEVOX_URL", "http://localhost:50021")
GEMINI_MODEL = os.environ.get("GEMINI_IMAGE_MODEL", "gemini-3.1-flash-image")


def log(msg):
    print(msg, flush=True)


def find_font():
    pats = [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/**/NotoSansCJK*Bold*.tt*",
        "/usr/share/fonts/**/NotoSansCJK*.tt*",
        "/usr/share/fonts/**/*CJK*.tt*",
    ]
    for p in pats:
        hits = sorted(glob.glob(p, recursive=True))
        if hits:
            return hits[0]
    sys.exit("日本語フォントが見つかりません（fonts-noto-cjk をインストールしてください）")


def http_json(url, data=None, headers=None, timeout=180):
    req = urllib.request.Request(url, data=data, headers=headers or {}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


# ---------- 音声（VOICEVOX） ----------
def synth_voice(text, speaker, out_wav, speed, mock):
    if mock:
        secs = max(2.0, len(text) / 5.5)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                        "anullsrc=r=24000:cl=mono", "-t", f"{secs:.2f}", out_wav], check=True)
        return
    q = urllib.parse.urlencode({"text": text, "speaker": speaker})
    query = json.loads(http_json(f"{VOICEVOX_URL}/audio_query?{q}", data=b""))
    query["speedScale"] = speed
    query["postPhonemeLength"] = 0.3
    wav = http_json(f"{VOICEVOX_URL}/synthesis?speaker={speaker}",
                    data=json.dumps(query).encode(), headers={"Content-Type": "application/json"})
    with open(out_wav, "wb") as f:
        f.write(wav)


def wav_seconds(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "default=nw=1:nk=1", path], capture_output=True, text=True, check=True)
    return float(out.stdout.strip())


# ---------- 画像（Gemini API） ----------
def gemini_image(prompt, ref_png, out_png):
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        sys.exit("GEMINI_API_KEY が設定されていません")
    parts = [{"text": prompt}]
    if ref_png and os.path.exists(ref_png):
        with open(ref_png, "rb") as f:
            parts.append({"inline_data": {"mime_type": "image/png",
                                          "data": base64.b64encode(f.read()).decode()}})
    body = {"contents": [{"parts": parts}],
            "generationConfig": {"responseFormat": {"image": {"aspectRatio": "9:16"}}}}
    url = f"https://generativelanguage.googleapis.com/v1/models/{GEMINI_MODEL}:generateContent"
    headers = {"x-goog-api-key": key, "Content-Type": "application/json"}
    for attempt in range(4):
        try:
            res = json.loads(http_json(url, json.dumps(body).encode(), headers))
            break
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:500]
            if e.code == 400 and "generationConfig" in body:
                log(f"  generationConfig を外して再試行します: {detail}")
                body.pop("generationConfig")
                continue
            if e.code in (429, 500, 503) and attempt < 3:
                time.sleep(10 * (attempt + 1))
                continue
            sys.exit(f"Gemini API エラー {e.code}: {detail}")
    for cand in res.get("candidates", []):
        for p in cand.get("content", {}).get("parts", []):
            d = p.get("inlineData") or p.get("inline_data")
            if d and not p.get("thought"):
                with open(out_png, "wb") as f:
                    f.write(base64.b64decode(d["data"]))
                return
    sys.exit(f"画像が返りませんでした: {json.dumps(res)[:500]}")


def mock_image(text, out_png, font_path):
    img = Image.new("RGB", (W, H), (226, 240, 228))
    d = ImageDraw.Draw(img)
    f = ImageFont.truetype(font_path, 48)
    d.multiline_text((80, 600), textwrap.fill(text, 18), font=f, fill=(60, 90, 70), spacing=16)
    img.save(out_png)


# ---------- 字幕を重ねる ----------
def compose_frame(src_png, subtitle, out_png, font_path, credit=None):
    base = Image.new("RGB", (W, H), (255, 255, 255))
    im = Image.open(src_png).convert("RGB")
    scale = max(W / im.width, H / im.height)
    im = im.resize((int(im.width * scale), int(im.height * scale)))
    base.paste(im, ((W - im.width) // 2, (H - im.height) // 2))
    d = ImageDraw.Draw(base, "RGBA")
    if subtitle:
        f = ImageFont.truetype(font_path, 64)
        lines = textwrap.wrap(subtitle, 14)
        lh = 84
        top = int(H * 0.60)
        d.rounded_rectangle((60, top - 30, W - 60, top + lh * len(lines) + 20),
                            radius=32, fill=(255, 255, 255, 225))
        for i, line in enumerate(lines):
            tw = d.textlength(line, font=f)
            d.text(((W - tw) / 2, top + i * lh), line, font=f, fill=(40, 40, 40))
    if credit:
        f2 = ImageFont.truetype(font_path, 30)
        d.text((40, H - 70), credit, font=f2, fill=(90, 90, 90))
    base.save(out_png)


def render(ep_dir, mock):
    ep_dir = os.path.abspath(ep_dir)
    with open(os.path.join(ep_dir, "episode.json"), encoding="utf-8") as f:
        ep = json.load(f)
    with open(CHANNEL, encoding="utf-8") as f:
        ch = json.load(f)
    font = find_font()
    work = os.path.join(ep_dir, "build")
    os.makedirs(work, exist_ok=True)
    speaker = ep.get("speaker", ch["voice"]["speaker"])
    speed = ep.get("speed", ch["voice"].get("speed", 1.1))
    credit = ch["voice"].get("credit")
    style = ch["image_style"]

    # キャラクターの基準画像（なければ最初に作る）
    if not os.path.exists(CHARACTER):
        os.makedirs(os.path.dirname(CHARACTER), exist_ok=True)
        log("キャラクター基準画像を生成します")
        if mock:
            mock_image("キャラクター（モック）", CHARACTER, font)
        else:
            gemini_image(f"{ch['character']}。{style}。全身、正面、白背景、文字なし。", None, CHARACTER)

    segments = []
    for i, sc in enumerate(ep["scenes"], 1):
        log(f"場面 {i}/{len(ep['scenes'])}")
        wav = os.path.join(work, f"s{i:02d}.wav")
        raw = os.path.join(work, f"s{i:02d}_raw.png")
        frame = os.path.join(work, f"s{i:02d}.png")
        seg = os.path.join(work, f"s{i:02d}.mp4")
        synth_voice(sc["narration"], speaker, wav, speed, mock)
        if not os.path.exists(raw):
            prompt = (f"添付したキャラクターと同じ見た目で、{sc['image_prompt']}。"
                      f"{style}。縦長9:16、文字やロゴは入れない。")
            if mock:
                mock_image(sc["image_prompt"], raw, font)
            else:
                gemini_image(prompt, CHARACTER, raw)
        compose_frame(raw, sc.get("subtitle", ""), frame, font, credit)
        dur = wav_seconds(wav) + 0.2
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-i", frame, "-i", wav,
                        "-t", f"{dur:.2f}", "-r", "30", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                        "-c:a", "aac", "-ar", "44100", "-ac", "2", "-shortest", seg], check=True)
        segments.append(seg)

    lst = os.path.join(work, "concat.txt")
    with open(lst, "w") as f:
        f.writelines(f"file '{s}'\n" for s in segments)
    out = os.path.join(ep_dir, "video.mp4")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", lst,
                    "-c", "copy", out], check=True)
    total = wav_seconds(out)
    log(f"完成: {out}（{total:.1f}秒）")
    if total > 60:
        log("注意: 60秒を超えています。台本を短くしてください。")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("episode_dir")
    ap.add_argument("--mock", action="store_true", help="API を使わずにダミーの音声・画像で動作確認する")
    a = ap.parse_args()
    render(a.episode_dir, a.mock)
