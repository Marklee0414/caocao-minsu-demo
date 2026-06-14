"""
曹操民宿 · Streamlit 前端展示
=================================
功能：在手机/电脑浏览器上查看月度财务报告和异常预警

启动方式：
  pip install streamlit pandas
  streamlit run streamlit_app.py

部署到云端（免费）：
  1. 把 caocao_minsu_demo/ 整个目录推到 GitHub
  2. 打开 https://streamlit.io/cloud
  3. 连接到你的 GitHub 仓库
  4. 选 streamlit_app.py 作为入口文件
  5. 一键部署，得到一个公开网址，手机也能访问
"""

import streamlit as st
import pandas as pd
from datetime import datetime
from pathlib import Path
import sys
import os

# 确保能导入同级模块
sys.path.insert(0, str(Path(__file__).parent.resolve()))

from data_manager import (
    init_database_v2, insert_record_v2,
    get_status_summary, get_anomaly_records,
    calculate_commission_v2, ORDER_STATUS_LABELS,
    ORDER_STATUS_CHOICES
)
from ai_parser import parse_message_ai, parse_message_batch_ai, STANDARD_PRICES

# ============================================================
# 页面配置
# ============================================================

st.set_page_config(
    page_title="曹操民宿 · 记账系统",
    page_icon="🏠",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# 自定义移动端友好的 CSS
st.markdown("""
<style>
    /* 移动端优化 */
    .stApp { max-width: 100%; }
    .block-container { padding: 1rem 1rem; }
    
    /* 数据卡片 */
    .metric-card {
        background: #f8f9fa;
        border-radius: 12px;
        padding: 16px;
        text-align: center;
        border: 1px solid #eee;
    }
    .metric-value {
        font-size: 28px;
        font-weight: 700;
        color: #e94560;
    }
    .metric-label {
        font-size: 13px;
        color: #666;
        margin-top: 4px;
    }
    
    /* 异常卡片 */
    .anomaly-card {
        background: #fff5f5;
        border-left: 4px solid #ff4444;
        border-radius: 8px;
        padding: 12px 16px;
        margin: 8px 0;
    }
    .anomaly-title { font-weight: 600; color: #cc0000; }
    .anomaly-detail { font-size: 13px; color: #666; margin-top: 4px; }
    
    /* 状态标签 */
    .status-tag {
        display: inline-block;
        padding: 2px 10px;
        border-radius: 12px;
        font-size: 12px;
        font-weight: 600;
    }
    .status-anomaly { background: #ffe0e0; color: #cc0000; }
    .status-pending { background: #fff3cd; color: #856404; }
    .status-confirmed { background: #d4edda; color: #155724; }
    .status-settled { background: #cce5ff; color: #004085; }
</style>
""", unsafe_allow_html=True)


# ============================================================
# 数据初始化
# ============================================================

@st.cache_resource
def get_db():
    """获取数据库连接（缓存避免重复初始化）
    
    check_same_thread=False 确保在 Streamlit 多线程环境下不会报错
    """
    import sqlite3
    conn = init_database_v2()
    conn.execute("SELECT 1")  # 验证连接可用
    return conn


def load_demo_data(conn):
    """加载示例数据（如果数据库为空）"""
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM service_records")
    if cursor.fetchone()[0] > 0:
        return  # 已有数据
    
    with st.spinner("正在加载演示数据..."):
        from caocao_demo import get_sample_messages
        messages = get_sample_messages()
        success = 0
        for ts, sender, text in messages:
            parsed = parse_message_ai(text, sender, ts)
            if parsed:
                insert_record_v2(conn, parsed)
                success += 1
        st.success(f"✅ 已加载 {success} 条演示数据")


# ============================================================
# 页面内容
# ============================================================

def main():
    conn = get_db()
    load_demo_data(conn)
    
    current_month = datetime.now().month
    current_year = datetime.now().year
    
    # 侧边栏：月份选择
    with st.sidebar:
        st.markdown("### 📅 筛选条件")
        months = list(range(1, 13))
        month = st.selectbox("月份", months, 
                            index=current_month - 1,
                            format_func=lambda m: f"{current_year}年{m}月")
        
        st.markdown("---")
        st.markdown("### 💡 操作指南")
        st.markdown("""
        1. 员工在微信群发消息
        2. 系统自动解析记账
        3. 异常自动标红报警
        4. 老板每月查看结算
        """)
        
        st.markdown("---")
        st.markdown(f"**运行命令：**")
        st.code("python caocao_demo.py")
        
        if st.button("🔄 刷新数据", type="primary"):
            st.cache_resource.clear()
            st.rerun()
    
    # ============================================================
    # 主面板
    # ============================================================
    
    st.title("🏠 曹操民宿 · 自动记账系统")
    st.caption(f"📊 {current_year}年{month}月 · 手机端自动适配")
    
    # -------- 数据概览卡片 --------
    st.markdown("### 📊 本月概览")
    
    summary = get_status_summary(conn, month, current_year)
    results = calculate_commission_v2(conn, month, current_year)
    
    col1, col2, col3, col4 = st.columns(4)
    
    total_records = sum(summary.values())
    total_revenue = sum(r["total_amount"] for r in results)
    total_commission = sum(r["commission"] for r in results)
    anomaly_count = summary.get("anomaly", 0)
    
    with col1:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-value">{total_records}</div>
            <div class="metric-label">📨 总服务单数</div>
        </div>
        """, unsafe_allow_html=True)
    
    with col2:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-value">{total_revenue:.0f}</div>
            <div class="metric-label">💰 总营收（迪拉姆）</div>
        </div>
        """, unsafe_allow_html=True)
    
    with col3:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-value">{total_commission:.0f}</div>
            <div class="metric-label">💸 总提成支出</div>
        </div>
        """, unsafe_allow_html=True)
    
    with col4:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-value" style="color: {'#ff4444' if anomaly_count > 0 else '#00a854'}">
                {anomaly_count}
            </div>
            <div class="metric-label">🚨 异常记录</div>
        </div>
        """, unsafe_allow_html=True)
    
    # -------- 异常预警 --------
    if anomaly_count > 0:
        st.markdown("### 🚨 异常预警")
        anomalies = get_anomaly_records(conn, month, current_year)
        
        for a in anomalies:
            st.markdown(f"""
            <div class="anomaly-card">
                <div class="anomaly-title">
                    🚨 #{a['id']} {a['employee_name']} - {a['service_type']}
                </div>
                <div style="font-size:16px; font-weight:600; color:#cc0000;">
                    {a['amount']:.0f} 迪拉姆
                </div>
                <div class="anomaly-detail">
                    📅 {a['service_date']} {a['service_time']} ·
                    客人: {a['guest_name']}
                </div>
                <div class="anomaly-detail">
                    🔍 原因: {a.get('anomaly_reason', '系统自动标记')}
                </div>
            </div>
            """, unsafe_allow_html=True)
    
    # -------- 提成结算 --------
    st.markdown("### 💰 提成结算")
    
    for r in results:
        with st.expander(f"👤 {r['employee']}（提成 {int(r['rate']*100)}%）", expanded=True):
            col_a, col_b, col_c = st.columns(3)
            col_a.metric("服务次数", f"{r['total_count']} 次")
            col_b.metric("服务总额", f"{r['total_amount']:.0f} 迪拉姆")
            col_c.metric("应得提成", f"{r['commission']:.0f} 迪拉姆",
                        delta_color="off")
            
            # 状态分布
            breakdown = r['status_breakdown']
            if any(breakdown.values()):
                st.markdown("**状态分布：**")
                for status, count in breakdown.items():
                    if count > 0:
                        label = ORDER_STATUS_LABELS.get(status, status)
                        st.markdown(f"- {label}: {count}单")
    
    # -------- 公司总览 --------
    st.markdown("---")
    st.markdown("### 🏢 公司月度总览")
    
    total_net = total_revenue - total_commission
    commission_ratio = (total_commission / total_revenue * 100) if total_revenue > 0 else 0
    
    col_a, col_b, col_c = st.columns(3)
    col_a.metric("总营收", f"{total_revenue:.0f} 迪拉姆")
    col_b.metric("总提成支出", f"{total_commission:.0f} 迪拉姆")
    col_c.metric("公司净收入", f"{total_net:.0f} 迪拉姆",
                delta=f"提成占比 {commission_ratio:.1f}%")
    
    # -------- AI 解析测试 --------
    st.markdown("---")
    st.markdown("### 🤖 AI 模糊解析测试")
    st.caption("输入一段员工发的微信消息，看看系统能不能正确理解")
    
    test_text = st.text_input(
        "输入消息（支持中文、英文、错别字、口语化表达）",
        value="刚给Tom按了个全身，搞了60分钟，收了他300迪拉姆",
        placeholder="例如：给Lucy做了个足底按摩，30分钟，150块"
    )
    
    if st.button("🧪 测试解析", type="secondary"):
        if test_text:
            result = parse_message_ai(test_text)
            if result:
                st.success("✅ 解析成功！")
                
                col1, col2 = st.columns(2)
                with col1:
                    st.markdown(f"**客人：** {result['guest_name']}")
                    st.markdown(f"**服务项目：** {result['service_type']}")
                with col2:
                    st.markdown(f"**时长：** {result['duration']}")
                    st.markdown(f"**金额：** {result['amount']:.0f} 迪拉姆")
                
                std_price = STANDARD_PRICES.get(result["service_type"], 0)
                if std_price > 0 and result["amount"] > std_price * 1.3:
                    st.warning(f"⚠️ 金额 {result['amount']:.0f} 超过标准价 {std_price}，将被标记为异常")
                else:
                    st.info(f"✅ 金额在正常范围内（标准价 {std_price:.0f} 迪拉姆）")
                
                with st.expander("查看原始解析数据"):
                    st.json(result)
            else:
                st.error("❌ 解析失败，请检查消息格式")
    
    # 底部
    st.markdown("---")
    st.caption("🏠 曹操民宿 · 自动记账提成系统 · Powered by Cline")


if __name__ == "__main__":
    main()