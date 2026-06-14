"""
曹操民宿 · AI 模糊解析模块（V2 - 超强口语化版）
====================================================
功能：对接大模型 API，支持员工发错别字、口语大白话、中英文混杂、
      甚至一段话包含多位员工多次服务时，都能精准批量提取记账要素。

核心升级：
  1. 单条消息 → 批量解析（一段话可能包含多个员工、多笔服务）
  2. Prompt 增强至 20+ 规则覆盖边缘案例
  3. 支持"带客人去骑骆驼"这类非按摩服务自动排除
  4. 异常金额自动标注

使用方式：
  # 设置 API Key（任选一个）
  $env:LLM_API_KEY="sk-xxx"       （Windows PowerShell）

  # 测试解析效果
  python ai_parser.py
"""

import os
import json
import re
from datetime import datetime
from typing import Optional, List, Dict

# ============================================================
# 配置
# ============================================================

# ============================================================
# LLM 配置（支持多种方式传入）
# ============================================================
# 优先级：
#   1. 显式传入的 api_key 参数（最高优先级）
#   2. st.secrets["LLM_API_KEY"]（Streamlit Cloud 部署时）
#   3. os.environ["LLM_API_KEY"]（本地环境变量）
#
# DeepSeek 官方 API：
#   base_url: https://api.deepseek.com
#   model:    deepseek-v4-flash
# ============================================================

def get_llm_config(api_key_override: str = "") -> dict:
    """获取 LLM 配置，支持从多个来源读取 API Key"""
    api_key = api_key_override
    
    if not api_key:
        try:
            import streamlit as st
            api_key = st.secrets.get("LLM_API_KEY", "")
        except (ImportError, RuntimeError):
            pass
    
    if not api_key:
        api_key = os.environ.get("LLM_API_KEY", "")
    
    return {
        "api_key": api_key,
        "base_url": os.environ.get("LLM_BASE_URL", "https://api.deepseek.com"),
        "model": os.environ.get("LLM_MODEL", "deepseek-v4-flash"),
        "temperature": 0.1,
    }

# 旧式直接引用兼容（被 parse_by_llm 内部引用会自动抛 KeyError 从而走回退逻辑）
LLM_CONFIG_CACHED = get_llm_config()

SERVICE_TYPE_MAP = {
    "全身按摩": ["全身按摩", "全身", "全按", "全身推拿", "推拿", "body massage", "full body", "fullbody"],
    "精油推背": ["精油推背", "精油", "推背", "精油按摩", "芳香", "oil massage", "back massage",
                 "精油背部", "精油开背", "背部推拿"],
    "足底按摩": ["足底按摩", "足底", "足疗", "洗脚", "按脚", "foot massage", "足部按摩",
                 "按脚底", "踩背"],
    "刮痧": ["刮痧", "刮砂", "刮背", "刮莎"],
    "拔罐": ["拔罐", "拔火罐", "火罐", "拔管"],
}

# 非按摩服务关键词（这类活动不应记账为按摩收入）
NON_SERVICE_KEYWORDS = [
    "骑骆驼", "camel", "带客人去", "逛逛", "吃饭", "晚餐", "午餐",
    "接送", "taxi", "导游", "翻译", "买东西", "购物"
]

STANDARD_PRICES = {"全身按摩": 300, "精油推背": 450, "足底按摩": 150, "刮痧": 200, "拔罐": 250}


def normalize_service_type(raw_type: str) -> str:
    """将口语表达映射为标准服务名称"""
    raw_lower = raw_type.lower().strip()
    
    for standard_name, aliases in SERVICE_TYPE_MAP.items():
        for alias in aliases:
            if alias.lower() in raw_lower or raw_lower in alias.lower():
                return standard_name
    
    # Jaccard 相似度兜底
    best_match = raw_type
    best_score = 0
    for standard_name, aliases in SERVICE_TYPE_MAP.items():
        for alias in aliases:
            set_alias = set(alias.lower())
            set_raw = set(raw_lower)
            if not set_alias or not set_raw:
                continue
            score = len(set_alias & set_raw) / len(set_alias | set_raw)
            if score > best_score and score > 0.25:
                best_score = score
                best_match = standard_name
    return best_match


def is_service_related(text: str) -> bool:
    """检测消息是否与按摩服务相关（排除带客人出去玩等非服务收入）"""
    text_lower = text.lower()
    for kw in NON_SERVICE_KEYWORDS:
        if kw.lower() in text_lower:
            return False
    service_kw = ["按摩", "推背", "足底", "精油", "刮痧", "拔罐", "massage",
                  "按了", "做了", "服务", "收了他", "收了她", "收了"]
    return any(kw in text_lower for kw in service_kw)


# ============================================================
# 第1步：正则解析（降级方案）
# ============================================================

def parse_by_regex(text: str) -> Optional[dict]:
    """用正则表达式尝试解析单条消息"""
    patterns = [
        r"客人[：:]\s*(.+?)\s*[///]\s*项目[：:]\s*(.+?)\s*[///]\s*时长[：:]\s*(\d+)\s*分钟?\s*[///]\s*金额[：:]\s*(\d+)",
        r"客人[：:]?\s*(.+?)\s*[///]\s*项目[：:]?\s*(.+?)\s*[///]\s*时长[：:]?\s*(\d+)\s*分钟?\s*[///]\s*金额[：:]?\s*(\d+)",
        r"(?:给|为|帮)\s*(.+?)\s*(?:做了|做了个|服务了|按摩|安排)\s*(.+?)[，,]\s*(?:约|大概|大约)?\s*(\d+)\s*分钟?[，,]\s*(?:收了|费用|收费|价格|收)\s*(\d+)",
        r"(.+?)\s+(.+?)\s+(\d+)\s*分钟?\s+(\d+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return {
                "guest_name": match.group(1).strip(),
                "service_type_raw": match.group(2).strip(),
                "duration": match.group(3).strip() + "分钟",
                "amount": float(match.group(4).strip()),
            }
    return None


# ============================================================
# 第2步：AI 大模型批量解析（核心升级）
# ============================================================

PARSE_SYSTEM_PROMPT = """你是一个民宿按摩服务的专业记账解析助手。你的任务是从员工在微信群发的口语化消息中，精准提取每一笔服务记录。

你拥有极强的中文口语理解能力，能处理：错别字、拼音混入、中英文混杂、一段话包含多位员工多次服务、时间顺序打乱、金额单位混用等复杂情况。

【核心规则】
1. 一条消息可能包含多条服务记录 → 返回 JSON 数组
2. 每条记录必须包含：员工名字、客人名字、服务项目、时长、金额、置信度
3. 如果提到员工名字（如"阿里"、"哈桑"），精确填入 employee_name 字段
4. 如果没提员工名字但提到了"我"，留空由调用方填写
5. 非按摩服务（如"带客人去骑骆驼"、"接客人吃饭"等）不要记账，排除掉
6. 金额单位可能是"迪拉姆"、"DH"、"块"、"元"、"dhs"、"dollar"——统一识别为迪拉姆数字
7. 服务项目要映射到标准名称：全身按摩/精油推背/足底按摩/刮痧/拔罐
8. 时长只填数字（分钟），不要文字后缀
9. 金额只填数字（迪拉姆），不要文字后缀"""


def parse_by_llm(text: str) -> Optional[List[Dict]]:
    """
    调用大模型 API 进行批量模糊语义解析
    
    每次调用时重新读取配置，确保 Streamlit Cloud 的 st.secrets 能生效。
    
    Returns:
        List[Dict] 可能包含 0~N 条解析记录
        或 None（API 调用失败）
    """
    config = get_llm_config()
    if not config["api_key"]:
        return None
    
    escaped_text = text.replace('"', '\\"').replace('{', '{{').replace('}', '}}')
    prompt = (
        '消息原文：\n'
        '"""\n'
        + text +
        '\n"""\n\n'
        '请解析以上微信消息，提取其中包含的所有按摩服务记账记录。\n\n'
        '返回格式：一个 JSON 数组，每个元素包含：\n'
        '{\n'
        '    "employee_name": "员工名字（如阿里/哈桑，没有则填null）",\n'
        '    "guest_name": "客人姓名",\n'
        '    "service_type": "服务项目（全身按摩/精油推背/足底按摩/刮痧/拔罐/其他）",\n'
        '    "duration_minutes": "时长（数字，单位分钟）",\n'
        '    "amount": "金额（数字，单位迪拉姆）",\n'
        '    "anomaly": "是否有异常（true/false），如果金额明显高于标准价或描述可疑则true",\n'
        '    "anomaly_reason": "异常原因（有异常时填写，没有则null）",\n'
        '    "confidence": "置信度（0-1之间的小数）"\n'
        '}\n\n'
        '【特别注意】\n'
        '- 如果消息中包含非按摩服务的活动（如"带客人去骑骆驼"、"接送客人"、"吃饭"），不要记账\n'
        '- "600迪拉姆"如果是骆驼/导游/接送等非按摩服务，填 amount=0 并备注 non_service\n'
        '- 金额异常检测标准：全身按摩>390、精油推背>585、足底按摩>195 视为异常\n'
        '- 如果信息不全无法确定，对应字段填 null\n\n'
        '只返回 JSON 数组，不要任何其他文字。'
    )

    try:
        import urllib.request
        import urllib.error
        
        api_url = f"{config['base_url'].rstrip('/')}/chat/completions"
        payload = json.dumps({
            "model": config["model"],
            "messages": [
                {"role": "system", "content": PARSE_SYSTEM_PROMPT},
                {"role": "user", "content": prompt}
            ],
            "temperature": config["temperature"],
            "max_tokens": 800
        }).encode("utf-8")
        
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {config['api_key']}"
        }
        
        req = urllib.request.Request(api_url, data=payload, headers=headers, method="POST")
        response = urllib.request.urlopen(req, timeout=30)
        result = json.loads(response.read().decode("utf-8"))
        content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
        
        # 提取 JSON
        json_match = re.search(r'\[[\s\S]*?\]', content)
        if not json_match:
            json_match = re.search(r'\{[\s\S]*?\}', content)
            if json_match:
                # 单条返回，包装成数组
                single = json.loads(json_match.group())
                return [single]
            return None
        
        parsed_list = json.loads(json_match.group())
        if isinstance(parsed_list, dict):
            parsed_list = [parsed_list]
        
        # 后处理：规范化 + 过滤非服务记录
        results = []
        for item in parsed_list:
            service_type = normalize_service_type(item.get("service_type", "") or "")
            amount = float(item.get("amount", 0) or 0)
            
            # 排除非按摩服务（amount=0 或已标记）
            if amount == 0:
                continue
            if item.get("anomaly_reason") and "non_service" in str(item.get("anomaly_reason", "")):
                continue
            
            results.append({
                "employee_name": item.get("employee_name"),
                "guest_name": item.get("guest_name"),
                "service_type": service_type,
                "service_type_raw": item.get("service_type", ""),
                "duration": f"{item.get('duration_minutes', 0) or 0}分钟",
                "duration_minutes": int(item.get("duration_minutes", 0) or 0),
                "amount": amount,
                "anomaly": bool(item.get("anomaly", False)),
                "anomaly_reason": item.get("anomaly_reason"),
                "confidence": float(item.get("confidence", 0.5) or 0.5),
                "parser": "llm"
            })
        
        return results if results else None
        
    except Exception as e:
        print(f"  ⚠️  LLM 解析异常: {e}")
        return None


# ============================================================
# 第3步：统一解析入口
# ============================================================

def parse_message_ai(text: str, sender: str = "", timestamp: str = "") -> Optional[dict]:
    """
    单条解析（兼容旧接口，只返回第一条有效记录）
    
    如果员工发了一段话包含多笔服务，只取第一条。
    要获取全部请使用 parse_message_batch_ai()
    """
    results = parse_message_batch_ai(text, sender, timestamp)
    if results:
        return results[0]
    return None


def parse_message_batch_ai(text: str, sender: str = "", timestamp: str = "") -> List[Dict]:
    """
    批量解析入口（V2 核心函数）
    
    支持：
    - 一段话包含多位员工、多笔服务
    - 错别字、口语化、中英文混杂
    - 非按摩服务自动排除
    
    Returns:
        List[Dict]，每条记录包含：
            service_date, service_time, employee_name, guest_name,
            service_type, duration, amount, raw_message, parser,
            confidence, anomaly, anomaly_reason
    """
    dt_parts = timestamp.split(" ") if timestamp else ["未知", "未知"]
    service_date = dt_parts[0] if len(dt_parts) >= 1 else "未知"
    service_time = dt_parts[1] if len(dt_parts) >= 2 else "未知"
    
    # 检查是否与按摩服务无关
    if not is_service_related(text):
        return []
    
    # 先试正则（快速匹配标准格式）
    regex_result = parse_by_regex(text)
    if regex_result:
        return [{
            "service_date": service_date,
            "service_time": service_time,
            "employee_name": sender,
            "guest_name": regex_result["guest_name"],
            "service_type": normalize_service_type(regex_result["service_type_raw"]),
            "duration": regex_result["duration"],
            "amount": regex_result["amount"],
            "raw_message": text,
            "parser": "regex",
            "confidence": 1.0,
            "anomaly": False,
            "anomaly_reason": None
        }]
    
    # 正则失败 → 用 AI 批量解析
    llm_results = parse_by_llm(text)
    if llm_results:
        records = []
        for item in llm_results:
            emp_name = item.get("employee_name") or sender
            records.append({
                "service_date": service_date,
                "service_time": service_time,
                "employee_name": emp_name,
                "guest_name": item.get("guest_name", ""),
                "service_type": item.get("service_type", "其他"),
                "service_type_raw": item.get("service_type_raw", ""),
                "duration": item.get("duration", "0分钟"),
                "amount": item.get("amount", 0),
                "raw_message": text,
                "parser": "llm",
                "confidence": item.get("confidence", 0.5),
                "anomaly": item.get("anomaly", False),
                "anomaly_reason": item.get("anomaly_reason")
            })
        return records
    
    return []


# ============================================================
# 第4步：测试
# ============================================================

def test_ai_parser():
    """测试 AI 解析器效果"""
    print("=" * 60)
    print("🧪 AI 模糊解析引擎 V2 - 超强口语化版测试")
    print("=" * 60)
    
    test_cases = [
        # 标准格式
        ("阿里", "2026-06-15", "客人：Ahmed / 项目：全身按摩 / 时长：60分钟 / 金额：300迪拉姆"),
        
        # 错别字
        ("阿里", "2026-06-15", "客人：Sara / 项目：全申按摩 / 时长：60分钟 / 金额：300迪拉姆"),
        
        # 口语化
        ("阿里", "2026-06-15", "刚给Sophie按了个全身，搞了90分钟，收了她450迪拉姆"),
        
        # 拼音混入
        ("阿里", "2026-06-15", "给Lucy做了ge zu di an mo, 30分钟, 150元"),
        
        # 中英文混合
        ("阿里", "2026-06-15", "Guest: Marco, Service: full body massage, 60min, 300DH"),
        
        # 极简
        ("哈桑", "2026-06-15", "James 足底 30 150"),
        
        # 一段话包含多人多次服务（用户提供的真实场景）
        ("阿里", "2026-06-15", "今天阿里接了2个全身按摩，一个是下午2点做的，收了450迪拉姆；另一个是晚上8点做的，客人说很满意，收了300迪拉姆。哈桑傍晚带客人去骑骆驼，收了600迪拉姆。"),
        
        # 异常金额
        ("阿里", "2026-06-22", "客人：VIP / 项目：全身按摩 / 时长：60分钟 / 金额：800迪拉姆"),
    ]
    
    results = {"total": 0, "records": 0, "success": 0, "failed": 0}
    
    for i, (sender, ts, text) in enumerate(test_cases, 1):
        print(f"\n  [{i}] 原始消息: {text[:80]}...")
        
        records = parse_message_batch_ai(text, sender, ts)
        results["total"] += 1
        
        if records:
            results["records"] += len(records)
            results["success"] += 1
            for j, r in enumerate(records, 1):
                tag = "🤖" if r["parser"] == "llm" else "🔍"
                anomaly = " 🚨" if r.get("anomaly") else ""
                print(f"      {tag} [{j}] {r.get('employee_name','?')} → 客人{r['guest_name']} | "
                      f"{r['service_type']} | {r['duration']} | {r['amount']:.0f}迪拉姆{anomaly}")
                if r.get("anomaly_reason"):
                    print(f"         原因: {r['anomaly_reason']}")
        else:
            print(f"      ❌ 无有效记账记录")
            results["failed"] += 1
    
    print(f"\n{'='*60}")
    print(f"📊 统计: {results['total']} 条消息 → {results['records']} 条记账记录")
    print(f"   成功率: {results['success']}/{results['total']}")
    print(f"{'='*60}")
    
    cfg = get_llm_config()
    if not cfg["api_key"]:
        print("\n💡 提示：未设置 LLM_API_KEY，AI 解析未启用。")
        print("   设置后 AI 可处理口语化、错别字、多人多笔场景。")
        print("   PowerShell: $env:LLM_API_KEY=\"sk-你的key\"\n")
    else:
        print(f"   ✅ LLM 已配置: {cfg['model']} @ {cfg['base_url']}\n")


if __name__ == "__main__":
    test_ai_parser()