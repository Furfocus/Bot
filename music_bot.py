import discord
from discord.ext import commands
from discord import app_commands
import yt_dlp
import asyncio
import os
import re

try:
    from dotenv import load_dotenv
    load_dotenv()
except:
    pass

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
bot = commands.Bot(command_prefix="/", intents=intents)

# Multiple FFmpeg fallback options (from best to worst)
FFMPEG_OPTIONS_LIST = [
    {
        'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -bufsize 10000k',
        'options': '-vn -q:a 9 -b:a 128k'
    },
    {
        'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
        'options': '-vn -q:a 9'
    },
    {
        'before_options': '-reconnect 1 -reconnect_delay_max 5',
        'options': '-vn'
    },
    {
        'before_options': '',
        'options': '-vn'
    }
]

# Multiple YDL format options (from best to worst)
YDL_FORMAT_OPTIONS = [
    'worstaudio/worst',
    'worst',
    'bestaudio[ext=m4a]/best[ext=m4a]/best',
]

# YouTube headers to look like a real browser
YDL_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept-Language': 'en-US,en;q=0.9',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
}

class Player:
    def __init__(self):
        self.queue = []
        self.playing = False
        self.voice = None
        self.text_channel = None

players = {}

def get_player(guild_id):
    if guild_id not in players:
        players[guild_id] = Player()
    return players[guild_id]

async def clean_youtube_url(url):
    """Clean YouTube URL by removing extra parameters"""
    # Handle youtu.be short links
    if 'youtu.be' in url:
        # Extract just the video ID
        match = re.search(r'youtu\.be/([a-zA-Z0-9_-]{11})', url)
        if match:
            video_id = match.group(1)
            return f"https://youtu.be/{video_id}"
    
    # Handle youtube.com full links
    if 'youtube.com/watch' in url:
        match = re.search(r'[?&]v=([a-zA-Z0-9_-]{11})', url)
        if match:
            video_id = match.group(1)
            return f"https://www.youtube.com/watch?v={video_id}"
    
    # Return original if no match
    return url

async def get_audio_url(url, format_idx=0):
    """Extract audio URL from YouTube with fallback formats"""
    if format_idx >= len(YDL_FORMAT_OPTIONS):
        return None
    
    # Clean the URL first
    url = await clean_youtube_url(url)
    print(f"[INFO] Cleaned URL: {url}")
    
    try:
        ydl_options = {
            'format': YDL_FORMAT_OPTIONS[format_idx],
            'noplaylist': False,
            'quiet': True,
            'no_warnings': True,
            'socket_timeout': 30,
            'http_headers': YDL_HEADERS,
        }
        
        ydl = yt_dlp.YoutubeDL(ydl_options)
        info = await asyncio.to_thread(ydl.extract_info, url, download=False)
        
        # Try to get URL from various sources
        audio_url = None
        if info.get('url'):
            audio_url = info.get('url')
        elif info.get('formats'):
            for fmt in info['formats']:
                if fmt.get('url'):
                    audio_url = fmt.get('url')
                    break
        
        if audio_url:
            print(f"[SUCCESS] Got URL with format {format_idx}")
            return {
                'url': audio_url,
                'title': info.get('title', 'Unknown'),
                'webpage_url': info.get('webpage_url', url)
            }
        else:
            print(f"[FALLBACK] Format {format_idx} had no URL, trying next...")
            return await get_audio_url(url, format_idx + 1)
    
    except Exception as e:
        print(f"[FALLBACK] Format {format_idx} failed: {e}")
        return await get_audio_url(url, format_idx + 1)

async def play_with_fallback(voice_client, audio_info, after_callback, ffmpeg_idx=0):
    """Try to play audio with fallback FFmpeg options"""
    if ffmpeg_idx >= len(FFMPEG_OPTIONS_LIST):
        print("[ERROR] All FFmpeg options failed")
        return False
    
    try:
        print(f"[ATTEMPT] Playing with FFmpeg option {ffmpeg_idx}")
        ffmpeg_options = FFMPEG_OPTIONS_LIST[ffmpeg_idx]
        
        source = discord.FFmpegPCMAudio(
            audio_info['url'],
            before_options=ffmpeg_options['before_options'],
            options=ffmpeg_options['options']
        )
        
        voice_client.play(source, after=after_callback)
        print(f"[SUCCESS] Playing with FFmpeg option {ffmpeg_idx}")
        return True
    
    except Exception as e:
        print(f"[FALLBACK] FFmpeg option {ffmpeg_idx} failed: {e}")
        if ffmpeg_idx + 1 < len(FFMPEG_OPTIONS_LIST):
            await asyncio.sleep(0.5)
            return await play_with_fallback(voice_client, audio_info, after_callback, ffmpeg_idx + 1)
        return False

@bot.event
async def on_ready():
    print(f"Bot logged in as {bot.user}")
    try:
        await bot.tree.sync()
    except:
        pass

@bot.tree.command(name="play", description="Play a YouTube video")
@app_commands.describe(url="YouTube video URL")
async def play(interaction: discord.Interaction, url: str):
    """Play a YouTube video with multiple fallback methods"""
    await interaction.response.defer()
    
    if not interaction.user.voice:
        return await interaction.followup.send("Join a voice channel first!")
    
    player = get_player(interaction.guild.id)
    player.text_channel = interaction.channel
    
    # Get audio info with fallback
    await interaction.followup.send("⏳ Loading...")
    audio_info = await get_audio_url(url)
    
    if not audio_info:
        return await interaction.followup.send("❌ Could not find video")
    
    # Connect to voice
    if not player.voice or not player.voice.is_connected():
        try:
            player.voice = await interaction.user.voice.channel.connect()
            print("[SUCCESS] Connected to voice channel")
        except Exception as e:
            print(f"[ERROR] Failed to connect to voice: {e}")
            return await interaction.followup.send(f"❌ Can't connect: {str(e)}")
    
    # Play audio with fallback
    if not player.voice.is_playing():
        try:
            def after(error):
                if error and str(error) != '':
                    print(f"[ERROR] Playback error: {error}")
            
            success = await play_with_fallback(
                player.voice,
                audio_info,
                after
            )
            
            if success:
                player.playing = True
                await interaction.followup.send(f"🎵 Now playing: **{audio_info['title']}**")
            else:
                await interaction.followup.send("❌ Could not start playback (all methods failed)")
                player.playing = False
        
        except Exception as e:
            print(f"[ERROR] Playback exception: {e}")
            await interaction.followup.send(f"❌ Error: {str(e)}")
            player.playing = False

@bot.tree.command(name="stop", description="Stop playback")
async def stop(interaction: discord.Interaction):
    """Stop playback"""
    player = get_player(interaction.guild.id)
    if player.voice and player.voice.is_playing():
        player.voice.stop()
        player.playing = False
        await interaction.response.send_message("⏹️ Stopped")
    else:
        await interaction.response.send_message("Nothing playing")

@bot.tree.command(name="pause", description="Pause playback")
async def pause(interaction: discord.Interaction):
    """Pause playback"""
    player = get_player(interaction.guild.id)
    if player.voice and player.voice.is_playing():
        player.voice.pause()
        await interaction.response.send_message("⏸️ Paused")
    else:
        await interaction.response.send_message("Nothing playing")

@bot.tree.command(name="resume", description="Resume playback")
async def resume(interaction: discord.Interaction):
    """Resume playback"""
    player = get_player(interaction.guild.id)
    if player.voice and player.voice.is_paused():
        player.voice.resume()
        await interaction.response.send_message("▶️ Resumed")
    else:
        await interaction.response.send_message("Nothing to resume")

@bot.tree.command(name="disconnect", description="Leave voice channel")
async def disconnect(interaction: discord.Interaction):
    """Disconnect from voice"""
    player = get_player(interaction.guild.id)
    if player.voice:
        await player.voice.disconnect()
        player.voice = None
        await interaction.response.send_message("👋 Disconnected")
    else:
        await interaction.response.send_message("Not in voice")

if __name__ == "__main__":
    TOKEN = os.getenv('DISCORD_TOKEN')
    if not TOKEN:
        print("No token!")
        exit(1)
    bot.run(TOKEN)
