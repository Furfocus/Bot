import discord
from discord.ext import commands
import yt_dlp
import asyncio
from collections import deque
import os

# Load environment variables (works with Railway and local .env)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # dotenv not required for Railway

# Bot setup - Enable required intents
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.guild_messages = True
intents.voice_states = True
bot = commands.Bot(command_prefix="/", intents=intents)

# FFmpeg options for audio playback
FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn'
}

# yt-dlp options
YDL_OPTIONS = {
    'format': 'bestaudio/best',
    'noplaylist': False,
    'default_search': 'ytsearch',
    'quiet': True,
    'no_warnings': True,
    'extract_flat': 'in_playlist',
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

# Store player instances per guild
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
            await player.text_channel.send("Queue is empty.")
        return
    
    track_info = player.queue.popleft()
    player.current_track = track_info
    player.is_playing = True
    player.is_paused = False
    
    try:
        audio_source = discord.FFmpegPCMAudio(
            track_info['url'],
            **FFMPEG_OPTIONS
        )
        
        def after_playing(error):
            if error:
                print(f"Playback error: {error}")
            asyncio.run_coroutine_threadsafe(
                play_next(guild_id, voice_client),
                bot.loop
            )
        
        voice_client.play(audio_source, after=after_playing)
        
        if player.text_channel:
            embed = discord.Embed(
                title="Now Playing",
                description=f"[{track_info['title']}]({track_info['webpage_url']})",
                color=discord.Color.green()
            )
            embed.add_field(name="Duration", value=format_duration(track_info.get('duration', 0)), inline=True)
            embed.add_field(name="Queue Length", value=str(len(player.queue)), inline=True)
            await player.text_channel.send(embed=embed)
    
    except Exception as e:
        print(f"Error playing audio: {e}")
        if player.text_channel:
            await player.text_channel.send(f"Error playing audio: {e}")
        await play_next(guild_id, voice_client)

def format_duration(seconds):
    """Convert seconds to MM:SS format"""
    if not seconds:
        return "Unknown"
    mins, secs = divmod(int(seconds), 60)
    return f"{mins}:{secs:02d}"

async def fetch_youtube_info(url):
    """Fetch video info from YouTube URL"""
    ydl = yt_dlp.YoutubeDL(YDL_OPTIONS)
    try:
        loop = asyncio.get_event_loop()
        info = await loop.run_in_executor(None, lambda: ydl.extract_info(url, download=False))
        return info
    except Exception as e:
        print(f"Error fetching info: {e}")
        return None

async def fetch_channel_videos(channel_url, limit=10):
    """Fetch videos from a YouTube channel"""
    # Convert channel URL to videos list
    if 'youtube.com/@' in channel_url or 'youtube.com/c/' in channel_url or 'youtube.com/user/' in channel_url:
        url = channel_url.rstrip('/') + '/videos'
    else:
        url = channel_url
    
    ydl_options = YDL_OPTIONS.copy()
    ydl_options['extract_flat'] = 'in_playlist'
    ydl_options['playlist_items'] = f'1-{limit}'
    
    ydl = yt_dlp.YoutubeDL(ydl_options)
    try:
        loop = asyncio.get_event_loop()
        info = await loop.run_in_executor(None, lambda: ydl.extract_info(url, download=False))
        return info
    except Exception as e:
        print(f"Error fetching channel videos: {e}")
        return None

@bot.event
async def on_ready():
    print(f"{bot.user} has connected to Discord!")
    await bot.change_presence(activity=discord.Activity(
        type=discord.ActivityType.listening,
        name="/play for music"
    ))

@bot.command(name='play', description='Play a YouTube video or channel')
async def play(ctx, *, args):
    """
    Play a YouTube video or channel
    Usage: /play <YouTube URL>
           /play youtuber <channel URL>
    """
    if not ctx.author.voice:
        return await ctx.send("You need to be in a voice channel!")
    
    player = get_player(ctx.guild.id)
    player.text_channel = ctx.channel
    
    # Check if user wants to play a channel
    if args.lower().startswith('youtuber '):
        channel_url = args[9:].strip()
        await ctx.send(f"📥 Fetching videos from channel... (This may take a moment)")
        
        channel_info = await fetch_channel_videos(channel_url)
        if not channel_info:
            return await ctx.send("❌ Could not fetch channel videos. Check the URL.")
        
        videos = channel_info.get('entries', [])
        if not videos:
            return await ctx.send("❌ No videos found in this channel.")
        
        # Add all videos to queue
        added_count = 0
        for video in videos:
            if video:
                video_url = f"https://www.youtube.com/watch?v={video['id']}"
                video_info = await fetch_youtube_info(video_url)
                if video_info:
                    player.add_to_queue(video_info)
                    added_count += 1
        
        await ctx.send(f"✅ Added {added_count} videos from the channel to queue!")
    
    else:
        # Single video
        video_info = await fetch_youtube_info(args)
        if not video_info:
            return await ctx.send("❌ Could not find that video. Check the URL.")
        
        # Handle playlists
        if 'entries' in video_info:
            for entry in video_info['entries']:
                if entry:
                    player.add_to_queue(entry)
            await ctx.send(f"✅ Added {len(video_info['entries'])} videos to queue!")
        else:
            player.add_to_queue(video_info)
            await ctx.send(f"✅ Added **{video_info['title']}** to queue!")
    
    # Connect to voice channel if not already connected
    if not player.voice_client or not player.voice_client.is_connected():
        player.voice_client = await ctx.author.voice.channel.connect()
    
    # Start playing if not already playing
    if not player.is_playing:
        await play_next(ctx.guild.id, player.voice_client)

@bot.command(name='pause', description='Pause the current track')
async def pause(ctx):
    """Pause the current track"""
    player = get_player(ctx.guild.id)
    
    if not player.voice_client or not player.voice_client.is_playing():
        return await ctx.send("❌ Nothing is currently playing.")
    
    player.voice_client.pause()
    player.is_paused = True
    await ctx.send("⏸️ Paused.")

@bot.command(name='resume', description='Resume the paused track')
async def resume(ctx):
    """Resume the paused track"""
    player = get_player(ctx.guild.id)
    
    if not player.voice_client:
        return await ctx.send("❌ Not connected to a voice channel.")
    
    if not player.is_paused:
        return await ctx.send("❌ Nothing is paused.")
    
    player.voice_client.resume()
    player.is_paused = False
    await ctx.send("▶️ Resumed.")

@bot.command(name='skip', description='Skip the current track')
async def skip(ctx):
    """Skip to the next track"""
    player = get_player(ctx.guild.id)
    
    if not player.voice_client or not player.voice_client.is_playing():
        return await ctx.send("❌ Nothing is currently playing.")
    
    player.voice_client.stop()
    await ctx.send("⏭️ Skipped.")

@bot.command(name='stop', description='Stop playing and clear the queue')
async def stop(ctx):
    """Stop playing and clear the queue"""
    player = get_player(ctx.guild.id)
    
    if not player.voice_client:
        return await ctx.send("❌ Not connected to a voice channel.")
    
    player.voice_client.stop()
    player.clear_queue()
    player.current_track = None
    player.is_playing = False
    player.is_paused = False
    await ctx.send("⏹️ Stopped and cleared queue.")

@bot.command(name='queue', description='Show the current queue')
async def queue(ctx):
    """Display the current queue"""
    player = get_player(ctx.guild.id)
    
    if not player.queue and not player.current_track:
        return await ctx.send("Queue is empty.")
    
    # Build queue display
    embed = discord.Embed(title="Music Queue", color=discord.Color.blue())
    
    if player.current_track:
        embed.add_field(
            name="Currently Playing",
            value=f"[{player.current_track['title']}]({player.current_track['webpage_url']})",
            inline=False
        )
    
    queue_list = player.get_queue()
    if queue_list:
        queue_text = ""
        for idx, track in enumerate(queue_list[:10], 1):  # Show first 10
            duration = format_duration(track.get('duration', 0))
            queue_text += f"{idx}. [{track['title']}]({track['webpage_url']}) - {duration}\n"
        
        if len(queue_list) > 10:
            queue_text += f"\n... and {len(queue_list) - 10} more"
        
        embed.add_field(name="Up Next", value=queue_text, inline=False)
        embed.set_footer(text=f"Total in queue: {len(queue_list)}")
    
    await ctx.send(embed=embed)

@bot.command(name='disconnect', description='Disconnect from voice channel')
async def disconnect(ctx):
    """Disconnect from voice channel"""
    player = get_player(ctx.guild.id)
    
    if not player.voice_client:
        return await ctx.send("❌ Not connected to a voice channel.")
    
    await player.voice_client.disconnect()
    player.voice_client = None
    await ctx.send("👋 Disconnected.")

# Main execution
if __name__ == "__main__":
    TOKEN = os.getenv('DISCORD_TOKEN')
    
    if not TOKEN:
        print("❌ Error: DISCORD_TOKEN not found in .env file!")
        print("Please create a .env file with your Discord bot token.")
        print("See .env.example for reference.")
        exit(1)
    
    bot.run(TOKEN)
