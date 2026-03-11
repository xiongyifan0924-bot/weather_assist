import streamlit as st
from llm_agent import chat_with_agent

# 页面基础配置
st.set_page_config(page_title="AI 场景化出行助理", page_icon="🧭", layout="centered")
st.title("🧭 AI 场景化出行决策助理")
st.markdown("架构验证：`LLM 意图识别` + `Function Calling` + `Open-Meteo API`")

# 初始化 Session 记忆体系
if "messages" not in st.session_state:
    st.session_state.messages = []
    # 模拟良好的开场白体验
    st.session_state.messages.append({
        "role": "assistant", 
        "content": "您好！我是您开发的 AI 出行决策助理。您可以问我类似**“这周末去广州看小蛮腰天气怎么样？”**的问题，我将为您调取气象基座数据并提供决策指引。"
    })

# 渲染历史气泡
for msg in st.session_state.messages:
    # 过滤掉底层系统 Prompt 和底层 Tool 返回的数据，保持 UI 纯净
    if msg["role"] in ["user", "assistant"] and isinstance(msg["content"], str):
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

# 接收用户指令并触发管线 (Pipeline)
if user_input := st.chat_input("输入您的出行计划..."):
    # 1. 渲染用户输入
    with st.chat_message("user"):
        st.markdown(user_input)
    st.session_state.messages.append({"role": "user", "content": user_input})
    
    # 2. 调度 Agent 处理
    with st.chat_message("assistant"):
        with st.spinner("正在解析要素与调取气象网格数据..."):
            # 深拷贝一份历史记录传给大模型（避免直接修改页面状态）
            api_messages = [{"role": m["role"], "content": m["content"]} 
                            for m in st.session_state.messages 
                            if "content" in m and isinstance(m["content"], str)]
            
            # 获取回答并渲染
            response_text = chat_with_agent(api_messages)
            st.markdown(response_text)
            
    # 3. 记录模型回答
    st.session_state.messages.append({"role": "assistant", "content": response_text})