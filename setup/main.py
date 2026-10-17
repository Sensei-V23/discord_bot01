import os
import sqlite3
import threading
import asyncio
from datetime import datetime, timedelta
import discord
from discord.ext import commands
from flask import Flask, render_template, request, redirect, url_for, session, flash

# --- กำหนด USERNAME และ PASSWORD สำหรับเข้าเว็บที่นี่ ---
DASHBOARD_USERNAME = "admin"
DASHBOARD_PASSWORD = "clan1234"

DB_NAME = "clan_attendance.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            username TEXT NOT NULL,
            status TEXT NOT NULL, -- 'มา', 'ลา', 'ขาด'
            note TEXT,
            date TEXT NOT NULL,       -- YYYY-MM-DD
            date_display TEXT NOT NULL, -- DD/MM/YYYY
            month_year TEXT NOT NULL
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    ''')
    conn.commit()
    conn.close()

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

def parse_time_to_minutes(time_str):
    time_str = time_str.strip()
    if ":" in time_str:
        parts = time_str.split(":")
        if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
            hrs = int(parts[0])
            mins = int(parts[1])
            total = (hrs * 60) + mins
            return total if total > 0 else None
    elif time_str.isdigit():
        val = int(time_str)
        return val if val > 0 else None
    return None

# --- Modal สำหรับสมาชิกกด มา ---
class ComeModal(discord.ui.Modal, title="ลงชื่อเข้าเช็คชื่อ (มา)"):
    def __init__(self, target_date_db, target_date_disp, month_year):
        super().__init__()
        self.target_date_db = target_date_db
        self.target_date_disp = target_date_disp
        self.month_year = month_year

    char_name = discord.ui.TextInput(
        label="ชื่อตัวละคร / ชื่อในเกม",
        placeholder="กรอกชื่อของคุณ...",
        required=True,
        max_length=50
    )

    async def on_submit(self, interaction: discord.Interaction):
        user_id = str(interaction.user.id)
        username = self.char_name.value

        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM attendance WHERE user_id = ? AND date = ?", (user_id, self.target_date_db))
        row = cursor.fetchone()

        if row:
            conn.close()
            await interaction.response.send_message(
                f"❌ คุณได้ลงชื่อของวันที่ **{self.target_date_disp}** ไปแล้วครับ! หากต้องการแก้ไขข้อมูล กรุณาติดต่อหัวหน้าแคลน", 
                ephemeral=True
            )
            return

        cursor.execute("INSERT INTO attendance (user_id, username, status, note, date, date_display, month_year) VALUES (?, ?, 'มา', NULL, ?, ?, ?)",
                       (user_id, username, self.target_date_db, self.target_date_disp, self.month_year))
        
        conn.commit()
        conn.close()
        await interaction.response.send_message(f"✅ บันทึกสถานะ **มา** (วันที่ {self.target_date_disp}) ในนาม **{username}** เรียบร้อยครับ!", ephemeral=True)

# --- Modal สำหรับสมาชิกกด ลา ---
class LeaveModal(discord.ui.Modal, title="แจ้งลาหยุด"):
    def __init__(self, target_date_db, target_date_disp, month_year):
        super().__init__()
        self.target_date_db = target_date_db
        self.target_date_disp = target_date_disp
        self.month_year = month_year

    char_name = discord.ui.TextInput(
        label="ชื่อตัวละคร / ชื่อในเกม",
        placeholder="กรอกชื่อของคุณ...",
        required=True,
        max_length=50
    )
    
    reason = discord.ui.TextInput(
        label="สาเหตุการลา",
        placeholder="ระบุเหตุผลที่ลา...",
        style=discord.TextStyle.paragraph,
        required=True,
        max_length=200
    )

    async def on_submit(self, interaction: discord.Interaction):
        user_id = str(interaction.user.id)
        username = self.char_name.value
        note = self.reason.value

        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM attendance WHERE user_id = ? AND date = ?", (user_id, self.target_date_db))
        row = cursor.fetchone()

        if row:
            conn.close()
            await interaction.response.send_message(
                f"❌ คุณได้ลงชื่อของวันที่ **{self.target_date_disp}** ไปแล้วครับ! หากต้องการแก้ไขข้อมูล กรุณาติดต่อหัวหน้าแคลน", 
                ephemeral=True
            )
            return

        cursor.execute("INSERT INTO attendance (user_id, username, status, note, date, date_display, month_year) VALUES (?, ?, 'ลา', ?, ?, ?, ?)",
                       (user_id, username, note, self.target_date_db, self.target_date_disp, self.month_year))
        
        conn.commit()
        conn.close()
        await interaction.response.send_message(f"📌 บันทึกการ **ลา** (วันที่ {self.target_date_disp}) เรียบร้อยครับ!", ephemeral=True)

# --- Modal สำหรับหัวหน้าเช็คชื่อแทนสมาชิก ---
class AdminProxyModal(discord.ui.Modal, title="🛡️ เช็คชื่อ/แก้สถานะแทนสมาชิก"):
    member_input = discord.ui.TextInput(
        label="แท็กสมาชิก หรือ User ID สมาชิก",
        placeholder="เช่น @Somchai หรือ 123456789012345678",
        required=True,
        max_length=100
    )
    char_name = discord.ui.TextInput(
        label="ชื่อตัวละคร / ชื่อในเกม ของสมาชิก",
        placeholder="กรอกชื่อตัวละคร...",
        required=True,
        max_length=50
    )
    status_input = discord.ui.TextInput(
        label="สถานะ (มา, ลา, ขาด)",
        placeholder="พิมพ์: มา / ลา / ขาด",
        required=True,
        max_length=10
    )
    target_date = discord.ui.TextInput(
        label="วันที่ (วัน/เดือน/ปี)",
        placeholder="เช่น 15/10/2026 (ปล่อยว่างไว้ = วันนี้)",
        required=False,
        max_length=10
    )
    note_input = discord.ui.TextInput(
        label="หมายเหตุ / สาเหตุการลา (ถ้ามี)",
        placeholder="ระบุเหตุผล...",
        required=False,
        max_length=200
    )

    async def on_submit(self, interaction: discord.Interaction):
        mem_str = self.member_input.value.strip()
        c_name = self.char_name.value.strip()
        status = self.status_input.value.strip()
        dt_val = self.target_date.value.strip()
        note = self.note_input.value.strip() or None

        if status not in ["มา", "ลา", "ขาด"]:
            await interaction.response.send_message("❌ สถานะต้องเป็น 'มา', 'ลา' หรือ 'ขาด' เท่านั้นครับ!", ephemeral=True)
            return

        clean_id = mem_str.replace("<@", "").replace(">", "").replace("!", "").strip()
        target_member = None
        if clean_id.isdigit():
            target_member = interaction.guild.get_member(int(clean_id))

        if not target_member:
            await interaction.response.send_message("❌ ไม่พบสมาชิกคนนี้ในเซิร์ฟเวอร์ กรุณาแท็กชื่อ หรือระบุ Discord ID ให้ถูกต้องครับ", ephemeral=True)
            return

        user_id = str(target_member.id)
        target_date_db, target_date_disp, month_year = parse_date_input(dt_val)

        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM attendance WHERE user_id = ? AND date = ?", (user_id, target_date_db))
        row = cursor.fetchone()

        if row:
            cursor.execute("UPDATE attendance SET status = ?, username = ?, note = ? WHERE id = ?", (status, c_name, note, row[0]))
        else:
            cursor.execute("INSERT INTO attendance (user_id, username, status, note, date, date_display, month_year) VALUES (?, ?, ?, ?, ?, ?, ?)",
                           (user_id, c_name, status, note, target_date_db, target_date_disp, month_year))
        
        conn.commit()
        conn.close()

        await interaction.response.send_message(f"✅ บันทึกสถานะ **{status}** แทนสมาชิก {target_member.mention} (ชื่อในเกม: **{c_name}**) วันที่ {target_date_disp} เรียบร้อย!", ephemeral=True)

# --- Modal เปิดเช็คชื่อ ---
class OpenCheckDateModal(discord.ui.Modal, title="เปิดระบบเช็คชื่อประจำวัน"):
    date_input = discord.ui.TextInput(
        label="วันที่เช็คชื่อ (วัน/เดือน/ปี)",
        placeholder="เช่น 15/10/2026 (ปล่อยว่างไว้ = วันนี้)",
        required=False,
        max_length=10
    )

    async def on_submit(self, interaction: discord.Interaction):
        dt_val = self.date_input.value.strip()
        target_date_db, target_date_disp, month_year = parse_date_input(dt_val)

        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM settings WHERE key = 'target_channel_id'")
        row = cursor.fetchone()
        conn.close()

        if not row:
            await interaction.response.send_message("❌ ยังไม่ได้ตั้งค่าห้องเช็คชื่อ! กรุณากดปุ่ม **📌 ตั้งค่าห้องเช็คชื่อ** ก่อนครับ", ephemeral=True)
            return

        target_channel = interaction.guild.get_channel(int(row[0]))
        if not target_channel:
            await interaction.response.send_message("❌ ไม่พบห้องเช็คชื่อที่เคยตั้งค่าไว้ (ห้องอาจถูกลบไปแล้ว)", ephemeral=True)
            return

        embed = discord.Embed(
            title="⚔️ ระบบเช็คชื่อแคลนประจำวัน",
            description=f"📅 สำหรับวันที่: **{target_date_disp}**\n\nกรุณากดปุ่มด้านล่างเพื่อลงชื่อ **มา** หรือ **ลา** ครับ\n*(⚠️ ลงชื่อได้เพียงครั้งเดียว หากต้องการแก้ไขกรุณาติดต่อหัวหน้าแคลน)*",
            color=discord.Color.blue()
        )
        view = AttendanceView(target_date_db, target_date_disp, month_year)
        await target_channel.send(embed=embed, view=view)
        await interaction.response.send_message(f"🟢 เปิดระบบเช็คชื่อ (วันที่ {target_date_disp}) ไปยังห้อง {target_channel.mention} เรียบร้อยแล้ว!", ephemeral=True)

# --- ฟังก์ชันสร้างและส่งข้อความสรุปผลพร้อมแท็กคนไม่เช็ค ---
async def send_attendance_summary(guild, target_date_db, target_date_disp):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, username, status, note FROM attendance WHERE date = ?", (target_date_db,))
    records = cursor.fetchall()

    cursor.execute("SELECT value FROM settings WHERE key = 'summary_channel_id'")
    sum_ch_row = cursor.fetchone()
    cursor.execute("SELECT value FROM settings WHERE key = 'clan_role_id'")
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

    embed = discord.Embed(
        title=f"📊 สรุปผลการเช็คชื่อ ประจำวันที่ {target_date_disp}",
        color=discord.Color.gold()
    )

    come_text = "\n".join([f"• {r[1]}" for r in records if r[2] == 'มา']) or "ไม่มี"
    leave_text = "\n".join([f"• {r[1]} (เหตุผล: {r[3] if r[3] else '-'})" for r in records if r[2] == 'ลา']) or "ไม่มี"
    not_checked_text = " ".join(not_checked_mentions) if not_checked_mentions else "ไม่มี (เช็คครบทุกคนแล้วยอดเยี่ยม!)"

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
        embed.color = discord.Color.dark_gray()
        await msg.edit(embed=embed, view=disabled_view)

        desc = orig_embed.description
        if "สำหรับวันที่:" in desc:
            parts = desc.split("สำหรับวันที่:")
            if len(parts) > 1:
                date_part = parts[1].split("\n")[0].replace("*", "").strip()
                target_date_disp = date_part
                target_date_db, _, _ = parse_date_input(target_date_disp)
    else:
        await msg.edit(view=disabled_view)

    await send_attendance_summary(guild, target_date_db, target_date_disp if target_date_disp else datetime.now().strftime("%d/%m/%Y"))

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
        
        select = discord.ui.Select(
            placeholder="🔒 เลือกรายการเช็คชื่อที่ต้องการปิดรับทันที...",
            options=options
        )
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

class SetTimerModal(discord.ui.Modal, title="⏱️ ตั้งเวลาปิดรับเช็คชื่อ"):
    time_input = discord.ui.TextInput(
        label="ระบุระยะเวลาที่ต้องการปิด (ชั่วโมง:นาที)",
        placeholder="เช่น 01:30 (1 ชม. 30 นาที) หรือ 00:45 หรือ 30...",
        required=True,
        max_length=10
    )

    async def on_submit(self, interaction: discord.Interaction):
        val_str = self.time_input.value.strip()
        total_minutes = parse_time_to_minutes(val_str)

        if not total_minutes:
            await interaction.response.send_message("❌ กรุณากรอกรูปแบบเวลาให้ถูกต้อง เช่น `01:30` หรือ `00:45` หรือ `30` ครับ", ephemeral=True)
            return

        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM settings WHERE key = 'target_channel_id'")
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

        hrs = total_minutes // 60
        mins = total_minutes % 60
        time_desc = f"{hrs} ชั่วโมง {mins} นาที" if hrs > 0 else f"{mins} นาที"

        view = SelectMessageForTimerView(active_msgs, total_minutes, time_desc, target_channel, interaction.guild)
        await interaction.response.send_message(f"⏱️ ตั้งเวลา **{time_desc}** กรุณาเลือกรายการเช็คชื่อที่ต้องการตั้งเวลาปิดด้านล่าง:", view=view, ephemeral=True)

class SelectMessageForTimerView(discord.ui.View):
    def __init__(self, messages, total_minutes, time_desc, target_channel, guild):
        super().__init__(timeout=60)
        self.total_minutes = total_minutes
        self.time_desc = time_desc
        self.target_channel = target_channel
        self.guild = guild
        options = []
        for msg in messages:
            date_info = msg.embeds[0].description.split('\n')[0] if msg.embeds else f"ID: {msg.id}"
            options.append(discord.SelectOption(
                label=f"ตั้งเวลาปิด: {date_info.replace('*', '')}",
                value=str(msg.id),
                description=f"ส่งเมื่อ: {msg.created_at.strftime('%d/%m/%Y %H:%M')}"
            ))
        
        select = discord.ui.Select(
            placeholder="⏱️ เลือกรายการเช็คชื่อที่ต้องการตั้งเวลาปิด...",
            options=options
        )
        select.callback = self.select_callback
        self.add_item(select)

    async def select_callback(self, interaction: discord.Interaction):
        msg_id = int(interaction.data["values"][0])
        await interaction.response.send_message(f"⏳ ตั้งเวลาเรียบร้อย! บอทจะปิดรับและส่งสรุปผลอัตโนมัติในอีก **{self.time_desc}**", ephemeral=True)

        async def timer_task():
            await asyncio.sleep(self.total_minutes * 60)
            try:
                msg = await self.target_channel.fetch_message(msg_id)
                if "[ปิดรับแล้ว]" not in msg.embeds[0].title:
                    await disable_attendance_message(msg, self.guild)
                    date_label = msg.embeds[0].description.split('**')[1] if '**' in msg.embeds[0].description else ""
                    await self.target_channel.send(f"⏰ **หมดเวลา!** ปิดรับและส่งสรุปผลสำหรับรายการวันที่ {date_label} เรียบร้อยแล้ว")
            except Exception:
                pass

        asyncio.create_task(timer_task())

class AttendanceView(discord.ui.View):
    def __init__(self, target_date_db, target_date_disp, month_year):
        super().__init__(timeout=None)
        self.target_date_db = target_date_db
        self.target_date_disp = target_date_disp
        self.month_year = month_year

    @discord.ui.button(label="✅ มา", style=discord.ButtonStyle.green, custom_id="btn_come_public")
    async def come_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ComeModal(self.target_date_db, self.target_date_disp, self.month_year))

    @discord.ui.button(label="📌 ลา", style=discord.ButtonStyle.secondary, custom_id="btn_leave_public")
    async def leave_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(LeaveModal(self.target_date_db, self.target_date_disp, self.month_year))

class ChannelSelectView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)

    @discord.ui.select(
        cls=discord.ui.ChannelSelect,
        placeholder="📌 เลือกห้องสำหรับเปิดส่งปุ่มเช็คชื่อ...",
        channel_types=[discord.ChannelType.text],
        min_values=1,
        max_values=1
    )
    async def select_channel(self, interaction: discord.Interaction, select: discord.ui.ChannelSelect):
        selected_channel = select.values[0]
        channel_id = str(selected_channel.id)

        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('target_channel_id', ?)", (channel_id,))
        conn.commit()
        conn.close()

        await interaction.response.send_message(f"📌 บันทึกตั้งค่าห้อง {selected_channel.mention} เป็นห้องเช็คชื่อหลักเรียบร้อย!", ephemeral=True)

class SummaryChannelSelectView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)

    @discord.ui.select(
        cls=discord.ui.ChannelSelect,
        placeholder="📊 เลือกห้องสำหรับส่งข้อความสรุปผล...",
        channel_types=[discord.ChannelType.text],
        min_values=1,
        max_values=1
    )
    async def select_channel(self, interaction: discord.Interaction, select: discord.ui.ChannelSelect):
        selected_channel = select.values[0]
        channel_id = str(selected_channel.id)

        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('summary_channel_id', ?)", (channel_id,))
        conn.commit()
        conn.close()

        await interaction.response.send_message(f"📊 บันทึกตั้งค่าห้อง {selected_channel.mention} เป็นห้องส่งสรุปผลเรียบร้อย!", ephemeral=True)

class SetRoleModal(discord.ui.Modal, title="🏷️ ตั้งค่ายศแคลน"):
    role_input = discord.ui.TextInput(
        label="แท็กยศ หรือ Role ID ของสมาชิกแคลน",
        placeholder="เช่น @ClanMember หรือ 1234567890...",
        required=True,
        max_length=50
    )

    async def on_submit(self, interaction: discord.Interaction):
        val = self.role_input.value.strip()
        clean_role_id = val.replace("<@&", "").replace(">", "").strip()

        if not clean_role_id.isdigit():
            await interaction.response.send_message("❌ กรุณาแท็กยศ (Role) หรือใส่ Role ID ให้ถูกต้องครับ", ephemeral=True)
            return

        role = interaction.guild.get_role(int(clean_role_id))
        if not role:
            await interaction.response.send_message("❌ ไม่พบยศนี้ในเซิร์ฟเวอร์", ephemeral=True)
            return

        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('clan_role_id', ?)", (clean_role_id,))
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
        await interaction.response.send_message("🛠️ กรุณาเลือกห้องสำหรับ **ส่งปุ่มเช็คชื่อ** จากเมนูด้านล่าง:", view=ChannelSelectView(), ephemeral=True)

    @discord.ui.button(label="📊 ตั้งค่าห้องสรุปผล", style=discord.ButtonStyle.secondary, custom_id="admin_set_summary")
    async def set_summary(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ คุณไม่มีสิทธิ์ใช้ปุ่มนี้", ephemeral=True)
            return
        await interaction.response.send_message("📊 กรุณาเลือกห้องสำหรับ **ส่งข้อความสรุปผล** จากเมนูด้านล่าง:", view=SummaryChannelSelectView(), ephemeral=True)

    @discord.ui.button(label="🏷️ ตั้งค่ายศแคลน", style=discord.ButtonStyle.secondary, custom_id="admin_set_role")
    async def set_role(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ คุณไม่มีสิทธิ์ใช้ปุ่มนี้", ephemeral=True)
            return
        await interaction.response.send_modal(SetRoleModal())

    @discord.ui.button(label="🟢 เปิดเช็คชื่อ", style=discord.ButtonStyle.success, custom_id="admin_open_today")
    async def open_today(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ คุณไม่มีสิทธิ์ใช้ปุ่มนี้", ephemeral=True)
            return
        await interaction.response.send_modal(OpenCheckDateModal())

    @discord.ui.button(label="⏱️ ตั้งเวลาปิดเช็คชื่อ", style=discord.ButtonStyle.primary, custom_id="admin_timer_close")
    async def timer_close(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ คุณไม่มีสิทธิ์ใช้ปุ่มนี้", ephemeral=True)
            return
        await interaction.response.send_modal(SetTimerModal())

    @discord.ui.button(label="🛡️ เช็คชื่อ/แก้สถานะแทนสมาชิก", style=discord.ButtonStyle.primary, custom_id="admin_proxy_check")
    async def proxy_check(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ คุณไม่มีสิทธิ์ใช้ปุ่มนี้", ephemeral=True)
            return
        await interaction.response.send_modal(AdminProxyModal())

    @discord.ui.button(label="🔒 ปิดรับเช็คชื่อ (เลือกรายการ)", style=discord.ButtonStyle.danger, custom_id="admin_close_check")
    async def close_check(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ คุณไม่มีสิทธิ์ใช้ปุ่มนี้", ephemeral=True)
            return

        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM settings WHERE key = 'target_channel_id'")
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
        await interaction.response.send_message("🔒 กรุณาเลือกรายการเช็คชื่อที่ต้องการปิดรับและส่งสรุปผลทันทีจากเมนูด้านล่างครับ:", view=view, ephemeral=True)

@bot.event
async def on_ready():
    print(f"🤖 Bot ออนไลน์แล้วในชื่อ: {bot.user.name}")

@bot.command()
@commands.has_permissions(administrator=True)
async def แผงควบคุม(ctx):
    embed = discord.Embed(
        title="🛠️ แผงควบคุมระบบเช็คชื่อแคลน",
        description=(
            "เลือกปุ่มด้านล่างเพื่อจัดการระบบ:\n\n"
            "• **📌 ตั้งค่าห้องเช็คชื่อ**: เลือกห้องส่งปุ่มเช็คชื่อ\n"
            "• **📊 ตั้งค่าห้องสรุปผล**: เลือกห้องส่งสรุปผล\n"
            "• **🏷️ ตั้งค่ายศแคลน**: ตั้งค่ายศสำหรับแท็กคนไม่เช็ค\n"
            "• **🟢 เปิดเช็คชื่อ**: ส่งปุ่มไปยังห้องที่ตั้งค่าไว้\n"
            "• **⏱️ ตั้งเวลาปิดเช็คชื่อ**: ตั้งเวลานับถอยหลัง ปิดและส่งสรุปผลออโต้\n"
            "• **🛡️ เช็คชื่อ/แก้สถานะแทนสมาชิก**: แก้ไขหรือเช็คชื่อแทนสมาชิก\n"
            "• **🔒 ปิดรับเช็คชื่อ**: ล็อคปุ่มปิดรับทันที พร้อมส่งสรุปรายชื่อ"
        ),
        color=discord.Color.gold()
    )
    await ctx.send(embed=embed, view=AdminControlView())

# --- FLASK WEB SERVER WITH REMEMBER ME & DYNAMIC SORTING ---
app = Flask(__name__)
app.secret_key = os.urandom(24)

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

    selected_month = request.args.get("month", datetime.now().strftime("%Y-%m"))
    sort_by = request.args.get("sort", "come") # กำหนดประเภทการเรียงลำดับ: come, leave, absent

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute("SELECT DISTINCT month_year FROM attendance ORDER BY month_year DESC")
    months = [r[0] for r in cursor.fetchall()]
    if selected_month not in months and months:
        months.insert(0, selected_month)

    # เลือกเงื่อนไข Order By ตามปุ่มที่กดเลือก
    order_column = "come_cnt"
    if sort_by == "leave":
        order_column = "leave_cnt"
    elif sort_by == "absent":
        order_column = "absent_cnt"

    cursor.execute(f'''
        SELECT user_id, username,
               SUM(CASE WHEN status = 'มา' THEN 1 ELSE 0 END) as come_cnt,
               SUM(CASE WHEN status = 'ลา' THEN 1 ELSE 0 END) as leave_cnt,
               SUM(CASE WHEN status = 'ขาด' THEN 1 ELSE 0 END) as absent_cnt
        FROM attendance
        WHERE month_year = ?
        GROUP BY user_id
        ORDER BY {order_column} DESC, username ASC
    ''', (selected_month,))
    summary_data = cursor.fetchall()

    cursor.execute("SELECT id, username, status, note, date, COALESCE(date_display, date) FROM attendance WHERE month_year = ? ORDER BY date DESC, username ASC", (selected_month,))
    raw_logs = cursor.fetchall()
    conn.close()

    return render_template("dashboard.html", summary=summary_data, logs=raw_logs, months=months, current_month=selected_month, current_sort=sort_by)

@app.route("/update_log", methods=["POST"])
def update_log():
    if not session.get("logged_in"):
        return redirect(url_for("login"))

    log_id = request.form.get("log_id")
    new_status = request.form.get("status")
    new_note = request.form.get("note")
    current_month = request.form.get("current_month")

    if log_id and new_status in ["มา", "ลา", "ขาด"]:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("UPDATE attendance SET status = ?, note = ? WHERE id = ?", (new_status, new_note, log_id))
        conn.commit()
        conn.close()

    return redirect(url_for("dashboard", month=current_month))

def run_flask():
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

if __name__ == "__main__":
    t = threading.Thread(target=run_flask)
    t.start()

    token = os.environ.get("DISCORD_BOT_TOKEN")
    if token:
        bot.run(token)
    else:
        print("❌ กรุณาตั้งค่า DISCORD_BOT_TOKEN ก่อนรันโปรแกรม")