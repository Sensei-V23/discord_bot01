import os
import threading
import asyncio
from datetime import datetime, timedelta
import discord
from discord.ext import commands
from flask import Flask, render_template, request, redirect, url_for, session, flash, Response
import pymysql

DASHBOARD_USERNAME = os.environ.get("DASHBOARD_USERNAME", "admin")
DASHBOARD_PASSWORD = os.environ.get("DASHBOARD_PASSWORD", "clan1234")

MYSQL_HOST = os.environ.get("MYSQL_HOST", "localhost")
MYSQL_USER = os.environ.get("MYSQL_USER", "root")
MYSQL_PASSWORD = os.environ.get("MYSQL_PASSWORD", "")
MYSQL_DATABASE = os.environ.get("MYSQL_DATABASE", "defaultdb")
MYSQL_PORT = int(os.environ.get("MYSQL_PORT", 3306))

def get_db_connection():
    return pymysql.connect(
        host=MYSQL_HOST,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
        database=MYSQL_DATABASE,
        port=MYSQL_PORT,
        charset='utf8mb4',
        cursorclass=pymysql.cursors.Cursor
    )

def init_db():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS attendance (
                id INT AUTO_INCREMENT PRIMARY KEY,
                user_id VARCHAR(50) NOT NULL,
                username VARCHAR(100) NOT NULL,
                status VARCHAR(20) NOT NULL,
                note TEXT,
                date VARCHAR(20) NOT NULL,
                date_display VARCHAR(20) NOT NULL,
                month_year VARCHAR(20) NOT NULL
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        ''')
        cursor.execute("SHOW COLUMNS FROM attendance LIKE 'date_display'")
        if not cursor.fetchone():
            cursor.execute("ALTER TABLE attendance ADD COLUMN date_display VARCHAR(20) NOT NULL DEFAULT ''")
        cursor.execute("SHOW COLUMNS FROM attendance LIKE 'month_year'")
        if not cursor.fetchone():
            cursor.execute("ALTER TABLE attendance ADD COLUMN month_year VARCHAR(20) NOT NULL DEFAULT ''")

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS settings (
                `key` VARCHAR(50) PRIMARY KEY,
                `value` TEXT NOT NULL
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS members (
                user_id VARCHAR(50) PRIMARY KEY,
                discord_tag VARCHAR(100) NOT NULL
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        ''')
        conn.commit()
        conn.close()
        print("✅ เชื่อมต่อและอัปเดตโครงสร้างตาราง MySQL สำเร็จ!")
    except Exception as e:
        print(f"❌ เชื่อมต่อ MySQL ไม่สำเร็จ: {e}")

init_db()

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

def parse_date_input(date_str):
    if not date_str:
        now = datetime.now()
        return now.strftime("%Y-%m-%d"), now.strftime("%d/%m/%Y"), now.strftime("%Y-%m")
    
    date_str = date_str.strip()
    try:
        if "/" in date_str:
            parts = date_str.split("/")
            d, m, y = int(parts[0]), int(parts[1]), int(parts[2])
            dt = datetime(y, m, d)
            return dt.strftime("%Y-%m-%d"), dt.strftime("%d/%m/%Y"), dt.strftime("%Y-%m")
        elif "-" in date_str:
            parts = date_str.split("-")
            if len(parts[0]) == 4:
                dt = datetime.strptime(date_str, "%Y-%m-%d")
            else:
                dt = datetime.strptime(date_str, "%d-%m-%Y")
            return dt.strftime("%Y-%m-%d"), dt.strftime("%d/%m/%Y"), dt.strftime("%Y-%m")
    except Exception:
        pass
    
    now = datetime.now()
    return now.strftime("%Y-%m-%d"), now.strftime("%d/%m/%Y"), now.strftime("%Y-%m")

class LeaveModal(discord.ui.Modal):
    def __init__(self, target_date_db, target_date_disp, month_year):
        super().__init__(title="แจ้งลาหยุดประจำวัน")
        self.target_date_db = target_date_db
        self.target_date_disp = target_date_disp
        self.month_year = month_year

    reason = discord.ui.TextInput(
        label="สาเหตุการลา",
        placeholder="ระบุเหตุผลที่ลา...",
        style=discord.TextStyle.paragraph,
        required=True,
        max_length=200
    )

    async def on_submit(self, interaction: discord.Interaction):
        user_id = str(interaction.user.id)
        username = interaction.user.display_name
        note = self.reason.value

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM attendance WHERE user_id = %s AND date = %s", (user_id, self.target_date_db))
        row = cursor.fetchone()

        if row:
            conn.close()
            await interaction.response.send_message(f"❌ คุณได้ลงชื่อของวันที่ **{self.target_date_disp}** ไปแล้วครับ!", ephemeral=True)
            return

        cursor.execute("INSERT INTO attendance (user_id, username, status, note, date, date_display, month_year) VALUES (%s, %s, 'ลา', %s, %s, %s, %s)",
                       (user_id, username, note, self.target_date_db, self.target_date_disp, self.month_year))
        conn.commit()
        conn.close()
        await interaction.response.send_message(f"📌 บันทึกการ **ลา** (วันที่ {self.target_date_disp}) เรียบร้อยครับ!", ephemeral=True)

class DirectAttendanceView(discord.ui.View):
    def __init__(self, target_date_db, target_date_disp, month_year):
        super().__init__(timeout=None)
        self.target_date_db = target_date_db
        self.target_date_disp = target_date_disp
        self.month_year = month_year

    @discord.ui.button(label="✅ มา", style=discord.ButtonStyle.green, custom_id="btn_come_direct")
    async def come_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_id = str(interaction.user.id)
        username = interaction.user.display_name

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM attendance WHERE user_id = %s AND date = %s", (user_id, self.target_date_db))
        row = cursor.fetchone()

        if row:
            conn.close()
            await interaction.response.send_message(f"❌ คุณได้ลงชื่อของวันที่ **{self.target_date_disp}** ไปแล้วครับ!", ephemeral=True)
            return

        cursor.execute("INSERT INTO attendance (user_id, username, status, note, date, date_display, month_year) VALUES (%s, %s, 'มา', NULL, %s, %s, %s)",
                       (user_id, username, self.target_date_db, self.target_date_disp, self.month_year))
        conn.commit()
        conn.close()
        await interaction.response.send_message(f"✅ บันทึกสถานะ **มา** (วันที่ {self.target_date_disp}) ให้คุณ **{username}** เรียบร้อยครับ!", ephemeral=True)

    @discord.ui.button(label="📌 ลา", style=discord.ButtonStyle.secondary, custom_id="btn_leave_direct")
    async def leave_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_id = str(interaction.user.id)
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM attendance WHERE user_id = %s AND date = %s", (user_id, self.target_date_db))
        row = cursor.fetchone()

        if row:
            conn.close()
            await interaction.response.send_message(f"❌ คุณได้ลงชื่อของวันที่ **{self.target_date_disp}** ไปแล้วครับ!", ephemeral=True)
            return

        conn.close()
        await interaction.response.send_modal(LeaveModal(self.target_date_db, self.target_date_disp, self.month_year))

async def send_attendance_summary(guild, target_date_db, target_date_disp):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, username, status, note FROM attendance WHERE date = %s", (target_date_db,))
    records = cursor.fetchall()
    cursor.execute("SELECT `value` FROM settings WHERE `key` = 'summary_channel_id'")
    sum_ch_row = cursor.fetchone()
    cursor.execute("SELECT `value` FROM settings WHERE `key` = 'clan_role_id'")
    role_row = cursor.fetchone()
    conn.close()

    checked_user_ids = {r[0] for r in records}
    not_checked_mentions = []
    if role_row and role_row[0].isdigit():
        role = guild.get_role(int(role_row[0]))
        if role:
            for member in role.members:
                if str(member.id) not in checked_user_ids and not member.bot:
                    not_checked_mentions.append(member.mention)

    embed = discord.Embed(title=f"📊 สรุปผลการเช็คชื่อ ประจำวันที่ {target_date_disp}", color=discord.Color.gold())
    come_text = "\n".join([f"• {r[1]}" for r in records if r[2] == 'มา']) or "ไม่มี"
    leave_text = "\n".join([f"• {r[1]} (เหตุผล: {r[3] if r[3] else '-'})" for r in records if r[2] == 'ลา']) or "ไม่มี"
    not_checked_text = " ".join(not_checked_mentions) if not_checked_mentions else "ไม่มี (เช็คครบทุกคนแล้ว!)"

    embed.add_field(name="✅ มาเช็คชื่อ", value=come_text, inline=False)
    embed.add_field(name="📌 ลาหยุด", value=leave_text, inline=False)
    embed.add_field(name="⚠️ ยังไม่เช็คชื่อ (ยังไม่ส่งผล)", value=not_checked_text, inline=False)

    target_channel = guild.text_channels[0]
    if sum_ch_row and sum_ch_row[0].isdigit():
        ch = guild.get_channel(int(sum_ch_row[0]))
        if ch:
            target_channel = ch
    await target_channel.send(embed=embed)

async def disable_attendance_message(msg, guild):
    disabled_view = discord.ui.View()
    disabled_view.add_item(discord.ui.Button(label="✅ มา", style=discord.ButtonStyle.green, disabled=True))
    disabled_view.add_item(discord.ui.Button(label="📌 ลา", style=discord.ButtonStyle.secondary, disabled=True))
    
    orig_embed = msg.embeds[0] if msg.embeds else None
    target_date_disp = ""
    target_date_db = datetime.now().strftime("%Y-%m-%d")

    if orig_embed:
        embed = orig_embed.copy()
        embed.title = "🔒 [ปิดรับแล้ว] ระบบเช็คชื่อแคลนประจำวัน"
        embed.description = (orig_embed.description or "") + "\n\n*(🗑️ ข้อความนี้จะถูกลบอัตโนมัติในอีก 30 นาที)*"
        embed.color = discord.Color.dark_gray()
        await msg.edit(embed=embed, view=disabled_view)
        desc = orig_embed.description
        if "สำหรับวันที่ปัจจุบัน:" in desc:
            parts = desc.split("สำหรับวันที่ปัจจุบัน:")
            if len(parts) > 1:
                date_part = parts[1].split("\n")[0].replace("*", "").strip()
                target_date_disp = date_part
                target_date_db, _, _ = parse_date_input(target_date_disp)
    else:
        await msg.edit(view=disabled_view)

    await send_attendance_summary(guild, target_date_db, target_date_disp if target_date_disp else datetime.now().strftime("%d/%m/%Y"))

    async def delete_after_30_mins():
        await asyncio.sleep(1800)
        try:
            await msg.delete()
        except Exception:
            pass
    asyncio.create_task(delete_after_30_mins())

class SelectMessageToCloseView(discord.ui.View):
    def __init__(self, messages, target_channel, guild):
        super().__init__(timeout=60)
        self.target_channel = target_channel
        self.guild = guild
        options = []
        for msg in messages:
            date_info = msg.embeds[0].description.split('\n')[0] if msg.embeds else f"ID: {msg.id}"
            options.append(discord.SelectOption(
                label=f"ปิดรายการ: {date_info.replace('*', '')}",
                value=str(msg.id),
                description=f"ส่งเมื่อ: {msg.created_at.strftime('%d/%m/%Y %H:%M')}"
            ))
        select = discord.ui.Select(placeholder="🔒 เลือกรายการเช็คชื่อที่ต้องการปิดรับทันที...", options=options)
        select.callback = self.select_callback
        self.add_item(select)

    async def select_callback(self, interaction: discord.Interaction):
        msg_id = int(interaction.data["values"][0])
        try:
            msg = await self.target_channel.fetch_message(msg_id)
            await disable_attendance_message(msg, self.guild)
            await interaction.response.send_message("🔒 ปิดรับเช็คชื่อและส่งสรุปผลเรียบร้อยแล้ว!", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ เกิดข้อผิดพลาดไม่พบข้อความ: {e}", ephemeral=True)

class ChannelSelectView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)

    @discord.ui.select(cls=discord.ui.ChannelSelect, placeholder="📌 เลือกห้องสำหรับเปิดส่งปุ่มเช็คชื่อ...", channel_types=[discord.ChannelType.text], min_values=1, max_values=1)
    async def select_channel(self, interaction: discord.Interaction, select: discord.ui.ChannelSelect):
        selected_channel = select.values[0]
        channel_id = str(selected_channel.id)
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO settings (`key`, `value`) VALUES ('target_channel_id', %s) ON DUPLICATE KEY UPDATE `value` = %s", (channel_id, channel_id))
        conn.commit()
        conn.close()
        await interaction.response.send_message(f"📌 บันทึกตั้งค่าห้อง {selected_channel.mention} เรียบร้อย!", ephemeral=True)

class SummaryChannelSelectView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)

    @discord.ui.select(cls=discord.ui.ChannelSelect, placeholder="📊 เลือกห้องสำหรับส่งข้อความสรุปผล...", channel_types=[discord.ChannelType.text], min_values=1, max_values=1)
    async def select_channel(self, interaction: discord.Interaction, select: discord.ui.ChannelSelect):
        selected_channel = select.values[0]
        channel_id = str(selected_channel.id)
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO settings (`key`, `value`) VALUES ('summary_channel_id', %s) ON DUPLICATE KEY UPDATE `value` = %s", (channel_id, channel_id))
        conn.commit()
        conn.close()
        await interaction.response.send_message(f"📊 บันทึกตั้งค่าห้อง {selected_channel.mention} เรียบร้อย!", ephemeral=True)

class SetRoleSelectView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)

    @discord.ui.select(cls=discord.ui.RoleSelect, placeholder="🏷️ เลือกยศแคลนจากรายการ...", min_values=1, max_values=1)
    async def select_role(self, interaction: discord.Interaction, select: discord.ui.RoleSelect):
        selected_role = select.values[0]
        role_id = str(selected_role.id)
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO settings (`key`, `value`) VALUES ('clan_role_id', %s) ON DUPLICATE KEY UPDATE `value` = %s", (role_id, role_id))
        conn.commit()
        conn.close()
        await interaction.response.send_message(f"🏷️ บันทึกตั้งค่ายศแคลนเป็น **{selected_role.name}** (ID: {role_id}) เรียบร้อย!", ephemeral=True)

    @discord.ui.button(label="✏️ หรือพิมพ์ระบุ Role ID เอง", style=discord.ButtonStyle.secondary)
    async def manual_role_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(SetRoleModal())

class SetRoleModal(discord.ui.Modal, title="🏷️ ตั้งค่ายศแคลน (กรอก ID)"):
    role_input = discord.ui.TextInput(label="แท็กยศ หรือ Role ID ของสมาชิกแคลน", placeholder="เช่น @ClanMember หรือ 1234567890...", required=True, max_length=50)

    async def on_submit(self, interaction: discord.Interaction):
        val = self.role_input.value.strip()
        clean_role_id = val.replace("<@&", "").replace(">", "").strip()
        if not clean_role_id.isdigit():
            await interaction.response.send_message("❌ กรุณาแท็กยศ หรือใส่ Role ID ให้ถูกต้อง", ephemeral=True)
            return
        role = interaction.guild.get_role(int(clean_role_id))
        if not role:
            await interaction.response.send_message("❌ ไม่พบยศนี้ในเซิร์ฟเวอร์", ephemeral=True)
            return
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO settings (`key`, `value`) VALUES ('clan_role_id', %s) ON DUPLICATE KEY UPDATE `value` = %s", (clean_role_id, clean_role_id))
        conn.commit()
        conn.close()
        await interaction.response.send_message(f"🏷️ ตั้งค่ายศแคลนเป็น **{role.name}** เรียบร้อย!", ephemeral=True)

class AdminControlView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="📌 ตั้งค่าห้องเช็คชื่อ", style=discord.ButtonStyle.secondary, custom_id="admin_set_channel")
    async def set_channel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ คุณไม่มีสิทธิ์ใช้ปุ่มนี้", ephemeral=True)
            return
        await interaction.response.send_message("🛠️ กรุณาเลือกห้องสำหรับ **ส่งปุ่มเช็คชื่อ**:", view=ChannelSelectView(), ephemeral=True)

    @discord.ui.button(label="📊 ตั้งค่าห้องสรุปผล", style=discord.ButtonStyle.secondary, custom_id="admin_set_summary")
    async def set_summary(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ คุณไม่มีสิทธิ์ใช้ปุ่มนี้", ephemeral=True)
            return
        await interaction.response.send_message("📊 กรุณาเลือกห้องสำหรับ **ส่งข้อความสรุปผล**:", view=SummaryChannelSelectView(), ephemeral=True)

    @discord.ui.button(label="🏷️ ตั้งค่ายศแคลน", style=discord.ButtonStyle.secondary, custom_id="admin_set_role")
    async def set_role(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ คุณไม่มีสิทธิ์ใช้ปุ่มนี้", ephemeral=True)
            return
        await interaction.response.send_message("🏷️ กรุณาเลือกยศแคลน หรือกดปุ่มพิมพ์ ID ยศ:", view=SetRoleSelectView(), ephemeral=True)

    @discord.ui.button(label="🟢 เปิดเช็คชื่อทันที", style=discord.ButtonStyle.success, custom_id="admin_open_today")
    async def open_today(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ คุณไม่มีสิทธิ์ใช้ปุ่มนี้", ephemeral=True)
            return
        target_date_db, target_date_disp, month_year = parse_date_input("")
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT `value` FROM settings WHERE `key` = 'target_channel_id'")
        row = cursor.fetchone()
        conn.close()

        if not row:
            await interaction.response.send_message("❌ ยังไม่ได้ตั้งค่าห้องเช็คชื่อ!", ephemeral=True)
            return
        target_channel = interaction.guild.get_channel(int(row[0]))
        if not target_channel:
            await interaction.response.send_message("❌ ไม่พบห้องเช็คชื่อที่เคยตั้งค่าไว้", ephemeral=True)
            return

        embed = discord.Embed(
            title="⚔️ ระบบเช็คชื่อแคลนประจำวัน",
            description=f"📅 สำหรับวันที่ปัจจุบัน: **{target_date_disp}**\n\nกดปุ่ม **✅ มา** หรือ **📌 ลา** ด้านล่างเพื่อลงชื่อได้ทันทีครับ!",
            color=discord.Color.blue()
        )
        view = DirectAttendanceView(target_date_db, target_date_disp, month_year)
        await target_channel.send(embed=embed, view=view)
        await interaction.response.send_message(f"🟢 เปิดระบบเช็คชื่อ (วันที่ปัจจุบัน {target_date_disp}) เรียบร้อย!", ephemeral=True)

    @discord.ui.button(label="🔒 ปิดรับเช็คชื่อ (เลือกรายการ)", style=discord.ButtonStyle.danger, custom_id="admin_close_check")
    async def close_check(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ คุณไม่มีสิทธิ์ใช้ปุ่มนี้", ephemeral=True)
            return
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT `value` FROM settings WHERE `key` = 'target_channel_id'")
        row = cursor.fetchone()
        conn.close()
        target_channel = interaction.channel
        if row:
            ch = interaction.guild.get_channel(int(row[0]))
            if ch:
                target_channel = ch
        active_msgs = []
        async for msg in target_channel.history(limit=30):
            if msg.author == bot.user and msg.embeds and "ระบบเช็คชื่อแคลน" in msg.embeds[0].title and "[ปิดรับแล้ว]" not in msg.embeds[0].title:
                active_msgs.append(msg)
        if not active_msgs:
            await interaction.response.send_message(f"❌ ไม่พบรายการเช็คชื่อที่เปิดอยู่ในห้อง {target_channel.mention}", ephemeral=True)
            return
        view = SelectMessageToCloseView(active_msgs, target_channel, interaction.guild)
        await interaction.response.send_message("🔒 เลือกรายการเช็คชื่อที่ต้องการปิดรับและส่งสรุปผลทันที:", view=view, ephemeral=True)

@bot.event
async def on_ready():
    print(f"🤖 Bot ออนไลน์แล้วในชื่อ: {bot.user.name}")

@bot.command()
@commands.has_permissions(administrator=True)
async def แผงควบคุม(ctx):
    embed = discord.Embed(
        title="🛠️ แผงควบคุมระบบเช็คชื่อแคลน (MySQL)",
        description=(
            "เลือกปุ่มด้านล่างเพื่อจัดการระบบ:\n\n"
            "• **📌 ตั้งค่าห้องเช็คชื่อ**: เลือกห้องส่งปุ่มเช็คชื่อ\n"
            "• **📊 ตั้งค่าห้องสรุปผล**: เลือกห้องส่งสรุปผล\n"
            "• **🏷️ ตั้งค่ายศแคลน**: เลือกยศ หรือใส่ Role ID\n"
            "• **🟢 เปิดเช็คชื่อทันที**: เปิดระบบเช็คชื่อด้วยตัวเองทันที\n"
            "• **🔒 ปิดรับเช็คชื่อ**: เลือกปิดรับและสรุปผลทันที"
        ),
        color=discord.Color.gold()
    )
    await ctx.send(embed=embed, view=AdminControlView())

# --- FLASK WEB SERVER ---
app = Flask(__name__)
app.secret_key = os.urandom(24)

@app.route("/ping")
def ping():
    return "OK", 200

@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("logged_in"):
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        remember = request.form.get("remember")
        if username == DASHBOARD_USERNAME and password == DASHBOARD_PASSWORD:
            session["logged_in"] = True
            if remember:
                session.permanent = True
                app.permanent_session_lifetime = timedelta(days=30)
            else:
                session.permanent = False
            return redirect(url_for("dashboard"))
        else:
            flash("❌ ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/")
def dashboard():
    if not session.get("logged_in"):
        return redirect(url_for("login"))

    sort_by = request.args.get("sort", "come")
    today_db, today_disp, default_month = parse_date_input("")
    selected_month = request.args.get("month", default_month)

    summary_data = []
    raw_logs = []
    months = [default_month]

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT DISTINCT month_year FROM attendance ORDER BY month_year DESC")
        db_months = [r[0] for r in cursor.fetchall() if r[0]]
        if db_months:
            months = db_months
        if selected_month not in months:
            months.insert(0, selected_month)

        order_column = "come_cnt"
        if sort_by == "leave":
            order_column = "leave_cnt"
        elif sort_by == "absent":
            order_column = "absent_cnt"

        # ดึงสรุปผลแบบรวมทั้งหมด (ไม่กรองเดือน เพื่อให้แสดงผลข้อมูลที่มีอยู่ชัวร์ๆ 100%)
        cursor.execute(f'''
            SELECT user_id, username,
                   SUM(CASE WHEN status = 'มา' THEN 1 ELSE 0 END) as come_cnt,
                   SUM(CASE WHEN status = 'ลา' THEN 1 ELSE 0 END) as leave_cnt,
                   SUM(CASE WHEN status = 'ขาด' THEN 1 ELSE 0 END) as absent_cnt
            FROM attendance
            GROUP BY user_id, username
            ORDER BY {order_column} DESC, username ASC
        ''')
        summary_data = cursor.fetchall()

        # ดึงประวัติรายการทั้งหมดมาแสดง
        cursor.execute("SELECT id, username, status, note, date, date_display FROM attendance ORDER BY id DESC")
        raw_logs = cursor.fetchall()
        conn.close()
    except Exception as e:
        print(f"Dashboard Error: {e}")

    return render_template("dashboard.html", summary=summary_data, logs=raw_logs, months=months, current_month=selected_month, current_sort=sort_by, today_disp=today_disp)

@app.route("/delete_log/<int:log_id>", methods=["POST"])
def delete_log(log_id):
    if not session.get("logged_in"):
        return redirect(url_for("login"))
    current_month = request.form.get("current_month", datetime.now().strftime("%Y-%m"))
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM attendance WHERE id = %s", (log_id,))
        conn.commit()
        conn.close()
        flash("🗑️ ลบรายการเช็คชื่อสำเร็จ!")
    except Exception as e:
        flash(f"❌ เกิดข้อผิดพลาดในการลบรายการ: {e}")
    return redirect(url_for("dashboard", month=current_month))

@app.route("/review_absent", methods=["GET"])
def review_absent():
    if not session.get("logged_in"):
        return redirect(url_for("login"))
    today_db, today_disp, month_year = parse_date_input("")
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, discord_tag FROM members ORDER BY discord_tag ASC")
    all_members = cursor.fetchall()
    cursor.execute("SELECT user_id FROM attendance WHERE date = %s", (today_db,))
    checked_ids = {r[0] for r in cursor.fetchall()}
    not_checked_list = []
    for uid, dtag in all_members:
        if uid not in checked_ids:
            not_checked_list.append({"user_id": uid, "discord_tag": dtag})
    conn.close()
    return render_template("review_absent.html", not_checked=not_checked_list, today_disp=today_disp)

@app.route("/mark_absent_action", methods=["POST"])
def mark_absent_action():
    if not session.get("logged_in"):
        return redirect(url_for("login"))
    action_type = request.form.get("action_type")
    user_id = request.form.get("user_id")
    today_db, today_disp, month_year = parse_date_input("")
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        if action_type == "single" and user_id:
            cursor.execute("SELECT discord_tag FROM members WHERE user_id = %s", (user_id,))
            m_row = cursor.fetchone()
            if m_row:
                dtag = m_row[0]
                cursor.execute("SELECT id FROM attendance WHERE user_id = %s AND date = %s", (user_id, today_db))
                if not cursor.fetchone():
                    cursor.execute(
                        "INSERT INTO attendance (user_id, username, status, note, date, date_display, month_year) VALUES (%s, %s, 'ขาด', 'ไม่มาเช็คชื่อ', %s, %s, %s)",
                        (user_id, dtag, today_db, today_disp, month_year)
                    )
                    conn.commit()
                    flash(f"✅ บันทึกสถานะ 'ขาด' ให้คุณ {dtag} เรียบร้อย!")
        elif action_type == "all":
            cursor.execute("SELECT user_id, discord_tag FROM members")
            all_members = cursor.fetchall()
            cursor.execute("SELECT user_id FROM attendance WHERE date = %s", (today_db,))
            checked_ids = {r[0] for r in cursor.fetchall()}
            added_count = 0
            for uid, dtag in all_members:
                if uid not in checked_ids:
                    cursor.execute(
                        "INSERT INTO attendance (user_id, username, status, note, date, date_display, month_year) VALUES (%s, %s, 'ขาด', 'ไม่มาเช็คชื่อ', %s, %s, %s)",
                        (uid, dtag, today_db, today_disp, month_year)
                    )
                    added_count += 1
            conn.commit()
            if added_count > 0:
                flash(f"✅ บันทึกสถานะ 'ขาด' ให้สมาชิกที่ยังไม่ได้เช็คชื่อวันนี้ทั้งหมด {added_count} คน เรียบร้อย!")
            else:
                flash("ℹ️ สมาชิกทุกคนเช็คชื่อครบแล้ว!")
        conn.close()
    except Exception as e:
        flash(f"❌ เกิดข้อผิดพลาด: {e}")
    return redirect(url_for("review_absent"))

@app.route("/members", methods=["GET", "POST"])
def members_management():
    if not session.get("logged_in"):
        return redirect(url_for("login"))
    conn = get_db_connection()
    cursor = conn.cursor()
    if request.method == "POST":
        action = request.form.get("action")
        user_id = request.form.get("user_id", "").strip()
        discord_tag = request.form.get("discord_tag", "").strip()
        try:
            if action == "save" and user_id and discord_tag:
                cursor.execute('''
                    INSERT INTO members (user_id, discord_tag) VALUES (%s, %s)
                    ON DUPLICATE KEY UPDATE discord_tag=%s
                ''', (user_id, discord_tag, discord_tag))
                conn.commit()
                flash("✅ บันทึกรายชื่อสมาชิกเรียบร้อยแล้ว!")
            elif action == "delete" and user_id:
                cursor.execute("DELETE FROM members WHERE user_id = %s", (user_id,))
                conn.commit()
                flash("🗑️ ลบรายชื่อสมาชิกเรียบร้อยแล้ว!")
        except Exception as e:
            conn.rollback()
            flash(f"❌ เกิดข้อผิดพลาด: {e}")
    cursor.execute("SELECT user_id, discord_tag FROM members ORDER BY discord_tag ASC")
    members_list = cursor.fetchall()
    conn.close()
    return render_template("members.html", members=members_list)

@app.route("/update_log", methods=["POST"])
def update_log():
    if not session.get("logged_in"):
        return redirect(url_for("login"))
    log_id = request.form.get("log_id")
    new_status = request.form.get("status")
    new_note = request.form.get("note")
    new_date_str = request.form.get("date_display")
    current_month = request.form.get("current_month")

    if log_id and new_status in ["มา", "ลา", "ขาด"]:
        date_db, date_disp, month_yr = parse_date_input(new_date_str)
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE attendance SET status = %s, note = %s, date = %s, date_display = %s, month_year = %s WHERE id = %s", 
                       (new_status, new_note, date_db, date_disp, month_yr, log_id))
        conn.commit()
        conn.close()
        flash("✅ แก้ไขบันทึกเรียบร้อยแล้ว!")
    return redirect(url_for("dashboard", month=current_month))

@app.route("/clear_all", methods=["POST"])
def clear_all():
    if not session.get("logged_in"):
        return redirect(url_for("login"))
    current_month = request.form.get("current_month", datetime.now().strftime("%Y-%m"))
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM attendance")
        conn.commit()
        conn.close()
        flash("🗑️ ล้างประวัติการเช็คชื่อทั้งหมดเรียบร้อยแล้ว!")
    except Exception as e:
        flash(f"❌ เกิดข้อผิดพลาดในการลบข้อมูล: {e}")
    return redirect(url_for("dashboard", month=current_month))

@app.route("/export_csv")
def export_csv():
    if not session.get("logged_in"):
        return redirect(url_for("login"))
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT username,
               SUM(CASE WHEN status = 'มา' THEN 1 ELSE 0 END) as come_cnt,
               SUM(CASE WHEN status = 'ลา' THEN 1 ELSE 0 END) as leave_cnt,
               SUM(CASE WHEN status = 'ขาด' THEN 1 ELSE 0 END) as absent_cnt
        FROM attendance
        GROUP BY user_id, username
        ORDER BY come_cnt DESC, username ASC
    ''')
    rows = cursor.fetchall()
    conn.close()

    def generate():
        data = [["ชื่อสมาชิก Discord", "มา", "ลา", "ขาด"]]
        for r in rows:
            data.append([r[0], r[1], r[2], r[3]])
        for row in data:
            yield ','.join([str(val) for val in row]) + '\n'

    Response_obj = Response(generate(), mimetype="text/csv")
    Response_obj.headers["Content-Disposition"] = f"attachment; filename=attendance_summary.csv"
    return Response_obj

def run_flask():
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

if __name__ == "__main__":
    t = threading.Thread(target=run_flask)
    t.daemon = True
    t.start()

    token = os.environ.get("DISCORD_BOT_TOKEN")
    if token:
        try:
            bot.run(token)
        except Exception as e:
            print(f"❌ Discord Bot Error: {e}")
    else:
        print("❌ กรุณาตั้งค่า DISCORD_BOT_TOKEN ก่อนรันโปรแกรม")
        import time
        while True:
            time.sleep(1)