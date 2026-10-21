import requests
import pandas as pd
import numpy as np
from ta.momentum import RSIIndicator
from ta.volatility import BollingerBands, AverageTrueRange
from ta.trend import MACD, SMAIndicator, ADXIndicator
from ta.volume import OnBalanceVolumeIndicator
from datetime import datetime
import telebot
import schedule
import time
import threading
from flask import Flask

# ==============================================================================
# 1. CONFIGURAÇÃO DA SUA CARTEIRA E CHAVES
# ==============================================================================
PORTFOLIO = {
    "BTC": {
        "coingecko_id": "bitcoin",
        "preco_medio": 67960.90,
        "lote_dca_usd": 100.00,
        "taxa_dex_pct": 0.35
    },
    "ETH": {
        "coingecko_id": "ethereum",
        "preco_medio": 2550.00,
        "lote_dca_usd": 100.00,
        "taxa_dex_pct": 0.35
    }
}

TELEGRAM_BOT_TOKEN = "8659521907:AAGw7rCxoUZxWyDkRYu0mpA-LvuXocCq34Y" 
TELEGRAM_CHAT_ID = "8740599167"

bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)
app = Flask(__name__)

@app.route('/')
def home():
    return "🤖 Copiloto Quant Pro (Coingecko) Rodando 24/7 na Nuvem Render!"

# ==============================================================================
# 2. MOTORES DE DADOS VIA COINGECKO API
# ==============================================================================
def buscar_candles_coingecko(coin_id, days="30"):
    """Busca o histórico de preços diários da Coingecko para calcular os indicadores."""
    url = f"https://api.coingecko.com/api/v3/coins/{coin_id}/market_chart"
    params = {"vs_currency": "usd", "days": days, "interval": "daily"}
    try:
        res = requests.get(url, params=params, timeout=10)
        data = res.json()
        precos = data.get("prices", [])
         volumes = data.get("total_volumes", [])
        
        df_p = pd.DataFrame(precos, columns=["timestamp", "close"])
        df_v = pd.DataFrame(volumes, columns=["timestamp", "volume"])
        
        df = pd.merge(df_p, df_v, on="timestamp")
        df["high"] = df["close"] * 1.015  # Estimativa de alta diária para o ATR/Fibo
        df["low"] = df["close"] * 0.985   # Estimativa de baixa diária
        df["open"] = df["close"]
        
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = df[col].astype(float)
        return df
    except Exception as e:
        print(f"Erro ao buscar dados da Coingecko para {coin_id}: {e}")
        return None

def buscar_sentimento_hyperliquid():
    url = "https://api.hyperliquid.xyz/info"
    headers = {"Content-Type": "application/json"}
    payload = {"type": "metaAndAssetCtxs"}
    sentimento = {}
    try:
        res = requests.post(url, json=payload, headers=headers, timeout=10)
        data = res.json()
        universo = data[0]["universe"]
        contextos = data[1]
        for i, token in enumerate(universo):
            nome = token["name"]
            funding_anualizado = float(contextos[i]["funding"]) * 24 * 365 * 100
            open_interest = float(contextos[i]["openInterest"])
            sentimento[nome] = {
                "funding_anual_pct": funding_anualizado,
                "open_interest": open_interest
            }
        return sentimento
    except Exception:
        return {}

# ==============================================================================
# 3. CÉREBRO QUANTITATIVO PRO
# ==============================================================================
def analisar_ativo(moeda, config, hl_data):
    df = buscar_candles_coingecko(config["coingecko_id"], days="90")
    if df is None or len(df) < 30: 
        return f"Dados insuficientes para {moeda}."

    close = df["close"]
    high = df["high"]
    low = df["low"]
    vol = df["volume"]
    preco_atual = close.iloc[-1]

    rsi = RSIIndicator(close=close, window=14).rsi().iloc[-1]
    bb = BollingerBands(close=close, window=20, window_dev=2)
    bb_sup = bb.bollinger_hband().iloc[-1]
    bb_inf = bb.bollinger_lband().iloc[-1]
    bb_pos = ((preco_atual - bb_inf) / (bb_sup - bb_inf)) * 100 if (bb_sup - bb_inf) > 0 else 50

    macd_obj = MACD(close=close, window_slow=26, window_fast=12, window_sign=9)
    macd_hist = macd_obj.macd_diff().iloc[-1]
    atr = AverageTrueRange(high=high, low=low, close=close, window=14).average_true_range().iloc[-1]

    # Fibonacci Automático
    perna_high = high.max()
    perna_low = low.min()
    diff_fibo = perna_high - perna_low
    fib_618 = perna_high - (diff_fibo * 0.618)

    score = 50
    if rsi < 30: score += 20
    elif rsi > 70: score -= 20
    if bb_pos < 15: score += 15
    elif bb_pos > 85: score -= 15
    if macd_hist > 0: score += 10
    else: score -= 10

    score = max(0, min(100, score))
    lote_base = config["lote_dca_usd"]
    
    if score >= 75: veredito = "🟢 COMPRA FORTE (DCA 2x)"; acao = f"Aportar ${lote_base * 2:.2f}"
    elif score >= 55: veredito = "🟢 ACUMULAR (DCA Padrão)"; acao = f"Aportar ${lote_base:.2f}"
    elif score >= 40: veredito = "🟡 AGUARDAR / NEUTRO"; acao = "Manter caixa"
    else: veredito = "🔴 SOBRECOMPRA / REALIZAR"; acao = "Proteger lucros"

    pm = config["preco_medio"]
    preco_breakeven = pm * (1 + ((config["taxa_dex_pct"] / 100) * 2))
    pnl = ((preco_atual - preco_breakeven) / preco_breakeven) * 100

    return (
        f"🎯 {moeda}/USD (Coingecko) | Preço: ${preco_atual:,.2f}\n"
        f"📊 SCORE: {score}/100 | {veredito}\n"
        f"💡 Ação: {acao}\n"
        f"📐 Zona de Ouro (Fib 0.618): ${fib_618:,.2f}\n"
        f"🛡️ Seu Médio: ${pm:,.2f} | PnL: {pnl:+.2f}%\n"
        f"--------------------------------------------------\n"
    )

def compilar_relatorio_completo():
    hl_sentimento = buscar_sentimento_hyperliquid()
    relatorio = f"🤖 RADAR QUANT PRO (NUVEM COINGECKO)\n\n"
    for moeda, cfg in PORTFOLIO.items():
        relatorio += analisar_ativo(moeda, cfg, hl_sentimento)
    return relatorio

@bot.message_handler(func=lambda message: message.text.lower() == "mercado agora")
def escutar_comando_manual(message):
    bot.reply_to(message, "⏳ Consultando a Coingecko para BTC e ETH...")
    relatorio = compilar_relatorio_completo()
    bot.send_message(message.chat.id, relatorio)

def rotina_automatica():
    relatorio = compilar_relatorio_completo()
    bot.send_message(TELEGRAM_CHAT_ID, "⏰ **ALERTA PROGRAMADO:**\n\n" + relatorio)

def motor_de_agendamento():
    schedule.every().day.at("08:00").do(rotina_automatica)
    schedule.every().day.at("20:00").do(rotina_automatica)
    while True:
        schedule.run_pending()
        time.sleep(30)

def iniciar_background():
    threading.Thread(target=motor_de_agendamento, daemon=True).start()
    bot.infinity_polling(timeout=10, long_polling_timeout=5)

if __name__ == "__main__":
    threading.Thread(target=iniciar_background, daemon=True).start()
    app.run(host="0.0.0.0", port=10000)
