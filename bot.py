"""
Asosiy bot fayli — Webhook rejimi (Render uchun moslangan)
"""

import logging
import os
import asyncio
from telegram import BotCommand
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, PollAnswerHandler, filters,
)

# Handlerlarni import qilish
from database import init_db
from user_handlers import (
    cmd_start, cmd_surveys, cmd_about, cmd_survey_link,
    cb_sv_info, cb_sv_start, cb_sv_results, cb_sv_ai, cb_sv_list,
    handle_poll_answer, handle_text_answer,
    cb_reg_faculty, cb_reg_course, cb_reg_gender,
)
from admin_handlers import (
    cmd_admin,
    cb_adm_home, cb_adm_list, cb_adm_survey,
    cb_adm_results, cb_adm_close,
    cb_adm_ai, cb_adm_ai_show,
    cb_adm_del_confirm, cb_adm_del_yes,
    cb_adm_stats,
    cb_adm_send_start, cb_send_fac, cb_send_course, cb_send_gender,
    cb_adm_edit_questions, cb_adm_del_question,
    handle_admin_menu,
    build_create_conv, build_add_admin_conv,
)

# Logging sozlamalari
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

# Muhit o'zgaruvchilari (Render Environment Variables dan olinadi)
BOT_TOKEN = os.getenv("BOT_TOKEN", "8543327422:AAGmnW9mTBsMUsQD1pw8j4iwsh9vY3ms8_E")
ADMIN_ID = os.getenv("ADMIN_ID", "1959567617")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # Masalan: https://sizning-botingiz.onrender.com
PORT = int(os.getenv("PORT", 8443))

async def post_init(app: Application):
    await init_db()
    logger.info("✅ Database tayyor.")
    await app.bot.set_my_commands([
        BotCommand("start",   "Botni boshlash"),
        BotCommand("surveys", "Faol so'rovnomalar"),
        BotCommand("about",   "Bot haqida"),
        BotCommand("admin",   "Admin panel"),
        BotCommand("cancel",  "Bekor qilish"),
        BotCommand("skip",    "O'tkazib yuborish"),
    ])
    logger.info("✅ Bot buyruqlari sozlandi.")

def main():
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN topilmadi!")
        return

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    # ── 1. ConversationHandlers ──
    app.add_handler(build_create_conv())
    app.add_handler(build_add_admin_conv())

    # ── 2. Foydalanuvchi komandalar ──
    app.add_handler(CommandHandler("start",   cmd_start))
    app.add_handler(CommandHandler("surveys", cmd_surveys))
    app.add_handler(CommandHandler("about",   cmd_about))

    # ── 3. Admin komandalar ──
    app.add_handler(CommandHandler("admin",  cmd_admin))
    app.add_handler(CommandHandler("cancel", lambda u, c: None))

    # ── 4. /s_N direct link ──
    app.add_handler(MessageHandler(filters.Regex(r"^/s_\d+"), cmd_survey_link))

    # ── 5. PollAnswer ──
    app.add_handler(PollAnswerHandler(handle_poll_answer))

    # ── 6. Ro'yxatdan o'tish callback-lar ──
    app.add_handler(CallbackQueryHandler(cb_reg_faculty, pattern=r"^reg_fac:\d+$"))
    app.add_handler(CallbackQueryHandler(cb_reg_course,  pattern=r"^reg_course:.+$"))
    app.add_handler(CallbackQueryHandler(cb_reg_gender,  pattern=r"^reg_gender:.+$"))

    # ── 7. Foydalanuvchi callback-lar ──
    app.add_handler(CallbackQueryHandler(cb_sv_info,     pattern=r"^sv_info:\d+$"))
    app.add_handler(CallbackQueryHandler(cb_sv_start,    pattern=r"^sv_start:\d+$"))
    app.add_handler(CallbackQueryHandler(cb_sv_results,  pattern=r"^sv_results:\d+$"))
    app.add_handler(CallbackQueryHandler(cb_sv_ai,       pattern=r"^sv_ai:\d+$"))
    app.add_handler(CallbackQueryHandler(cb_sv_list,     pattern=r"^sv_list$"))

    # ── 8. Admin callback-lar ──
    app.add_handler(CallbackQueryHandler(cb_adm_home,        pattern=r"^adm_home$"))
    app.add_handler(CallbackQueryHandler(cb_adm_list,        pattern=r"^adm_list$"))
    app.add_handler(CallbackQueryHandler(cb_adm_survey,      pattern=r"^adm_sv:\d+$"))
    app.add_handler(CallbackQueryHandler(cb_adm_results,     pattern=r"^adm_res:\d+$"))
    app.add_handler(CallbackQueryHandler(cb_adm_close,       pattern=r"^adm_close:\d+$"))
    app.add_handler(CallbackQueryHandler(cb_adm_ai,          pattern=r"^adm_ai:\d+:(fast|deep)$"))
    app.add_handler(CallbackQueryHandler(cb_adm_ai_show,     pattern=r"^adm_ai_show:\d+$"))
    app.add_handler(CallbackQueryHandler(cb_adm_del_confirm, pattern=r"^adm_del_confirm:\d+$"))
    app.add_handler(CallbackQueryHandler(cb_adm_del_yes,      pattern=r"^adm_del_yes:\d+$"))
    app.add_handler(CallbackQueryHandler(cb_adm_stats,       pattern=r"^adm_stats$"))

    # ── 9. Test yuborish callback-lar ──
    app.add_handler(CallbackQueryHandler(cb_adm_send_start, pattern=r"^adm_send_start:\d+$"))
    app.add_handler(CallbackQueryHandler(cb_send_fac,       pattern=r"^send_fac:.+$"))
    app.add_handler(CallbackQueryHandler(cb_send_course,    pattern=r"^send_course:.+$"))
    app.add_handler(CallbackQueryHandler(cb_send_gender,    pattern=r"^send_gender:.+$"))

    # ── 10. Tahrirlash callback-lar ──
    app.add_handler(CallbackQueryHandler(cb_adm_edit_questions, pattern=r"^adm_edit_qs:\d+$"))
    app.add_handler(CallbackQueryHandler(cb_adm_del_question,   pattern=r"^adm_del_q:\d+:\d+$"))

    # ── 11. Admin Reply Keyboard menyusi ──
    app.add_handler(MessageHandler(
        filters.Regex(r"^(➕ Yangi So'rovnoma|📋 So'rovnomalar|📊 Statistika|✏️ Savollarni tahrirlash)$"),
        handle_admin_menu,
    ))

    # ── 12. Yozma javoblar ──
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        handle_text_answer,
    ))

    # ── Webhook yoki Polling ──
    if WEBHOOK_URL:
        logger.info(f"🌐 Webhook ishga tushmoqda: {WEBHOOK_URL} Port: {PORT}")
        app.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=BOT_TOKEN,
            webhook_url=f"{WEBHOOK_URL}/{BOT_TOKEN}",
            drop_pending_updates=True
        )
    else:
        logger.info("🔄 Polling rejimida ishga tushmoqda...")
        app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
