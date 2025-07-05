from google.generativeai import configure, GenerativeModel
from config.constants import FAQ
from difflib import get_close_matches
from db.db import SessionLocal
from db.db_models import Users, Manittos
from utils.get_week_index import GetWeekIndex
from datetime import datetime
from utils.support_utils import get_notice_channel_content
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.runnables import RunnableLambda
from dotenv import load_dotenv
import os
import asyncio
import json
import discord

dotenv_path = os.path.join(os.path.dirname(__file__), '..', '.env')
load_dotenv(os.path.abspath(dotenv_path))
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

intents = discord.Intents.default()
intents.guilds = True  # ✅ 이 줄 꼭 추가
intents.message_content = True
intents.members = True
client = discord.Client(intents=intents)

configure(api_key=os.getenv("GEMINI_API_KEY"))
model = GenerativeModel("models/gemini-1.5-flash")

llm = ChatGoogleGenerativeAI(
    model="gemini-1.5-flash",
    temperature=0.7,
    google_api_key=os.getenv("GEMINI_API_KEY")
)

paused_channels: dict[int, float] = {}

def faq_response_func(query: str) -> str:
    if query in FAQ:
        return FAQ[query]
    match = get_close_matches(query, FAQ.keys(), n=1, cutoff=0.6)
    if match:
        return FAQ[match[0]]
    return "FAQ에서 답변을 찾을 수 없습니다."

def gemini_answer_func(query: str) -> str:
    faq_context = "\n".join([f"- {k}: {v}" for k, v in FAQ.items()])
    prompt = f"""\
당신은 마롱의 고객센터 AI 챗봇입니다.

[FAQ]
{faq_context}

[질문]
{query}

[답변]
"""
    try:
        response = model.generate_content(prompt)
        return response.text
    except Exception:
        return "Gemini 호출 중 오류가 발생했습니다."

def this_week_manittee_func(arg_json: str) -> str:
    data = json.loads(arg_json)
    manitto_id = data["manitto_id"]
    group_id = data["group_id"]
    
    base_date = datetime(2025, 1, 6)
    today = datetime.today()
    week_index = GetWeekIndex(today, base_date).get()
    
    with SessionLocal() as session:
        result = (
            session.query(Users.nickname)
            .join(Manittos, Users.id == Manittos.manittee_id)
            .filter(
                Manittos.manitto_id == manitto_id,
                Manittos.week == week_index,
                Manittos.group_id == group_id
            )
            .first()
        )
    if not result:
        return f"이번 주({week_index}) 마니띠 매칭이 없습니다."
    return f"이번 주({week_index}) 당신의 마니띠는 **{result[0]}** 님입니다!"

def pause_messaging_func(arg_json: str) -> str:
    data = json.loads(arg_json)
    channel_id = data["channel_id"]
    minutes = data.get("minutes", 1)

    now = asyncio.get_event_loop().time()
    resume_at = now + minutes * 60
    paused_channels[channel_id] = resume_at

    async def _unpause_later():
        await asyncio.sleep(minutes * 60)
        paused_channels.pop(channel_id, None)
    asyncio.create_task(_unpause_later())

    return f"{minutes}분 동안 응답을 멈춥니다."

GUILD_ID = 1373482494497787964  # 서버 ID

# tools/notice_summary_func.py 등에서 정의했다고 가정
async def notice_summary_func(state: dict) -> dict:
    guild = state.get("guild")  # ✅ 전달받은 guild 객체

    notice_channel_id = 1373910102913847366
    if guild is None:
        print(f"[DEBUG] notice_summary_func: guild is None, channel_id = {notice_channel_id}")
        return {**state, "result": "📛 공지 분석 실패: 서버 정보를 찾을 수 없습니다."}

    try:
        channel = guild.get_channel(notice_channel_id)
        if not channel:
            return {**state, "result": "📛 공지 채널을 찾을 수 없습니다."}
        
        messages = [msg async for msg in channel.history(limit=5)]
        content = "\n".join([f"{m.author.name}: {m.content}" for m in reversed(messages)])
        prompt = f"다음은 디스코드 공지입니다:\n\n{content}\n\n요약해주세요."
        response = await llm.ainvoke(prompt)
        return {**state, "result": response.content}
    except Exception as e:
        return {**state, "result": f"📛 공지 분석 중 오류: {e}"}

def safe_str_result(fn):
    def wrapper(x):
        print(f"[DEBUG] safe_str_result: input = {x.get('input')}")
        try:
            output = str(fn(x["input"]))
        except Exception as e:
            output = f"❗ 오류: {e}"
        return {**x, "result": output}
    return wrapper

graph_nodes = {
    "faq_response": RunnableLambda(safe_str_result(faq_response_func)),
    "gemini_answer": RunnableLambda(safe_str_result(gemini_answer_func)),
    "this_week_manittee": RunnableLambda(safe_str_result(this_week_manittee_func)),
    "pause_messaging": RunnableLambda(safe_str_result(pause_messaging_func)),
    "notice_summary": RunnableLambda(notice_summary_func),
}

__all__ = ["graph_nodes", "paused_channels"]