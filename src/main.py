import yfinance as yf
import pandas as pd
import pandas_ta as ta
from datetime import datetime
import requests
import schedule
import time
import os
# ===== Slack Webhook URL =====
SLACK_WEBHOOK_URL = os.getenv("MY_WEBHOOK_URL")

if not SLACK_WEBHOOK_URL:
    raise ValueError("❌ Environment variable MY_WEBHOOK_URL not set! Please configure it in GitHub Secrets.")

# ===== ETF 列表 =====
ETF_LIST = ["VOO", "SPY", "VTI", "ARKK", "AAPL", "MSFT", "GOOG", "TSLA",
            "DXCM", "NVDA", "AXP", "ISRG", "COST", "ASML", "AMZN", "META",
            "QQQ", "QQQM", "SCHD", "UNH", "AMD", "TSM", "JPM", "DIS", "T",
             "PYPL", "TDOC"]

def analyze_etf(ticker):
    """分析单个 ETF，返回买入信号或 None"""
    try:
        # 下载过去1年数据
        data = yf.download(ticker, period="1y", progress=False)

        # 检查数据是否为空
        if data is None or data.empty:
            print(f"No data for {ticker}")
            return None

        # 计算 RSI
        data["RSI"] = ta.rsi(data["Close"], length=14)

        # 计算 MACD
        macd_df = ta.macd(data["Close"])
        if macd_df is None or macd_df.empty:
            print(f"MACD not computed for {ticker}")
            return None

        # 合并 MACD 数据
        data = pd.concat([data, macd_df], axis=1)

        # 检查最后两天是否足够
        if len(data) < 2:
            return None

        today = data.iloc[-1]
        yesterday = data.iloc[-2]

        # 检查数据完整性
        if pd.isna(today["RSI"]) or pd.isna(today["MACD_12_26_9"]) or pd.isna(today["MACDs_12_26_9"]):
            return None

        # 策略逻辑
        macd_cross = yesterday["MACD_12_26_9"] < yesterday["MACDs_12_26_9"] and today["MACD_12_26_9"] > today["MACDs_12_26_9"]
        rsi_buy = today["RSI"] < 40

        if macd_cross and rsi_buy:
            return {
                "ticker": ticker,
                "price": round(today["Close"], 2),
                "rsi": round(today["RSI"], 2),
                "macd": round(today["MACD_12_26_9"], 4),
                "macd_signal": round(today["MACDs_12_26_9"], 4),
                "date": today.name.strftime("%Y-%m-%d")
            }
        else:
            return None

    except Exception as e:
        print(f"Error analyzing {ticker}: {e}")
        return None


def send_slack_message(message: str):
    """发送 Slack 通知"""
    try:
        payload = {"text": message}
        requests.post(SLACK_WEBHOOK_URL, json=payload)
        print("✅ Slack message sent!")
    except Exception as e:
        print(f"Slack error: {e}")


def daily_check():
    """每天运行一次的主函数"""
    print(f"📊 Running ETF check at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    buy_signals = []

    for ticker in ETF_LIST:
        signal = analyze_etf(ticker)
        if signal:
            buy_signals.append(signal)

    if buy_signals:
        msg_lines = ["🚀 *Buy Signals Detected!*"]
        for s in buy_signals:
            msg_lines.append(
                f"{s['ticker']} — Price: ${s['price']}, RSI: {s['rsi']}, "
                f"MACD: {s['macd']} > Signal: {s['macd_signal']} ({s['date']})"
            )
        send_slack_message("\n".join(msg_lines))
    else:
        send_slack_message("😴 No buy signals detected today.")


# ===== 每天上午 09:00 运行 =====
# schedule.every().day.at("16:25").do(daily_check)
#
# print("🔁 ETF buy signal monitor started...")
# while True:
#     schedule.run_pending()
#     time.sleep(60)

def main():
    """Main entry point of the program."""
    print("🚀 Starting daily check process...")
    daily_check()
    print("✅ Daily check completed successfully!")


if __name__ == "__main__":
    main()