import os
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, Response
import pymysql
import csv
import io

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "clan_attendance_secret_key_12345")

# ตั้งค่าฐานข้อมูลจาก Environment Variables บน Render
MYSQL_HOST = os.environ.get("MYSQL_HOST", "clan-mysql-db-zaytmop-9e0b.h.aivencloud.com")
MYSQL_USER = os.environ.get("MYSQL_USER", "avnadmin")
MYSQL_PASSWORD = os.environ.get("MYSQL_PASSWORD", "")
MYSQL_DATABASE = os.environ.get("MYSQL_DATABASE", "defaultdb")
MYSQL_PORT = int(os.environ.get("MYSQL_PORT", 11911))

# รหัสผ่านสำหรับเข้าหน้า Dashboard
DASHBOARD_USERNAME = os.environ.get("DASHBOARD_USERNAME", "admin")
DASHBOARD_PASSWORD = os.environ.get("DASHBOARD_PASSWORD", "1234")

def get_db_connection():
    return pymysql.connect(
        host=MYSQL_HOST,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
        database=MYSQL_DATABASE,
        port=MYSQL_PORT,
        autocommit=True
    )

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
    default_month = datetime.now().strftime("%Y-%m")
    selected_month = request.args.get("month", default_month)

    summary_data = []
    raw_logs = []
    months = [default_month]

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # ดึงรายการเดือนที่มีในระบบ
        cursor.execute("SELECT DISTINCT DATE_FORMAT(date, '%%Y-%%m') FROM attendance ORDER BY date DESC")
        fetched_months = [r[0] for r in cursor.fetchall() if r[0]]
        if fetched_months:
            months = fetched_months

        # สรุปผลการเช็คชื่อตามเดือนที่เลือก
        summary_query = f'''
            SELECT a.user_id,
                   COALESCE(m.discord_tag, a.username) as display_name,
                   SUM(CASE WHEN TRIM(a.status) = 'มา' THEN 1 ELSE 0 END) as come_cnt,
                   SUM(CASE WHEN TRIM(a.status) = 'ลา' THEN 1 ELSE 0 END) as leave_cnt,
                   SUM(CASE WHEN TRIM(a.status) = 'ขาด' THEN 1 ELSE 0 END) as absent_cnt
            FROM attendance a
            LEFT JOIN members m ON a.user_id = m.user_id
            WHERE DATE_FORMAT(a.date, '%%Y-%%m') = %s
            GROUP BY a.user_id, display_name
            ORDER BY { 'come_cnt DESC' if sort_by == 'come' else 'absent_cnt DESC' }, display_name ASC
        '''
        cursor.execute(summary_query, (selected_month,))
        summary_data = cursor.fetchall()

        # รายการประวัติทั้งหมดตามเดือนที่เลือก (ไม่มีการกรองวัน)
        logs_query = '''
            SELECT a.id,
                   COALESCE(m.discord_tag, a.username) as display_name,
                   a.status, 
                   a.note, 
                   a.date
            FROM attendance a
            LEFT JOIN members m ON a.user_id = m.user_id
            WHERE DATE_FORMAT(a.date, '%%Y-%%m') = %s
            ORDER BY a.id DESC
        '''
        cursor.execute(logs_query, (selected_month,))
        raw_logs = cursor.fetchall()

        conn.close()
    except Exception as e:
        print(f"Dashboard Error: {e}")

    return render_template(
        "dashboard.html",
        summary=summary_data,
        logs=raw_logs,
        months=months,
        selected_month=selected_month,
        sort_by=sort_by
    )

@app.route("/export_csv")
def export_csv():
    if not session.get("logged_in"):
        return redirect(url_for("login"))
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT a.date, COALESCE(m.discord_tag, a.username), a.status, a.note 
            FROM attendance a 
            LEFT JOIN members m ON a.user_id = m.user_id 
            ORDER BY a.id DESC
        ''')
        rows = cursor.fetchall()
        conn.close()

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["วันที่", "ชื่อสมาชิก", "สถานะ", "หมายเหตุ"])
        for row in rows:
            writer.writerow(row)

        return Response(
            "\ufeff" + output.getvalue(),
            mimetype="text/csv",
            headers={"Content-disposition": "attachment; filename=attendance_export.csv"}
        )
    except Exception as e:
        flash(f"❌ Export CSV Error: {e}")
        return redirect(url_for("dashboard"))

@app.route("/delete_log/<int:log_id>")
def delete_log(log_id):
    if not session.get("logged_in"):
        return redirect(url_for("login"))
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM attendance WHERE id = %s", (log_id,))
        conn.close()
        flash("✅ ลบรายการเรียบร้อยแล้ว")
    except Exception as e:
        print(f"Delete Log Error: {e}")
        flash("❌ เกิดข้อผิดพลาดในการลบรายการ")
    return redirect(url_for("dashboard"))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))