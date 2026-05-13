"""
AI tahlil moduli — Azure OpenAI yordamida survey natijalarini tahlil qilish.
"""

import os
import json
import logging
import asyncio
from openai import AsyncAzureOpenAI
from database import get_survey, get_survey_results, save_ai_analysis, log_analysis

logger = logging.getLogger(__name__)


def _client(secondary=False):
    key = os.getenv("AZURE_OPENAI_API_KEY_2" if secondary else "AZURE_OPENAI_API_KEY")
    return AsyncAzureOpenAI(
        api_key=key,
        azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
        api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-08-01-preview"),
    )


def _deployment(secondary=False):
    k = "AZURE_OPENAI_DEPLOYMENT_NAME_SECONDARY" if secondary else "AZURE_OPENAI_DEPLOYMENT_NAME_PRIMARY"
    return os.getenv(k, "gpt-4o-mini-standard")


async def analyze_survey(survey_id: int, use_secondary: bool = False) -> dict:
    survey = await get_survey(survey_id)
    if not survey:
        return {"error": "Survey topilmadi"}

    results = await get_survey_results(survey_id)
    if not results:
        return {"error": "Hali javoblar yo'q"}

    # Natijalar matni
    sections = []
    total_respondents = 0
    for qid, data in results.items():
        total = data["total"]
        if total > total_respondents:
            total_respondents = total
        opts = []
        for i, opt in enumerate(data["options"]):
            cnt = data["counts"].get(i, 0)
            pct = round(cnt / total * 100, 1) if total else 0
            opts.append(f"    {i+1}. {opt}: {cnt} ({pct}%)")
        sections.append(
            f"Savol: {data['question']}\n  Ishtirokchilar: {total}\n" + "\n".join(opts)
        )
    results_text = "\n\n".join(sections)

    system_prompt = (
        "Siz so'rovnoma natijalarini tahlil qiluvchi ekspertsiz. "
        "Javobingiz FAQAT Uzbek tilida, FAQAT JSON formatida bo'lsin:\n"
        "{\n"
        '  "summary": "Umumiy xulosa (2-3 gap)",\n'
        '  "question_insights": ["Har bir savol bo\'yicha asosiy topilma (har birini alohida)"],\n'
        '  "key_trends": ["Umumiy trendlar (2-4 ta)"],\n'
        '  "dominant_opinion": "Yetakchi fikr yoki yo\'nalish",\n'
        '  "sentiment": "ijobiy|salbiy|neytral|aralash",\n'
        '  "participation_note": "Ishtirok sifati haqida qisqa baho",\n'
        '  "recommendation": "Amaliy tavsiya yoki keyingi qadam",\n'
        '  "confidence_score": 0.0\n'
        "}"
    )
    
    desc = survey.get("description") or "Yo'q"
    user_prompt = (
        f"Survey: {survey['title']}\n"
        f"Tavsif: {desc}\n"
        f"Savollar soni: {len(results)}\n"
        f"Jami respondentlar (taxminan): {total_respondents}\n\n"
        f"Natijalar:\n{results_text}"
    )

    client = _client(use_secondary)
    dep = _deployment(use_secondary)
    
    logger.info(f"AI analysis started for survey {survey_id} (mode={'deep' if use_secondary else 'fast'})")
    
    try:
        # 45 soniya timeout qo'shamiz
        resp = await asyncio.wait_for(
            client.chat.completions.create(
                model=dep,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user",   "content": user_prompt},
                ],
                temperature=0.3,
                max_tokens=1500,
                response_format={"type": "json_object"},
            ),
            timeout=45.0
        )
        raw = resp.choices[0].message.content
        logger.info(f"AI analysis finished for survey {survey_id}")
        analysis = json.loads(raw)
        pt = resp.usage.prompt_tokens if resp.usage else 0
        ct = resp.usage.completion_tokens if resp.usage else 0
        await log_analysis(survey_id, dep, pt, ct, raw)
        await save_ai_analysis(survey_id, analysis)
        return analysis
    except asyncio.TimeoutError:
        logger.error(f"AI analysis timeout for survey {survey_id}")
        return {"error": "AI tahlil vaqti tugadi (timeout). Iltimos, qayta urinib ko'ring.", "summary": "AI tahlil juda uzoq davom etdi"}
    except Exception as e:
        logger.error(f"AI analysis error: {e}")
        return {"error": str(e), "summary": "AI tahlil amalga oshmadi"}


def format_analysis(analysis: dict, survey_title: str = "") -> str:
    if "error" in analysis and "summary" not in analysis:
        return f"❌ <b>Xato:</b> {analysis['error']}"

    lines = [f"🤖 <b>AI Tahlil</b>"]
    if survey_title:
        lines.append(f"📊 <i>{survey_title}</i>\n")

    if s := analysis.get("summary"):
        lines.append(f"📋 <b>Xulosa:</b>\n{s}\n")

    if qi := analysis.get("question_insights"):
        lines.append("🔍 <b>Savol bo'yicha topilmalar:</b>")
        for item in qi:
            lines.append(f"  • {item}")
        lines.append("")

    if kt := analysis.get("key_trends"):
        lines.append("📈 <b>Asosiy trendlar:</b>")
        for t in kt:
            lines.append(f"  → {t}")
        lines.append("")

    if do_ := analysis.get("dominant_opinion"):
        lines.append(f"🏆 <b>Yetakchi fikr:</b> {do_}\n")

    sent_map = {"ijobiy": "😊", "salbiy": "😟", "neytral": "😐", "aralash": "🌀"}
    if sent := analysis.get("sentiment"):
        emoji = sent_map.get(sent, "💬")
        lines.append(f"{emoji} <b>Kayfiyat:</b> {sent.capitalize()}\n")

    if pn := analysis.get("participation_note"):
        lines.append(f"👥 <b>Ishtirok:</b> {pn}\n")

    if rec := analysis.get("recommendation"):
        lines.append(f"💡 <b>Tavsiya:</b>\n{rec}\n")

    if cs := analysis.get("confidence_score"):
        pct = int(float(cs) * 100)
        bar = "█" * (pct // 10) + "░" * (10 - pct // 10)
        lines.append(f"🎯 <b>Ishonch:</b> [{bar}] {pct}%")

    return "\n".join(lines)
