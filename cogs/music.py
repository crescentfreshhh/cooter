import asyncio
import yt_dlp
import discord
from discord import app_commands
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

    def play_next(self, interaction: discord.Interaction):
        queue = self.get_queue(interaction.guild_id)
        entry = queue.next()
        if not entry:
            return

        source = discord.FFmpegPCMAudio(entry["url"], **FFMPEG_OPTIONS)
        interaction.guild.voice_client.play(
            discord.PCMVolumeTransformer(source, volume=0.5),
            after=lambda e: self.bot.loop.call_soon_threadsafe(self.play_next, interaction),
        )
        asyncio.run_coroutine_threadsafe(
            interaction.channel.send(f":musical_note: Now playing: **{entry.get('title', 'Unknown')}**"),
            self.bot.loop,
        )

    @app_commands.command(name="play", description="Play a song or playlist from a URL or search query")
    @app_commands.describe(query="YouTube/Spotify URL or search terms")
    async def play(self, interaction: discord.Interaction, query: str):
        if not interaction.user.voice:
            return await interaction.response.send_message("You need to be in a voice channel.", ephemeral=True)

        await interaction.response.defer()

        vc = interaction.guild.voice_client
        if not vc:
            vc = await interaction.user.voice.channel.connect()
        elif vc.channel != interaction.user.voice.channel:
            await vc.move_to(interaction.user.voice.channel)

        entries = await self.resolve_entries(query)
        if not entries:
            return await interaction.followup.send("Could not find anything for that query.")

        queue = self.get_queue(interaction.guild_id)
        for entry in entries:
            queue.add(entry)

        if len(entries) > 1:
            await interaction.followup.send(f"Queued **{len(entries)}** tracks.")
        else:
            await interaction.followup.send(f"Queued: **{entries[0].get('title', 'Unknown')}**")

        if not vc.is_playing() and not vc.is_paused():
            self.play_next(interaction)

    @app_commands.command(name="skip", description="Skip the current song")
    async def skip(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client
        if vc and vc.is_playing():
            vc.stop()
            await interaction.response.send_message("Skipped.")
        else:
            await interaction.response.send_message("Nothing is playing.", ephemeral=True)

    @app_commands.command(name="stop", description="Stop playback and disconnect")
    async def stop(self, interaction: discord.Interaction):
        queue = self.get_queue(interaction.guild_id)
        queue.clear()
        vc = interaction.guild.voice_client
        if vc:
            vc.stop()
            await vc.disconnect()
        await interaction.response.send_message("Stopped and disconnected.")

    @app_commands.command(name="pause", description="Pause playback")
    async def pause(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client
        if vc and vc.is_playing():
            vc.pause()
            await interaction.response.send_message("Paused.")
        else:
            await interaction.response.send_message("Nothing is playing.", ephemeral=True)

    @app_commands.command(name="resume", description="Resume playback")
    async def resume(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client
        if vc and vc.is_paused():
            vc.resume()
            await interaction.response.send_message("Resumed.")
        else:
            await interaction.response.send_message("Nothing is paused.", ephemeral=True)

    @app_commands.command(name="queue", description="Show the current queue")
    async def queue(self, interaction: discord.Interaction):
        queue = self.get_queue(interaction.guild_id)
        if not queue.current and not queue.queue:
            return await interaction.response.send_message("The queue is empty.")

        lines = []
        if queue.current:
            lines.append(f":arrow_forward: **{queue.current.get('title', 'Unknown')}**")
        for i, entry in enumerate(queue.queue[:10], 1):
            lines.append(f"{i}. {entry.get('title', 'Unknown')}")
        if len(queue.queue) > 10:
            lines.append(f"...and {len(queue.queue) - 10} more")

        await interaction.response.send_message("\n".join(lines))

    @app_commands.command(name="volume", description="Set the volume (0-100)")
    @app_commands.describe(level="Volume level between 0 and 100")
    async def volume(self, interaction: discord.Interaction, level: int):
        vc = interaction.guild.voice_client
        if not vc or not vc.source:
            return await interaction.response.send_message("Nothing is playing.", ephemeral=True)
        if not 0 <= level <= 100:
            return await interaction.response.send_message("Volume must be between 0 and 100.", ephemeral=True)
        vc.source.volume = level / 100
        await interaction.response.send_message(f"Volume set to {level}%.")


async def setup(bot: commands.Bot):
    await bot.add_cog(Music(bot))
