"""
曹操民宿 · 自动记账提成系统 Demo
====================================
工作流：
  1. 员工在微信群按格式发消息
  2. 本脚本解析消息 → 存入 SQLite 数据库
  3. 自动计算提成
  4. 生成月度结算报告

使用说明：
  python caocao_demo.py
"""

import sqlite3
import re
from datetime import datetime
from pathlib import Path
import sys

# 输出目录固定为脚本所在目录
SCRIPT_DIR = Path(__file__).parent.resolve()
OUTPUT_DIR = SCRIPT_DIR


def get_sample_messages():
    """模拟一个月的按摩服务记录，包含正常和异常数据"""
    messages = [
        ("2026-06-01 10:30", "阿里", "客人：Ahmed / 项目：全身按摩 / 时长：60分钟 / 金额：300迪拉姆"),
        ("2026-06-01 14:00", "阿里", "客人：Sophie / 项目：精油推背 / 时长：90分钟 / 金额：450迪拉姆"),
        ("2026-06-01 19:30", "阿里", "客人：Marco / 项目：足底按摩 / 时长：30分钟 / 金额：150迪拉姆"),
        ("2026-06-02 11:00", "阿里", "客人：Yuki / 项目：全身按摩 / 时长：60分钟 / 金额：300迪拉姆"),
        ("2026-06-02 16:30", "阿里", "客人：Lena / 项目：精油推背 / 时长：60分钟 / 金额：300迪拉姆"),
        ("2026-06-03 09:00", "哈桑", "客人：James / 项目：足底按摩 / 时长：30分钟 / 金额：150迪拉姆"),
        ("2026-06-03 12:30", "哈桑", "客人：Nina / 项目：全身按摩 / 时长：60分钟 / 金额：300迪拉姆"),
        ("2026-06-03 15:00", "哈桑", "客人：Paul / 项目：精油推背 / 时长：90分钟 / 金额：450迪拉姆"),
        ("2026-06-03 20:00", "哈桑", "客人：Emma / 项目：全身按摩 / 时长：60分钟 / 金额：300迪拉姆"),
        ("2026-06-05 10:00", "阿里", "客人：Carlos / 项目：全身按摩 / 时长：60分钟 / 金额：300迪拉姆"),
        ("2026-06-05 13:30", "阿里", "客人：Mia / 项目：精油推背 / 时长：60分钟 / 金额：300迪拉姆"),
        ("2026-06-05 17:00", "阿里", "客人：Omar / 项目：足底按摩 / 时长：30分钟 / 金额：150迪拉姆"),
        ("2026-06-07 10:00", "哈桑", "客人：David / 项目：全身按摩 / 时长：60分钟 / 金额：300迪拉姆"),
        ("2026-06-07 14:30", "哈桑", "客人：Anna / 项目：精油推背 / 时长：90分钟 / 金额：450迪拉姆"),
        ("2026-06-08 09:00", "阿里", "客人：Tom / 项目：足底按摩 / 时长：30分钟 / 金额：150迪拉姆"),
        ("2026-06-08 11:00", "阿里", "客人：Sara / 项目：全身按摩 / 时长：60分钟 / 金额：300迪拉姆"),
        ("2026-06-08 13:00", "阿里", "客人：Jack / 项目：精油推背 / 时长：60分钟 / 金额：300迪拉姆"),
        ("2026-06-08 15:30", "阿里", "客人：Lily / 项目：全身按摩 / 时长：60分钟 / 金额：300迪拉姆"),
        ("2026-06-08 18:00", "阿里", "客人：Max / 项目：足底按摩 / 时长：30分钟 / 金额：150迪拉姆"),
        ("2026-06-08 20:00", "阿里", "客人：Eva / 项目：精油推背 / 时长：90分钟 / 金额：450迪拉姆"),
        ("2026-06-10 11:00", "哈桑", "客人：Ben / 项目：全身按摩 / 时长：60分钟 / 金额：300迪拉姆"),
        ("2026-06-10 15:00", "哈桑", "客人：Kate / 项目：精油推背 / 时长：60分钟 / 金额：300迪拉姆"),
        ("2026-06-12 10:30", "阿里", "客人：Rayan / 项目：全身按摩 / 时长：60分钟 / 金额：300迪拉姆"),
        ("2026-06-12 14:00", "阿里", "客人：Jade / 项目：足底按摩 / 时长：30分钟 / 金额：150迪拉姆"),
        ("2026-06-15 09:00", "阿里", "客人：Victor / 项目：精油推背 / 时长：90分钟 / 金额：450迪拉姆"),
        ("2026-06-15 13:00", "阿里", "客人：Rosa / 项目：全身按摩 / 时长：60分钟 / 金额：300迪拉姆"),
        ("2026-06-15 16:00", "阿里", "客人：Leo / 项目：足底按摩 / 时长：30分钟 / 金额：150迪拉姆"),
        ("2026-06-15 19:30", "阿里", "客人：Zara / 项目：精油推背 / 时长：60分钟 / 金额：300迪拉姆"),
        ("2026-06-18 10:00", "哈桑", "客人：Noah / 项目：全身按摩 / 时长：60分钟 / 金额：300迪拉姆"),
        ("2026-06-18 14:30", "哈桑", "客人：Iris / 项目：精油推背 / 时长：90分钟 / 金额：450迪拉姆"),
        ("2026-06-18 18:00", "哈桑", "客人：Finn / 项目：全身按摩 / 时长：60分钟 / 金额：300迪拉姆"),
        ("2026-06-20 10:00", "阿里", "客人：Hugo / 项目：全身按摩 / 时长：60分钟 / 金额：300迪拉姆"),
        ("2026-06-20 15:00", "阿里", "客人：Nora / 项目：精油推背 / 时长：60分钟 / 金额：300迪拉姆"),
        # 模拟虚报：全身按摩标准价300，报800
        ("2026-06-22 11:00", "阿里", "客人：VIP / 项目：全身按摩 / 时长：60分钟 / 金额：800迪拉姆"),
        ("2026-06-25 09:30", "哈桑", "客人：Miles / 项目：足底按摩 / 时长：30分钟 / 金额：150迪拉姆"),
        ("2026-06-25 13:00", "哈桑", "客人：Clara / 项目：全身按摩 / 时长：60分钟 / 金额：300迪拉姆"),
        ("2026-06-28 10:00", "阿里", "客人：Oscar / 项目：精油推背 / 时长：90分钟 / 金额：450迪拉姆"),
        ("2026-06-28 14:30", "阿里", "客人：Ella / 项目：全身按摩 / 时长：60分钟 / 金额：300迪拉姆"),
        ("2026-06-28 17:00", "阿里", "客人：Liam / 项目：足底按摩 / 时长：30分钟 / 金额：150迪拉姆"),
        ("2026-06-28 20:00", "阿里", "客人：Grace / 项目：精油推背 / 时长：60分钟 / 金额：300迪拉姆"),
        ("2026-06-30 10:00", "哈桑", "客人：Ryan / 项目：全身按摩 / 时长：60分钟 / 金额：300迪拉姆"),
        ("2026-06-30 15:00", "哈桑", "客人：Amy / 项目：精油推背 / 时长：60分钟 / 金额：300迪拉姆"),
    ]
    return messages


def init_database():
    """初始化 SQLite 数据库"""
    db_path = OUTPUT_DIR / "caocao_data.db"
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS employees (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            commission_rate REAL DEFAULT 0.40
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS service_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            service_date TEXT NOT NULL,
            service_time TEXT NOT NULL,
            employee_name TEXT NOT NULL,
            guest_name TEXT,
            service_type TEXT,
            duration TEXT,
            amount REAL NOT NULL,
            raw_message TEXT
        )
    """)
    cursor.execute("""
        INSERT OR IGNORE INTO employees (name, commission_rate)
        VALUES ('阿里', 0.40), ('哈桑', 0.35)
    """)
    conn.commit()
    return conn


def parse_message(timestamp, sender, text):
    """解析微信群消息"""
    pattern = r"客人[：:]\s*(.+?)\s*/\s*项目[：:]\s*(.+?)\s*/\s*时长[：:]\s*(\d+分钟?)\s*/\s*金额[：:]\s*(\d+)"
    match = re.search(pattern, text)
    if not match:
        return None
    dt = timestamp.split(" ")
    return {
        "service_date": dt[0],
        "service_time": dt[1],
        "employee_name": sender,
        "guest_name": match.group(1).strip(),
        "service_type": match.group(2).strip(),
        "duration": match.group(3).strip(),
        "amount": float(match.group(4).strip()),
        "raw_message": text
    }


def insert_record(conn, record):
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO service_records 
        (service_date, service_time, employee_name, guest_name, 
         service_type, duration, amount, raw_message)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        record["service_date"], record["service_time"],
        record["employee_name"], record["guest_name"],
        record["service_type"], record["duration"],
        record["amount"], record["raw_message"]
    ))
    conn.commit()


def detect_anomalies(conn, month, year=2026):
    """检测异常数据"""
    cursor = conn.cursor()
    anomalies = []
    standard_prices = {"全身按摩": 300, "精油推背": 450, "足底按摩": 150}
    month_str = f"{year}-{month:02d}"
    
    cursor.execute("SELECT service_date, employee_name, service_type, amount FROM service_records WHERE service_date LIKE ?", (f"{month_str}%",))
    for row in cursor.fetchall():
        std = standard_prices.get(row[2], 0)
        if std > 0 and row[3] > std * 1.3:
            anomalies.append({
                "type": "金额异常偏高",
                "detail": f"{row[1]} - {row[0]} - {row[2]} - {row[3]:.0f}迪拉姆 (标准价{std}迪拉姆)",
                "severity": "高" if row[3] > std * 1.5 else "中"
            })
    
    cursor.execute("""
        SELECT service_date, employee_name, COUNT(*) as cnt
        FROM service_records WHERE service_date LIKE ?
        GROUP BY service_date, employee_name HAVING cnt > 5
    """, (f"{month_str}%",))
    for row in cursor.fetchall():
        anomalies.append({
            "type": "单日服务次数过多",
            "detail": f"{row[1]} - {row[0]} - 共{row[2]}次",
            "severity": "中"
        })
    
    return anomalies


def calculate_commissions(conn, month, year=2026):
    """计算提成"""
    cursor = conn.cursor()
    month_str = f"{year}-{month:02d}"
    cursor.execute("SELECT name, commission_rate FROM employees WHERE is_active = 1")
    employees = cursor.fetchall()
    results = []
    
    for name, rate in employees:
        cursor.execute("SELECT COUNT(*), SUM(amount) FROM service_records WHERE employee_name = ? AND service_date LIKE ?", (name, f"{month_str}%"))
        cnt, amt = cursor.fetchone()
        amt = amt or 0
        results.append({
            "employee": name, "rate": rate,
            "total_count": int(cnt), "total_amount": amt,
            "commission": amt * rate
        })
    return results


def generate_report(conn, month, year=2026):
    """生成月度报告"""
    results = calculate_commissions(conn, month, year)
    lines = [f"# 曹操民宿 · {year}年{month}月薪资结算报告", "",
             f"*报告日期：{datetime.now().strftime('%Y年%m月%d日')}*", "",
             "---", ""]
    for r in results:
        lines.append(f"## 员工：{r['employee']}")
        lines.append(f"- 提成比例：{int(r['rate']*100)}%")
        lines.append(f"- 服务次数：{r['total_count']} 次")
        lines.append(f"- 服务总额：{r['total_amount']:.0f} 迪拉姆")
        lines.append(f"- **应得提成：{r['commission']:.0f} 迪拉姆**")
        lines.append("")
    
    total_rev = sum(r["total_amount"] for r in results)
    total_com = sum(r["commission"] for r in results)
    lines.append("---")
    lines.append(f"总营收：{total_rev:.0f} 迪拉姆")
    lines.append(f"总提成：{total_com:.0f} 迪拉姆")
    lines.append(f"公司净收：{total_rev - total_com:.0f} 迪拉姆")
    lines.append("")
    lines.append("*系统自动生成*")
    
    report_path = OUTPUT_DIR / f"结算报告_{year}年{month}月.md"
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return results


def main(save_log=True):
    """主程序"""
    log_lines = []
    
    log_lines.append("=" * 50)
    log_lines.append("曹操民宿 · 自动记账提成系统")
    log_lines.append("=" * 50)
    
    log_lines.append("\n[Step 1] 获取微信群消息...")
    messages = get_sample_messages()
    log_lines.append(f"  -> 共 {len(messages)} 条消息")
    
    log_lines.append("\n[Step 2] 初始化数据库...")
    conn = init_database()
    
    log_lines.append("\n[Step 3] 解析并存入数据库...")
    success = 0
    for ts, sender, text in messages:
        rec = parse_message(ts, sender, text)
        if rec:
            insert_record(conn, rec)
            success += 1
    log_lines.append(f"  -> 成功解析 {success}/{len(messages)} 条")
    
    log_lines.append("\n[Step 4] 自动计算提成...")
    results = calculate_commissions(conn, 6, 2026)
    for r in results:
        log_lines.append(f"  -> {r['employee']}: {r['total_count']}次, {r['total_amount']:.0f}迪拉姆, 提成{r['commission']:.0f}迪拉姆")
    
    total_rev = sum(r["total_amount"] for r in results)
    total_com = sum(r["commission"] for r in results)
    log_lines.append(f"  -> 总收入: {total_rev:.0f}迪拉姆 | 提成支出: {total_com:.0f}迪拉姆 | 净收入: {total_rev - total_com:.0f}迪拉姆")
    
    log_lines.append("\n[Step 5] 异常检测...")
    anomalies = detect_anomalies(conn, 6, 2026)
    if anomalies:
        for a in anomalies:
            log_lines.append(f"  -> 🚨 [{a['severity']}] {a['detail']}")
    else:
        log_lines.append("  -> ✅ 数据正常")
    
    log_lines.append("\n[Step 6] 生成月度报告...")
    generate_report(conn, 6, 2026)
    log_lines.append("  -> 结算报告已生成")
    
    log_lines.append("\n" + "=" * 50)
    log_lines.append("全部完成！")
    log_lines.append("=" * 50)
    
    # 输出到控制台
    text = "\n".join(log_lines)
    print(text)
    
    # 保存日志
    if save_log:
        log_path = OUTPUT_DIR / "运行日志.txt"
        log_path.write_text(text, encoding="utf-8")
        print(f"\n(运行日志已保存至: {log_path})")
    
    conn.close()
    return text


if __name__ == "__main__":
    main()