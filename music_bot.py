import discord
from discord.ext import commands
from discord import app_commands
import yt_dlp
import asyncio
from collections import deque
import os
import re

# Load environment variables
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Bot setup
intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
bot = commands.Bot(command_prefix="/", intents=intents)

# Optimized FFmpeg options
FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -hide_banner -loglevel error',
    'options': '-vn -q:a 9'
}

# Optimized yt-dlp options
YDL_OPTIONS = {
    'format': 'worstaudio/worst',  # Use lower quality to reduce bandwidth
    'noplaylist': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'ytsearch',
    'socket_timeout': 30,
}

class MusicPlayer:
    """Manages music playback for a guild"""
    def __init__(self):
        self.queue = deque()
        self.current_track = None
        self.is_playing = False
        self.is_paused = False
        self.voice_client = None
        self.text_channel = None
        
    def add_to_queue(self, track_info):
        self.queue.append(track_info)
        
    def get_queue(self):
        return list(self.queue)
    
    def clear_queue(self):
        self.queue.clear()

players = {}

def get_player(guild_id):
    """Get or create a player for a guild"""
    if guild_id not in players:
        players[guild_id] = MusicPlayer()
    return players[guild_id]

async def play_next(guild_id, voice_client):
    """Play the next song in queue"""
    player = get_player(guild_id)
    
    if not player.queue:
        player.is_playing = False
        player.current_track = None
        if player.text_channel:
            try:
                await player.text_channel.send("✅ Queue finished!")
            except:
                pass
        return
    
    # Check if voice client is still connected
    if not voice_client or not voice_client.is_connected():
        print(f"[ERROR] Voice client disconnected")
        player.is_playing = False
        if player.text_channel:
            try:
                await player.text_channel.send("❌ Lost connection to voice channel!")
            except:
                pass
        return
    
    track_info = player.queue.popleft()
    player.current_track = track_info
    player.is_playing = True
    player.is_paused = False
    
    try:
        print(f"[INFO] Playing: {track_info['title']}")
        
        audio_source = discord.FFmpegPCMAudio(
            track_info['url'],
            **FFMPEG_OPTIONS
        )
        
        def after_playing(error):
            if error and str(error) != '':
                print(f"[ERROR] Playback ended with error: {error}")
            asyncio.run_coroutine_threadsafe(
                play_next(guild_id, voice_client),
                bot.loop
            )
        
        voice_client.play(audio_source, after=after_playing)
        
        if player.text_channel:
            try:
                embed = discord.Embed(
                    title="🎵 Now Playing",
                    description=f"[{track_info['title']}]({track_info['webpage_url']})",
                    color=discord.Color.green()
                )
                await player.text_channel.send(embed=embed)
            except:
                pass
    
    except Exception as e:
        print(f"[ERROR] Failed to play: {e}")
        player.is_playing = False
        if player.text_channel:
            try:
                await player.text_channel.send(f"❌ Error playing audio")
            except:
                pass

def format_duration(seconds):
    """Convert seconds to MM:SS format"""
    if not seconds:
        return "Unknown"
    mins, secs = divmod(int(seconds), 60)
    return f"{mins}:{secs:02d}"

async def fetch_youtube_info(url):
    """Fetch video info from YouTube URL"""
    # Clean URL
    if 'youtu.be' in url:
        video_id = url.split('/')[-1].split('?')[0].split('&')[0]
        url = f"https://youtu.be/{video_id}"
    elif 'youtube.com/watch' in url:
        match = re.search(r'[?&]v=([a-zA-Z0-9_-]{11})', url)
        if match:
            video_id = match.group(1)
            url = f"https://www.youtube.com/watch?v={video_id}"
    
    ydl = yt_dlp.YoutubeDL(YDL_OPTIONS)
    try:
        loop = asyncio.get_event_loop()
        print(f"[INFO] Fetching: {url}")
        info = await loop.run_in_executor(None, lambda: ydl.extract_info(url, download=False))
        return info
    except Exception as e:
        print(f"[ERROR] Failed to fetch: {e}")
        return None

async def fetch_channel_videos(channel_url, limit=5):
    """Fetch videos from YouTube channel (reduced from 10 to 5)"""
    if 'youtube.com/@' in channel_url or 'youtube.com/c/' in channel_url or 'youtube.com/user/' in channel_url:
        url = channel_url.rstrip('/') + '/videos'
    else:
        url = channel_url
    
    ydl_options = YDL_OPTIONS.copy()
    ydl_options['playlist_items'] = f'1-{limit}'
    
    ydl = yt_dlp.YoutubeDL(ydl_options)
    try:
        loop = asyncio.get_event_loop()
        info = await loop.run_in_executor(None, lambda: ydl.extract_info(url, download=False))
        return info
    except Exception as e:
        print(f"[ERROR] Failed to fetch channel: {e}")
        return None

@bot.event
async def on_ready():
    print(f"{bot.user} has connected to Discord!")
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s)")
    except Exception as e:
        print(f"Failed to sync commands: {e}")
    
    await bot.change_presence(activity=discord.Activity(
        type=discord.ActivityType.listening,
        name="/play for music"
    ))

@bot.tree.command(name="play", description="Play a YouTube video or channel")
@app_commands.describe(
    url="YouTube video/playlist URL",
    youtuber="YouTube channel URL"
)
async def play(interaction: discord.Interaction, url: str = None, youtuber: str = None):
    """Play YouTube video/channel"""
    await interaction.response.defer()
    
    if not url and not youtuber:
        return await interaction.followup.send("❌ Provide a video or channel URL!")
    
    if not interaction.user.voice:
        return await interaction.followup.send("You must be in a voice channel!")
    
    player = get_player(interaction.guild.id)
    player.text_channel = interaction.channel
    
    # Handle channel
    if youtuber:
        await interaction.followup.send("📥 Loading channel videos...")
        channel_info = await fetch_channel_videos(youtuber)
        if not channel_info or not channel_info.get('entries'):
            return await interaction.followup.send("❌ Could not fetch channel videos.")
        
        videos = channel_info.get('entries', [])
        added = 0
        for video in videos:
            if video:
                vid_url = f"https://www.youtube.com/watch?v={video['id']}"
                vid_info = await fetch_youtube_info(vid_url)
                if vid_info:
                    player.add_to_queue(vid_info)
                    added += 1
        
        await interaction.followup.send(f"✅ Added {added} videos to queue!")
    
    # Handle video/playlist
    elif url:
        await interaction.followup.send("📥 Loading video...")
        video_info = await fetch_youtube_info(url)
        if not video_info:
            return await interaction.followup.send("❌ Could not find that video.")
        
        if 'entries' in video_info:
            count = 0
            for entry in video_info['entries']:
                if entry:
                    player.add_to_queue(entry)
                    count += 1
            await interaction.followup.send(f"✅ Added {count} videos to queue!")
        else:
            player.add_to_queue(video_info)
            await interaction.followup.send(f"✅ Added **{video_info['title']}** to queue!")
    
    # Connect to voice
    if not player.voice_client or not player.voice_client.is_connected():
        try:
            player.voice_client = await interaction.user.voice.channel.connect()
            print(f"[INFO] Connected to voice")
        except Exception as e:
            return await interaction.followup.send(f"❌ Failed to connect: {str(e)}")
    
    # Start playing
    if not player.is_playing:
        await asyncio.sleep(0.5)  # Brief delay for connection
        await play_next(interaction.guild.id, player.voice_client)

@bot.tree.command(name="pause", description="Pause playback")
async def pause(interaction: discord.Interaction):
    """Pause current track"""
    player = get_player(interaction.guild.id)
    if not player.voice_client or not player.voice_client.is_playing():
        return await interaction.response.send_message("❌ Nothing playing")
    
    player.voice_client.pause()
    player.is_paused = True
    await interaction.response.send_message("⏸️ Paused")

@bot.tree.command(name="resume", description="Resume playback")
async def resume(interaction: discord.Interaction):
    """Resume paused track"""
    player = get_player(interaction.guild.id)
    if not player.voice_client or not player.is_paused:
        return await interaction.response.send_message("❌ Nothing to resume")
    
    player.voice_client.resume()
    player.is_paused = False
    await interaction.response.send_message("▶️ Resumed")

@bot.tree.command(name="skip", description="Skip current track")
async def skip(interaction: discord.Interaction):
    """Skip to next track"""
    player = get_player(interaction.guild.id)
    if not player.voice_client or not player.voice_client.is_playing():
        return await interaction.response.send_message("❌ Nothing playing")
    
    player.voice_client.stop()
    await interaction.response.send_message("⏭️ Skipped")

@bot.tree.command(name="stop", description="Stop and clear queue")
async def stop(interaction: discord.Interaction):
    """Stop playback and clear queue"""
    player = get_player(interaction.guild.id)
    if not player.voice_client:
        return await interaction.response.send_message("❌ Not in voice")
    
    player.voice_client.stop()
    player.clear_queue()
    player.is_playing = False
    await interaction.response.send_message("⏹️ Stopped")

@bot.tree.command(name="queue", description="Show queue")
async def queue(interaction: discord.Interaction):
    """Display current queue"""
    player = get_player(interaction.guild.id)
    
    if not player.queue and not player.current_track:
        return await interaction.response.send_message("Queue is empty")
    
    embed = discord.Embed(title="🎵 Queue", color=discord.Color.blue())
    
    if player.current_track:
        embed.add_field(
            name="Now Playing",
            value=f"[{player.current_track['title']}]({player.current_track['webpage_url']})",
            inline=False
        )
    
    queue_list = player.get_queue()
    if queue_list:
        text = ""
        for idx, track in enumerate(queue_list[:5], 1):
            text += f"{idx}. {track['title']}\n"
        if len(queue_list) > 5:
            text += f"\n... and {len(queue_list) - 5} more"
        embed.add_field(name="Up Next", value=text, inline=False)
    
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="disconnect", description="Leave voice channel")
async def disconnect(interaction: discord.Interaction):
    """Disconnect from voice"""
    player = get_player(interaction.guild.id)
    if not player.voice_client:
        return await interaction.response.send_message("❌ Not in voice")
    
    await player.voice_client.disconnect()
    player.voice_client = None
    await interaction.response.send_message("👋 Disconnected")

if __name__ == "__main__":
    TOKEN = os.getenv('DISCORD_TOKEN')
    if not TOKEN:
        print("❌ DISCORD_TOKEN not found!")
        exit(1)
    
    bot.run(TOKEN)
