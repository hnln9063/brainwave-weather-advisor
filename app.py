"""Run with: uv run streamlit run app.py"""

import os

import streamlit as st
from dotenv import load_dotenv

from weather_advisor.graph import ask, build_graph

load_dotenv()
st.set_page_config(page_title="Weatherwise · BrainWave", page_icon="⛅", layout="centered")
st.title("⛅ Weatherwise")
st.caption("Outdoor plans, checked against a written policy.")

with st.sidebar:
    st.header("Your session")
    if st.button("New conversation", use_container_width=True):
        st.session_state.clear()
        st.rerun()
    provider = os.getenv("MODEL_PROVIDER", "demo")
    st.write(f"Language mode: **{provider}**")
    if provider == "demo":
        st.warning(
            "Limited no-key demo: uses keyword patterns, not an LLM. Use OpenAI, OpenRouter, or Anthropic for natural-language matching."
        )
    st.caption("Weather: live Open-Meteo hourly forecasts. Memory lasts only for this browser session.")
    st.markdown(
        "**Try asking**\n\nCycling in Bhopal today?\n\nWhat about tomorrow evening instead?\n\nA picnic in Berlin tomorrow?"
    )

if "messages" not in st.session_state:
    st.session_state.messages = []
    st.session_state.context = {}

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.write(message["content"])
        if message.get("audit"):
            with st.expander("Policy and weather evidence"):
                st.json(message["audit"])

if question := st.chat_input("What are you planning, where, and when?", max_chars=4000):
    st.session_state.messages.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.write(question)
    with st.chat_message("assistant"):
        with st.spinner("Checking your plan and the forecast…"):
            result = ask(build_graph(), question, st.session_state.context)
        if result.get("intent"):
            st.session_state.context = result["intent"]
        st.write(result["answer"])
        audit = {k: result[k] for k in ("status", "trace", "intent", "hits") if k in result}
        if "weather" in result:
            audit["weather"] = result["weather"]
        with st.expander("Policy and weather evidence"):
            st.json(audit)
        st.session_state.messages.append({"role": "assistant", "content": result["answer"], "audit": audit})
