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

# 2. 升级版 Tools (加入并发约束与 POI 转化逻辑)
tools = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "获取城市天气。当用户提到地点和出行计划时调用此工具。🎯【多目的地调度指令】：如果用户的行程包含多个目的地（例如“先去大理，再去丽江”），你必须【多次并行调用】本工具，分别查询每个城市的天气。绝不能将多个城市合并传入！",
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {
                        "type": "string",
                        "description": "【极其重要】必须是标准的中国地级市行政区划名称！每次调用只能包含【一个】城市名。如果用户输入著名景点（如'玉龙雪山'、'泰山'）或简称，必须先转化为该景点所在的【标准地级市名称】（如'丽江'、'泰安'）后再输出。"
                    }
                },
                "required": ["city"]
            }
        }
    }
]

# 3. 铁腕级系统提示词（加入产品边界与免责声明）
def get_dynamic_system_prompt():
    now = datetime.datetime.now()
    date_str = now.strftime("%Y年%m月%d日，%A")
    
    return f"""当前系统真实时间：{date_str}。
你是一个专业的出行天气决策助理。

【核心工作流与铁律】
1. 地点绝对忠实：当用户提供具体城市时，必须完全忠实于该城市！绝对禁止擅自替换为省会！
2. 相对时间推算：对于“明天”、“周末”等相对时间，直接利用系统时间推算。
3. 🎯【并发行程规划】：面对多节点行程（如跨城旅游），你需要通过多次调用工具收集所有城市的天气，并输出有条理的多段行程建议。
4. 🛡️【能力边界与微气候免责】：你获取的天气数据精度仅为【市级大盘数据】。如果用户询问高海拔山区（如玉龙雪山顶）、海岛等特殊微气候场景的精细天气，你必须在回答中加入严重警示：“⚠️ 当前气象为市区宏观预报，山区/海岛微气候复杂多变（常有大风或突发降温），出于安全考虑，能否登顶/坐缆车请务必参考景区官方实时通报。”
5. 【防格式崩溃】：当你需要调用工具时，绝对禁止输出 `<|DSML|>` 等底层控制标签！必须严格使用标准 JSON 结构！

【输出规范】
获取到天气数据后，结合用户的活动，输出以下 Markdown 结构：
☁️ 【气象简报】（如果是多城市，请分城市列出）
🎯 【决策结论】
💡 【出行贴士】（如果涉及微气候盲区，务必在此处进行安全免责提示）
"""

# 4. 核心调度逻辑 (原有代码逻辑保持不变，天然支持并发处理)
def chat_with_agent(messages_history):
    dynamic_system_prompt = get_dynamic_system_prompt()
    
    # 注入系统提示词
    if not messages_history or messages_history[0].get("role") != "system":
        messages_history.insert(0, {"role": "system", "content": dynamic_system_prompt})
    else:
        messages_history[0]["content"] = dynamic_system_prompt

    # 🚀 核心大招：引入 ReAct 循环调度（最大允许它思考/调工具 3 次）
    max_loops = 3
    
    for i in range(max_loops):
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
        
        # 状况 A：大模型乖乖使用了标准 Function Calling
        if response_message.tool_calls:
            messages_history.append(response_message)
            
            for tool_call in response_message.tool_calls:
                if tool_call.function.name == "get_weather":
                    function_args = json.loads(tool_call.function.arguments)
                    city = function_args.get("city", "")
                    
                    weather_result = fetch_weather_for_city(city)
                    
                    # 把查到的天气塞入记忆
                    messages_history.append({
                        "tool_call_id": tool_call.id,
                        "role": "tool",
                        "name": "get_weather",
                        "content": str(weather_result),
                    })
            # 查完天气后，【不要 return】，使用 continue 进入下一轮循环！
            # 让大模型自己判断是继续查下一个城市，还是输出最终答案。
            continue
            
        # 状况 B：大模型没用标准工具，但发生了 DSML 乱码外溢（强行自愈）
        content = response_message.content or ""
        if "DSML" in content:
            match = re.search(r'name="city" string="true">(.*?)</', content)
            if match:
                city = match.group(1)
                weather_result = fetch_weather_for_city(city)
                
                # 强行修复上下文
                messages_history.append({"role": "assistant", "content": f"（系统静默拦截并解析意图：查询{city}天气）"})
                messages_history.append({"role": "user", "content": f"【系统后门传入数据】：{city}的天气数据如下：{weather_result}。如果你还需要查其他城市，请继续；如果查完了，请输出最终决策。"})
                # 继续进入下一轮循环
                continue
            else:
                # 乱码里没提取出城市名，用正则暴力抹除乱码后返回
                return re.sub(r'<\s*\|\s*DSML\s*\|[^>]*>', '', content)
                
        # 状况 C：既没有工具调用，也没有乱码。说明大模型认为资料收集完毕，给出了最终的人类语言！
        return content
        
    # 如果循环了 3 次还没结束，强制掐断，防止大模型死循环烧钱
    return "🧠 抱歉，查询该行程涉及的数据过于复杂，我的处理时间超时了，请尝试拆分您的问题。"
