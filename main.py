import os
import time
import math
import csv
import pandas as pd
from datetime import datetime, timedelta
from binance.client import Client
from ta.momentum import RSIIndicator
from ta.trend import EMAIndicator, ADXIndicator
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv("BINANCE_API_KEY")
api_secret = os.getenv("BINANCE_API_SECRET")

print("✅ Боевой бот стартовал!")
print("🔐 API_KEY (первые символы):", api_key[:5], "...")
print("🔐 API_SECRET (первые символы):", api_secret[:5], "...")

client = Client(api_key, api_secret)
client.FUTURES_URL = 'https://testnet.binancefuture.com/fapi'

# Получаем точности округления для каждой монеты
symbol_precisions = {}
try:
    exchange_info = client.futures_exchange_info()
    for symbol_info in exchange_info['symbols']:
        symbol = symbol_info['symbol']
        for f in symbol_info['filters']:
            if f['filterType'] == 'LOT_SIZE':
                step_size = float(f['stepSize'])
                precision = int(round(-math.log(step_size, 10), 0))
                symbol_precisions[symbol] = precision
except Exception as e:
    print("❌ Ошибка при получении информации о бирже:", e)

symbols = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "AVAXUSDT",
    "LINKUSDT", "INJUSDT", "APTUSDT", "SUIUSDT",
    "XRPUSDT", "NEARUSDT", "OPUSDT", "LDOUSDT", "FTMUSDT"
]

INTERVAL = Client.KLINE_INTERVAL_15MINUTE
LIMIT = 100

def analyze_and_trade(symbol):
    try:
        print(f"▶️ Начинаю анализ: {symbol}")

        open_orders = client.futures_get_open_orders(symbol=symbol)
        tp_orders = [o for o in open_orders if o['type'] == "TAKE_PROFIT_MARKET"]
        sl_orders = [o for o in open_orders if o['type'] == "STOP_MARKET"]

        positions = client.futures_position_information(symbol=symbol)
        position = next((p for p in positions if float(p['positionAmt']) != 0), None)

        if position is None and (tp_orders or sl_orders):
            for o in open_orders:
                client.futures_cancel_order(symbol=symbol, orderId=o['orderId'])
            print(f"🧹 {symbol}: Позиции нет, но TP/SL были — всё очищено")
            return

        if position:
            entry_price = float(position['entryPrice'])
            side = 'LONG' if float(position['positionAmt']) > 0 else 'SHORT'

            if len(tp_orders) + len(sl_orders) > 2:
                for o in open_orders:
                    client.futures_cancel_order(symbol=symbol, orderId=o['orderId'])
                print(f"❌ {symbol}: Найдено дублирование TP/SL, всё очищено")

            elif len(tp_orders) == 0 or len(sl_orders) == 0:
                for o in open_orders:
                    client.futures_cancel_order(symbol=symbol, orderId=o['orderId'])

                if side == 'LONG':
                    stop_loss = round(entry_price * 0.99, 2)
                    take_profit = round(entry_price * 1.05, 2)
                    client.futures_create_order(
                        symbol=symbol,
                        side="SELL",
                        type="TAKE_PROFIT_MARKET",
                        stopPrice=take_profit,
                        closePosition=True,
                        timeInForce='GTC',
                        workingType='MARK_PRICE'
                    )
                    client.futures_create_order(
                        symbol=symbol,
                        side="SELL",
                        type="STOP_MARKET",
                        stopPrice=stop_loss,
                        closePosition=True,
                        timeInForce='GTC',
                        workingType='MARK_PRICE'
                    )
                    print(f"🔁 {symbol}: TP/SL восстановлены для LONG")
                else:
                    stop_loss = round(entry_price * 1.01, 2)
                    take_profit = round(entry_price * 0.95, 2)
                    client.futures_create_order(
                        symbol=symbol,
                        side="BUY",
                        type="TAKE_PROFIT_MARKET",
                        stopPrice=take_profit,
                        closePosition=True,
                        timeInForce='GTC',
                        workingType='MARK_PRICE'
                    )
                    client.futures_create_order(
                        symbol=symbol,
                        side="BUY",
                        type="STOP_MARKET",
                        stopPrice=stop_loss,
                        closePosition=True,
                        timeInForce='GTC',
                        workingType='MARK_PRICE'
                    )
                    print(f"🔁 {symbol}: TP/SL восстановлены для SHORT")
            else:
                print(f"⏸ {symbol}: Позиция уже открыта, TP/SL в порядке")
            return

        klines = client.futures_klines(symbol=symbol, interval=INTERVAL, limit=LIMIT)
        df = pd.DataFrame(klines, columns=[
            "timestamp", "open", "high", "low", "close", "volume",
            "close_time", "quote_asset_volume", "number_of_trades",
            "taker_buy_base_vol", "taker_buy_quote_vol", "ignore"])

        df[["open", "high", "low", "close"]] = df[["open", "high", "low", "close"]].astype(float)
        df['rsi'] = RSIIndicator(df['close']).rsi()
        df['ema20'] = EMAIndicator(df['close'], window=20).ema_indicator()
        df['ema50'] = EMAIndicator(df['close'], window=50).ema_indicator()
        df['adx'] = ADXIndicator(df['high'], df['low'], df['close']).adx()

        latest = df.iloc[-1]
        price = latest['close']
        low = df['close'].iloc[-20:].min()
        high = df['close'].iloc[-20:].max()
        rsi = latest['rsi']
        ema20 = latest['ema20']
        ema50 = latest['ema50']
        adx = latest['adx']

        qty_raw = 100 / price
        prec = symbol_precisions.get(symbol, 2)
        qty = math.floor(qty_raw * 10**prec) / 10**prec

        if adx < 25 and price <= low * 1.01 and rsi < 40 and price < ema20 < ema50:
            stop_loss = round(price * 0.99, 2)
            take_profit = round(price * 1.05, 2)
            client.futures_create_order(
                symbol=symbol,
                side="BUY",
                type="MARKET",
                quantity=qty
            )
            client.futures_create_order(
                symbol=symbol,
                side="SELL",
                type="TAKE_PROFIT_MARKET",
                stopPrice=take_profit,
                closePosition=True,
                timeInForce='GTC',
                workingType='MARK_PRICE'
            )
            client.futures_create_order(
                symbol=symbol,
                side="SELL",
                type="STOP_MARKET",
                stopPrice=stop_loss,
                closePosition=True,
                timeInForce='GTC',
                workingType='MARK_PRICE'
            )
            print(f"✅ {symbol} | ЛОНГ | Цена: {price} | Qty: {qty} | TP: {take_profit} | SL: {stop_loss}")

        elif adx < 25 and price >= high * 0.99 and rsi > 60 and price > ema20 > ema50:
            stop_loss = round(price * 1.01, 2)
            take_profit = round(price * 0.95, 2)
            client.futures_create_order(
                symbol=symbol,
                side="SELL",
                type="MARKET",
                quantity=qty
            )
            client.futures_create_order(
                symbol=symbol,
                side="BUY",
                type="TAKE_PROFIT_MARKET",
                stopPrice=take_profit,
                closePosition=True,
                timeInForce='GTC',
                workingType='MARK_PRICE'
            )
            client.futures_create_order(
                symbol=symbol,
                side="BUY",
                type="STOP_MARKET",
                stopPrice=stop_loss,
                closePosition=True,
                timeInForce='GTC',
                workingType='MARK_PRICE'
            )
            print(f"✅ {symbol} | ШОРТ | Цена: {price} | Qty: {qty} | TP: {take_profit} | SL: {stop_loss}")

        else:
            print(f"{symbol}: Условия не выполнены")

    except Exception as e:
        print(f"❌ Ошибка при анализе {symbol}: {type(e).__name__} — {e}")


def log_pnl():
    try:
        start_time = int((datetime.now() - timedelta(minutes=15)).timestamp() * 1000)
        income = client.futures_income_history(startTime=start_time, incomeType="REALIZED_PNL")
        if not income:
            print("📭 Нет новых закрытых позиций")
            return
        
        total_pnl = 0
        file_exists = os.path.isfile("pnl_log.csv")
        with open("pnl_log.csv", mode="a", newline='') as file:
            writer = csv.writer(file)
            if not file_exists:
                writer.writerow(["Time", "Symbol", "PnL"])
            for record in income:
                ts = datetime.fromtimestamp(record['time'] / 1000).strftime('%Y-%m-%d %H:%M:%S')
                symbol = record['symbol']
                pnl = float(record['income'])
                total_pnl += pnl
                writer.writerow([ts, symbol, pnl])
                print(f"💸 {symbol} | PnL: {pnl:.2f} USDT")
        
        print(f"\n💰 Общий результат за 15 мин: {round(total_pnl, 2)} USDT")

    except Exception as e:
        print(f"❌ Ошибка при логировании PnL: {e}")


while True:
    print(f"\n🕒 Анализ монет ({datetime.now().strftime('%H:%M:%S')}):")
    for symbol in symbols:
        analyze_and_trade(symbol)
        time.sleep(1)
    log_pnl()
    time.sleep(60)
