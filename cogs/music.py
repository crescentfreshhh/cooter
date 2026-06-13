import asyncio
import yt_dlp
import discord
from discord.ext import commands

YDL_OPTIONS = {
    "format": "bestaudio/best",
    "noplaylist": False,
    "quiet": True,
    "no_warnings": True,
    "default_search": "ytsearch",
    "source_address": "0.0.0.0",
}

FFMPEG_OPTIONS = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn",
}


def get_spotify_query(url: str) -> str | None:
    """Convert a Spotify URL to a search query via the Spotify API if configured."""
    import os
    import re

    client_id = os.getenv("SPOTIFY_CLIENT_ID")
    client_secret = os.getenv("SPOTIFY_CLIENT_SECRET")
    if not client_id or not client_secret:
        return None

    track_match = re.search(r"spotify\.com/track/([A-Za-z0-9]+)", url)
    if not track_match:
        return None

    import spotipy
    from spotipy.oauth2 import SpotifyClientCredentials

    sp = spotipy.Spotify(
        auth_manager=SpotifyClientCredentials(
            client_id=client_id, client_secret=client_secret
        )
    )
    track = sp.track(track_match.group(1))
    artists = ", ".join(a["name"] for a in track["artists"])
    return f"{artists} - {track['name']}"


class MusicQueue:
    def __init__(self):
        self.queue: list[dict] = []
        self.current: dict | None = None

    def add(self, entry: dict):
        self.queue.append(entry)

    def next(self) -> dict | None:
        if self.queue:
            self.current = self.queue.pop(0)
            return self.current
        self.current = None
        return None

    def clear(self):
        self.queue.clear()
        self.current = None


class Music(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.queues: dict[int, MusicQueue] = {}

    def get_queue(self, guild_id: int) -> MusicQueue:
        if guild_id not in self.queues:
            self.queues[guild_id] = MusicQueue()
        return self.queues[guild_id]

    async def resolve_entries(self, query: str) -> list[dict]:
        """Resolve a URL or search query to a list of yt-dlp entries."""
        if query.startswith("http") and "spotify.com" in query:
            resolved = get_spotify_query(query)
            if resolved:
                query = resolved
            else:
                return []

        loop = asyncio.get_event_loop()
        with yt_dlp.YoutubeDL(YDL_OPTIONS) as ydl:
            info = await loop.run_in_executor(
                None, lambda: ydl.extract_info(query, download=False)
            )

        if "entries" in info:
            return [e for e in info["entries"] if e]
        return [info]

    def play_next(self, ctx: commands.Context):
        queue = self.get_queue(ctx.guild.id)
        entry = queue.next()
        if not entry:
            return

        source = discord.FFmpegPCMAudio(entry["url"], **FFMPEG_OPTIONS)
        ctx.voice_client.play(
            discord.PCMVolumeTransformer(source, volume=0.5),
            after=lambda e: self.bot.loop.call_soon_threadsafe(self.play_next, ctx),
        )
        asyncio.run_coroutine_threadsafe(
            ctx.send(f":musical_note: Now playing: **{entry.get('title', 'Unknown')}**"),
            self.bot.loop,
        )

    @commands.command(aliases=["p"])
    async def play(self, ctx: commands.Context, *, query: str):
        """Play a song or playlist from a URL or search query."""
        if not ctx.author.voice:
            return await ctx.send("You need to be in a voice channel.")

        if not ctx.voice_client:
            await ctx.author.voice.channel.connect()
        elif ctx.voice_client.channel != ctx.author.voice.channel:
            await ctx.voice_client.move_to(ctx.author.voice.channel)

        async with ctx.typing():
            entries = await self.resolve_entries(query)

        if not entries:
            return await ctx.send("Could not find anything for that query.")

        queue = self.get_queue(ctx.guild.id)
        for entry in entries:
            queue.add(entry)

        if len(entries) > 1:
            await ctx.send(f"Queued **{len(entries)}** tracks.")
        else:
            await ctx.send(f"Queued: **{entries[0].get('title', 'Unknown')}**")

        if not ctx.voice_client.is_playing():
            self.play_next(ctx)

    @commands.command()
    async def skip(self, ctx: commands.Context):
        """Skip the current song."""
        if ctx.voice_client and ctx.voice_client.is_playing():
            ctx.voice_client.stop()
            await ctx.send("Skipped.")
        else:
            await ctx.send("Nothing is playing.")

    @commands.command()
    async def stop(self, ctx: commands.Context):
        """Stop playback and clear the queue."""
        queue = self.get_queue(ctx.guild.id)
        queue.clear()
        if ctx.voice_client:
            ctx.voice_client.stop()
            await ctx.voice_client.disconnect()
        await ctx.send("Stopped and disconnected.")

    @commands.command()
    async def queue(self, ctx: commands.Context):
        """Show the current queue."""
        queue = self.get_queue(ctx.guild.id)
        if not queue.current and not queue.queue:
            return await ctx.send("The queue is empty.")

        lines = []
        if queue.current:
            lines.append(f":arrow_forward: **{queue.current.get('title', 'Unknown')}**")
        for i, entry in enumerate(queue.queue[:10], 1):
            lines.append(f"{i}. {entry.get('title', 'Unknown')}")
        if len(queue.queue) > 10:
            lines.append(f"...and {len(queue.queue) - 10} more")

        await ctx.send("\n".join(lines))

    @commands.command()
    async def pause(self, ctx: commands.Context):
        """Pause playback."""
        if ctx.voice_client and ctx.voice_client.is_playing():
            ctx.voice_client.pause()
            await ctx.send("Paused.")

    @commands.command()
    async def resume(self, ctx: commands.Context):
        """Resume playback."""
        if ctx.voice_client and ctx.voice_client.is_paused():
            ctx.voice_client.resume()
            await ctx.send("Resumed.")

    @commands.command()
    async def volume(self, ctx: commands.Context, vol: int):
        """Set volume (0-100)."""
        if not ctx.voice_client or not ctx.voice_client.source:
            return await ctx.send("Nothing is playing.")
        if not 0 <= vol <= 100:
            return await ctx.send("Volume must be between 0 and 100.")
        ctx.voice_client.source.volume = vol / 100
        await ctx.send(f"Volume set to {vol}%.")


async def setup(bot: commands.Bot):
    await bot.add_cog(Music(bot))
