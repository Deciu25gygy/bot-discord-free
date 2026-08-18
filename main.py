import discord
from discord.ext import commands, tasks
from datetime import datetime, timedelta, timezone

# --- CẤU HÌNH BẮT BUỘC SỬA ---
TOKEN = "MTUzOTI1OTk2Njc0MzkwNDI1Ng.GQQR_8.7kOa1aVaijEjOklRTtPP4Wsqlar0zJFJFgw1tw"
SETUP_CHANNEL_ID = 1503922700408586240  # ID kênh nhận báo cáo & lệnh (Số nguyên, KHÔNG dùng dấu "")
MIN_MESSAGES = 1  # Số tin nhắn tối thiểu trong 7 ngày để không bị kick

intents = discord.Intents.default()
intents.members = True        
intents.message_content = True 

bot = commands.Bot(command_prefix="!", intents=intents)

async def get_stats_data(guild):
    one_week_ago = datetime.now(timezone.utc) - timedelta(days=7)
    bot_member = guild.get_member(bot.user.id)
    if not bot_member:
        return []
    bot_top_role = bot_member.top_role

    # Lọc danh sách: Không tính bot, chỉ tính member có Role thấp hơn Bot và không phải Server Owner
    stats = {m: 0 for m in guild.members if not m.bot and m.top_role < bot_top_role and m.id != guild.owner_id}

    for channel in guild.text_channels:
        # Kiểm tra quyền đọc lịch sử tin nhắn
        perms = channel.permissions_for(bot_member)
        if not perms.read_messages or not perms.read_message_history:
            continue
        try:
            async for message in channel.history(after=one_week_ago, limit=None):
                if message.author in stats:
                    stats[message.author] += 1
        except Exception:
            continue

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
    
    if total > 15:
        table_text += "... và các thành viên khác\n"
    table_text += "```"
    
    embed.add_field(name="📋 Thống kê chi tiết", value=table_text, inline=False)
    embed.add_field(name="Tóm tắt", value=f"✅ Hoạt động: {active}\n❌ Cần Kick: {total - active}", inline=False)
    embed.set_footer(text="Hệ thống quản lý tương tác tự động")
    return embed

# --- TÁC VỤ QUÉT VÀ KICK TỰ ĐỘNG (CHỦ NHẬT HÀNG TUẦN) ---
@tasks.loop(hours=24)
async def auto_kick_loop():
    if datetime.now(timezone.utc).weekday() != 6: 
        return  # Chỉ chạy vào Chủ Nhật

    for guild in bot.guilds:
        stats_list = await get_stats_data(guild)
        channel = bot.get_channel(SETUP_CHANNEL_ID)
        to_kick = [m for m, count in stats_list if count < MIN_MESSAGES]

        if channel:
            await channel.send(embed=create_table_embed(guild.name, stats_list))
            if to_kick:
                await channel.send(f"⚠️ **Đang kick {len(to_kick)} thành viên không hoạt động...**")

        for member in to_kick:
            try:
                await member.kick(reason="Không tương tác trong 7 ngày qua.")
            except Exception:
                continue

# --- LỆNH KIỂM TRA THỦ CÔNG ---
@bot.command()
@commands.has_permissions(kick_members=True)
async def check(ctx):
    if ctx.channel.id != SETUP_CHANNEL_ID:
        return
    status_msg = await ctx.send("⏳ Đang tổng hợp dữ liệu tin nhắn, vui lòng chờ...")
    stats_list = await get_stats_data(ctx.guild)
    await status_msg.delete()
    await ctx.send(embed=create_table_embed(ctx.guild.name, stats_list))

@bot.event
async def on_ready():
    print(f"Bot đã khởi động thành công: {bot.user}")
    if not auto_kick_loop.is_running():
        auto_kick_loop.start()

bot.run(TOKEN)
