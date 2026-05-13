"""
Admin handlerlari — to'liq qayta yozilgan versiya.
"""

import os
import json
import logging
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, ReplyKeyboardRemove,
    KeyboardButton, KeyboardButtonPollType,
)
from telegram.constants import ParseMode
from telegram.ext import (
    ContextTypes, CommandHandler, MessageHandler, CallbackQueryHandler,
    filters, ConversationHandler,
)

from database import (
    list_surveys, get_survey, create_survey,
    close_survey, delete_survey, get_survey_results,
    get_questions, delete_question, update_question,
    get_users_by_filter, get_all_user_ids,
    add_admin, get_db_admins,
)
from ai_analyzer import analyze_survey, format_analysis

logger = logging.getLogger(__name__)

_MAIN_ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", os.getenv("ADMIN_ID", "0")).split(",")]


async def _all_admin_ids():
    db_admins = await get_db_admins()
    return list(set(_MAIN_ADMIN_IDS + db_admins))


async def _is_admin(user_id: int) -> bool:
    return user_id in await _all_admin_ids()


def admin_only(fn):
    async def wrapper(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        uid = update.effective_user.id if update.effective_user else 0
        if not uid or not await _is_admin(uid):
            if update.callback_query:
                await update.callback_query.answer("🚫 Ruxsat yo'q!", show_alert=True)
            elif update.message:
                await update.message.reply_text("🚫 Bu buyruq faqat adminlar uchun.")
            return
        return await fn(update, ctx)
    wrapper.__name__ = fn.__name__
    return wrapper


def pbar(pct: float, w: int = 10) -> str:
    filled = round(pct / 100 * w)
    return "█" * filled + "░" * (w - filled)


def questions_summary(questions: list) -> str:
    if not questions:
        return "<i>Hali savollar yo'q</i>"
    lines = []
    type_icons = {"single": "🔘", "multi": "☑️", "text": "✍️"}
    for i, q in enumerate(questions):
        q_type = q.get("q_type", "single")
        icon = type_icons.get(q_type, "🔘")
        if q_type == "text":
            lines.append(f"{i+1}. {icon} <b>{q['question']}</b>\n   <i>Yozma javob</i>")
        else:
            opts = ", ".join(q.get("options", [])[:3])
            if len(q.get("options", [])) > 3:
                opts += f" (+{len(q['options'])-3})"
            lines.append(f"{i+1}. {icon} <b>{q['question']}</b>\n   <i>{opts}</i>")
    return "\n".join(lines)


BACK_BTN = InlineKeyboardButton("🏠 Asosiy menyu", callback_data="adm_home")


# ═══════════════════════════════════════════════════════════
# ADMIN PANEL — Asosiy menyu (Reply Keyboard)
# ═══════════════════════════════════════════════════════════

ADMIN_MAIN_KB = ReplyKeyboardMarkup(
    [
        ["➕ Yangi So'rovnoma", "📋 So'rovnomalar"],
        ["📊 Statistika", "✏️ Savollarni tahrirlash"],
        ["👥 Admin qo'shish"],
    ],
    resize_keyboard=True,
)


@admin_only
async def cmd_admin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    surveys = await list_surveys()
    active = sum(1 for s in surveys if s["is_active"])
    closed = len(surveys) - active

    await update.message.reply_text(
        "⚙️ <b>Admin Panel</b>\n\n"
        f"🟢 Faol: <b>{active}</b>   🔴 Yopilgan: <b>{closed}</b>\n\n"
        "Pastdagi tugmalardan foydalaning:",
        parse_mode=ParseMode.HTML,
        reply_markup=ADMIN_MAIN_KB,
    )


@admin_only
async def cb_adm_home(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    surveys = await list_surveys()
    active = sum(1 for s in surveys if s["is_active"])
    closed = len(surveys) - active

    await query.edit_message_text(
        "⚙️ <b>Admin Panel</b>\n\n"
        f"🟢 Faol: <b>{active}</b>   🔴 Yopilgan: <b>{closed}</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Yangi So'rovnoma", callback_data="adm_create")],
            [InlineKeyboardButton("📋 So'rovnomalar", callback_data="adm_list")],
            [InlineKeyboardButton("📊 Statistika", callback_data="adm_stats")],
        ])
    )


# ─── Reply Keyboard tugmalar ───

@admin_only
async def handle_admin_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "➕ Yangi So'rovnoma":
        await _start_create_survey(update, ctx)
    elif text == "📋 So'rovnomalar":
        await _show_surveys_list(update.message.reply_text, ctx)
    elif text == "📊 Statistika":
        await _show_stats(update.message.reply_text)
    elif text == "✏️ Savollarni tahrirlash":
        await _show_edit_surveys(update.message.reply_text)
    elif text == "👥 Admin qo'shish":
        await _start_add_admin(update, ctx)


# ═══════════════════════════════════════════════════════════
# SO'ROVNOMA YARATISH — yangi tizim (inline tugmalar bilan)
# ═══════════════════════════════════════════════════════════

(
    CV_TITLE, CV_DESC,
    CV_Q_TYPE, CV_Q_TEXT, CV_Q_OPTIONS,
    CV_CONFIRM,
    CV_SEND_SELECT_FAC, CV_SEND_SELECT_COURSE, CV_SEND_SELECT_GENDER,
) = range(20, 29)


async def _start_create_survey(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear()
    ctx.user_data["new_sv"] = {"questions": []}
    await update.message.reply_text(
        "➕ <b>Yangi So'rovnoma</b>\n\n"
        "1️⃣ So'rovnoma <b>sarlavhasini</b> kiriting:\n\n"
        "<i>Bekor qilish: /cancel</i>",
        parse_mode=ParseMode.HTML,
        reply_markup=ReplyKeyboardRemove(),
    )
    return CV_TITLE


async def cv_title(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    title = update.message.text.strip()
    if len(title) < 3:
        await update.message.reply_text("⚠️ Sarlavha juda qisqa. Qayta kiriting:")
        return CV_TITLE
    ctx.user_data["new_sv"]["title"] = title
    await update.message.reply_text(
        "2️⃣ <b>Tavsif kiriting</b> (ixtiyoriy):\n<i>O'tkazib yuborish: /skip</i>",
        parse_mode=ParseMode.HTML,
    )
    return CV_DESC


async def cv_desc(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["new_sv"]["description"] = update.message.text.strip()
    return await _ask_question_type(update, ctx)


async def cv_skip_desc(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["new_sv"]["description"] = ""
    return await _ask_question_type(update, ctx)


async def _ask_question_type(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    qs = ctx.user_data["new_sv"]["questions"]
    n = len(qs)
    prefix = f"✅ {n} ta savol qo'shildi.\n\n" if n > 0 else ""

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔘 1 ta javob (Yagona)", callback_data="qtype:single")],
        [InlineKeyboardButton("☑️ Ko'p javob (Multiple)", callback_data="qtype:multi")],
        [InlineKeyboardButton("✍️ Yozma javob (Text)", callback_data="qtype:text")],
        [InlineKeyboardButton("✅ Savollar tayyor → Davom et", callback_data="qtype:done")],
    ])

    text = (
        f"{prefix}"
        f"3️⃣ <b>Savol #{n+1}</b> — Savol turini tanlang:\n\n"
        "🔘 <i>Yagona — faqat 1 ta javob tanlanadi</i>\n"
        "☑️ <i>Ko'p — bir nechta javob tanlanishi mumkin</i>\n"
        "✍️ <i>Yozma — foydalanuvchi matn yozadi</i>"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
    return CV_Q_TYPE


async def cv_q_type_chosen(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    q_type = query.data.split(":")[1]

    if q_type == "done":
        qs = ctx.user_data["new_sv"].get("questions", [])
        if not qs:
            await query.edit_message_text(
                "⚠️ Kamida 1 ta savol qo'shing!",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔘 Yagona javob", callback_data="qtype:single")],
                    [InlineKeyboardButton("☑️ Ko'p javob", callback_data="qtype:multi")],
                    [InlineKeyboardButton("✍️ Yozma javob", callback_data="qtype:text")],
                ])
            )
            return CV_Q_TYPE
        return await _show_confirm(query, ctx)

    ctx.user_data["current_q"] = {"q_type": q_type}
    type_names = {"single": "Yagona javob 🔘", "multi": "Ko'p javob ☑️", "text": "Yozma javob ✍️"}
    await query.edit_message_text(
        f"✅ Tur: <b>{type_names[q_type]}</b>\n\n"
        "Savol matni kiriting:",
        parse_mode=ParseMode.HTML,
    )
    return CV_Q_TEXT


async def cv_q_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q_text = update.message.text.strip()
    if len(q_text) < 3:
        await update.message.reply_text("⚠️ Savol juda qisqa. Qayta kiriting:")
        return CV_Q_TEXT

    ctx.user_data["current_q"]["question"] = q_text
    q_type = ctx.user_data["current_q"]["q_type"]

    if q_type == "text":
        # Yozma savol uchun variantlar kerak emas
        ctx.user_data["current_q"]["options"] = []
        q = ctx.user_data["current_q"]
        ctx.user_data["new_sv"]["questions"].append(q.copy())
        ctx.user_data.pop("current_q", None)
        n = len(ctx.user_data["new_sv"]["questions"])

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Yana savol qo'shish", callback_data="qtype:more")],
            [InlineKeyboardButton("✅ Testni boshlashga o'tish", callback_data="qtype:done")],
        ])
        await update.message.reply_text(
            f"✅ <b>Savol #{n}</b> saqlandi! (Yozma javob)\n\n"
            "Nimani qilmoqchisiz?",
            parse_mode=ParseMode.HTML,
            reply_markup=kb,
        )
        return CV_Q_TYPE
    else:
        await update.message.reply_text(
            "Javob variantlarini kiriting.\n"
            "<i>Har bir variantni yangi qatorda yozing (kamida 2 ta):</i>\n\n"
            "<b>Masalan:</b>\n"
            "Ha\n"
            "Yo'q\n"
            "Bilmayman",
            parse_mode=ParseMode.HTML,
        )
        return CV_Q_OPTIONS


async def cv_q_options(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    raw = update.message.text.strip()
    options = [o.strip() for o in raw.splitlines() if o.strip()]

    if len(options) < 2:
        await update.message.reply_text("⚠️ Kamida 2 ta variant kiriting! Qayta yozing:")
        return CV_Q_OPTIONS

    ctx.user_data["current_q"]["options"] = options
    q = ctx.user_data["current_q"]
    ctx.user_data["new_sv"]["questions"].append(q.copy())
    ctx.user_data.pop("current_q", None)
    n = len(ctx.user_data["new_sv"]["questions"])

    type_icons = {"single": "🔘", "multi": "☑️"}
    icon = type_icons.get(q["q_type"], "🔘")

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Yana savol qo'shish", callback_data="qtype:more")],
        [InlineKeyboardButton("✅ Testni boshlashga o'tish", callback_data="qtype:done")],
    ])
    await update.message.reply_text(
        f"✅ <b>Savol #{n}</b> {icon} saqlandi!\n\n"
        f"<b>{q['question']}</b>\n"
        + "\n".join(f"  • {o}" for o in options[:5])
        + ("\n  ..." if len(options) > 5 else "")
        + "\n\nNimani qilmoqchisiz?",
        parse_mode=ParseMode.HTML,
        reply_markup=kb,
    )
    return CV_Q_TYPE


async def cv_q_more(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Inline 'yana savol qo'shish' tugmasi bosilganda."""
    query = update.callback_query
    await query.answer()
    qs = ctx.user_data["new_sv"]["questions"]
    n = len(qs)

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔘 1 ta javob (Yagona)", callback_data="qtype:single")],
        [InlineKeyboardButton("☑️ Ko'p javob (Multiple)", callback_data="qtype:multi")],
        [InlineKeyboardButton("✍️ Yozma javob (Text)", callback_data="qtype:text")],
        [InlineKeyboardButton("✅ Savollar tayyor → Davom et", callback_data="qtype:done")],
    ])
    await query.edit_message_text(
        f"✅ Hozirgacha {n} ta savol qo'shildi.\n\n"
        f"<b>Savol #{n+1}</b> — Savol turini tanlang:",
        parse_mode=ParseMode.HTML,
        reply_markup=kb,
    )
    return CV_Q_TYPE


async def _show_confirm(query_or_msg, ctx: ContextTypes.DEFAULT_TYPE):
    sv = ctx.user_data["new_sv"]
    qs = sv["questions"]
    text = (
        "✅ <b>So'rovnomani tasdiqlang:</b>\n\n"
        f"📌 Sarlavha: <b>{sv['title']}</b>\n"
        f"📝 Tavsif: {sv.get('description') or '—'}\n"
        f"❓ Savollar: <b>{len(qs)}</b> ta\n\n"
        f"{questions_summary(qs)}"
    )
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Tasdiqlash", callback_data="cv_confirm_yes"),
            InlineKeyboardButton("❌ Bekor", callback_data="cv_confirm_no"),
        ]
    ])
    if hasattr(query_or_msg, "edit_message_text"):
        await query_or_msg.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
    else:
        await query_or_msg.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
    return CV_CONFIRM


async def cv_confirm(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "cv_confirm_no":
        ctx.user_data.clear()
        await query.edit_message_text("❌ Bekor qilindi.")
        return ConversationHandler.END

    sv = ctx.user_data["new_sv"]
    survey_id = await create_survey(
        title=sv["title"],
        description=sv.get("description", ""),
        questions=sv["questions"],
        admin_id=query.from_user.id,
    )
    ctx.user_data.clear()

    # So'rovnomani saqlash, keyin yuborish so'ralsin
    ctx.user_data["send_survey_id"] = survey_id
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 Testni boshlash (yuborish)", callback_data=f"adm_send_start:{survey_id}")],
        [InlineKeyboardButton("📊 So'rovnomani ko'rish", callback_data=f"adm_sv:{survey_id}")],
        [BACK_BTN],
    ])
    await query.edit_message_text(
        f"🎉 <b>So'rovnoma yaratildi!</b>\n\n"
        f"🆔 ID: <code>{survey_id}</code>\n\n"
        f"Havola: /s_{survey_id}\n\n"
        f"Endi kimga yuborishni tanlang:",
        parse_mode=ParseMode.HTML,
        reply_markup=kb,
    )
    return ConversationHandler.END


async def cv_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear()
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text("❌ Bekor qilindi.")
    elif update.message:
        await update.message.reply_text("❌ Bekor qilindi.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END


# ═══════════════════════════════════════════════════════════
# TESTNI YUBORISH — fakultet, kurs, jins tanlash
# ═══════════════════════════════════════════════════════════

FACULTIES = [
    "Kompyuter injiniring va Sun'iy intelekt fakulteti",
    "Telekommunikatsiya fakulteti",
]
COURSES = ["1-kurs", "2-kurs", "3-kurs", "4-kurs"]
GENDERS = ["Erkak", "Ayol"]


@admin_only
async def cb_adm_send_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Testni yuborish — avval manzil tanlash."""
    query = update.callback_query
    await query.answer()
    survey_id = int(query.data.split(":")[1])
    # Yuborish sessiyasini yangilash
    ctx.user_data["send_sv_id"] = survey_id
    ctx.user_data["send_faculties"] = []
    ctx.user_data["send_courses"] = []
    ctx.user_data["send_genders"] = []
    logger.info("SEND START: survey_id=%d user=%d", survey_id, query.from_user.id)

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            f"{'✅' if FACULTIES[0] in ctx.user_data['send_faculties'] else '⬜'} KI va SI fakulteti",
            callback_data="send_fac:0"
        )],
        [InlineKeyboardButton(
            f"{'✅' if FACULTIES[1] in ctx.user_data['send_faculties'] else '⬜'} Telekommunikatsiya",
            callback_data="send_fac:1"
        )],
        [InlineKeyboardButton("🌍 Hammaga yuborish", callback_data="send_fac:all")],
        [InlineKeyboardButton("➡️ Davom et", callback_data="send_fac:next")],
        [BACK_BTN],
    ])
    await query.edit_message_text(
        "📤 <b>Kimga yuborilsin?</b>\n\n"
        "Fakultet(lar)ni tanlang (bir necha tanlash mumkin):\n\n"
        "<i>Hammaga yuborish uchun 🌍 tugmasini bosing</i>",
        parse_mode=ParseMode.HTML,
        reply_markup=kb,
    )


@admin_only
async def cb_send_fac(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    val = query.data.split(":")[1]
    survey_id = ctx.user_data.get("send_sv_id", 0)

    if val == "all":
        # Hammaga yuborish
        await _send_survey_to_all(query, ctx, survey_id)
        return

    if val == "next":
        # Hech kim tanlanmagan — xato
        if not ctx.user_data.get("send_faculties"):
            await query.answer("⚠️ Kamida 1 ta fakultet tanlang!", show_alert=True)
            return
        ctx.user_data["send_courses"] = []
        logger.info("FAC NEXT: faculties=%s", ctx.user_data.get("send_faculties"))
        return await _show_course_select(query, ctx)

    idx = int(val)
    facs = ctx.user_data.setdefault("send_faculties", [])
    fac = FACULTIES[idx]
    if fac in facs:
        facs.remove(fac)
    else:
        facs.append(fac)

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            f"{'✅' if FACULTIES[0] in facs else '⬜'} KI va SI fakulteti",
            callback_data="send_fac:0"
        )],
        [InlineKeyboardButton(
            f"{'✅' if FACULTIES[1] in facs else '⬜'} Telekommunikatsiya",
            callback_data="send_fac:1"
        )],
        [InlineKeyboardButton("🌍 Hammaga yuborish", callback_data="send_fac:all")],
        [InlineKeyboardButton("➡️ Davom et", callback_data="send_fac:next")],
        [BACK_BTN],
    ])
    await query.edit_message_reply_markup(reply_markup=kb)


async def _show_course_select(query, ctx: ContextTypes.DEFAULT_TYPE):
    courses = ctx.user_data.get("send_courses", [])

    def course_btn(c):
        return InlineKeyboardButton(
            f"{'✅' if c in courses else '⬜'} {c}",
            callback_data=f"send_course:{c}"
        )

    kb = InlineKeyboardMarkup([
        [course_btn("1-kurs"), course_btn("2-kurs")],
        [course_btn("3-kurs"), course_btn("4-kurs")],
        [InlineKeyboardButton("📚 Barcha kurslar", callback_data="send_course:all")],
        [InlineKeyboardButton("➡️ Davom et", callback_data="send_course:next")],
        [BACK_BTN],
    ])
    await query.edit_message_text(
        "📚 <b>Qaysi kurslarga yuborilsin?</b>\n\n"
        "Kurs(lar)ni tanlang (bir necha tanlash mumkin):",
        parse_mode=ParseMode.HTML,
        reply_markup=kb,
    )


@admin_only
async def cb_send_course(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    val = query.data.split(":")[1]

    if val == "all":
        ctx.user_data["send_courses"] = list(COURSES)
        return await _show_gender_select(query, ctx)

    if val == "next":
        if not ctx.user_data.get("send_courses"):
            await query.answer("⚠️ Kamida 1 ta kurs tanlang!", show_alert=True)
            return
        return await _show_gender_select(query, ctx)

    courses = ctx.user_data.setdefault("send_courses", [])
    if val in courses:
        courses.remove(val)
    else:
        courses.append(val)

    def course_btn(c):
        return InlineKeyboardButton(
            f"{'✅' if c in courses else '⬜'} {c}",
            callback_data=f"send_course:{c}"
        )

    kb = InlineKeyboardMarkup([
        [course_btn("1-kurs"), course_btn("2-kurs")],
        [course_btn("3-kurs"), course_btn("4-kurs")],
        [InlineKeyboardButton("📚 Barcha kurslar", callback_data="send_course:all")],
        [InlineKeyboardButton("➡️ Davom et", callback_data="send_course:next")],
        [BACK_BTN],
    ])
    await query.edit_message_reply_markup(reply_markup=kb)


async def _show_gender_select(query, ctx: ContextTypes.DEFAULT_TYPE):
    genders = ctx.user_data.get("send_genders", [])

    def g_btn(g, label):
        return InlineKeyboardButton(
            f"{'✅' if g in genders else '⬜'} {label}",
            callback_data=f"send_gender:{g}"
        )

    kb = InlineKeyboardMarkup([
        [g_btn("Erkak", "👨 Erkak"), g_btn("Ayol", "👩 Ayol")],
        [InlineKeyboardButton("👥 Ikkalasi ham", callback_data="send_gender:all")],
        [InlineKeyboardButton("✅ Yuborish", callback_data="send_gender:next")],
        [BACK_BTN],
    ])
    await query.edit_message_text(
        "👤 <b>Qaysi jinsga yuborilsin?</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=kb,
    )


@admin_only
async def cb_send_gender(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    val = query.data.split(":")[1]
    survey_id = ctx.user_data.get("send_sv_id", 0)

    if val == "all":
        ctx.user_data["send_genders"] = list(GENDERS)
        await _do_send_survey(
            query, ctx, survey_id,
            faculties=ctx.user_data.get("send_faculties") or None,
            courses=ctx.user_data.get("send_courses") or None,
            genders=list(GENDERS),
        )
        return

    if val == "next":
        if not ctx.user_data.get("send_genders"):
            await query.answer("⚠️ Kamida 1 ta jins tanlang!", show_alert=True)
            return
        await _do_send_survey(
            query, ctx, survey_id,
            faculties=ctx.user_data.get("send_faculties") or None,
            courses=ctx.user_data.get("send_courses") or None,
            genders=ctx.user_data.get("send_genders") or None,
        )
        return

    genders = ctx.user_data.setdefault("send_genders", [])
    if val in genders:
        genders.remove(val)
    else:
        genders.append(val)

    def g_btn(g, label):
        return InlineKeyboardButton(
            f"{'✅' if g in genders else '⬜'} {label}",
            callback_data=f"send_gender:{g}"
        )

    kb = InlineKeyboardMarkup([
        [g_btn("Erkak", "👨 Erkak"), g_btn("Ayol", "👩 Ayol")],
        [InlineKeyboardButton("👥 Ikkalasi ham", callback_data="send_gender:all")],
        [InlineKeyboardButton("✅ Yuborish", callback_data="send_gender:next")],
        [BACK_BTN],
    ])
    await query.edit_message_reply_markup(reply_markup=kb)


async def _send_survey_to_all(query, ctx, survey_id: int):
    """Hammaga yuborish — filtr yo'q."""
    user_ids = await get_all_user_ids()
    await _do_send_survey(
        query, ctx, survey_id,
        faculties=None, courses=None, genders=None,
        user_ids=user_ids,
    )


async def _do_send_survey(query, ctx, survey_id: int,
                           faculties, courses, genders, user_ids=None):
    """
    Faqat filtrga mos foydalanuvchilarga yuboradi.
    user_ids berilsa — bevosita shu ro'yxatdan foydalanadi (hammaga yuborish).
    faculties/courses/genders None bo'lsa — filtrlanmaydi.
    """
    if user_ids is None:
        # Faqat tanlangan filtrlar bo'yicha qidirish
        fac_filter = faculties if faculties else None
        course_filter = courses if courses else None
        gender_filter = genders if genders else None
        logger.info("FILTER: faculties=%s courses=%s genders=%s", fac_filter, course_filter, gender_filter)
        user_ids = await get_users_by_filter(
            faculties=fac_filter,
            courses=course_filter,
            genders=gender_filter,
        )
        logger.info("FILTER RESULT: %d users found", len(user_ids))

    survey = await get_survey(survey_id)
    if not survey:
        await query.edit_message_text("❌ So'rovnoma topilmadi.")
        return

    # Filtr ma'lumoti
    filter_lines = []
    if faculties:
        filter_lines.append(f"🏫 {', '.join(faculties)}")
    if courses:
        filter_lines.append(f"📚 {', '.join(courses)}")
    if genders:
        filter_lines.append(f"👤 {', '.join(genders)}")
    filter_info = "\n".join(filter_lines) if filter_lines else "🌍 Barcha foydalanuvchilar"

    if not user_ids:
        await query.edit_message_text(
            f"⚠️ <b>Foydalanuvchi topilmadi!</b>\n\n"
            f"{filter_info}\n\n"
            "Bu filtrlarga mos ro'yxatdan o'tgan foydalanuvchi yo'q.",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Ortga", callback_data=f"adm_sv:{survey_id}")],
                [BACK_BTN],
            ])
        )
        return

    await query.edit_message_text(
        f"📤 <b>Yuborilmoqda...</b>\n\n"
        f"{filter_info}\n\n"
        f"👥 Topildi: <b>{len(user_ids)}</b> ta foydalanuvchi",
        parse_mode=ParseMode.HTML,
    )

    # Chiroyli xabar
    msg_text = (
        f"📊 <b>Yangi so'rovnoma!</b>\n\n"
        f"📌 <b>{survey['title']}</b>\n"
    )
    if survey.get("description"):
        msg_text += f"📝 <i>{survey['description']}</i>\n"
    q_count = len(survey.get("questions", []))
    msg_text += (
        f"\n❓ Savollar: <b>{q_count}</b> ta\n"
        f"🔒 <i>Javoblar mutloq anonim</i>\n\n"
        f"Ishtirok etish uchun quyidagi tugmani bosing 👇"
    )

    sent = 0
    failed = 0
    bot = ctx.bot
    for uid in user_ids:
        try:
            await bot.send_message(
                chat_id=uid,
                text=msg_text,
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("▶️ So'rovnomani boshlash", callback_data=f"sv_start:{survey_id}")]
                ])
            )
            sent += 1
        except Exception as e:
            logger.warning("Yuborib bo'lmadi uid=%d: %s", uid, e)
            failed += 1

    await query.edit_message_text(
        f"✅ <b>Yuborildi!</b>\n\n"
        f"{filter_info}\n\n"
        f"📤 Muvaffaqiyatli: <b>{sent}</b>\n"
        f"❌ Xato: <b>{failed}</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📊 So'rovnomani ko'rish", callback_data=f"adm_sv:{survey_id}")],
            [BACK_BTN],
        ])
    )


# ═══════════════════════════════════════════════════════════
# SO'ROVNOMALAR RO'YXATI
# ═══════════════════════════════════════════════════════════

async def _show_surveys_list(send_fn, ctx):
    surveys = await list_surveys()
    if not surveys:
        await send_fn(
            "📭 Hali so'rovnomalar yo'q.",
            reply_markup=InlineKeyboardMarkup([[BACK_BTN]])
        )
        return

    buttons = []
    for s in surveys:
        icon = "🟢" if s["is_active"] else "🔴"
        label = f"{icon} {s['title']} ({s['question_count']} savol)"
        buttons.append([InlineKeyboardButton(label, callback_data=f"adm_sv:{s['id']}")])
    buttons.append([BACK_BTN])

    await send_fn(
        "📋 <b>Barcha So'rovnomalar:</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(buttons),
    )


@admin_only
async def cb_adm_list(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await _show_surveys_list(query.edit_message_text, ctx)


# ═══════════════════════════════════════════════════════════
# SURVEY PANEL
# ═══════════════════════════════════════════════════════════

@admin_only
async def cb_adm_survey(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    survey_id = int(query.data.split(":")[1])
    await _render_survey_panel(query.edit_message_text, survey_id)


async def _render_survey_panel(send_fn, survey_id: int):
    survey = await get_survey(survey_id)
    if not survey:
        await send_fn("❌ Topilmadi.")
        return

    results = await get_survey_results(survey_id)
    total_res = max((v["total"] for v in results.values()), default=0) if results else 0

    status = "🟢 Faol" if survey["is_active"] else "🔴 Yopilgan"
    text = (
        f"📊 <b>{survey['title']}</b>\n"
        f"{status} | 📅 {survey['created_at'][:16]}\n"
    )
    if survey.get("closed_at"):
        text += f"🔒 Yopildi: {survey['closed_at'][:16]}\n"
    if survey.get("description"):
        text += f"\n📝 <i>{survey['description']}</i>\n"

    text += f"\n❓ Savollar: <b>{len(survey['questions'])}</b> ta\n"
    text += f"👥 Ishtirokchilar: <b>{total_res}</b> ta\n"
    text += f"\n🔗 Ulashing: /s_{survey_id}\n"

    buttons = []
    if survey["is_active"]:
        buttons.append([
            InlineKeyboardButton("🔒 Yopish", callback_data=f"adm_close:{survey_id}"),
            InlineKeyboardButton("📊 Natijalar", callback_data=f"adm_res:{survey_id}"),
        ])
        buttons.append([
            InlineKeyboardButton("🚀 Yuborish", callback_data=f"adm_send_start:{survey_id}"),
        ])
    else:
        buttons.append([
            InlineKeyboardButton("🤖 AI (tez)", callback_data=f"adm_ai:{survey_id}:fast"),
            InlineKeyboardButton("🤖 AI (chuqur)", callback_data=f"adm_ai:{survey_id}:deep"),
        ])
        buttons.append([InlineKeyboardButton("📊 Natijalar", callback_data=f"adm_res:{survey_id}")])
        if survey.get("ai_analysis"):
            buttons.append([InlineKeyboardButton("📄 AI Tahlilni Ko'r", callback_data=f"adm_ai_show:{survey_id}")])

    buttons.append([
        InlineKeyboardButton("✏️ Savollarni tahrirlash", callback_data=f"adm_edit_qs:{survey_id}"),
    ])
    buttons.append([
        InlineKeyboardButton("🗑️ O'chirish", callback_data=f"adm_del_confirm:{survey_id}"),
        InlineKeyboardButton("🔙 Ro'yxat", callback_data="adm_list"),
    ])
    buttons.append([BACK_BTN])

    await send_fn(text, parse_mode=ParseMode.HTML,
                  reply_markup=InlineKeyboardMarkup(buttons))


# ═══════════════════════════════════════════════════════════
# SAVOLLARNI TAHRIRLASH VA O'CHIRISH
# ═══════════════════════════════════════════════════════════

async def _show_edit_surveys(send_fn):
    surveys = await list_surveys()
    if not surveys:
        await send_fn("📭 Hali so'rovnomalar yo'q.")
        return
    buttons = []
    for s in surveys:
        icon = "🟢" if s["is_active"] else "🔴"
        buttons.append([InlineKeyboardButton(
            f"{icon} {s['title']}", callback_data=f"adm_edit_qs:{s['id']}"
        )])
    buttons.append([BACK_BTN])
    await send_fn(
        "✏️ <b>Tahrirlash uchun so'rovnoma tanlang:</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(buttons),
    )


@admin_only
async def cb_adm_edit_questions(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    survey_id = int(query.data.split(":")[1])
    await _render_edit_questions(query.edit_message_text, survey_id)


async def _render_edit_questions(send_fn, survey_id: int):
    survey = await get_survey(survey_id)
    if not survey:
        await send_fn("❌ Topilmadi.")
        return

    qs = survey["questions"]
    if not qs:
        await send_fn(
            "❌ Bu so'rovnomada savollar yo'q.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Ortga", callback_data=f"adm_sv:{survey_id}")
            ]])
        )
        return

    type_icons = {"single": "🔘", "multi": "☑️", "text": "✍️"}
    text = f"✏️ <b>Savollarni tahrirlash</b>\n<i>{survey['title']}</i>\n\n"
    buttons = []
    for q in qs:
        icon = type_icons.get(q.get("q_type", "single"), "🔘")
        short_q = q["question"][:35] + ("..." if len(q["question"]) > 35 else "")
        text += f"{icon} {short_q}\n"
        buttons.append([
            InlineKeyboardButton(f"✏️ {short_q}", callback_data=f"adm_edit_q:{q['id']}:{survey_id}"),
            InlineKeyboardButton("🗑️", callback_data=f"adm_del_q:{q['id']}:{survey_id}"),
        ])

    buttons.append([InlineKeyboardButton("🔙 Ortga", callback_data=f"adm_sv:{survey_id}")])
    buttons.append([BACK_BTN])

    await send_fn(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(buttons))


@admin_only
async def cb_adm_del_question(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split(":")
    q_id = int(parts[1])
    survey_id = int(parts[2])
    await delete_question(q_id)
    await query.answer("🗑️ Savol o'chirildi!", show_alert=True)
    await _render_edit_questions(query.edit_message_text, survey_id)


# ═══════════════════════════════════════════════════════════
# NATIJALAR
# ═══════════════════════════════════════════════════════════

@admin_only
async def cb_adm_results(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    survey_id = int(query.data.split(":")[1])
    survey = await get_survey(survey_id)
    results = await get_survey_results(survey_id)

    if not results:
        await query.edit_message_text(
            "📭 Hali javoblar yo'q.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Ortga", callback_data=f"adm_sv:{survey_id}")
            ]])
        )
        return

    text = f"📊 <b>{survey['title']}</b> — Batafsil Natijalar\n\n"
    for qdata in results.values():
        total = qdata["total"]
        text += f"❓ <b>{qdata['question']}</b>\n"
        text += f"<i>Jami: {total} javob</i>\n"
        if qdata.get("q_type") == "text":
            answers = qdata.get("text_answers", [])
            for a in answers[:10]:
                text += f"  ✍️ {a}\n"
            if len(answers) > 10:
                text += f"  <i>...va yana {len(answers)-10} ta</i>\n"
        else:
            for i, opt in enumerate(qdata["options"]):
                cnt = qdata["counts"].get(i, 0)
                pct = round(cnt / total * 100, 1) if total else 0
                bar = pbar(pct)
                text += f"[{bar}] {pct}%  {opt}  (<b>{cnt}</b>)\n"
        text += "\n"

    buttons = [
        [InlineKeyboardButton("🔙 Ortga", callback_data=f"adm_sv:{survey_id}")],
        [BACK_BTN],
    ]
    await query.edit_message_text(text, parse_mode=ParseMode.HTML,
                                   reply_markup=InlineKeyboardMarkup(buttons))


# ═══════════════════════════════════════════════════════════
# CLOSE / DELETE
# ═══════════════════════════════════════════════════════════

@admin_only
async def cb_adm_close(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await close_survey(int(query.data.split(":")[1]))
    await query.answer("✅ So'rovnoma yopildi.", show_alert=True)
    await _render_survey_panel(query.edit_message_text, int(query.data.split(":")[1]))


@admin_only
async def cb_adm_del_confirm(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    survey_id = int(query.data.split(":")[1])
    survey = await get_survey(survey_id)
    await query.edit_message_text(
        f"⚠️ <b>Tasdiqlang</b>\n\n«{survey['title']}» va barcha javoblar o'chiriladi.",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Ha, o'chir", callback_data=f"adm_del_yes:{survey_id}"),
            InlineKeyboardButton("❌ Bekor", callback_data=f"adm_sv:{survey_id}"),
        ]])
    )


@admin_only
async def cb_adm_del_yes(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await delete_survey(int(query.data.split(":")[1]))
    await query.edit_message_text(
        "🗑️ So'rovnoma o'chirildi.",
        reply_markup=InlineKeyboardMarkup([[BACK_BTN]])
    )


# ═══════════════════════════════════════════════════════════
# AI TAHLIL
# ═══════════════════════════════════════════════════════════

@admin_only
async def cb_adm_ai(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("🤖 AI tahlil boshlandi...")
    parts = query.data.split(":")
    survey_id = int(parts[1])
    mode = parts[2] if len(parts) > 2 else "fast"

    await query.edit_message_text(
        "⏳ <b>AI tahlil amalga oshirilmoqda...</b>",
        parse_mode=ParseMode.HTML
    )

    analysis = await analyze_survey(survey_id, use_secondary=(mode == "deep"))
    survey = await get_survey(survey_id)
    text = format_analysis(analysis, survey["title"] if survey else "")

    await query.edit_message_text(text, parse_mode=ParseMode.HTML,
                                   reply_markup=InlineKeyboardMarkup([
                                       [InlineKeyboardButton("🔙 Ortga", callback_data=f"adm_sv:{survey_id}")],
                                       [BACK_BTN],
                                   ]))


@admin_only
async def cb_adm_ai_show(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    survey_id = int(query.data.split(":")[1])
    survey = await get_survey(survey_id)
    analysis = survey.get("ai_analysis") if survey else None

    if not analysis:
        await query.answer("❌ AI tahlil topilmadi.", show_alert=True)
        return

    text = format_analysis(analysis, survey["title"])
    await query.edit_message_text(text, parse_mode=ParseMode.HTML,
                                   reply_markup=InlineKeyboardMarkup([
                                       [InlineKeyboardButton("🔙 Ortga", callback_data=f"adm_sv:{survey_id}")],
                                       [BACK_BTN],
                                   ]))


# ═══════════════════════════════════════════════════════════
# STATISTIKA
# ═══════════════════════════════════════════════════════════

async def _show_stats(send_fn):
    surveys = await list_surveys()
    total_resp = 0
    max_sv, max_sv_n = None, 0
    for s in surveys:
        res = await get_survey_results(s["id"])
        n = max((v["total"] for v in res.values()), default=0) if res else 0
        total_resp += n
        if n > max_sv_n:
            max_sv_n = n
            max_sv = s["title"]

    text = (
        "📈 <b>Umumiy Statistika</b>\n\n"
        f"📊 Jami so'rovnomalar: <b>{len(surveys)}</b>\n"
        f"🟢 Faol: <b>{sum(1 for s in surveys if s['is_active'])}</b>\n"
        f"🔴 Yopilgan: <b>{sum(1 for s in surveys if not s['is_active'])}</b>\n"
        f"🗳️ Jami ishtiroklar: <b>~{total_resp}</b>\n"
    )
    if max_sv:
        text += f"\n🏆 Eng faol: <b>{max_sv}</b> ({max_sv_n} ta)\n"

    await send_fn(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([[BACK_BTN]])
    )


@admin_only
async def cb_adm_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await _show_stats(query.edit_message_text)


# ═══════════════════════════════════════════════════════════
# ADMIN QO'SHISH
# ═══════════════════════════════════════════════════════════

ADD_ADMIN_STATE = 50


async def _start_add_admin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👥 <b>Yangi Admin Qo'shish</b>\n\n"
        "Yangi adminning Telegram <b>user ID</b> raqamini yuboring:\n\n"
        "<i>ID ni bilish uchun @userinfobot ga /start yozing</i>\n\n"
        "/cancel — bekor qilish",
        parse_mode=ParseMode.HTML,
        reply_markup=ReplyKeyboardRemove(),
    )
    return ADD_ADMIN_STATE


async def cv_add_admin_id(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    try:
        new_admin_id = int(text)
    except ValueError:
        await update.message.reply_text("⚠️ Noto'g'ri ID. Faqat raqam kiriting:")
        return ADD_ADMIN_STATE

    added_by = update.effective_user.id
    await add_admin(new_admin_id, added_by)

    await update.message.reply_text(
        f"✅ <b>Admin qo'shildi!</b>\n\n"
        f"🆔 ID: <code>{new_admin_id}</code>",
        parse_mode=ParseMode.HTML,
        reply_markup=ADMIN_MAIN_KB,
    )
    return ConversationHandler.END


async def cv_add_admin_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Bekor qilindi.", reply_markup=ADMIN_MAIN_KB)
    return ConversationHandler.END


# ═══════════════════════════════════════════════════════════
# ConversationHandler — So'rovnoma yaratish
# ═══════════════════════════════════════════════════════════

def build_create_conv() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[
            CallbackQueryHandler(lambda u, c: _start_create_survey_cb(u, c), pattern="^adm_create$"),
            MessageHandler(
                filters.Regex("^➕ Yangi So'rovnoma$"),
                _start_create_survey
            ),
        ],
        states={
            CV_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, cv_title)],
            CV_DESC: [
                CommandHandler("skip", cv_skip_desc),
                MessageHandler(filters.TEXT & ~filters.COMMAND, cv_desc),
            ],
            CV_Q_TYPE: [
                CallbackQueryHandler(cv_q_more, pattern="^qtype:more$"),
                CallbackQueryHandler(cv_q_type_chosen, pattern="^qtype:(single|multi|text|done)$"),
            ],
            CV_Q_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, cv_q_text)],
            CV_Q_OPTIONS: [MessageHandler(filters.TEXT & ~filters.COMMAND, cv_q_options)],
            CV_CONFIRM: [CallbackQueryHandler(cv_confirm, pattern="^cv_confirm_(yes|no)$")],
        },
        fallbacks=[
            CommandHandler("cancel", cv_cancel),
            CallbackQueryHandler(cv_cancel, pattern="^adm_create_cancel$"),
        ],
        per_user=True,
        per_chat=True,
        per_message=False,
    )


async def _start_create_survey_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Callback query orqali yaratishni boshlash."""
    query = update.callback_query
    await query.answer()
    ctx.user_data.clear()
    ctx.user_data["new_sv"] = {"questions": []}
    await query.edit_message_text(
        "➕ <b>Yangi So'rovnoma</b>\n\n"
        "1️⃣ So'rovnoma <b>sarlavhasini</b> kiriting:\n\n"
        "<i>Bekor qilish: /cancel</i>",
        parse_mode=ParseMode.HTML,
    )
    return CV_TITLE


def build_add_admin_conv() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex("^👥 Admin qo'shish$"), _start_add_admin),
        ],
        states={
            ADD_ADMIN_STATE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, cv_add_admin_id),
            ],
        },
        fallbacks=[CommandHandler("cancel", cv_add_admin_cancel)],
        per_user=True,
        per_chat=True,
        per_message=False,
    )
