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
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
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

async def main():
    """Botni ishga tushirish (Python 3.10+ async uslubida)"""
    
    if not BOT_TOKEN:
        logger.error("❌ BOT_TOKEN muhit o'zgaruvchisi topilmadi!")
        return

    # Application qurish
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    # --- Handlerlarni ro'yxatga olish ---
    app.add_handler(build_create_conv())
    app.add_handler(build_add_admin_conv())
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("surveys", cmd_surveys))
    app.add_handler(CommandHandler("about", cmd_about))
    app.add_handler(CommandHandler("admin", cmd_admin))
    app.add_handler(MessageHandler(filters.Regex(r"^/s_\d+"), cmd_survey_link))
    app.add_handler(PollAnswerHandler(handle_poll_answer))
    
    # Callbacklar
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

    # Admin Menu va Matnli javoblar
    app.add_handler(MessageHandler(
        filters.Regex(r"^(➕ Yangi So'rovnoma|📋 So'rovnomalar|📊 Statistika|✏️ Savollarni tahrirlash)$"),
        handle_admin_menu,
    ))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_answer))

    # --- Ishga tushirish tartibi ---
    if WEBHOOK_URL:
        logger.info(f"🌐 Webhook rejimida ishga tushmoqda: {WEBHOOK_URL}")
        await app.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=BOT_TOKEN,
            webhook_url=f"{WEBHOOK_URL}/{BOT_TOKEN}",
            drop_pending_updates=True
        )
    else:
        logger.info("🔄 Polling rejimida ishga tushmoqda...")
        # Pollingni async muhitda xavfsiz ishga tushirish
        async with app:
            await app.updater.start_polling(drop_pending_updates=True)
            await app.start()
            # Bot to'xtab qolmasligi uchun
            await asyncio.Event().wait()

if __name__ == "__main__":
    try:
        # Python 3.10+ uchun asosiy ishga tushirish nuqtasi
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot to'xtatildi.")
