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
        "par_spot": "BTCUSDT",
        "preco_medio": 67960.90,
        "lote_dca_usd": 100.00,
        "taxa_dex_pct": 0.35
    },
    "ETH": {
        "par_spot": "ETHUSDT",
        "preco_medio": 2550.00,
        "lote_dca_usd": 100.00,
        "taxa_dex_pct": 0.35
    }
}

TIMEFRAME_CURTO = "4h"
TIMEFRAME_MACRO = "1d"

TELEGRAM_BOT_TOKEN = "8659521907:AAGw7rCxoUZxWyDkRYu0mpA-LvuXocCq34Y" 
TELEGRAM_CHAT_ID = "8740599167"

bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)
app = Flask(__name__)

@app.route('/')
def home():
    return "🤖 Copiloto Quant Pro Rodando 24/7 na Nuvem Render!"

# ==============================================================================
# 2. MOTORES DE DADOS PÚBLICOS
# ==============================================================================
def buscar_candles(symbol, interval="4h", limit=250):
    url = "https://api.binance.com/api/v3/klines"
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    try:
        res = requests.get(url, params=params, timeout=10)
        data = res.json()
        df = pd.DataFrame(data, columns=[
            "timestamp", "open", "high", "low", "close", "volume",
            "close_time", "quote_vol", "trades", "tb_base", "tb_quote", "ignore"
        ])
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = df[col].astype(float)
        return df
    except Exception:
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

def analisar_rotacao_eth_btc():
    df = buscar_candles("ETHBTC", "1d", limit=60)
    if df is None or len(df) < 50: return "Neutro"
    close = df["close"]
    preco_atual = close.iloc[-1]
    sma20 = SMAIndicator(close=close, window=20).sma_indicator().iloc[-1]
    sma50 = SMAIndicator(close=close, window=50).sma_indicator().iloc[-1]
    rsi_ratio = RSIIndicator(close=close, window=14).rsi().iloc[-1]

    if preco_atual > sma20 and sma20 > sma50:
        return f"🔥 ETH ganhando força contra o BTC (Ratio: {preco_atual:.5f} | RSI: {rsi_ratio:.0f}) -> Prioridade de DCA: ETH"
    elif preco_atual < sma20 and sma20 < sma50:
        if rsi_ratio < 30: return f"⚖️ BTC dominante, mas ETH/BTC em exaustão (RSI {rsi_ratio:.0f}) -> Dividir DCA"
        return f"👑 BTC sugando liquidez (Ratio: {preco_atual:.5f}) -> Prioridade de DCA: BTC"
    return f"🔄 Transição no par ETH/BTC (Ratio: {preco_atual:.5f}) -> Manter proporção"

# ==============================================================================
# 3. CÉREBRO QUANTITATIVO PRO
# ==============================================================================
def analisar_ativo(moeda, config, hl_data):
    df_4h = buscar_candles(config["par_spot"], TIMEFRAME_CURTO, limit=250)
    df_1d = buscar_candles(config["par_spot"], TIMEFRAME_MACRO, limit=250)
    if df_4h is None or df_1d is None: return f"Dados insuficientes para {moeda}."

    close = df_4h["close"]
    high = df_4h["high"]
    low = df_4h["low"]
    vol = df_4h["volume"]
    preco_atual = close.iloc[-1]

    close_1d = df_1d["close"]
    sma50_1d = SMAIndicator(close=close_1d, window=50).sma_indicator().iloc[-1]
    sma200_1d = SMAIndicator(close=close_1d, window=200).sma_indicator().iloc[-1]
    rsi_1d = RSIIndicator(close=close_1d, window=14).rsi().iloc[-1]
    tendencia_1d = "Alta Macro" if preco_atual > sma200_1d else "Correção / Baixa Macro"

    sma50_4h = SMAIndicator(close=close, window=50).sma_indicator().iloc[-1]
    sma200_4h = SMAIndicator(close=close, window=200).sma_indicator().iloc[-1]
    tendencia_4h = "Alta" if preco_atual > sma200_4h else "Baixa / Recuo"

    adx_obj = ADXIndicator(high=high, low=low, close=close, window=14)
    adx = adx_obj.adx().iloc[-1]
    plus_di = adx_obj.adx_pos().iloc[-1]
    minus_di = adx_obj.adx_neg().iloc[-1]
    status_adx = f"Tendência Forte ({adx:.1f})" if adx > 25 else f"Lateral / Sem Força ({adx:.1f})"

    preco_tipico = (high + low + close) / 3
    vwap_50 = (preco_tipico.tail(50) * vol.tail(50)).sum() / vol.tail(50).sum()
    dist_vwap_pct = ((preco_atual - vwap_50) / vwap_50) * 100

    obv_series = OnBalanceVolumeIndicator(close=close, volume=vol).on_balance_volume()
    obv_atual = obv_series.iloc[-1]
    obv_sma20 = obv_series.tail(20).mean()
    var_preco_20 = preco_atual - close.iloc[-20]
    var_obv_20 = obv_atual - obv_series.iloc[-20]
    
    bonus_obv = 0
    if var_preco_20 < 0 and var_obv_20 > 0:
        fluxo_obv = "🐋 ACUMULAÇÃO SILENCIOSA"
        bonus_obv = 12
    elif var_preco_20 > 0 and var_obv_20 < 0:
        fluxo_obv = "⚠️ DISTRIBUIÇÃO"
        bonus_obv = -10
    else:
        fluxo_obv = "Positivo" if obv_atual > obv_sma20 else "Vendedor"

    rsi_4h = RSIIndicator(close=close, window=14).rsi().iloc[-1]
    bb = BollingerBands(close=close, window=20, window_dev=2)
    bb_sup = bb.bollinger_hband().iloc[-1]
    bb_inf = bb.bollinger_lband().iloc[-1]
    bb_pos = ((preco_atual - bb_inf) / (bb_sup - bb_inf)) * 100 if (bb_sup - bb_inf) > 0 else 50

    macd_obj = MACD(close=close, window_slow=26, window_fast=12, window_sign=9)
    macd_hist = macd_obj.macd_diff().iloc[-1]
    macd_hist_ant = macd_obj.macd_diff().iloc[-2]
    atr = AverageTrueRange(high=high, low=low, close=close, window=14).average_true_range().iloc[-1]

    perna_high = high.tail(100).max()
    perna_low = low.tail(100).min()
    diff_fibo = perna_high - perna_low
    fib_382 = perna_high - (diff_fibo * 0.382)
    fib_500 = perna_high - (diff_fibo * 0.500)
    fib_618 = perna_high - (diff_fibo * 0.618)

    topo_22 = high.tail(22).max()
    chandelier_stop = topo_22 - (3.0 * atr)
    status_chandelier = "Acima da Catraca 📈" if preco_atual > chandelier_stop else "Abaixo da Catraca ⚠️"

    score = 50 + bonus_obv
    if rsi_4h < 30: score += 20
    elif rsi_4h > 75: score -= 20
    if bb_pos < 15: score += 12
    elif bb_pos > 85: score -= 12
    if preco_atual < vwap_50: score += 5
    else: score -= 3
    if macd_hist > macd_hist_ant and macd_hist < 0: score += 8
    elif macd_hist < macd_hist_ant and macd_hist > 0: score -= 8
    if fib_618 * 0.99 <= preco_atual <= fib_500 * 1.01: score += 10
    if adx > 28 and minus_di > plus_di: score -= 10

    score = max(0, min(100, score))
    lote_base = config["lote_dca_usd"]
    
    if score >= 80: veredito = "🟢 COMPRA FORTE"; acao = f"Aportar 1.5x a 2x (${lote_base * 1.5:.2f})"
    elif score >= 65: veredito = "🟢 ACUMULAR"; acao = f"Aportar lote padrão (${lote_base:.2f})"
    elif score >= 40: veredito = "🟡 AGUARDAR / NEUTRO"; acao = "Manter caixa em Stablecoin"
    elif score >= 25: veredito = "🟠 SOBRECOMPRA"; acao = "Zero compras. Proteja lucros."
    else: veredito = "🔴 REALIZAR LUCRO"; acao = "Realizar parcial para Stablecoin"

    pm = config["preco_medio"]
    alvo_curto = preco_atual + (1.5 * atr)
    preco_breakeven = pm * (1 + ((config["taxa_dex_pct"] / 100) * 2))
    pnl = ((preco_atual - preco_breakeven) / preco_breakeven) * 100

    return (
        f"🎯 {moeda}/USD | Preço: ${preco_atual:,.2f}\n"
        f"📊 SCORE: {score}/100 | {veredito}\n"
        f"💡 Ação: {acao}\n\n"
        f"🧭 TENDÊNCIAS: Diário ({tendencia_1d}) | 4H ({tendencia_4h})\n"
        f"🐋 FLUXO: OBV {fluxo_obv} | VWAP ${vwap_50:,.2f}\n"
        f"📐 ZONA DE OURO (Fib 0.618): ${fib_618:,.2f}\n\n"
        f"🛡️ SUA POSIÇÃO:\n"
        f" • Médio: ${pm:,.2f} | Zero a Zero: ${preco_breakeven:,.2f}\n"
        f" • PnL: {pnl:+.2f}% | Catraca: {status_chandelier}\n"
        f"--------------------------------------------------\n"
    )

def compilar_relatorio_completo():
    hl_sentimento = buscar_sentimento_hyperliquid()
    rotacao_msg = analisar_rotacao_eth_btc()
    relatorio = f"🤖 RADAR QUANT PRO SPOT & DCA\n🔄 {rotacao_msg}\n\n"
    for moeda, cfg in PORTFOLIO.items():
        relatorio += analisar_ativo(moeda, cfg, hl_sentimento)
    return relatorio

@bot.message_handler(func=lambda message: message.text.lower() == "mercado agora")
def escutar_comando_manual(message):
    bot.reply_to(message, "⏳ Calculando métricas Pro (MTF, Volume, ADX, Fibo) para BTC e ETH...")
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