import discord
from discord.ext import commands
from discord import app_commands
import yt_dlp
import asyncio
import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except:
    pass

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
bot = commands.Bot(command_prefix="/", intents=intents)

# More robust FFmpeg settings
FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn -q:a 9'
}

YDL_OPTIONS = {
    'format': 'worstaudio/worst',
    'noplaylist': False,
    'quiet': True,
    'no_warnings': True,
    'socket_timeout': 30,
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

async def get_audio_url(url):
    """Extract audio URL from YouTube"""
    ydl = yt_dlp.YoutubeDL(YDL_OPTIONS)
    try:
        info = await asyncio.to_thread(ydl.extract_info, url, download=False)
        return {
            'url': info.get('url') or info.get('formats', [{}])[0].get('url'),
            'title': info.get('title', 'Unknown'),
            'webpage_url': info.get('webpage_url', url)
        }
    except:
        return None

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
    """Play a YouTube video"""
    await interaction.response.defer()
    
    if not interaction.user.voice:
        return await interaction.followup.send("Join a voice channel first!")
    
    player = get_player(interaction.guild.id)
    player.text_channel = interaction.channel
    
    # Get audio info
    await interaction.followup.send("⏳ Loading...")
    audio_info = await get_audio_url(url)
    
    if not audio_info:
        return await interaction.followup.send("❌ Could not find video")
    
    # Connect to voice
    if not player.voice or not player.voice.is_connected():
        try:
            player.voice = await interaction.user.voice.channel.connect()
        except Exception as e:
            return await interaction.followup.send(f"❌ Can't connect: {str(e)}")
    
    # Play audio
    if not player.voice.is_playing():
        try:
            source = discord.FFmpegPCMAudio(audio_info['url'], **FFMPEG_OPTIONS)
            
            def after(error):
                if error:
                    print(f"Playback error: {error}")
            
            player.voice.play(source, after=after)
            player.playing = True
            
            await interaction.followup.send(f"🎵 Now playing: **{audio_info['title']}**")
        except Exception as e:
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
