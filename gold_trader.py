import streamlit as st
import pandas as pd
import yfinance as yf
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta, timezone
import numpy as np
from streamlit_gsheets import GSheetsConnection

# ------------------------------------------------------------
# PAGE CONFIG
# ------------------------------------------------------------
st.set_page_config(
    page_title="Gold Trading Portfolio Tracker",
    page_icon="🥇",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ------------------------------------------------------------
# IST TIME HELPERS
# ------------------------------------------------------------
def _ist_now():
    ist = timezone(timedelta(hours=5, minutes=30))
    return datetime.now(ist).strftime("%H:%M:%S")


def _ist_today():
    ist = timezone(timedelta(hours=5, minutes=30))
    return datetime.now(ist).date()


# ------------------------------------------------------------
# GOOGLE SHEETS CONNECTION
# ------------------------------------------------------------
conn = st.connection("gsheets", type=GSheetsConnection)

BUYS_SHEET = "Buys"
SELLS_SHEET = "Sells"

BUY_COLUMNS = ["id", "buy_date", "shares", "price", "invested_amount", "notes", "created_at"]
SELL_COLUMNS = ["id", "sell_date", "shares", "price", "sold_amount", "profit", "notes", "created_at"]


# ------------------------------------------------------------
# LOAD DATA
# ------------------------------------------------------------
def load_buys():
    try:
        df = conn.read(worksheet=BUYS_SHEET, ttl=5)
        if df.empty:
            return pd.DataFrame(columns=BUY_COLUMNS)
        df = df.dropna(how='all')
        if 'id' in df.columns:
            df = df.dropna(subset=['id'])
            df['id'] = pd.to_numeric(df['id'], errors='coerce')
            df = df.dropna(subset=['id'])
            df['id'] = df['id'].astype(int)
            df = df[df['id'] != 0]
            df = df.drop_duplicates(subset=['id'], keep='first')
        if 'shares' in df.columns:
            df['shares'] = pd.to_numeric(df['shares'], errors='coerce').fillna(0).astype(int)
            df = df[df['shares'] > 0]
        for col in ['price', 'invested_amount']:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0.0)
        if 'price' in df.columns:
            df = df[df['price'] > 0]
        return df
    except Exception as e:
        st.warning(f"Could not load Buys: {e}")
        return pd.DataFrame(columns=BUY_COLUMNS)


def load_sells():
    try:
        df = conn.read(worksheet=SELLS_SHEET, ttl=5)
        if df.empty:
            return pd.DataFrame(columns=SELL_COLUMNS)
        df = df.dropna(how='all')
        if 'id' in df.columns:
            df = df.dropna(subset=['id'])
            df['id'] = pd.to_numeric(df['id'], errors='coerce')
            df = df.dropna(subset=['id'])
            df['id'] = df['id'].astype(int)
            df = df[df['id'] != 0]
            df = df.drop_duplicates(subset=['id'], keep='first')
        if 'shares' in df.columns:
            df['shares'] = pd.to_numeric(df['shares'], errors='coerce').fillna(0).astype(int)
            df = df[df['shares'] > 0]
        for col in ['price', 'sold_amount', 'profit']:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0.0)
        if 'price' in df.columns:
            df = df[df['price'] > 0]
        return df
    except Exception as e:
        st.warning(f"Could not load Sells: {e}")
        return pd.DataFrame(columns=SELL_COLUMNS)


# ------------------------------------------------------------
# SAVE / ADD / DELETE
# ------------------------------------------------------------
def save_buys(df):
    conn.update(worksheet=BUYS_SHEET, data=df)


def save_sells(df):
    conn.update(worksheet=SELLS_SHEET, data=df)


def add_buy(buy_date, shares, price, notes=""):
    buys = conn.read(worksheet=BUYS_SHEET, ttl=0)
    if buys.empty or 'id' not in buys.columns:
        buys = pd.DataFrame(columns=BUY_COLUMNS)
    buys = buys.dropna(how='all')
    if 'id' in buys.columns:
        buys['id'] = pd.to_numeric(buys['id'], errors='coerce')
        buys = buys.dropna(subset=['id'])
        buys['id'] = buys['id'].astype(int)
        buys = buys.drop_duplicates(subset=['id'], keep='first')

    invested = shares * price
    new_id = int(buys['id'].max()) + 1 if not buys.empty else 1

    new_row = pd.DataFrame([{
        "id": new_id,
        "buy_date": str(buy_date),
        "shares": int(shares),
        "price": float(price),
        "invested_amount": float(invested),
        "notes": notes,
        "created_at": str(datetime.now())
    }])
    buys = pd.concat([buys, new_row], ignore_index=True)
    buys = buys.sort_values('id').reset_index(drop=True)
    save_buys(buys)


def add_sell(sell_date, shares, price, cost_basis, notes=""):
    sells = conn.read(worksheet=SELLS_SHEET, ttl=0)
    if sells.empty or 'id' not in sells.columns:
        sells = pd.DataFrame(columns=SELL_COLUMNS)
    sells = sells.dropna(how='all')
    if 'id' in sells.columns:
        sells['id'] = pd.to_numeric(sells['id'], errors='coerce')
        sells = sells.dropna(subset=['id'])
        sells['id'] = sells['id'].astype(int)
        sells = sells.drop_duplicates(subset=['id'], keep='first')

    sold = shares * price
    profit = sold - (shares * cost_basis)
    new_id = int(sells['id'].max()) + 1 if not sells.empty else 1

    new_row = pd.DataFrame([{
        "id": new_id,
        "sell_date": str(sell_date),
        "shares": int(shares),
        "price": float(price),
        "sold_amount": float(sold),
        "profit": float(profit),
        "notes": notes,
        "created_at": str(datetime.now())
    }])
    sells = pd.concat([sells, new_row], ignore_index=True)
    sells = sells.sort_values('id').reset_index(drop=True)
    save_sells(sells)


def delete_buy(buy_id):
    buys = load_buys()
    buys = buys[buys['id'] != buy_id]
    save_buys(buys)


def delete_sell(sell_id):
    sells = load_sells()
    sells = sells[sells['id'] != sell_id]
    save_sells(sells)


# ------------------------------------------------------------
# PORTFOLIO CALCULATION — FIFO COST BASIS
# ------------------------------------------------------------
def compute_portfolio(buys_df, sells_df):
    """FIFO cost basis for realized profit + remaining lots."""
    buys = buys_df.copy()
    sells = sells_df.copy()

    if not buys.empty:
        buys['buy_date'] = pd.to_datetime(buys['buy_date'], errors='coerce', dayfirst=True)
        buys = buys.sort_values('buy_date').reset_index(drop=True)

    if not sells.empty:
        sells['sell_date'] = pd.to_datetime(sells['sell_date'], errors='coerce', dayfirst=True)
        sells = sells.sort_values('sell_date').reset_index(drop=True)

    lots = []
    for _, row in buys.iterrows():
        lots.append({
            'id': int(row['id']),
            'shares': int(row['shares']),
            'price': float(row['price']),
            'date': row['buy_date'],
        })

    total_bought_shares = sum(lot['shares'] for lot in lots)
    lifetime_invested = sum(lot['shares'] * lot['price'] for lot in lots)

    realized_profit = 0.0
    total_sold_proceeds = 0.0
    total_sold_shares = 0

    for _, sell_row in sells.iterrows():
        sell_shares = int(sell_row['shares'])
        sell_price = float(sell_row['price'])
        remaining = sell_shares

        while remaining > 0 and lots:
            lot = lots[0]
            if lot['shares'] <= remaining:
                realized_profit += lot['shares'] * (sell_price - lot['price'])
                remaining -= lot['shares']
                lots.pop(0)
            else:
                realized_profit += remaining * (sell_price - lot['price'])
                lot['shares'] -= remaining
                remaining = 0

        total_sold_proceeds += sell_shares * sell_price
        total_sold_shares += sell_shares

    net_shares = sum(lot['shares'] for lot in lots)
    remaining_cost = sum(lot['shares'] * lot['price'] for lot in lots)
    avg_cost = (remaining_cost / net_shares) if net_shares > 0 else 0.0

    return {
        'total_shares_bought': total_bought_shares,
        'total_shares_sold': total_sold_shares,
        'net_shares': net_shares,
        'lifetime_invested': lifetime_invested,
        'total_sold_amount': total_sold_proceeds,
        'unsold_cost': remaining_cost,
        'total_profit': realized_profit,
        'avg_cost': avg_cost,
    }


# ------------------------------------------------------------
# NEXT SELL LOT — 20% PROFIT, CHEAPEST FIRST
# ------------------------------------------------------------
def get_next_sell_lot(buys_df, sells_df, profit_pct=20):
    """Find unsold lots, sort by price ascending, compute 20% target."""
    buys = buys_df.copy()
    sells = sells_df.copy()

    if not buys.empty:
        buys['buy_date'] = pd.to_datetime(buys['buy_date'], errors='coerce', dayfirst=True)
    if not sells.empty:
        sells['sell_date'] = pd.to_datetime(sells['sell_date'], errors='coerce', dayfirst=True)

    lots = []
    for _, row in buys.sort_values('buy_date').iterrows():
        lots.append({
            'id': int(row['id']),
            'date': row['buy_date'],
            'shares': int(row['shares']),
            'price': float(row['price']),
        })

    # FIFO consume but keep remaining lots only
    for _, sell_row in sells.sort_values('sell_date').iterrows():
        sell_shares = int(sell_row['shares'])
        remaining = sell_shares
        while remaining > 0 and lots:
            lot = lots[0]
            if lot['shares'] <= remaining:
                remaining -= lot['shares']
                lots.pop(0)
            else:
                lot['shares'] -= remaining
                remaining = 0

    lots_sorted = sorted(lots, key=lambda x: x['price'])

    for lot in lots_sorted:
        lot['target_price'] = round(lot['price'] * (1 + profit_pct / 100), 2)
        lot['target_value'] = round(lot['target_price'] * lot['shares'], 2)
        lot['cost'] = round(lot['price'] * lot['shares'], 2)
        lot['profit_at_target'] = round(lot['target_value'] - lot['cost'], 2)

    next_lot = lots_sorted[0] if lots_sorted else None
    return lots_sorted, next_lot


# ------------------------------------------------------------
# LOT-WISE P&L — includes ALL lots (fully sold + holding)
# ------------------------------------------------------------
def compute_lot_wise_pnl(buys_df, sells_df, current_price=None, profit_pct=20):
    """
    Per-lot P&L with SEPARATE Realized and Unrealized columns.
    ALL lots appear — including fully sold ones.
    """
    buys = buys_df.copy()
    sells = sells_df.copy()

    if not buys.empty:
        buys['buy_date'] = pd.to_datetime(buys['buy_date'], errors='coerce', dayfirst=True)
        buys = buys.sort_values('buy_date').reset_index(drop=True)
    if not sells.empty:
        sells['sell_date'] = pd.to_datetime(sells['sell_date'], errors='coerce', dayfirst=True)
        sells = sells.sort_values('sell_date').reset_index(drop=True)

    # Build lot tracker — ALL lots kept in list
    lots = []
    for _, row in buys.iterrows():
        lots.append({
            'id': int(row['id']),
            'date': row['buy_date'],
            'orig_shares': int(row['shares']),
            'remaining_shares': int(row['shares']),
            'price': float(row['price']),
            'realized_profit': 0.0,
            'sold_shares': 0,
        })

    # Consume lots FIFO — but DO NOT pop them
    for _, sell_row in sells.iterrows():
        sell_shares = int(sell_row['shares'])
        sell_price = float(sell_row['price'])
        remaining = sell_shares

        for lot in lots:
            if remaining <= 0:
                break
            if lot['remaining_shares'] <= 0:
                continue

            if lot['remaining_shares'] <= remaining:
                profit = lot['remaining_shares'] * (sell_price - lot['price'])
                lot['realized_profit'] += profit
                lot['sold_shares'] += lot['remaining_shares']
                remaining -= lot['remaining_shares']
                lot['remaining_shares'] = 0
            else:
                profit = remaining * (sell_price - lot['price'])
                lot['realized_profit'] += profit
                lot['sold_shares'] += remaining
                lot['remaining_shares'] -= remaining
                remaining = 0

    # Build output — ALL lots included
    rows = []
    for lot in lots:
        cost_total = lot['orig_shares'] * lot['price']
        cost_remaining = lot['remaining_shares'] * lot['price']
        realized = round(lot['realized_profit'], 2)

        if current_price is not None and lot['remaining_shares'] > 0:
            unrealized = round((current_price - lot['price']) * lot['remaining_shares'], 2)
        else:
            unrealized = 0.0

        total_pnl = round(realized + unrealized, 2)
        target_price = round(lot['price'] * (1 + profit_pct / 100), 2)
        target_profit = round((target_price - lot['price']) * lot['remaining_shares'], 2)

        if lot['remaining_shares'] == 0:
            status = "✅ Fully Sold"
        elif current_price is not None and current_price >= target_price:
            status = "🎯 SELL NOW"
        else:
            status = "⏳ Holding"

        rows.append({
            "Lot ID": lot['id'],
            "Buy Date": lot['date'].strftime('%d-%b-%Y'),
            "Buy Price (₹)": round(lot['price'], 2),
            "Orig Units": lot['orig_shares'],
            "Sold Units": lot['sold_shares'],
            "Remaining Units": lot['remaining_shares'],
            "Total Cost (₹)": round(cost_total, 2),
            "Remaining Cost (₹)": round(cost_remaining, 2),
            "Realized Profit (₹)": realized,
            "Unrealized P&L (₹)": unrealized,
            "Total P&L (₹)": total_pnl,
            "Target Price (₹)": target_price,
            "Target Profit (₹)": target_profit,
            "Status": status,
        })

    return pd.DataFrame(rows)


# ------------------------------------------------------------
# LIVE PRICE HELPERS
# ------------------------------------------------------------
@st.cache_data(ttl=300)
def fetch_gold_data():
    result = {}
    try:
        gold = yf.download("GC=F", period="90d", progress=False, auto_adjust=False)
        if not gold.empty:
            result['gold'] = gold
    except Exception:
        pass
    try:
        usdinr = yf.download("INR=X", period="90d", progress=False, auto_adjust=False)
        if not usdinr.empty:
            result['usdinr'] = usdinr
    except Exception:
        pass
    try:
        setfgold = yf.download("SETFGOLD.NS", period="90d", progress=False, auto_adjust=False)
        if not setfgold.empty:
            result['setfgold'] = setfgold
    except Exception:
        pass
    return result


def _squeeze_close(df):
    if df is None or df.empty:
        return None
    close = df['Close']
    if isinstance(close, pd.DataFrame):
        close = close.iloc[:, 0]
    close = pd.to_numeric(close, errors='coerce').dropna()
    return close if len(close) > 0 else None


def predict_next_day_open(gold_df, inr_df, etf_df):
    predictions = {}

    gold_close = _squeeze_close(gold_df)
    if gold_close is not None and len(gold_close) >= 10:
        last = float(gold_close.iloc[-1])
        recent_5 = gold_close.tail(5).values.astype(float)
        slope = float(np.polyfit(np.arange(len(recent_5)), recent_5, 1)[0])
        returns_3 = float(gold_close.pct_change().tail(3).mean())
        gold_pred = float((last + slope) * 0.6 + last * (1 + returns_3) * 0.4)
        predictions['gold'] = {
            'last_close': round(last, 2),
            'predicted_open': round(gold_pred, 2),
            'change_pct': round(((gold_pred - last) / last) * 100, 2),
        }

    inr_close = _squeeze_close(inr_df)
    if inr_close is not None and len(inr_close) >= 10:
        last = float(inr_close.iloc[-1])
        recent_5 = inr_close.tail(5).values.astype(float)
        slope = float(np.polyfit(np.arange(len(recent_5)), recent_5, 1)[0])
        returns_3 = float(inr_close.pct_change().tail(3).mean())
        inr_pred = float((last + slope) * 0.6 + last * (1 + returns_3) * 0.4)
        predictions['usdinr'] = {
            'last_close': round(last, 4),
            'predicted_open': round(inr_pred, 4),
            'change_pct': round(((inr_pred - last) / last) * 100, 3),
        }

    etf_close = _squeeze_close(etf_df)
    if etf_close is not None and len(etf_close) >= 10:
        last = float(etf_close.iloc[-1])
        recent_5 = etf_close.tail(5).values.astype(float)
        slope = float(np.polyfit(np.arange(len(recent_5)), recent_5, 1)[0])
        returns_3 = float(etf_close.pct_change().tail(3).mean())
        etf_pred_tech = float((last + slope) * 0.6 + last * (1 + returns_3) * 0.4)

        etf_pred_corr = None
        if 'gold' in predictions and 'usdinr' in predictions:
            combined = (
                predictions['gold']['change_pct'] / 100 +
                predictions['usdinr']['change_pct'] / 100
            )
            etf_pred_corr = float(last * (1 + combined))

        etf_pred_final = (
            (etf_pred_tech * 0.5 + etf_pred_corr * 0.5)
            if etf_pred_corr is not None else etf_pred_tech
        )

        predictions['setfgold'] = {
            'last_close': round(last, 2),
            'predicted_open': round(etf_pred_final, 2),
            'change_pct': round(((etf_pred_final - last) / last) * 100, 2),
        }

    return predictions


# ============================================================
# MAIN UI
# ============================================================
st.title("🥇 Gold Trading Portfolio & Prediction Dashboard")
st.caption(f"🕐 Live prices updated {_ist_now()} IST · Data stored in Google Sheets")

col_r1, col_r2 = st.columns([1, 4])
with col_r1:
    if st.button("🔄 Refresh Prices", use_container_width=True, type="primary"):
        st.cache_data.clear()
        st.toast("♻️ Refreshed — fetching latest prices...", icon="🔄")
        st.rerun()

st.divider()

buys_df = load_buys()
sells_df = load_sells()

portfolio = compute_portfolio(buys_df, sells_df)

with st.spinner("Fetching live gold prices..."):
    bundle = fetch_gold_data()

gold_df = bundle.get('gold')
inr_df = bundle.get('usdinr')
etf_df = bundle.get('setfgold')

predictions = predict_next_day_open(gold_df, inr_df, etf_df)

current_price = None
if 'setfgold' in predictions:
    current_price = predictions['setfgold']['last_close']
elif etf_df is not None:
    s = _squeeze_close(etf_df)
    if s is not None:
        current_price = float(s.iloc[-1])

# ------------------------------------------------------------
# PORTFOLIO SUMMARY
# ------------------------------------------------------------
st.subheader("📊 Portfolio Summary")

col_p1, col_p2, col_p3, col_p4 = st.columns(4)

with col_p1:
    st.metric("Net Holdings", f"{portfolio['net_shares']} units")

with col_p2:
    st.metric("Avg Cost (FIFO)", f"₹{portfolio['avg_cost']:,.2f}")

with col_p3:
    st.metric("Invested (Remaining)", f"₹{portfolio['unsold_cost']:,.2f}")

with col_p4:
    st.metric("Realized Profit (FIFO)", f"₹{portfolio['total_profit']:,.2f}")

if current_price is not None and portfolio['net_shares'] > 0:
    unrealized = (current_price - portfolio['avg_cost']) * portfolio['net_shares']
    pct = ((current_price - portfolio['avg_cost']) / portfolio['avg_cost'] * 100) if portfolio['avg_cost'] > 0 else 0
    col_u1, col_u2, col_u3 = st.columns(3)
    with col_u1:
        st.metric("Current Price (SETFGOLD)", f"₹{current_price:,.2f}")
    with col_u2:
        st.metric("Current Value", f"₹{current_price * portfolio['net_shares']:,.2f}")
    with col_u3:
        st.metric("Unrealized P&L", f"₹{unrealized:,.0f}", delta=f"{pct:+.2f}%")

with st.expander("📊 Lifetime Summary (Cash Flow)"):
    col_l1, col_l2, col_l3 = st.columns(3)
    with col_l1:
        st.metric("Total Money Invested", f"₹{portfolio['lifetime_invested']:,.2f}")
    with col_l2:
        st.metric("Total Money Received", f"₹{portfolio['total_sold_amount']:,.2f}")
    with col_l3:
        st.metric("Net Cash Position", f"₹{portfolio['lifetime_invested'] - portfolio['total_sold_amount']:,.2f}")

# ------------------------------------------------------------
# NEXT SELL LOT — 20% PROFIT, CHEAPEST FIRST
# ------------------------------------------------------------
st.divider()
st.subheader("🎯 Next Sell Lot (20% Profit — Cheapest First)")

unsold_lots, next_lot = get_next_sell_lot(buys_df, sells_df, profit_pct=20)

if unsold_lots and current_price:
    st.markdown("### 🔔 Next Lot to Sell")

    col_n1, col_n2, col_n3, col_n4 = st.columns(4)

    with col_n1:
        st.metric("Lot Bought On", next_lot['date'].strftime('%d %b %Y'))

    with col_n2:
        st.metric("Lot Buy Price", f"₹{next_lot['price']:,.2f}")

    with col_n3:
        st.metric("🎯 Target Price (20% hike)", f"₹{next_lot['target_price']:,.2f}")

    with col_n4:
        gap = ((next_lot['target_price'] - current_price) / current_price) * 100
        st.metric("Distance to Target", f"{gap:+.2f}%")

    if current_price >= next_lot['target_price']:
        st.success(f"""
        ✅ **SELL NOW!** — Target reached. Sell **{next_lot['shares']} units** at **₹{next_lot['target_price']:,.2f}**
        - Expected proceeds: **₹{next_lot['target_value']:,.0f}**
        - Expected profit: **₹{next_lot['profit_at_target']:,.0f}** (20%)
        """)
    else:
        st.info(f"""
        💡 **Action Plan:**
        - Sell **{next_lot['shares']} units** at **₹{next_lot['target_price']:,.2f}** (20% above buy price)
        - Expected proceeds: **₹{next_lot['target_value']:,.0f}**
        - Expected profit: **₹{next_lot['profit_at_target']:,.0f}**
        - **Current:** ₹{current_price:,.2f} — {gap:+.2f}% from target
        """)

    st.markdown("### 📋 All Unsold Lots (Cheapest First)")

    lots_display = pd.DataFrame([{
        "Bought On": lot['date'].strftime('%d-%b-%Y'),
        "Units": lot['shares'],
        "Buy Price (₹)": lot['price'],
        "Cost (₹)": lot['cost'],
        "Target Price (₹)": lot['target_price'],
        "Target Value (₹)": lot['target_value'],
        "Profit @ Target (₹)": lot['profit_at_target'],
        "Status": "🎯 SELL NOW" if current_price >= lot['target_price'] else "⏳ Waiting",
    } for lot in unsold_lots])

    st.dataframe(
        lots_display,
        column_config={
            "Buy Price (₹)": st.column_config.NumberColumn(format="₹%.2f"),
            "Cost (₹)": st.column_config.NumberColumn(format="₹%.2f"),
            "Target Price (₹)": st.column_config.NumberColumn(format="₹%.2f"),
            "Target Value (₹)": st.column_config.NumberColumn(format="₹%.2f"),
            "Profit @ Target (₹)": st.column_config.NumberColumn(format="₹%.2f"),
        },
        hide_index=True,
        use_container_width=True
    )

    ready_count = sum(1 for lot in unsold_lots if current_price >= lot['target_price'])
    if ready_count > 0:
        st.success(f"✅ **{ready_count} lot(s)** have hit their 20% target — consider selling!")

elif not unsold_lots:
    st.info("ℹ️ No unsold lots. All lots have been sold.")
else:
    st.info("ℹ️ Live price unavailable — cannot compute distance to target.")

# ------------------------------------------------------------
# LOT-WISE PROFITABILITY TABLE
# ------------------------------------------------------------
st.divider()
st.subheader("📋 Lot-Wise Profitability")
st.caption("Realized (booked) · Unrealized (paper) · Total per lot — includes fully sold lots")

lot_pnl_df = compute_lot_wise_pnl(buys_df, sells_df, current_price, profit_pct=20)

if not lot_pnl_df.empty:
    total_realized = lot_pnl_df['Realized Profit (₹)'].sum()
    total_unrealized = lot_pnl_df['Unrealized P&L (₹)'].sum()
    total_pnl = lot_pnl_df['Total P&L (₹)'].sum()
    total_target_profit = lot_pnl_df['Target Profit (₹)'].sum()
    total_remaining_cost = lot_pnl_df['Remaining Cost (₹)'].sum()
    total_sold_units = lot_pnl_df['Sold Units'].sum()
    total_remaining_units = lot_pnl_df['Remaining Units'].sum()

    col_lp1, col_lp2, col_lp3, col_lp4, col_lp5 = st.columns(5)

    with col_lp1:
        st.metric("💰 Realized Profit", f"₹{total_realized:,.2f}")

    with col_lp2:
        st.metric("📈 Unrealized P&L", f"₹{total_unrealized:,.2f}")

    with col_lp3:
        st.metric("🎯 Total P&L", f"₹{total_pnl:,.2f}")

    with col_lp4:
        st.metric("💼 Remaining Cost", f"₹{total_remaining_cost:,.2f}")

    with col_lp5:
        st.metric("🎯 Target Profit (20%)", f"₹{total_target_profit:,.2f}")

    st.caption(
        f"📦 Recon check — Sold Units: **{total_sold_units}** (should = {portfolio['total_shares_sold']}) · "
        f"Remaining Units: **{total_remaining_units}** (should = {portfolio['net_shares']}) · "
        f"Realized total: **₹{total_realized:,.2f}** (should = ₹{portfolio['total_profit']:,.2f})"
    )

    def color_pnl(val):
        if isinstance(val, (int, float)):
            if val > 0:
                return 'color: #00ff88; font-weight: bold;'
            elif val < 0:
                return 'color: #ff6b6b; font-weight: bold;'
        return 'color: #cccccc;'

    styled_lot_df = lot_pnl_df.style.map(
        color_pnl,
        subset=['Realized Profit (₹)', 'Unrealized P&L (₹)', 'Total P&L (₹)']
    )

    st.dataframe(
        styled_lot_df,
        column_config={
            "Buy Price (₹)": st.column_config.NumberColumn(format="₹%.2f"),
            "Total Cost (₹)": st.column_config.NumberColumn(format="₹%.2f"),
            "Remaining Cost (₹)": st.column_config.NumberColumn(format="₹%.2f"),
            "Realized Profit (₹)": st.column_config.NumberColumn(format="₹%.2f"),
            "Unrealized P&L (₹)": st.column_config.NumberColumn(format="₹%.2f"),
            "Total P&L (₹)": st.column_config.NumberColumn(format="₹%.2f"),
            "Target Price (₹)": st.column_config.NumberColumn(format="₹%.2f"),
            "Target Profit (₹)": st.column_config.NumberColumn(format="₹%.2f"),
        },
        hide_index=True,
        use_container_width=True,
        height=500
    )

    csv_data = lot_pnl_df.to_csv(index=False).encode('utf-8')
    st.download_button(
        label="📥 Download Lot-Wise P&L (CSV)",
        data=csv_data,
        file_name=f"gold_lot_pnl_{_ist_today()}.csv",
        mime='text/csv'
    )

    st.markdown("### 📊 Per-Lot P&L Breakdown")
    chart_df = lot_pnl_df[lot_pnl_df['Orig Units'] > 0].copy()
    if not chart_df.empty:
        fig_lots = go.Figure()
        fig_lots.add_trace(go.Bar(
            x=chart_df['Lot ID'].astype(str),
            y=chart_df['Realized Profit (₹)'],
            name='Realized Profit',
            marker_color='#00ff88'
        ))
        fig_lots.add_trace(go.Bar(
            x=chart_df['Lot ID'].astype(str),
            y=chart_df['Unrealized P&L (₹)'],
            name='Unrealized P&L',
            marker_color='#4facfe'
        ))
        fig_lots.update_layout(
            title="Realized vs Unrealized P&L per Lot",
            xaxis_title="Lot ID",
            yaxis_title="P&L (₹)",
            barmode='stack',
            height=400,
            margin=dict(l=10, r=10, t=50, b=10),
            font=dict(size=10),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
        )
        st.plotly_chart(fig_lots, use_container_width=True,
                        config={'displayModeBar': False, 'responsive': True})

    st.markdown("### 📌 Lot Status Summary")
    fully_sold = len(lot_pnl_df[lot_pnl_df['Status'] == "✅ Fully Sold"])
    sell_now = len(lot_pnl_df[lot_pnl_df['Status'] == "🎯 SELL NOW"])
    holding = len(lot_pnl_df[lot_pnl_df['Status'] == "⏳ Holding"])

    col_st1, col_st2, col_st3 = st.columns(3)
    with col_st1:
        st.metric("✅ Fully Sold Lots", fully_sold)
    with col_st2:
        st.metric("🎯 Ready to Sell", sell_now)
    with col_st3:
        st.metric("⏳ Still Holding", holding)

# ------------------------------------------------------------
# PREDICTIONS
# ------------------------------------------------------------
st.divider()
st.subheader("🔮 Next-Day Gold Price Prediction")

if predictions:
    col_pred1, col_pred2, col_pred3 = st.columns(3)

    with col_pred1:
        if 'gold' in predictions:
            p = predictions['gold']
            arrow = "🔼" if p['change_pct'] > 0 else ("🔽" if p['change_pct'] < 0 else "➡️")
            st.metric("🌍 Gold (COMEX)", f"${p['predicted_open']:,.2f}",
                      delta=f"{p['change_pct']:+.2f}% {arrow}")
            st.caption(f"Last: ${p['last_close']:,.2f}")

    with col_pred2:
        if 'usdinr' in predictions:
            p = predictions['usdinr']
            arrow = "🔼" if p['change_pct'] > 0 else ("🔽" if p['change_pct'] < 0 else "➡️")
            st.metric("💱 USD/INR", f"₹{p['predicted_open']:,.4f}",
                      delta=f"{p['change_pct']:+.3f}% {arrow}")
            st.caption(f"Last: ₹{p['last_close']:,.4f}")

    with col_pred3:
        if 'setfgold' in predictions:
            p = predictions['setfgold']
            arrow = "🔼" if p['change_pct'] > 0 else ("🔽" if p['change_pct'] < 0 else "➡️")
            st.metric("🥇 SETFGOLD (NSE)", f"₹{p['predicted_open']:,.2f}",
                      delta=f"{p['change_pct']:+.2f}% {arrow}")
            st.caption(f"Last: ₹{p['last_close']:,.2f}")

if 'gold' in predictions and 'usdinr' in predictions and 'setfgold' in predictions:
    gold_chg = predictions['gold']['change_pct']
    inr_chg = predictions['usdinr']['change_pct']
    etf_chg = predictions['setfgold']['change_pct']

    if gold_chg > 0.3 and inr_chg > 0:
        st.success(f"🟢 **STRONG BUY** — Gold {gold_chg:+.2f}% + INR weak {inr_chg:+.3f}% → Expected: {etf_chg:+.2f}%")
    elif gold_chg > 0.3 and inr_chg <= 0:
        st.success(f"🟢 **BUY (Mild)** — Gold {gold_chg:+.2f}%, INR strong. Expected: {etf_chg:+.2f}%")
    elif gold_chg < -0.3 and inr_chg > 0:
        st.warning(f"🟡 **HOLD / WAIT** — Gold {gold_chg:+.2f}%, INR weak. Expected: {etf_chg:+.2f}%")
    elif gold_chg < -0.3 and inr_chg <= 0:
        st.error(f"🔴 **SELL / AVOID** — Gold {gold_chg:+.2f}% + INR strong {inr_chg:+.3f}% → Expected: {etf_chg:+.2f}%")
    else:
        st.info(f"⚪ **NEUTRAL** — Gold {gold_chg:+.2f}%, INR {inr_chg:+.3f}%. Expected: {etf_chg:+.2f}%")

# ------------------------------------------------------------
# TRANSACTION ENTRY
# ------------------------------------------------------------
st.divider()
st.subheader("➕ Add Transaction")

tab_buy, tab_sell = st.tabs(["🟢 Buy", "🔴 Sell"])

with tab_buy:
    with st.form("buy_form", clear_on_submit=True):
        col_b1, col_b2, col_b3 = st.columns(3)

        with col_b1:
            buy_date = st.date_input("Buy Date", value=_ist_today())

        with col_b2:
            buy_shares = st.number_input("Number of Units", min_value=1, value=1, step=1)

        with col_b3:
            default_price = current_price if current_price else 0.0
            buy_price = st.number_input("Price per Unit (₹)", min_value=0.01,
                                        value=float(default_price), step=0.01)

        buy_notes = st.text_input("Notes (optional)")

        submitted = st.form_submit_button("✅ Record Buy", use_container_width=True, type="primary")

        if submitted:
            if buy_shares > 0 and buy_price > 0:
                try:
                    add_buy(buy_date, int(buy_shares), float(buy_price), buy_notes)
                    st.success(f"✅ Recorded: {buy_shares} units @ ₹{buy_price:,.2f}")
                    st.cache_data.clear()
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ Failed to save: {e}")
            else:
                st.error("Please enter valid shares and price.")

with tab_sell:
    if portfolio['net_shares'] <= 0:
        st.warning("⚠️ No unsold holdings to sell.")
    else:
        default_lot_shares = next_lot['shares'] if next_lot else 1
        default_lot_price = next_lot['target_price'] if next_lot else (
            current_price if current_price else portfolio['avg_cost'] * 1.20
        )

        with st.form("sell_form", clear_on_submit=True):
            col_s1, col_s2, col_s3 = st.columns(3)

            with col_s1:
                sell_date = st.date_input("Sell Date", value=_ist_today())

            with col_s2:
                sell_shares = st.number_input(
                    "Number of Units",
                    min_value=1,
                    max_value=portfolio['net_shares'],
                    value=min(default_lot_shares, portfolio['net_shares']),
                    step=1
                )

            with col_s3:
                sell_price = st.number_input(
                    "Price per Unit (₹)",
                    min_value=0.01,
                    value=float(default_lot_price),
                    step=0.01
                )

            sell_notes = st.text_input("Notes (optional)")

            submitted = st.form_submit_button("✅ Record Sell", use_container_width=True, type="primary")

            if submitted:
                if sell_shares > 0 and sell_price > 0:
                    try:
                        add_sell(sell_date, int(sell_shares), float(sell_price),
                                 portfolio['avg_cost'], sell_notes)
                        st.success(f"✅ Sold: {sell_shares} units @ ₹{sell_price:,.2f}")
                        st.cache_data.clear()
                        st.rerun()
                    except Exception as e:
                        st.error(f"❌ Failed to save: {e}")
                else:
                    st.error("Please enter valid shares and price.")

# ------------------------------------------------------------
# TRANSACTION HISTORY
# ------------------------------------------------------------
st.divider()
st.subheader("📜 Transaction History")

col_h1, col_h2 = st.columns(2)

with col_h1:
    st.markdown("### 🟢 Buy Transactions")
    if buys_df.empty:
        st.info("No buy transactions yet.")
    else:
        display_buys = buys_df[['id', 'buy_date', 'shares', 'price', 'invested_amount', 'notes']].copy()
        display_buys.columns = ['ID', 'Date', 'Units', 'Price', 'Invested (₹)', 'Notes']
        st.dataframe(display_buys, hide_index=True, use_container_width=True)
        st.caption(f"Lifetime invested: **₹{portfolio['lifetime_invested']:,.2f}**")

with col_h2:
    st.markdown("### 🔴 Sell Transactions")
    if sells_df.empty:
        st.info("No sell transactions yet.")
    else:
        display_sells = sells_df[['id', 'sell_date', 'shares', 'price', 'sold_amount', 'profit', 'notes']].copy()
        display_sells.columns = ['ID', 'Date', 'Units', 'Price', 'Sold (₹)', 'Profit (₹)', 'Notes']
        st.dataframe(display_sells, hide_index=True, use_container_width=True)
        st.caption(f"Total sold: **₹{portfolio['total_sold_amount']:,.2f}** · FIFO Profit: **₹{portfolio['total_profit']:,.2f}**")

# ------------------------------------------------------------
# DELETE TRANSACTION
# ------------------------------------------------------------
with st.expander("🗑️ Delete a Transaction"):
    col_d1, col_d2 = st.columns(2)

    with col_d1:
        if not buys_df.empty:
            buy_to_delete = st.selectbox("Select Buy to delete", buys_df['id'].tolist())
            if st.button("🗑️ Delete Buy", key="del_buy"):
                delete_buy(int(buy_to_delete))
                st.cache_data.clear()
                st.success(f"Deleted buy #{buy_to_delete}")
                st.rerun()

    with col_d2:
        if not sells_df.empty:
            sell_to_delete = st.selectbox("Select Sell to delete", sells_df['id'].tolist())
            if st.button("🗑️ Delete Sell", key="del_sell"):
                delete_sell(int(sell_to_delete))
                st.cache_data.clear()
                st.success(f"Deleted sell #{sell_to_delete}")
                st.rerun()

# ------------------------------------------------------------
# FOOTER
# ------------------------------------------------------------
st.divider()
st.caption("""
🥇 **Gold Trading Portfolio Tracker** · Built by S. Mohapatra

⚠️ **Disclaimer:** For educational and personal tracking purposes only. 
Not investment advice. Prices from Yahoo Finance (may be delayed).

**Accounting Method:** FIFO (First-In-First-Out) — matches Indian tax reporting standard.
**Sell Strategy:** 20% profit target, cheapest lot first.
""")
