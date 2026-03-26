from openai import OpenAI
import json
import datetime
import re
import streamlit as st
from weather_api import fetch_weather_for_city

# 1. 基础配置
API_KEY = st.secrets["DEEPSEEK_API_KEY"]
BASE_URL = "https://api.deepseek.com"
client = OpenAI(api_key=API_KEY, base_url=BASE_URL)

# 2. 🌟 核心升级：将参数改为 Array（数组），支持一键并发多城市
tools = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "获取城市天气。当用户提到地点和出行计划时调用此工具。",
            "parameters": {
                "type": "object",
                "properties": {
                    "cities": {
                        "type": "array",
                        "items": {
                            "type": "string"
                        },
                        "description": "【极其重要】需要查询天气的城市列表，支持同时传入多个城市（例如：['大理', '上海', '丽江']）。必须是标准的中国地级市行政区划名称！如果用户输入著名景点（如'玉龙雪山'、'泰山'）或简称，必须先转化为该景点所在的【标准地级市名称】后再放入列表。"
                    }
                },
                "required": ["cities"]
            }
        }
    }
]

# 3. 铁腕级系统提示词
def get_dynamic_system_prompt():
    now = datetime.datetime.now()
    date_str = now.strftime("%Y年%m月%d日，%A")
    
    return f"""当前系统真实时间：{date_str}。
你是一个专业的出行天气决策助理。

【核心工作流与铁律】
1. 地点绝对忠实：当用户提供具体城市时，必须完全忠实于该城市！绝对禁止擅自替换为省会！
2. 相对时间推算：对于“明天”、“周末”等相对时间，直接利用系统时间推算。
3. 🛡️【能力边界与微气候免责】：你获取的天气数据精度仅为【市级大盘数据】。如果用户询问高海拔山区（如玉龙雪山顶）、海岛等特殊微气候场景的精细天气，你必须在回答中明确警示：“⚠️ 当前气象为市区宏观预报，山区/海岛微气候复杂多变，能否登顶/开展活动请务必参考景区官方实时通报。”
4. 【防格式崩溃】：调用工具时绝对禁止输出 `<|DSML|>` 等底层控制标签！必须严格使用标准的 JSON Array 格式！

【输出规范】
☁️ 【气象简报】（若查询多个城市，请分城市清晰列出天气状况）
🎯 【决策结论】（综合多地气候，给出行程建议）
💡 【出行贴士】（如涉及微气候盲区，务必在此处进行安全免责提示）
"""

# 4. 稳定的线性调度逻辑（内部包含并发处理）
def chat_with_agent(messages_history):
    dynamic_system_prompt = get_dynamic_system_prompt()
    
    if not messages_history or messages_history[0].get("role") != "system":
        messages_history.insert(0, {"role": "system", "content": dynamic_system_prompt})
    else:
        messages_history[0]["content"] = dynamic_system_prompt

    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=messages_history,
            tools=tools,
            tool_choice="auto",
            temperature=0.1
        )
    except Exception as e:
        return f"🚨 API 请求失败: {e}"
    
    response_message = response.choices[0].message
    tool_calls = response_message.tool_calls

    # ==========================================
    # 🛡️ 状况 A：强化版 DSML 泄漏自愈（支持提取多个乱码中的城市）
    # ==========================================
    if not tool_calls and response_message.content and "DSML" in response_message.content:
        # 使用 findall 把乱码里所有的城市全抓出来
        cities = re.findall(r'string="true">(.*?)</', response_message.content)
        if cities:
            all_weather_results = []
            for city in cities:
                weather_result = fetch_weather_for_city(city)
                all_weather_results.append(f"【{city}】天气: {weather_result}")
            
            combined_weather = "\n".join(all_weather_results)
            
            messages_history.append({"role": "assistant", "content": f"（系统静默解析意图：并发查询 {', '.join(cities)} 的天气）"})
            messages_history.append({
                "role": "user", 
                "content": f"【系统后门传入数据】：多地天气数据如下：\n{combined_weather}\n请立刻基于此数据，输出最终的多地出行决策简报！"
            })
            
            try:
                second_response = client.chat.completions.create(
                    model="deepseek-chat",
                    messages=messages_history,
                    temperature=0.1
                )
                return second_response.choices[0].message.content
            except Exception as e:
                return "🚨 获取最终决策时发生网络波动，请重试。"
        else:
            return "🧠 抱歉，我查询多地天气时遇到了一点格式问题，能换个说法问我吗？"

    # ==========================================
    # 🤖 状况 B：正常乖巧的 Function Calling (优雅处理 Array)
    # ==========================================
    if tool_calls:
        messages_history.append(response_message)
        
        for tool_call in tool_calls:
            if tool_call.function.name == "get_weather":
                function_args = json.loads(tool_call.function.arguments)
                # 接收大模型传来的数组，兜底转为列表
                cities = function_args.get("cities", [])
                if isinstance(cities, str):
                    cities = [cities]
                
                # 遍历数组，查完所有城市
                all_weather_results = []
                for city in cities:
                    weather_result = fetch_weather_for_city(city)
                    all_weather_results.append(f"【{city}】天气: {weather_result}")
                
                # 将所有城市的天气打包成一段字符串塞给大模型
                combined_weather = "\n".join(all_weather_results)
                
                messages_history.append({
                    "tool_call_id": tool_call.id,
                    "role": "tool",
                    "name": "get_weather",
                    "content": combined_weather,
                })
        
        second_response = client.chat.completions.create(
            model="deepseek-chat",
            messages=messages_history,
            temperature=0.1
        )
        return second_response.choices[0].message.content
        
    else:
        return response_message.content
