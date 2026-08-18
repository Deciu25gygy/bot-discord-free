import discord
from discord.ext import commands, tasks
from datetime import datetime, timedelta, timezone
import yt_dlp
import asyncio
import re
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials

# ==========================================
# CẤU HÌNH BẮT BUỘC SỬA THÔNG TIN CỦA BẠN
# ==========================================
TOKEN = "MTUzOTI1OTk2Njc0MzkwNDI1Ng.GrFwis.m8d72V5vtyfKo3g2Vs739sIvrTZQ0e42XgWfXU"
SETUP_CHANNEL_ID = 1539321909785657425  # Thay bằng ID kênh nhận báo cáo (Số nguyên, không để ngoặc kép)
MIN_MESSAGES = 1  # Số tin nhắn tối thiểu cần đạt trong 7 ngày

# Cấu hình Intents
intents = discord.Intents.default()
intents.members = True        
intents.message_content = True 

bot = commands.Bot(command_prefix="!", intents=intents)

# ==========================================
# CẤU HÌNH SPOTIFY
# ==========================================
sp = spotipy.Spotify(auth_manager=SpotifyClientCredentials(
    client_id="anonymous",
    client_secret="anonymous"
))

def get_spotify_query(url):
    """Trích xuất tên bài hát + ca sĩ từ link Spotify"""
    try:
        track_match = re.search(r'track/([a-zA-Z0-9]+)', url)
        if track_match:
            track_id = track_match.group(1)
            track_info = sp.track(track_id)
            song_name = track_info['name']
            artist_name = track_info['artists'][0]['name']
            return f"{song_name} {artist_name}"
    except Exception:
        pass
    return None

# ==========================================
# CẤU HÌNH PHÁT NHẠC CHỐNG RÈ / CHỐNG GIẬT LAG
# ==========================================
YTDL_OPTIONS = {
    'format': 'bestaudio/best',
    'extractaudio': True,
    'audioformat': 'mp3',
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'ytsearch',
    'source_address': '0.0.0.0',
}

FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn -filter:a "volume=0.8"'
}

ytdl = yt_dlp.YoutubeDL(YTDL_OPTIONS)

class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get('title')
        self.url = data.get('url')

    @classmethod
    async def from_url(cls, url, *, loop=None, stream=True):
        loop = loop or asyncio.get_event_loop()
        
        # Nếu là link Spotify, tự đổi thành từ khóa tìm kiếm
        if "spotify.com" in url:
            spotify_search = get_spotify_query(url)
            if spotify_search:
                url = spotify_search

        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=not stream))

        if 'entries' in data:
            data = data['entries'][0]

        filename = data['url'] if stream else ytdl.prepare_filename(data)
        return cls(discord.FFmpegPCMAudio(filename, **FFMPEG_OPTIONS), data=data)

# ==========================================
# CHỨC NĂNG THỐNG KÊ TƯƠNG TÁC & AUTO KICK
# ==========================================
async def get_stats_data(guild):
    one_week_ago = datetime.now(timezone.utc) - timedelta(days=7)
    bot_member = guild.get_member(bot.user.id)
    if not bot_member: return []
    bot_top_role = bot_member.top_role

    stats = {m: 0 for m in guild.members if not m.bot and m.top_role < bot_top_role and m.id != guild.owner_id}

    for channel in guild.text_channels:
        perms = channel.permissions_for(bot_member)
        if not perms.read_messages or not perms.read_message_history: continue
        try:
            async for message in channel.history(after=one_week_ago, limit=None):
                if message.author in stats: stats[message.author] += 1
        except Exception: continue

    return sorted(stats.items(), key=lambda item: item[1], reverse=True)

def create_table_embed(guild_name, stats_list):
    embed = discord.Embed(
        title=f"📊 BÁO CÁO TƯƠNG TÁC: {guild_name.upper()}", 
        color=discord.Color.blue(),
        timestamp=datetime.now(timezone.utc)
    )
    total = len(stats_list)
    active = sum(1 for _, count in stats_list if count >= MIN_MESSAGES)
    
    table_text = "```text\n"
    table_text += f"{'STT':<4} | {'TÊN':<12} | {'CHAT'}\n"
    table_text += "-" * 28 + "\n"
    for idx, (member, count) in enumerate(stats_list[:15], start=1):
        name = member.display_name[:12]
        table_text += f"{idx:<4} | {name:<12} | {count:<5}\n"
    if total > 15: table_text += "... và các thành viên khác\n"
    table_text += "```"
    
    embed.add_field(name="📋 Thống kê chi tiết", value=table_text, inline=False)
    embed.add_field(name="Tóm tắt", value=f"✅ Hoạt động: {active}\n❌ Cần Kick: {total - active}", inline=False)
    return embed

@tasks.loop(hours=24)
async def auto_kick_loop():
    # Tự động lọc và kick vào ngày Chủ Nhật hàng tuần
    if datetime.now(timezone.utc).weekday() != 6: return
    for guild in bot.guilds:
        stats_list = await get_stats_data(guild)
        channel = bot.get_channel(SETUP_CHANNEL_ID)
        to_kick = [m for m, count in stats_list if count < MIN_MESSAGES]
        if channel:
            await channel.send(embed=create_table_embed(guild.name, stats_list))
            if to_kick: await channel.send(f"⚠️ **Đang kick {len(to_kick)} thành viên không hoạt động...**")
        for member in to_kick:
            try: await member.kick(reason="Không tương tác trong 7 ngày qua.")
            except Exception: continue

@bot.command()
@commands.has_permissions(kick_members=True)
async def check(ctx):
    """Lệnh kiểm tra tương tác thủ công: !check"""
    if ctx.channel.id != SETUP_CHANNEL_ID: return
    status_msg = await ctx.send("⏳ Đang tổng hợp dữ liệu tin nhắn, vui lòng chờ...")
    stats_list = await get_stats_data(ctx.guild)
    await status_msg.delete()
    await ctx.send(embed=create_table_embed(ctx.guild.name, stats_list))

# ==========================================
# CÁC LỆNH PHÁT NHẠC
# ==========================================
@bot.command()
async def play(ctx, *, search: str):
    """Lệnh phát nhạc: !play <Tên bài / Link Youtube / Link Spotify>"""
    if not ctx.author.voice:
        return await ctx.send("❌ Bạn phải vào một phòng Voice trước!")

    channel = ctx.author.voice.channel
    if ctx.voice_client is None:
        await channel.connect()
    elif ctx.voice_client.channel != channel:
        await ctx.voice_client.move_to(channel)

    async with ctx.typing():
        try:
            player = await YTDLSource.from_url(search, loop=bot.loop, stream=True)
            ctx.voice_client.play(player, after=lambda e: print(f'Lỗi khi phát: {e}') if e else None)
            await ctx.send(f"🎵 **Đang phát:** `{player.title}`")
        except Exception as e:
            await ctx.send("❌ Không thể lấy bài hát. Vui lòng kiểm tra lại link hoặc thử tìm tên bài hát khác!")

@bot.command()
async def stop(ctx):
    """Lệnh dừng nhạc: !stop"""
    if ctx.voice_client:
        await ctx.voice_client.disconnect()
        await ctx.send("⏹️ Đã dừng nhạc và rời khỏi phòng thoại.")
    else:
        await ctx.send("❌ Bot chưa vào phòng thoại nào.")

@bot.event
async def on_ready():
    print(f"Bot đã sẵn sàng và online: {bot.user}")
    if not auto_kick_loop.is_running(): auto_kick_loop.start()

bot.run(TOKEN)
