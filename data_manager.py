"""
曹操民宿 · 数据管理层（升级版）
=================================
功能：在原有 SQLite 存储基础上增加订单状态管理

新增功能：
  1. 每条服务记录增加 status 字段（pending/confirmed/anomaly/settled）
  2. 支持批量更新状态
  3. 支持按状态筛选查询
  4. 记录状态变更历史
"""

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict

# ============================================================
# 常量定义
# ============================================================

OUTPUT_DIR = Path(__file__).parent.resolve()

# 订单状态
ORDER_STATUS_PENDING = "pending"      # 待确认（刚录入）
ORDER_STATUS_CONFIRMED = "confirmed"  # 已确认（老板已核实）
ORDER_STATUS_ANOMALY = "anomaly"      # 有异常（系统标记或老板标记）
ORDER_STATUS_SETTLED = "settled"      # 已结算（提成已发放）

ORDER_STATUS_CHOICES = [
    ORDER_STATUS_PENDING,
    ORDER_STATUS_CONFIRMED,
    ORDER_STATUS_ANOMALY,
    ORDER_STATUS_SETTLED,
]

ORDER_STATUS_LABELS = {
    ORDER_STATUS_PENDING: "⏳ 待确认",
    ORDER_STATUS_CONFIRMED: "✅ 已确认",
    ORDER_STATUS_ANOMALY: "🚨 有异常",
    ORDER_STATUS_SETTLED: "💰 已结算",
}


# ============================================================
# 数据库初始化（升级版）
# ============================================================

def init_database_v2(db_path: Optional[Path] = None) -> sqlite3.Connection:
    """初始化升级版数据库"""
    if db_path is None:
        db_path = OUTPUT_DIR / "caocao_data_v2.db"
    
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    cursor = conn.cursor()
    
    # 员工表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS employees (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            commission_rate REAL DEFAULT 0.40,
            phone TEXT,
            start_date TEXT,
            is_active INTEGER DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now', 'localtime'))
        )
    """)
    
    # 升级版服务记录表（含状态）
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
            raw_message TEXT,
            parser TEXT DEFAULT 'regex',
            confidence REAL DEFAULT 1.0,
            status TEXT DEFAULT 'pending',
            anomaly_reason TEXT,
            settled_date TEXT,
            created_at TEXT DEFAULT (datetime('now', 'localtime')),
            updated_at TEXT DEFAULT (datetime('now', 'localtime'))
        )
    """)
    
    # 状态变更历史表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS status_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            record_id INTEGER NOT NULL,
            old_status TEXT,
            new_status TEXT NOT NULL,
            changed_by TEXT DEFAULT 'system',
            change_reason TEXT,
            created_at TEXT DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY (record_id) REFERENCES service_records(id)
        )
    """)
    
    # 提成结算表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS settlements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_name TEXT NOT NULL,
            settlement_date TEXT NOT NULL,
            month INTEGER NOT NULL,
            year INTEGER NOT NULL,
            total_services INTEGER DEFAULT 0,
            total_amount REAL DEFAULT 0,
            commission_rate REAL DEFAULT 0,
            commission_amount REAL DEFAULT 0,
            status TEXT DEFAULT 'pending',
            paid_date TEXT,
            notes TEXT,
            created_at TEXT DEFAULT (datetime('now', 'localtime'))
        )
    """)
    
    # 插入默认员工
    cursor.execute("""
        INSERT OR IGNORE INTO employees (name, commission_rate, start_date)
        VALUES ('阿里', 0.40, '2026-01-01'),
               ('哈桑', 0.35, '2026-03-01')
    """)
    
    conn.commit()
    return conn


# ============================================================
# 核心 CRUD 操作
# ============================================================

def insert_record_v2(conn: sqlite3.Connection, record: dict) -> int:
    """
    插入一条服务记录（自动检测异常并设置状态）
    
    异常检测规则：
    - 金额 > 标准价 * 1.3 → 状态设为 anomaly，记录原因
    - 同一员工同一天超过5单 → 状态设为 anomaly，记录原因
    """
    cursor = conn.cursor()
    
    # 自动异常检测
    anomaly_reason = ""
    standard_prices = {"全身按摩": 300, "精油推背": 450, "足底按摩": 150}
    std_price = standard_prices.get(record.get("service_type", ""), 0)
    
    if std_price > 0 and record["amount"] > std_price * 1.3:
        anomaly_reason = f"金额异常：{record['amount']:.0f}迪拉姆 > 标准价{std_price}迪拉姆"
        if record["amount"] > std_price * 1.5:
            anomaly_reason += "（严重超标）"
    
    # 检测同一天同一员工的服务次数
    if not anomaly_reason:
        cursor.execute("""
            SELECT COUNT(*) FROM service_records
            WHERE employee_name = ? AND service_date = ?
        """, (record["employee_name"], record["service_date"]))
        daily_count = cursor.fetchone()[0]
        if daily_count >= 5:
            anomaly_reason = f"单日服务次数：第{daily_count + 1}单（超过5单阈值）"
    
    status = ORDER_STATUS_ANOMALY if anomaly_reason else ORDER_STATUS_PENDING
    
    cursor.execute("""
        INSERT INTO service_records 
        (service_date, service_time, employee_name, guest_name, 
         service_type, duration, amount, raw_message,
         parser, confidence, status, anomaly_reason)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        record["service_date"], record["service_time"],
        record["employee_name"], record["guest_name"],
        record["service_type"], record["duration"],
        record["amount"], record["raw_message"],
        record.get("parser", "regex"),
        record.get("confidence", 1.0),
        status,
        anomaly_reason if anomaly_reason else None
    ))
    
    conn.commit()
    record_id = cursor.lastrowid
    
    # 记录状态变更历史
    if anomaly_reason:
        log_status_change(conn, record_id, None, status, "system", anomaly_reason)
    
    return record_id


def update_record_status(conn: sqlite3.Connection, record_id: int, 
                         new_status: str, changed_by: str = "user",
                         reason: str = "") -> bool:
    """更新单条记录的状态"""
    if new_status not in ORDER_STATUS_CHOICES:
        return False
    
    cursor = conn.cursor()
    
    # 获取旧状态
    cursor.execute("SELECT status FROM service_records WHERE id = ?", (record_id,))
    row = cursor.fetchone()
    if not row:
        return False
    old_status = row[0]
    
    # 更新状态
    cursor.execute("""
        UPDATE service_records 
        SET status = ?, updated_at = datetime('now', 'localtime')
        WHERE id = ?
    """, (new_status, record_id))
    conn.commit()
    
    # 记录变更历史
    log_status_change(conn, record_id, old_status, new_status, changed_by, reason)
    
    return True


def batch_update_status(conn: sqlite3.Connection, record_ids: List[int],
                        new_status: str, changed_by: str = "user",
                        reason: str = "") -> int:
    """批量更新记录状态，返回更新的条数"""
    count = 0
    for rid in record_ids:
        if update_record_status(conn, rid, new_status, changed_by, reason):
            count += 1
    return count


def log_status_change(conn: sqlite3.Connection, record_id: int,
                      old_status: Optional[str], new_status: str,
                      changed_by: str, reason: str = ""):
    """记录状态变更日志"""
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO status_history (record_id, old_status, new_status, changed_by, change_reason)
        VALUES (?, ?, ?, ?, ?)
    """, (record_id, old_status, new_status, changed_by, reason))
    conn.commit()


# ============================================================
# 查询功能
# ============================================================

def get_records_by_status(conn: sqlite3.Connection, status: str,
                          month: int = 0, year: int = 2026) -> List[Dict]:
    """按状态查询记录"""
    cursor = conn.cursor()
    
    if month > 0:
        month_str = f"{year}-{month:02d}"
        cursor.execute("""
            SELECT * FROM service_records
            WHERE status = ? AND service_date LIKE ?
            ORDER BY service_date DESC, service_time DESC
        """, (status, f"{month_str}%"))
    else:
        cursor.execute("""
            SELECT * FROM service_records
            WHERE status = ?
            ORDER BY service_date DESC, service_time DESC
        """, (status,))
    
    columns = [desc[0] for desc in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def get_anomaly_records(conn: sqlite3.Connection, month: int = 0, 
                        year: int = 2026) -> List[Dict]:
    """获取所有异常记录"""
    return get_records_by_status(conn, ORDER_STATUS_ANOMALY, month, year)


def get_pending_records(conn: sqlite3.Connection, month: int = 0,
                        year: int = 2026) -> List[Dict]:
    """获取所有待确认记录"""
    return get_records_by_status(conn, ORDER_STATUS_PENDING, month, year)


def get_status_summary(conn: sqlite3.Connection, month: int = 0,
                       year: int = 2026) -> Dict:
    """获取状态汇总统计"""
    cursor = conn.cursor()
    
    if month > 0:
        month_str = f"{year}-{month:02d}"
        cursor.execute("""
            SELECT status, COUNT(*) as cnt
            FROM service_records
            WHERE service_date LIKE ?
            GROUP BY status
        """, (f"{month_str}%",))
    else:
        cursor.execute("""
            SELECT status, COUNT(*) as cnt
            FROM service_records
            GROUP BY status
        """)
    
    summary = {s: 0 for s in ORDER_STATUS_CHOICES}
    for row in cursor.fetchall():
        summary[row[0]] = row[1]
    
    return summary


# ============================================================
# 提成结算
# ============================================================

def calculate_commission_v2(conn: sqlite3.Connection, month: int, 
                            year: int = 2026,
                            include_anomaly: bool = True) -> List[Dict]:
    """
    计算月度提成（升级版）
    
    Args:
        include_anomaly: 是否将异常状态的记录也计入提成计算
    
    Returns:
        提成结果列表
    """
    cursor = conn.cursor()
    month_str = f"{year}-{month:02d}"
    
    # 获取所有员工
    cursor.execute("SELECT name, commission_rate FROM employees WHERE is_active = 1")
    employees = cursor.fetchall()
    results = []
    
    for name, rate in employees:
        if include_anomaly:
            cursor.execute("""
                SELECT COUNT(*), SUM(amount)
                FROM service_records
                WHERE employee_name = ? AND service_date LIKE ?
            """, (name, f"{month_str}%"))
        else:
            # 只算 confirmed 和 settled 状态
            cursor.execute("""
                SELECT COUNT(*), SUM(amount)
                FROM service_records
                WHERE employee_name = ? AND service_date LIKE ?
                AND status NOT IN ('anomaly')
            """, (name, f"{month_str}%"))
        
        cnt, amt = cursor.fetchone()
        amt = amt or 0
        
        # 各状态统计
        cursor.execute("""
            SELECT status, COUNT(*) FROM service_records
            WHERE employee_name = ? AND service_date LIKE ?
            GROUP BY status
        """, (name, f"{month_str}%"))
        status_breakdown = {s: 0 for s in ORDER_STATUS_CHOICES}
        for s, c in cursor.fetchall():
            status_breakdown[s] = c
        
        results.append({
            "employee": name,
            "rate": rate,
            "total_count": int(cnt),
            "total_amount": amt,
            "commission": amt * rate,
            "status_breakdown": status_breakdown
        })
    
    return results


# ============================================================
# 测试
# ============================================================

def test_data_manager():
    """测试数据管理模块"""
    print("=" * 60)
    print("🧪 数据管理层 - 测试")
    print("=" * 60)
    
    print("\n[1] 初始化数据库...")
    conn = init_database_v2()
    print("  ✅ 数据库就绪")
    
    print("\n[2] 插入测试记录...")
    from ai_parser import parse_message_ai
    
    test_records = [
        ("2026-06-15 10:00", "阿里", "客人：Ahmed / 项目：全身按摩 / 时长：60分钟 / 金额：300迪拉姆"),
        ("2026-06-15 14:00", "阿里", "客人：Sophie / 项目：精油推背 / 时长：90分钟 / 金额：450迪拉姆"),
        # 异常：金额过高
        ("2026-06-22 11:00", "阿里", "客人：VIP / 项目：全身按摩 / 时长：60分钟 / 金额：800迪拉姆"),
    ]
    
    for ts, sender, text in test_records:
        parsed = parse_message_ai(text, sender, ts)
        if parsed:
            record_id = insert_record_v2(conn, parsed)
            print(f"  -> 插入记录 #{record_id}: {sender} - {parsed['service_type']} - {parsed['amount']:.0f}迪拉姆")
    
    print("\n[3] 查询所有异常记录...")
    anomalies = get_anomaly_records(conn, 6, 2026)
    if anomalies:
        for a in anomalies:
            print(f"  🚨 #{a['id']} {a['employee_name']} - {a['service_type']} - {a['amount']:.0f}迪拉姆")
            print(f"     原因: {a['anomaly_reason']}")
            print(f"     状态: {ORDER_STATUS_LABELS.get(a['status'], a['status'])}")
    
    print("\n[4] 状态汇总...")
    summary = get_status_summary(conn, 6, 2026)
    for status, count in summary.items():
        if count > 0:
            print(f"  {ORDER_STATUS_LABELS.get(status, status)}: {count}条")
    
    print("\n[5] 提成计算...")
    results = calculate_commission_v2(conn, 6, 2026)
    for r in results:
        print(f"  {r['employee']}: {r['total_count']}次, {r['total_amount']:.0f}迪拉姆, 提成{r['commission']:.0f}迪拉姆")
        breakdown = ", ".join([f"{ORDER_STATUS_LABELS.get(s, s)}={c}" for s, c in r['status_breakdown'].items() if c > 0])
        print(f"     状态分布: {breakdown}")
    
    print("\n[6] 手动确认异常记录（模拟老板审核）...")
    if anomalies:
        record_id = anomalies[0]["id"]
        update_record_status(conn, record_id, ORDER_STATUS_CONFIRMED, 
                            changed_by="老板曹操",
                            reason="已核实，VIP客人确实给了小费，金额无误")
        print(f"  -> 记录 #{record_id} 已更新为「已确认」")
        
        # 查看变更历史
        cursor = conn.cursor()
        cursor.execute("""
            SELECT old_status, new_status, changed_by, change_reason, created_at
            FROM status_history WHERE record_id = ?
        """, (record_id,))
        for h in cursor.fetchall():
            print(f"     变更: {h[0]} → {h[1]}, 操作人: {h[2]}, 原因: {h[3]}")
    
    conn.close()
    print("\n✅ 测试完成")


if __name__ == "__main__":
    test_data_manager()