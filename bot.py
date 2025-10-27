import asyncio
import os
from dotenv import load_dotenv
import pandas as pd
import aiohttp
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# Ortam değişkenlerini yükle
load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
TEST_MODE = os.getenv("TEST_MODE", "False").lower() == "true"

# Genel ayarlar
CHECK_INTERVAL = 60  # saniye (canlı kullanımda 1800 gibi)
FUNDING_THRESHOLD = 0.5  # %0.5 üzerinde funding sinyal için eşik
RSI_PERIOD = 14

# Binance USDT Futures tüm sembolleri çekmek için endpoint
BINANCE_FUTURES_SYMBOLS_URL = "https://fapi.binance.com/fapi/v1/exchangeInfo"

# Komutlar
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ Funding & RSI Bot aktif! Bildirimleri buradan alacaksınız.")

# Test mesajı gönderme
async def test_message(app):
    try:
        await app.bot.send_message(chat_id=CHAT_ID, text="✅ Test mesajı: Bot Telegram’a mesaj atabiliyor!")
        print("Telegram test mesajı gönderildi.")
    except Exception as e:
        print("Telegram mesaj hatası:", e)

# RSI hesaplama
def calculate_rsi(series, period=RSI_PERIOD):
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(window=period).mean()
    avg_loss = loss.rolling(window=period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

# Tüm USDT futures coinlerini çek
async def get_all_symbols(session):
    async with session.get(BINANCE_FUTURES_SYMBOLS_URL) as resp:
        data = await resp.json()
        symbols = [s["symbol"] for s in data["symbols"] if s["quoteAsset"] == "USDT" and s["status"] == "TRADING"]
        return symbols

# RSI ve funding verisi çek
async def fetch_data(session, symbol):
    try:
        # Funding rate
        url_fr = f"https://fapi.binance.com/fapi/v1/fundingRate?symbol={symbol}&limit=1"
        async with session.get(url_fr) as resp:
            fr_data = await resp.json()
            funding_rate = float(fr_data[0]["fundingRate"]) * 100  # % formatında
            funding_time = pd.to_datetime(fr_data[0]["fundingTime"], unit='ms')

        # RSI 1m, 5m, 15m
        rsi_values = {}
        for interval in ["1m", "5m", "15m"]:
            url_klines = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval={interval}&limit=100"
            async with session.get(url_klines) as resp:
                klines = await resp.json()
                closes = pd.Series([float(k[4]) for k in klines])
                rsi_values[interval] = calculate_rsi(closes).iloc[-1]

        return symbol, funding_rate, funding_time, rsi_values
    except Exception as e:
        print(f"{symbol} verisi alınamadı: {e}")
        return symbol, None, None, None

# Sinyal kontrolü
async def check_symbols(app):
    async with aiohttp.ClientSession() as session:
        symbols = await get_all_symbols(session)
        for symbol in symbols:
            s, fr, ft, rsi_dict = await fetch_data(session, symbol)
            if fr is None or rsi_dict is None:
                continue

            rsi_text = "\n".join([f"{k} RSI: {v:.2f}" for k, v in rsi_dict.items()])
            text = f"💹 {s}\nFunding: {fr:.4f}%\nNext Funding: {ft}\n{rsi_text}"

            # Sinyal: tüm RSI’lar 70 üzerindeyse ve funding rate eşik üstünde
            if fr > FUNDING_THRESHOLD and all(v > 70 for v in rsi_dict.values()):
                text += "\n⚠️ AŞIRI LONG yönlü baskı!"
            elif fr < -FUNDING_THRESHOLD and all(v < 30 for v in rsi_dict.values()):
                text += "\n⚠️ AŞIRI SHORT yönlü baskı!"

            print(text)
            await app.bot.send_message(chat_id=CHAT_ID, text=text)

# Ana fonksiyon
async def main():
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    print("🚀 Bot aktif, /start yazabilirsiniz Telegram’da!")

    # Telegram test mesajı
    await test_message(app)

    if TEST_MODE:
        print("🧪 Test modu açık: yalnızca bir kez veri çekilecek...")
        await check_symbols(app)
    else:
        while True:
            await check_symbols(app)
            await asyncio.sleep(CHECK_INTERVAL)

# Çalıştır
if __name__ == "__main__":
    asyncio.run(main())
