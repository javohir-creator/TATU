import logging
import os
import sys
import asyncio
from telegram import BotCommand
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, PollAnswerHandler, filters,
)

# Handlerlarni import qilish
try:
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
except ImportError as e:
    print(f"❌ Import xatosi: {e}. Barcha .py fayllar mavjudligini tekshiring!")
    sys.exit(1)

# Logging sozlamalari
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s — %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# Muhit o'zgaruvchilari
BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # Masalan: https://your-app.onrender.com
PORT = int(os.getenv("PORT", 8080))


async def post_init(app: Application):
    """Baza va menyuni sozlash"""
    await init_db()
    await app.bot.set_my_commands([
        BotCommand("start", "Botni boshlash"),
        BotCommand("surveys", "Faol so'rovnomalar"),
        BotCommand("about", "Bot haqida"),
        BotCommand("admin", "Admin panel"),
    ])
    logger.info("✅ Bot post_init muvaffaqiyatli yakunlandi.")


def register_handlers(app: Application):
    """Barcha handlerlarni ro'yxatga olish"""
    app.add_handler(build_create_conv())
    app.add_handler(build_add_admin_conv())
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("surveys", cmd_surveys))
    app.add_handler(CommandHandler("about", cmd_about))
    app.add_handler(CommandHandler("admin", cmd_admin))
    app.add_handler(MessageHandler(filters.Regex(r"^/s_\d+"), cmd_survey_link))
    app.add_handler(PollAnswerHandler(handle_poll_answer))

    # User callbacklar
    app.add_handler(CallbackQueryHandler(cb_reg_faculty, pattern=r"^reg_fac:\d+$"))
    app.add_handler(CallbackQueryHandler(cb_reg_course, pattern=r"^reg_course:.+$"))
    app.add_handler(CallbackQueryHandler(cb_reg_gender, pattern=r"^reg_gender:.+$"))
    app.add_handler(CallbackQueryHandler(cb_sv_info, pattern=r"^sv_info:\d+$"))
    app.add_handler(CallbackQueryHandler(cb_sv_start, pattern=r"^sv_start:\d+$"))
    app.add_handler(CallbackQueryHandler(cb_sv_results, pattern=r"^sv_results:\d+$"))
    app.add_handler(CallbackQueryHandler(cb_sv_list, pattern=r"^sv_list$"))

    # Admin callbacklar
    app.add_handler(CallbackQueryHandler(cb_adm_home, pattern=r"^adm_home$"))
    app.add_handler(CallbackQueryHandler(cb_adm_list, pattern=r"^adm_list$"))
    app.add_handler(CallbackQueryHandler(cb_adm_survey, pattern=r"^adm_sv:\d+$"))
    app.add_handler(CallbackQueryHandler(cb_adm_results, pattern=r"^adm_res:\d+$"))
    app.add_handler(CallbackQueryHandler(cb_adm_stats, pattern=r"^adm_stats$"))
    app.add_handler(CallbackQueryHandler(cb_adm_send_start, pattern=r"^adm_send_start:\d+$"))

    # Admin menyu va matnli javoblar
    app.add_handler(MessageHandler(
        filters.Regex(r"^(➕ Yangi So'rovnoma|📋 So'rovnomalar|📊 Statistika|✏️ Savollarni tahrirlash)$"),
        handle_admin_menu,
    ))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_answer))


def main():
    """Botni ishga tushirish — Render uchun optimallashtirilgan"""

    if not BOT_TOKEN:
        logger.error("❌ BOT_TOKEN muhit o'zgaruvchisi topilmadi!")
        sys.exit(1)

    # Application qurish
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    # Handlerlarni ro'yxatga olish
    register_handlers(app)

    if WEBHOOK_URL:
        # ✅ RENDER uchun WEBHOOK rejimi (tavsiya etiladi)
        webhook_path = BOT_TOKEN
        full_webhook_url = f"{WEBHOOK_URL.rstrip('/')}/{webhook_path}"

        logger.info(f"🌐 Webhook rejimida ishga tushmoqda...")
        logger.info(f"🔗 Webhook URL: {full_webhook_url}")
        logger.info(f"🚪 Port: {PORT}")

        # run_webhook o'zi asyncio event loop ni boshqaradi
        app.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=webhook_path,
            webhook_url=full_webhook_url,
            drop_pending_updates=True,
            allowed_updates=["message", "callback_query", "poll_answer", "inline_query"],
        )
    else:
        # 🔄 LOCAL ishlab chiqish uchun POLLING rejimi
        logger.info("🔄 Polling rejimida ishga tushmoqda (local mode)...")
        app.run_polling(
            drop_pending_updates=True,
            allowed_updates=["message", "callback_query", "poll_answer", "inline_query"],
        )


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot to'xtatildi.")
    except Exception as e:
        logger.exception(f"❌ Kutilmagan xato: {e}")
        sys.exit(1)
