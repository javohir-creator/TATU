#!/bin/bash
# Bot ishga tushirish va avtomatik qayta ishga tushirish skripti

cd /home/ubuntu/anonim-voting

echo "📦 Kutubxonalar o'rnatilmoqda..."
pip install -r requirements.txt -q

echo "🚀 Bot ishga tushirilmoqda..."
while true; do
    python bot.py
    echo "⚠️ Bot to'xtadi. 5 soniyadan so'ng qayta ishga tushiriladi..."
    sleep 5
done
