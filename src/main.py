import yfinance as yf
import pandas as pd
import pandas_ta as pta
import ta
from datetime import datetime
import matplotlib.pyplot as plt
import requests
import schedule
import time
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ===== Slack Webhook URL =====
SLACK_WEBHOOK_URL = os.getenv("MY_WEBHOOK_URL")
PERIOD = "2y"
RSI_BUY = 40
RSI_SELL = 70
PE_BUY_MAX = 25
MA_PERIOD = 200
OUT_DIR = "results"
PLOT_DIR = os.path.join(OUT_DIR, "plots")

if not SLACK_WEBHOOK_URL:
    raise ValueError("❌ Environment variable MY_WEBHOOK_URL not set! Please configure it in GitHub Secrets.")

# ===== ETF 列表 =====
ETF_LIST = ["VOO", "SPY", "VTI", "ARKK", "AAPL", "MSFT", "GOOG", "TSLA",
            "DXCM", "NVDA", "AXP", "ISRG", "COST", "ASML", "AMZN", "META",
            "QQQ", "QQQM", "SCHD", "UNH", "AMD", "TSM", "JPM", "DIS", "T",
             "PYPL", "TDOC"]

def analyze_etf(ticker):
    """Analyze a single ETF and return a buy signal dict or None."""
    try:
        # download 1 year of data
        data = yf.download(ticker, period="1y", progress=False, auto_adjust=False)

        if data is None or data.empty:
            print(f"No data for {ticker}")
            return None

        # compute indicators using the shared compute_indicators (returns columns: Close, RSI, MACD, MACD_signal, MACD_diff, MA200)
        ind = compute_indicators(data)

        # need at least two rows to detect a cross
        if len(ind) < 2:
            return None

        today = ind.iloc[-1]
        yesterday = ind.iloc[-2]

        # ensure required values are present
        if pd.isna(today["RSI"]) or pd.isna(today["MACD"]) or pd.isna(today["MACD_signal"]):
            return None

        # strategy: MACD crosses above signal + RSI below threshold
        macd_cross = (yesterday["MACD"] < yesterday["MACD_signal"]) and (today["MACD"] > today["MACD_signal"])
        rsi_buy = today["RSI"] < RSI_BUY

        if macd_cross and rsi_buy:
            return {
                "ticker": ticker,
                "price": round(float(today["Close"]), 2),
                "rsi": round(float(today["RSI"]), 2),
                "macd": round(float(today["MACD"]), 4),
                "macd_signal": round(float(today["MACD_signal"]), 4),
                "date": today.name.strftime("%Y-%m-%d")
            }
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


def safe_series(df, col):
    s = df[col]
    if isinstance(s, pd.DataFrame):
        s = s.iloc[:, 0]
    return pd.Series(s.values, index=df.index, name=col)


def fetch_price_df(ticker, period=PERIOD):
    df = yf.download(ticker, period=period, progress=False, auto_adjust=False)
    if df.empty:
        raise SystemExit(f"No data downloaded for {ticker}")
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] for c in df.columns]
    df.index = pd.to_datetime(df.index)
    return df


def compute_indicators(df):
    close = safe_series(df, "Close")
    rsi = ta.momentum.RSIIndicator(close, window=14).rsi()
    macd_obj = ta.trend.MACD(close, window_slow=26, window_fast=12, window_sign=9)
    macd = macd_obj.macd()
    macd_signal = macd_obj.macd_signal()
    macd_diff = macd_obj.macd_diff()
    ma200 = close.rolling(window=MA_PERIOD, min_periods=1).mean()
    return pd.DataFrame({
        "Close": close,
        "RSI": rsi,
        "MACD": macd,
        "MACD_signal": macd_signal,
        "MACD_diff": macd_diff,
        "MA200": ma200
    })


def fetch_pe(ticker):
    try:
        info = yf.Ticker(ticker).info
        pe = info.get("trailingPE") or info.get("trailing_pe") or info.get("peRatio")
        return float(pe) if pe is not None else None
    except Exception:
        return None


def compute_indicators(df):
    close = safe_series(df, "Close")
    rsi = ta.momentum.RSIIndicator(close, window=14).rsi()
    macd_obj = ta.trend.MACD(close, window_slow=26, window_fast=12, window_sign=9)
    macd = macd_obj.macd()
    macd_signal = macd_obj.macd_signal()
    macd_diff = macd_obj.macd_diff()
    ma200 = close.rolling(window=MA_PERIOD, min_periods=1).mean()
    return pd.DataFrame({
        "Close": close,
        "RSI": rsi,
        "MACD": macd,
        "MACD_signal": macd_signal,
        "MACD_diff": macd_diff,
        "MA200": ma200
    })


def generate_signals(df, pe_val):
    macd_cross_up = (df["MACD"] > df["MACD_signal"]) & (df["MACD"].shift(1) <= df["MACD_signal"].shift(1))
    macd_cross_down = (df["MACD"] < df["MACD_signal"]) & (df["MACD"].shift(1) >= df["MACD_signal"].shift(1))
    cond_rsi_buy = df["RSI"] < RSI_BUY
    cond_rsi_sell = df["RSI"] > RSI_SELL
    cond_close_above_ma = df["Close"] > df["MA200"]
    cond_close_below_ma = df["Close"] < df["MA200"]
    cond_pe_buy = True if pe_val is None else (pe_val < PE_BUY_MAX)
    cond_pe_sell = True if pe_val is None else (pe_val > PE_BUY_MAX)

    buy_signal = cond_rsi_buy & macd_cross_up & cond_close_below_ma & cond_pe_buy
    sell_signal = cond_rsi_sell & macd_cross_down & cond_close_above_ma & cond_pe_sell

    df["Buy_Signal"] = buy_signal
    df["Sell_Signal"] = sell_signal
    return df


def simulate_trades(df):
    trades = []
    position = None
    for dt, row in df.iterrows():
        if row["Buy_Signal"] and position is None:
            position = {"buy_date": dt, "buy_price": float(row["Close"])}
            trades.append(position)
        elif row["Sell_Signal"] and position is not None:
            position["sell_date"] = dt
            position["sell_price"] = float(row["Close"])
            position["profit_pct"] = (position["sell_price"] - position["buy_price"]) / position["buy_price"] * 100
            position = None
    if position is not None and "sell_date" not in position:
        position["sell_date"] = None
        position["sell_price"] = None
        position["profit_pct"] = None
    return pd.DataFrame(trades)


def plot_signals(ticker, df):
    plt.figure(figsize=(12, 8))
    ax1 = plt.subplot(3, 1, 1)
    ax1.plot(df.index, df["Close"], label="Close")
    ax1.plot(df.index, df["MA200"], label="MA200", linestyle="--")
    ax1.scatter(df[df["Buy_Signal"]].index, df[df["Buy_Signal"]]["Close"], marker="^", color="g", label="Buy", zorder=5)
    ax1.scatter(df[df["Sell_Signal"]].index, df[df["Sell_Signal"]]["Close"], marker="v", color="r", label="Sell", zorder=5)
    ax1.set_title(f"{ticker} Price & Signals")
    ax1.legend()

    ax2 = plt.subplot(3, 1, 2, sharex=ax1)
    ax2.plot(df.index, df["RSI"], label="RSI")
    ax2.axhline(70, color="r", linestyle="--")
    ax2.axhline(30, color="g", linestyle="--")
    ax2.legend()

    ax3 = plt.subplot(3, 1, 3, sharex=ax1)
    ax3.plot(df.index, df["MACD"], label="MACD")
    ax3.plot(df.index, df["MACD_signal"], label="Signal", linestyle="--")
    ax3.bar(df.index, df["MACD_diff"], label="MACD_diff", alpha=0.3)
    ax3.legend()

    plt.tight_layout()
    os.makedirs(PLOT_DIR, exist_ok=True)
    out_path = os.path.join(PLOT_DIR, f"{ticker}.png")
    plt.savefig(out_path)
    plt.close()
    print(f"Saved plot: {out_path}")


def second_check():
    summary = []
    os.makedirs(OUT_DIR, exist_ok=True)
    for ticker in ETF_LIST:
        print("=" * 80)
        print(f"Processing {ticker} ...")

        df = fetch_price_df(ticker)
        df = compute_indicators(df)
        pe_val = fetch_pe(ticker)
        df = generate_signals(df, pe_val)
        trades = simulate_trades(df)

        latest_close = df["Close"].iloc[-1]
        latest_ma200 = df["MA200"].iloc[-1]
        recommended_buy_price = min(latest_ma200, latest_close * 0.97)
        has_buy_signal = df["Buy_Signal"].iloc[-1]
        has_sell_signal = df["Sell_Signal"].iloc[-1]

        # 保存结果
        df.to_csv(os.path.join(OUT_DIR, f"{ticker}_signals.csv"))
        trades.to_csv(os.path.join(OUT_DIR, f"{ticker}_trades.csv"), index=False)
        plot_signals(ticker, df)

        summary.append({
            "Ticker": ticker,
            "PE": pe_val,
            "Latest_Close": round(latest_close, 2),
            "MA200": round(latest_ma200, 2),
            "Buy_Signal_Today": bool(has_buy_signal),
            "Sell_Signal_Today": bool(has_sell_signal),
            "Recommended_Buy_Price": round(float(recommended_buy_price), 2)
        })
    summary_df = pd.DataFrame(summary)
    summary_df.to_csv(os.path.join(OUT_DIR, "summary.csv"), index=False)
    print("\nAll done! ✅ Summary:")
    print(summary_df)

    # ======= 发送 Slack 消息 =======
    slack_text = "*📊 Daily ETF Summary (Top Buy/Sell Signals)*\n\n"
    top_rows = summary_df[["Ticker", "Buy_Signal_Today", "Sell_Signal_Today", "Recommended_Buy_Price"]].head(10)
    slack_text += top_rows.to_string(index=False)
    send_slack_message(slack_text)
    send_email(summary_df.to_string(index=False))


def send_email(body):
    sender = os.getenv("GMAIL_USER")
    password = os.getenv("GMAIL_APP_PASSWORD")
    recipient = os.getenv("GMAIL_RECEIVER") or sender  # send to yourself by default

    if not sender or not password:
        raise ValueError("❌ GMAIL_USER or GMAIL_APP_PASSWORD not set in environment variables")

    # Create email
    msg = MIMEMultipart()
    msg["From"] = sender
    msg["To"] = recipient
    msg["Subject"] = "ETF Daily Report"
    msg.attach(MIMEText(body, "plain"))

    # Send through Gmail’s SMTP
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(sender, password)
        server.send_message(msg)

    print("✅ Email sent successfully to", recipient)


def main():
    """Main entry point of the program."""
    print("🚀 Starting daily check process...")
    daily_check()
    second_check()
    print("✅ Daily check completed successfully!")


if __name__ == "__main__":
    main()