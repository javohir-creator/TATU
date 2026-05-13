"""
Foydalanuvchi handlerlari — ro'yxatdan o'tish + so'rovnoma.
"""

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes, ConversationHandler, CallbackQueryHandler, MessageHandler, filters, CommandHandler

from database import (
    list_surveys, get_survey, get_questions, get_survey_results,
    save_response, save_text_response, has_answered, has_completed_survey,
    register_active_poll, get_active_poll, remove_active_poll,
    is_registered, register_user,
)

logger = logging.getLogger(__name__)
BAR_WIDTH = 10

# Registration states
REG_FACULTY, REG_COURSE, REG_GENDER = range(10, 13)

FACULTIES = [
    "Kompyuter injiniring va Sun'iy intelekt fakulteti",
    "Telekommunikatsiya fakulteti",
]
COURSES = ["1-kurs", "2-kurs", "3-kurs", "4-kurs"]
GENDERS = ["Erkak", "Ayol"]


def pbar(pct: float) -> str:
    filled = round(pct / 100 * BAR_WIDTH)
    return "█" * filled + "░" * (BAR_WIDTH - filled)


# ─────────────── REGISTRATION ───────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if await is_registered(user.id):
        text = (
            "👋 <b>Xush kelibsiz!</b>\n\n"
            "Bu bot orqali <b>mutloq anonim</b> so'rovnomalarda ishtirok etasiz.\n\n"
            "🔒 <i>Kim nima tanladi — hech kim bilmaydi, hatto bot ham.</i>\n\n"
            "📋 /surveys — Faol so'rovnomalar\n"
            "ℹ️ /about — Bot haqida\n"
        )
        await update.message.reply_text(text, parse_mode=ParseMode.HTML)
        return

    # Ro'yxatdan o'tish
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(FACULTIES[0], callback_data="reg_fac:0")],
        [InlineKeyboardButton(FACULTIES[1], callback_data="reg_fac:1")],
    ])
    await update.message.reply_text(
        "👋 <b>Xush kelibsiz!</b>\n\n"
        "Botdan foydalanish uchun avval <b>ro'yxatdan o'ting</b>.\n\n"
        "1️⃣ <b>Fakultetingizni tanlang:</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=kb,
    )


async def cb_reg_faculty(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    idx = int(query.data.split(":")[1])
    ctx.user_data["reg_faculty"] = FACULTIES[idx]

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(c, callback_data=f"reg_course:{c}") for c in COURSES[:2]],
        [InlineKeyboardButton(c, callback_data=f"reg_course:{c}") for c in COURSES[2:]],
    ])
    await query.edit_message_text(
        f"✅ Fakultet: <b>{FACULTIES[idx]}</b>\n\n"
        "2️⃣ <b>Kursingizni tanlang:</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=kb,
    )


async def cb_reg_course(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    course = query.data.split(":")[1]
    ctx.user_data["reg_course"] = course

    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("👨 Erkak", callback_data="reg_gender:Erkak"),
            InlineKeyboardButton("👩 Ayol", callback_data="reg_gender:Ayol"),
        ]
    ])
    await query.edit_message_text(
        f"✅ Fakultet: <b>{ctx.user_data['reg_faculty']}</b>\n"
        f"✅ Kurs: <b>{course}</b>\n\n"
        "3️⃣ <b>Jinsingizni tanlang:</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=kb,
    )


async def cb_reg_gender(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    gender = query.data.split(":")[1]
    user = query.from_user

    faculty = ctx.user_data.get("reg_faculty", "")
    course = ctx.user_data.get("reg_course", "")

    await register_user(
        user_id=user.id,
        username=user.username or "",
        full_name=user.full_name,
        faculty=faculty,
        course=course,
        gender=gender,
    )
    ctx.user_data.clear()

    await query.edit_message_text(
        "🎉 <b>Ro'yxatdan o'tdingiz!</b>\n\n"
        f"🏫 Fakultet: <b>{faculty}</b>\n"
        f"📚 Kurs: <b>{course}</b>\n"
        f"👤 Jins: <b>{gender}</b>\n\n"
        "Endi botdan foydalanishingiz mumkin!\n\n"
        "📋 /surveys — Faol so'rovnomalar\n"
        "ℹ️ /about — Bot haqida",
        parse_mode=ParseMode.HTML,
    )


# ─────────────── COMMANDS ───────────────

async def cmd_about(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (
        "🔒 <b>Anonim So'rovnoma Tizimi</b>\n\n"
        "<b>Maxfiylik qanday ta'minlanadi?</b>\n"
        "• Telegram ID'ingiz <b>hech qachon saqlanmaydi</b>\n"
        "• Har bir javob SHA-256 kriptografik token bilan qayd etiladi\n"
        "• Token noyob, lekin teskari aylantirish <b>mumkin emas</b>\n"
        "• Admin ham kim nima javob berganini bila olmaydi\n\n"
        "<b>Jarayon:</b>\n"
        "1️⃣ So'rovnoma tanlash\n"
        "2️⃣ Savollarni ketma-ket javoblash\n"
        "3️⃣ Natijalar real-vaqtda\n\n"
        "🤖 Natijalar <b>Sun'iy intellekt</b> tahlil qilinadi."
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def cmd_surveys(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await is_registered(update.effective_user.id):
        await update.message.reply_text(
            "⚠️ Avval ro'yxatdan o'ting. /start bosing."
        )
        return
    surveys = await list_surveys(active_only=True)
    if not surveys:
        await update.message.reply_text(
            "📭 Hozircha faol so'rovnomalar yo'q."
        )
        return

    buttons = []
    for s in surveys:
        label = f"📋 {s['title']} ({s['question_count']} savol)"
        buttons.append([InlineKeyboardButton(label, callback_data=f"sv_info:{s['id']}")])

    await update.message.reply_text(
        "📊 <b>Faol So'rovnomalar:</b>\n\nIshtirok etmoqchi bo'lgan so'rovnomani tanlang:",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def cmd_survey_link(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await is_registered(update.effective_user.id):
        await update.message.reply_text("⚠️ Avval ro'yxatdan o'ting. /start bosing.")
        return
    parts = update.message.text.split("_", 1)
    try:
        survey_id = int(parts[1])
    except (IndexError, ValueError):
        await update.message.reply_text("❌ Noto'g'ri havola.")
        return
    survey = await get_survey(survey_id)
    if not survey or not survey["is_active"]:
        await update.message.reply_text("❌ Bu so'rovnoma topilmadi yoki yopilgan.")
        return
    await _send_survey_info(update.message.reply_text, survey, update.effective_user.id)


# ─────────────── SURVEY INFO ───────────────

async def cb_sv_info(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    survey_id = int(query.data.split(":")[1])
    survey = await get_survey(survey_id)
    if not survey:
        await query.edit_message_text("❌ Topilmadi.")
        return
    await _send_survey_info(query.edit_message_text, survey, query.from_user.id)


async def _send_survey_info(send_fn, survey: dict, user_id: int):
    completed = await has_completed_survey(user_id, survey["id"])
    qs = survey["questions"]
    status_txt = "✅ <i>Siz bu so'rovnomani yakunladingiz</i>" if completed else ""

    text = (
        f"📊 <b>{survey['title']}</b>\n"
        f"{'—' * 30}\n"
    )
    if survey.get("description"):
        text += f"📝 {survey['description']}\n\n"

    text += f"❓ Savollar soni: <b>{len(qs)}</b>\n"
    text += f"🔒 <b>Mutloq anonim</b>\n"
    if status_txt:
        text += f"\n{status_txt}\n"

    buttons = []
    if survey["is_active"]:
        if completed:
            buttons.append([InlineKeyboardButton("🔁 Qayta ishtirok", callback_data=f"sv_start:{survey['id']}")])
        else:
            buttons.append([InlineKeyboardButton("▶️ Boshlash", callback_data=f"sv_start:{survey['id']}")])
        buttons.append([InlineKeyboardButton("📈 Joriy natijalar", callback_data=f"sv_results:{survey['id']}")])
    else:
        buttons.append([InlineKeyboardButton("📈 Natijalar", callback_data=f"sv_results:{survey['id']}")])
        buttons.append([InlineKeyboardButton("🤖 AI Tahlil", callback_data=f"sv_ai:{survey['id']}")])

    buttons.append([InlineKeyboardButton("🔙 Ro'yxatga", callback_data="sv_list")])

    await send_fn(text, parse_mode=ParseMode.HTML,
                  reply_markup=InlineKeyboardMarkup(buttons))


# ─────────────── START SURVEY ───────────────

async def cb_sv_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("▶️ So'rovnoma boshlanmoqda...")
    survey_id = int(query.data.split(":")[1])
    survey = await get_survey(survey_id)

    if not survey or not survey["is_active"]:
        await query.message.reply_text("❌ Bu so'rovnoma yopilgan.")
        return

    questions = survey["questions"]
    if not questions:
        await query.message.reply_text("❌ Bu so'rovnomada savollar yo'q.")
        return

    ctx.user_data["survey_session"] = {
        "survey_id": survey_id,
        "survey_title": survey["title"],
        "questions": questions,
        "current_idx": 0,
        "total": len(questions),
    }

    await query.message.reply_text(
        f"🚀 <b>{survey['title']}</b> so'rovnomasi boshlandi!\n\n"
        f"Jami {len(questions)} ta savol. Har biriga javob bering.\n"
        f"🔒 <i>Javoblaringiz mutloq anonim.</i>",
        parse_mode=ParseMode.HTML,
    )
    await _send_next_question(query.from_user.id, ctx, query.message.chat_id)


async def _send_next_question(user_id: int, ctx: ContextTypes.DEFAULT_TYPE, chat_id: int):
    session = ctx.user_data.get("survey_session")
    if not session:
        return

    idx = session["current_idx"]
    questions = session["questions"]
    total = session["total"]

    if idx >= total:
        await _finish_survey(user_id, ctx, chat_id)
        return

    q = questions[idx]
    progress = f"📝 Savol {idx + 1}/{total}"
    q_type = q.get("q_type", "single")

    if q_type == "text":
        # Yozma savol uchun matn so'rash
        ctx.user_data["waiting_text_answer"] = {
            "survey_id": session["survey_id"],
            "question_id": q["id"],
            "user_id": user_id,
        }
        await ctx.bot.send_message(
            chat_id=chat_id,
            text=f"{progress}\n\n❓ <b>{q['question']}</b>\n\n✍️ <i>Javobingizni matn ko'rinishida yozing:</i>",
            parse_mode=ParseMode.HTML,
        )
    else:
        msg = await ctx.bot.send_poll(
            chat_id=chat_id,
            question=f"{progress}\n\n{q['question']}",
            options=q["options"],
            is_anonymous=False,
            allows_multiple_answers=(q_type == "multi"),
            protect_content=False,
        )
        await register_active_poll(
            tg_poll_id=msg.poll.id,
            survey_id=session["survey_id"],
            question_id=q["id"],
            user_id=user_id,
        )
        logger.info("Poll yuborildi: user=%d survey=%d q=%d", user_id, session["survey_id"], q["id"])


async def handle_text_answer(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Yozma savol javobini qabul qilish."""
    waiting = ctx.user_data.get("waiting_text_answer")
    if not waiting:
        return

    answer = update.message.text.strip()
    if not answer:
        await update.message.reply_text("⚠️ Javob bo'sh bo'lmasligi kerak. Qayta yozing:")
        return

    user_id = update.effective_user.id
    await save_text_response(
        survey_id=waiting["survey_id"],
        question_id=waiting["question_id"],
        user_id=user_id,
        answer_text=answer,
    )
    ctx.user_data.pop("waiting_text_answer", None)

    await update.message.reply_text("✅ Javobingiz qabul qilindi!")

    session = ctx.user_data.get("survey_session")
    if session and session["survey_id"] == waiting["survey_id"]:
        session["current_idx"] += 1
        await _send_next_question(user_id, ctx, update.message.chat_id)


async def _finish_survey(user_id: int, ctx: ContextTypes.DEFAULT_TYPE, chat_id: int):
    session = ctx.user_data.pop("survey_session", {})
    survey_id = session.get("survey_id")
    title = session.get("survey_title", "")

    await ctx.bot.send_message(
        chat_id=chat_id,
        text=(
            "🎉 <b>Rahmat! So'rovnomani yakunladingiz.</b>\n\n"
            f"📊 <i>{title}</i>\n\n"
            "Javoblaringiz anonim tarzda qayd etildi.\n"
            "Natijalarni ko'rish uchun quyidagi tugmani bosing:"
        ),
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📈 Natijalarni ko'rish", callback_data=f"sv_results:{survey_id}")],
            [InlineKeyboardButton("📋 Barcha so'rovnomalar", callback_data="sv_list")],
        ]),
    )


# ─────────────── POLL ANSWER HANDLER ───────────────

async def handle_poll_answer(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    answer = update.poll_answer
    tg_poll_id = answer.poll_id
    user = answer.user
    chosen = list(answer.option_ids)

    if not chosen:
        return

    active = await get_active_poll(tg_poll_id)
    if not active:
        logger.warning("Noma'lum poll_id: %s", tg_poll_id)
        return

    survey_id = active["survey_id"]
    question_id = active["question_id"]
    registered_user_id = active["user_id"]

    if user.id != registered_user_id:
        return

    await save_response(survey_id, question_id, user.id, chosen)
    await remove_active_poll(tg_poll_id)

    session = ctx.user_data.get("survey_session", {})
    if session.get("survey_id") == survey_id:
        session["current_idx"] += 1
        await _send_next_question(user.id, ctx, user.id)
    else:
        await _resume_session_after_restart(user.id, ctx, survey_id, question_id)


async def _resume_session_after_restart(user_id, ctx, survey_id, last_question_id):
    survey = await get_survey(survey_id)
    if not survey or not survey["is_active"]:
        return
    questions = survey["questions"]
    last_idx = next((i for i, q in enumerate(questions) if q["id"] == last_question_id), -1)
    next_idx = last_idx + 1

    ctx.user_data["survey_session"] = {
        "survey_id": survey_id,
        "survey_title": survey["title"],
        "questions": questions,
        "current_idx": next_idx,
        "total": len(questions),
    }
    if next_idx >= len(questions):
        await _finish_survey(user_id, ctx, user_id)
    else:
        await _send_next_question(user_id, ctx, user_id)


# ─────────────── RESULTS ───────────────

async def cb_sv_results(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    survey_id = int(query.data.split(":")[1])
    survey = await get_survey(survey_id)
    if not survey:
        await query.edit_message_text("❌ Topilmadi.")
        return

    results = await get_survey_results(survey_id)
    if not results:
        await query.edit_message_text(
            "📭 Hali javoblar yo'q.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Ortga", callback_data=f"sv_info:{survey_id}")
            ]])
        )
        return

    text = f"📊 <b>{survey['title']}</b>\n<i>Natijalar</i>\n\n"

    for qid, data in results.items():
        total = data["total"]
        text += f"❓ <b>{data['question']}</b>\n"
        text += f"<i>Ishtirok: {total} ta javob</i>\n"
        if data.get("q_type") == "text":
            answers = data.get("text_answers", [])
            for a in answers[:5]:
                text += f"  ✍️ {a}\n"
            if len(answers) > 5:
                text += f"  <i>...va yana {len(answers)-5} ta javob</i>\n"
        else:
            for i, opt in enumerate(data["options"]):
                cnt = data["counts"].get(i, 0)
                pct = round(cnt / total * 100, 1) if total else 0
                bar = pbar(pct)
                text += f"[{bar}] {pct}%  {opt}  ({cnt})\n"
        text += "\n"

    buttons = []
    if not survey["is_active"] and survey.get("ai_analysis"):
        buttons.append([InlineKeyboardButton("🤖 AI Tahlil", callback_data=f"sv_ai:{survey_id}")])
    buttons.append([InlineKeyboardButton("🔙 Ortga", callback_data=f"sv_info:{survey_id}")])

    await query.edit_message_text(
        text, parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(buttons)
    )


async def cb_sv_ai(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    from ai_analyzer import format_analysis
    query = update.callback_query
    await query.answer()
    survey_id = int(query.data.split(":")[1])
    survey = await get_survey(survey_id)
    if not survey:
        await query.edit_message_text("❌ Topilmadi.")
        return

    analysis = survey.get("ai_analysis")
    if not analysis:
        text = "🤖 <i>AI tahlil hali amalga oshirilmagan.</i>"
    else:
        text = format_analysis(analysis, survey["title"])

    buttons = [[InlineKeyboardButton("🔙 Ortga", callback_data=f"sv_info:{survey_id}")]]
    await query.edit_message_text(text, parse_mode=ParseMode.HTML,
                                   reply_markup=InlineKeyboardMarkup(buttons))


async def cb_sv_list(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    surveys = await list_surveys(active_only=True)
    if not surveys:
        await query.edit_message_text("📭 Hozircha faol so'rovnomalar yo'q.")
        return

    buttons = []
    for s in surveys:
        label = f"📋 {s['title']} ({s['question_count']} savol)"
        buttons.append([InlineKeyboardButton(label, callback_data=f"sv_info:{s['id']}")])

    await query.edit_message_text(
        "📊 <b>Faol So'rovnomalar:</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(buttons),
    )
