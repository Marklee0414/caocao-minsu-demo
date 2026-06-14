"""
曹操民宿 · AI 模糊解析模块
============================
功能：对接大模型 API，代替正则表达式，让员工发错别字、口语化表达时也能精准提取记账要素。

支持的 API 提供商（通过环境变量配置）：
  1. OpenAI 兼容（DeepSeek / 通义千问 / GLM / 本地LLM）
  2. 自动降级到正则表达式（无 API Key 时）

使用方式：
  # 设置 API Key（任选一个）
  set LLM_API_KEY=sk-xxx          （Windows CMD）
  $env:LLM_API_KEY="sk-xxx"       （Windows PowerShell）

  # 测试解析效果
  python ai_parser.py
"""

import os
import json
import re
from datetime import datetime
from typing import Optional

# ============================================================
# 配置
# ============================================================

# 默认 LLM 配置（可通过环境变量覆盖）
LLM_CONFIG = {
    "api_key": os.environ.get("LLM_API_KEY", ""),
    "base_url": os.environ.get("LLM_BASE_URL", "https://api.deepseek.com/v1"),
    "model": os.environ.get("LLM_MODEL", "deepseek-chat"),
    "temperature": 0.1,  # 低温度确保结果稳定
}

# 服务项目标准名称映射（用于后处理规范化）
SERVICE_TYPE_MAP = {
    "全身按摩": ["全身按摩", "全身", "全按", "全身推拿", "推拿", "body massage", "full body"],
    "精油推背": ["精油推背", "精油", "推背", "精油按摩", "芳香", "oil massage", "back massage"],
    "足底按摩": ["足底按摩", "足底", "足疗", "洗脚", "按脚", "foot massage", "足部按摩"],
    "刮痧": ["刮痧", "刮砂"],
    "拔罐": ["拔罐", "拔火罐", "火罐"],
}

# 标准价格（用于异常检测）
STANDARD_PRICES = {"全身按摩": 300, "精油推背": 450, "足底按摩": 150, "刮痧": 200, "拔罐": 250}


# ============================================================
# 第1步：正则解析（传统方式，作为降级方案）
# ============================================================

def parse_by_regex(text: str) -> Optional[dict]:
    """用正则表达式尝试解析消息"""
    patterns = [
        # 标准格式：客人：XXX / 项目：XXX / 时长：XXX / 金额：XXX
        r"客人[：:]\s*(.+?)\s*[///]\s*项目[：:]\s*(.+?)\s*[///]\s*时长[：:]\s*(\d+)\s*分钟?\s*[///]\s*金额[：:]\s*(\d+)",
        # 简化格式：客人XXX / 项目XXX / 时长XXX分 / 金额XXX
        r"客人[：:]?\s*(.+?)\s*[///]\s*项目[：:]?\s*(.+?)\s*[///]\s*时长[：:]?\s*(\d+)\s*分钟?\s*[///]\s*金额[：:]?\s*(\d+)",
        # 纯文本：给XXX做了XXX，60分钟，收了XXX迪拉姆
        r"(?:给|为|帮)\s*(.+?)\s*(?:做了|做了个|做了个|服务了|按摩|安排)\s*(.+?)[，,]\s*(?:约|大概|大约)?\s*(\d+)\s*分钟?[，,]\s*(?:收了|收了|费用|收费|价格|收)\s*(\d+)",
        # 极简：Ahmed 全身按摩 60分钟 300
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
                "raw_message": text,
                "parser": "regex"
            }
    return None


# ============================================================
# 第2步：服务类型规范化
# ============================================================

def normalize_service_type(raw_type: str) -> str:
    """将客户/员工的口语表达映射为标准服务名称"""
    raw_lower = raw_type.lower().strip()
    
    for standard_name, aliases in SERVICE_TYPE_MAP.items():
        for alias in aliases:
            if alias.lower() in raw_lower or raw_lower in alias.lower():
                return standard_name
    
    # 模糊匹配：计算包含度
    best_match = raw_type
    best_score = 0
    for standard_name, aliases in SERVICE_TYPE_MAP.items():
        for alias in aliases:
            # 计算共同字符占比（简单 Jaccard 相似度）
            set_alias = set(alias.lower())
            set_raw = set(raw_lower)
            if len(set_alias | set_raw) == 0:
                continue
            score = len(set_alias & set_raw) / len(set_alias | set_raw)
            if score > best_score and score > 0.3:
                best_score = score
                best_match = standard_name
                break
    
    return best_match


# ============================================================
# 第3步：AI 大模型解析
# ============================================================

def parse_by_llm(text: str) -> Optional[dict]:
    """调用大模型 API 进行模糊语义解析"""
    
    if not LLM_CONFIG["api_key"]:
        print("  ⚠️  未设置 LLM_API_KEY，跳过 AI 解析")
        return None
    
    prompt = f"""你是一个民宿按摩服务的记账解析助手。请从以下微信消息中提取记账要素。

消息原文：
"{text}"

请严格按以下 JSON 格式返回，不要加任何其他文字：
{{
    "guest_name": "客人姓名",
    "service_type": "服务项目（全身按摩/精油推背/足底按摩/刮痧/拔罐/其他）",
    "duration_minutes": "时长（数字，单位分钟）",
    "amount": "金额（数字，单位迪拉姆）",
    "confidence": "置信度（0-1之间的小数）"
}}

注意：
- 如果消息中有明显的错别字，按意图纠正
- 如果信息不全，对应字段填 null
- 如果是口语化表达（如"刚给Ahmed按了个全身，收了他300"），也要正确理解
- duration_minutes 只填数字，不要"分钟"后缀
- amount 只填数字"""
    
    try:
        import urllib.request
        import urllib.error
        
        api_url = f"{LLM_CONFIG['base_url'].rstrip('/')}/chat/completions"
        
        payload = json.dumps({
            "model": LLM_CONFIG["model"],
            "messages": [
                {"role": "system", "content": "你是一个精准的记账信息提取助手。只返回 JSON，不要任何其他文字。"},
                {"role": "user", "content": prompt}
            ],
            "temperature": LLM_CONFIG["temperature"],
            "max_tokens": 300
        }).encode("utf-8")
        
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {LLM_CONFIG['api_key']}"
        }
        
        req = urllib.request.Request(api_url, data=payload, headers=headers, method="POST")
        
        try:
            response = urllib.request.urlopen(req, timeout=30)
            result = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            print(f"  ⚠️  API 请求失败 (HTTP {e.code}): {e.reason}")
            return None
        except urllib.error.URLError as e:
            print(f"  ⚠️  API 连接失败: {e.reason}")
            return None
        
        # 提取返回内容
        content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
        
        # 尝试从返回中提取 JSON
        json_match = re.search(r'\{[\s\S]*?\}', content)
        if not json_match:
            print(f"  ⚠️  LLM 返回格式异常: {content[:100]}...")
            return None
        
        parsed = json.loads(json_match.group())
        
        # 规范化服务类型
        service_type = normalize_service_type(parsed.get("service_type", ""))
        
        return {
            "guest_name": parsed.get("guest_name"),
            "service_type_raw": parsed.get("service_type"),
            "service_type": service_type,
            "duration": f"{parsed.get('duration_minutes', 0)}分钟",
            "duration_minutes": int(parsed.get("duration_minutes", 0)),
            "amount": float(parsed.get("amount", 0)),
            "confidence": float(parsed.get("confidence", 0.5)),
            "raw_message": text,
            "parser": "llm"
        }
        
    except ImportError:
        print("  ⚠️  缺少 urllib 库（不应发生）")
        return None
    except json.JSONDecodeError as e:
        print(f"  ⚠️  JSON 解析失败: {e}")
        return None
    except Exception as e:
        print(f"  ⚠️  未知错误: {e}")
        return None


# ============================================================
# 第4步：统一解析入口（AI优先，正则降级）
# ============================================================

def parse_message_ai(text: str, sender: str = "", timestamp: str = "") -> Optional[dict]:
    """
    统一的模糊解析入口
    
    策略：
    1. 先用正则尝试（快速、零成本、确定性）
    2. 如果正则失败，用 AI 解析
    3. 如果 AI 也失败，返回 None
    4. 对结果进行标准化后处理
    
    Returns:
        dict 包含 service_date, service_time, employee_name, guest_name, 
              service_type, duration, amount, raw_message, parser
        或 None（解析失败）
    """
    dt_parts = timestamp.split(" ") if timestamp else ["未知", "未知"]
    service_date = dt_parts[0] if len(dt_parts) >= 1 else "未知"
    service_time = dt_parts[1] if len(dt_parts) >= 2 else "未知"
    
    # 先试试正则（快）
    regex_result = parse_by_regex(text)
    if regex_result:
        result = {
            "service_date": service_date,
            "service_time": service_time,
            "employee_name": sender,
            "guest_name": regex_result["guest_name"],
            "service_type": normalize_service_type(regex_result["service_type_raw"]),
            "duration": regex_result["duration"],
            "amount": regex_result["amount"],
            "raw_message": text,
            "parser": "regex",
            "confidence": 1.0
        }
        return result
    
    # 正则失败 → 用 AI
    llm_result = parse_by_llm(text)
    if llm_result:
        result = {
            "service_date": service_date,
            "service_time": service_time,
            "employee_name": sender,
            "guest_name": llm_result["guest_name"],
            "service_type": llm_result.get("service_type", llm_result["service_type_raw"]),
            "duration": llm_result["duration"],
            "amount": llm_result["amount"],
            "raw_message": text,
            "parser": "llm",
            "confidence": llm_result["confidence"]
        }
        return result
    
    return None


# ============================================================
# 第5步：测试与演示
# ============================================================

def test_ai_parser():
    """测试 AI 解析器的效果，包含各种边缘案例"""
    
    print("=" * 60)
    print("🧪 AI 模糊解析引擎 - 测试")
    print("=" * 60)
    
    # 准备各种测试消息（包含错别字、口语化表达）
    test_cases = [
        # 标准格式（正则能处理）
        ("阿里", "2026-06-15 10:00", "客人：Ahmed / 项目：全身按摩 / 时长：60分钟 / 金额：300迪拉姆"),
        
        # 错别字版
        ("阿里", "2026-06-15 11:00", "客人：Sara / 项目：全申按摩 / 时长：60分钟 / 金额：300迪拉姆"),
        
        # 口语化版
        ("阿里", "2026-06-15 14:30", "刚给Sophie按了个全身，搞了90分钟，收了她450迪拉姆"),
        
        # 极简格式
        ("哈桑", "2026-06-15 15:00", "客人：Tom 项目 精油推背 60分钟 300迪拉姆"),
        
        # 拼音混入
        ("阿里", "2026-06-15 16:00", "给Lucy做了ge zu di an mo, 30分钟, 150元"),
        
        # 金额带单位但格式不對
        ("哈桑", "2026-06-15 17:00", "客人王先生，精油背部推拿，60分鈡，450块"),
        
        # 混合中英文
        ("阿里", "2026-06-15 19:30", "Guest: Marco, Service: full body massage, 60min, 300DH"),
        
        # 极简版：缺字段
        ("哈桑", "2026-06-15 20:00", "James 足底 30 150"),
        
        # 异常金额（虚报的）
        ("阿里", "2026-06-22 11:00", "客人：VIP / 项目：全身按摩 / 时长：60分钟 / 金额：800迪拉姆"),
    ]
    
    results = {
        "total": len(test_cases),
        "success_regex": 0,
        "success_llm": 0,
        "failed": 0
    }
    
    print(f"\n📋 共 {len(test_cases)} 条测试消息\n")
    
    for i, (sender, ts, text) in enumerate(test_cases, 1):
        print(f"  [{i}] 原始消息: {text[:60]}...")
        
        result = parse_message_ai(text, sender, ts)
        
        if result:
            parser_icon = "🔍" if result["parser"] == "regex" else "🤖"
            print(f"      {parser_icon} [{result['parser']}] 客人={result['guest_name']}, "
                  f"项目={result['service_type']}, "
                  f"时长={result['duration']}, "
                  f"金额={result['amount']:.0f}迪拉姆")
            
            if result["parser"] == "regex":
                results["success_regex"] += 1
            else:
                results["success_llm"] += 1
            
            # 异常检测
            std_price = STANDARD_PRICES.get(result["service_type"], 0)
            if std_price > 0 and result["amount"] > std_price * 1.3:
                print(f"      🚨 异常检测: 金额 {result['amount']:.0f} > 标准价 {std_price}")
        else:
            print(f"      ❌ 解析失败")
            results["failed"] += 1
        
        print()
    
    print("=" * 60)
    print(f"📊 统计: 总计 {results['total']} 条")
    print(f"   ✅ 正则解析: {results['success_regex']} 条")
    print(f"   🤖 AI 解析:  {results['success_llm']} 条")
    print(f"   ❌ 失败:     {results['failed']} 条")
    print(f"   成功率: {((results['success_regex'] + results['success_llm']) / results['total'] * 100):.0f}%")
    print("=" * 60)
    
    if not LLM_CONFIG["api_key"]:
        print("\n💡 提示：未设置 LLM_API_KEY，AI 解析未启用。")
        print("   要体验 AI 模糊解析效果，请设置环境变量：")
        print("   PowerShell: $env:LLM_API_KEY=\"sk-你的key\"")
        print("   CMD:        set LLM_API_KEY=sk-你的key")
        print("   支持 DeepSeek / OpenAI / 通义千问 / GLM 等任何 OpenAI 兼容 API\n")


if __name__ == "__main__":
    test_ai_parser()