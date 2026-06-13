# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

A Discord music bot ("cooter") that streams audio from YouTube, Spotify, SoundCloud, and any yt-dlp-supported source directly into Discord voice channels. No downloads — audio is streamed in real-time via yt-dlp + FFmpeg. Runs as a Docker container on an Unraid server.

## Commands

```bash
# Run locally (requires Python 3.12+ and ffmpeg installed)
pip install -r requirements.txt
python bot.py

# Build and run via Docker
docker compose up --build

# Run detached
docker compose up -d --build
```

## Architecture

- `bot.py` — entry point, sets up the `commands.Bot` instance and loads the music cog
- `cogs/music.py` — all music logic: queue management, yt-dlp resolution, FFmpeg streaming, Discord voice client control

### How playback works

1. `!play <url or search>` is invoked
2. If Spotify URL: resolved to a track name via Spotify API, then handed to yt-dlp as a search query
3. yt-dlp extracts a raw stream URL (no download) using `extract_info(..., download=False)`
4. `discord.FFmpegPCMAudio` streams that URL through FFmpeg into the voice channel
5. `after` callback on the voice client triggers `play_next` when the track ends

### Queue

`MusicQueue` is a per-guild in-memory queue (dict keyed by guild ID). It holds raw yt-dlp info dicts. State is lost on restart.

## Environment Variables

Copy `.env.example` to `.env` and fill in:

- `DISCORD_TOKEN` — required
- `SPOTIFY_CLIENT_ID` / `SPOTIFY_CLIENT_SECRET` — optional; enables Spotify link resolution. Without these, Spotify links will fail gracefully.

## Bot Commands

| Command | Alias | Description |
|---|---|---|
| `!play <url/query>` | `!p` | Play or queue a song/playlist |
| `!skip` | | Skip current song |
| `!stop` | | Stop and disconnect |
| `!queue` | | Show queue |
| `!pause` | | Pause |
| `!resume` | | Resume |
| `!volume <0-100>` | | Set volume |
