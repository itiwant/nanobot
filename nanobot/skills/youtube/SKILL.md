---
name: youtube
description: Download videos, extract subtitles/transcripts, get metadata, and search YouTube, Bilibili, and 1800+ other video sites using yt-dlp. Use when the user asks to watch, summarize, transcribe, download, search, or get information about any video from YouTube, Bilibili, or other video platforms. Also use for audio extraction (podcast-style) or getting subtitles from video URLs.
homepage: https://github.com/yt-dlp/yt-dlp
metadata: {"nanobot":{"emoji":"📺","requires":{"bins":["yt-dlp"]},"install":[{"id":"pip","kind":"pip","package":"yt-dlp","bins":["yt-dlp"],"label":"Install yt-dlp (pip)"},{"id":"brew","kind":"brew","formula":"yt-dlp","bins":["yt-dlp"],"label":"Install yt-dlp (brew)"}]}}
---

# YouTube / Video Skill

`yt-dlp` can access YouTube, Bilibili, Twitter, TikTok, and 1800+ other video sites.

## Install

```bash
pip install -U yt-dlp          # recommended (always latest)
# or
brew install yt-dlp
```

## Get video info & metadata

```bash
yt-dlp --dump-json "https://www.youtube.com/watch?v=VIDEO_ID" | python3 -c "
import json,sys
d=json.load(sys.stdin)
print('Title:', d['title'])
print('Channel:', d['uploader'])
print('Duration:', d['duration'], 'sec')
print('Views:', d.get('view_count'))
print('Description:', d['description'][:300])
"
```

For multiple fields at once (no Python needed):
```bash
yt-dlp --print "%(title)s | %(uploader)s | %(duration_string)s | %(view_count)s views" "URL"
```

## Extract subtitles / transcript

Auto-generated subtitles (best for most YouTube videos):
```bash
yt-dlp --write-auto-subs --sub-langs "en,vi,zh-Hans" --skip-download \
  --convert-subs srt -o "/tmp/%(title)s.%(ext)s" "URL"
# Output: /tmp/<title>.en.srt  (plain text, readable)
```

Check which subtitle languages are available:
```bash
yt-dlp --list-subs "URL"
```

Extract subtitle text only (strip timestamps):
```bash
yt-dlp --write-auto-subs --sub-langs en --skip-download \
  --convert-subs srt -o "/tmp/video.%(ext)s" "URL" \
  && grep -vE '^([0-9]|-->|$)' /tmp/video.en.srt
```

## Download audio (MP3)

```bash
yt-dlp -x --audio-format mp3 --audio-quality 192k \
  -o "/tmp/%(title)s.%(ext)s" "URL"
```

## Download video

Best quality (auto-merge video+audio):
```bash
yt-dlp -f "bestvideo+bestaudio" --merge-output-format mp4 \
  -o "/tmp/%(title)s.%(ext)s" "URL"
```

Limit resolution (saves bandwidth):
```bash
yt-dlp -f "bestvideo[height<=720]+bestaudio" --merge-output-format mp4 \
  -o "/tmp/%(title)s.%(ext)s" "URL"
```

Check available formats before downloading:
```bash
yt-dlp -F "URL"
```

## Search YouTube

Search and get top results:
```bash
yt-dlp --dump-json "ytsearch5:your search query" | python3 -c "
import json,sys
for line in sys.stdin:
    d=json.loads(line)
    print(d['title'], '|', d['webpage_url'], '|', d['duration_string'])
"
```

## Bilibili 🇨🇳

Same commands work for Bilibili URLs:
```bash
yt-dlp --dump-json "https://www.bilibili.com/video/BV..."
yt-dlp --write-auto-subs --sub-langs "zh-Hans,en" --skip-download "https://www.bilibili.com/video/BV..."
yt-dlp -f "bestvideo+bestaudio" "https://www.bilibili.com/video/BV..."
```

> **Server note:** Bilibili blocks non-CN server IPs. If behind a server, configure a proxy:
> ```bash
> yt-dlp --proxy "http://user:pass@host:port" "URL"
> ```

## Playlist / channel

Download whole playlist (audio only):
```bash
yt-dlp -x --audio-format mp3 -o "/tmp/%(playlist_index)s-%(title)s.%(ext)s" \
  "https://www.youtube.com/playlist?list=PLAYLIST_ID"
```

List playlist items without downloading:
```bash
yt-dlp --flat-playlist --dump-json "PLAYLIST_URL" | python3 -c "
import json,sys
for line in sys.stdin:
    d=json.loads(line)
    print(d.get('title','?'), '|', d.get('url','?'))
"
```

## Tips

- Always save to `/tmp/` to keep workspace clean.
- Use `--no-playlist` when passing a video URL that is part of a playlist.
- Use `--cookies-from-browser chrome` for age-restricted or login-required content (local only).
- Subtitle files (`.srt`) in `/tmp/` can be read with `read_file` and summarized or sent to the user.
- For very long transcripts, read key sections and summarize before sending to user.
- After downloading a file, send it to the user via the `message` tool with the `media` field.
