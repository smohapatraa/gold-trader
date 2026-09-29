import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, timedelta, timezone
import gspread
from google.oauth2.service_account import Credentials

# ------------------------------------------------------------
# PAGE CONFIG
# ------------------------------------------------------------
st.set_page_config(
    page_title="Travel Planner",
    page_icon="🛫",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# ------------------------------------------------------------
# IST HELPERS
# ------------------------------------------------------------
def _ist_now():
    ist = timezone(timedelta(hours=5, minutes=30))
    return datetime.now(ist)

def _ist_today():
    return _ist_now().date()

# ============================================================
# LOGIN
# ============================================================
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    st.markdown("""
    <div style="text-align:center; padding: 40px 0;">
        <h1 style="color:#FFD700; font-size: 48px;">🛫 Travel Planner</h1>
        <p style="color:#888; font-size: 16px;">Please log in to continue</p>
    </div>
    """, unsafe_allow_html=True)

    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        with st.form("login_form"):
            u = st.text_input("Username", placeholder="Enter your username")
            p = st.text_input("Password", type="password", placeholder="Enter your password")
            submitted = st.form_submit_button("🔐 Log In", use_container_width=True, type="primary")

        if submitted:
            try:
                correct_user = st.secrets.get("MY_USERNAME", "")
                correct_pass = st.secrets.get("MY_PASSWORD", "")
            except Exception:
                correct_user = ""
                correct_pass = ""

            if u and p and u == correct_user and p == correct_pass:
                st.session_state.authenticated = True
                st.session_state.logged_in_user = u
                st.rerun()
            else:
                st.error("❌ Invalid username or password")

    st.stop()

current_user = st.session_state.get("logged_in_user", "user")

# ============================================================
# GOOGLE SHEETS
# ============================================================
@st.cache_resource
def get_gspread_client():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds_info = dict(st.secrets["gcp_service_account"])
    creds = Credentials.from_service_account_info(creds_info, scopes=scopes)
    return gspread.authorize(creds)

@st.cache_resource
def get_spreadsheet():
    return get_gspread_client().open_by_key(st.secrets["spreadsheet_id"])

TRAVEL_SHEET = "TRAVELLING PLAN"
TRAVEL_RANGE = "A1:H25"
TRAVEL_HEADERS = ["Date", "From Time", "To Time", "FROM PLACE", "TO PLACE", "REMARKS", "DAY", "PNR"]

# ------------------------------------------------------------
# READ / WRITE
# ------------------------------------------------------------
@st.cache_data(ttl=60, show_spinner=False)
def load_travel():
    try:
        ws = get_spreadsheet().worksheet(TRAVEL_SHEET)
        rows = ws.get(TRAVEL_RANGE)
        if not rows:
            return pd.DataFrame(columns=TRAVEL_HEADERS)
        first = rows[0]
        if first and [str(c).strip().lower() for c in first] == [h.lower() for h in TRAVEL_HEADERS]:
            data = rows[1:]
        else:
            data = rows
        n = len(TRAVEL_HEADERS)
        data = [(r + [""] * n)[:n] for r in data]
        df = pd.DataFrame(data, columns=TRAVEL_HEADERS)
        df = df.replace("", pd.NA).dropna(how="all").fillna("")
        return df
    except Exception as e:
        st.warning(f"Could not read {TRAVEL_SHEET}: {e}")
        return pd.DataFrame(columns=TRAVEL_HEADERS)

def save_travel(df):
    try:
        ws = get_spreadsheet().worksheet(TRAVEL_SHEET)
        values = [TRAVEL_HEADERS] + df.fillna("").astype(str).values.tolist()
        while len(values) < 25:
            values.append([""] * len(TRAVEL_HEADERS))
        ws.update(TRAVEL_RANGE, values[:25])
        st.cache_data.clear()
    except Exception as e:
        st.error(f"Could not write to {TRAVEL_SHEET}: {e}")

# ============================================================
# LOAD DATA
# ============================================================
travel_df = load_travel()

def parse_date_safe(d):
    try:
        return pd.to_datetime(d, errors='coerce', dayfirst=True)
    except Exception:
        return pd.NaT

travel_df['_parsed_date'] = travel_df['Date'].apply(parse_date_safe)
travel_df = travel_df.sort_values('_parsed_date', na_position='last').reset_index(drop=True)

today = _ist_today()
today_ts = pd.Timestamp(today)

upcoming_df = travel_df[travel_df['_parsed_date'] >= today_ts].copy()
today_df = travel_df[travel_df['_parsed_date'] == today_ts].copy()

def is_flight_row(row):
    remarks = str(row.get('REMARKS', '')).upper()
    frm = str(row.get('FROM PLACE', '')).upper()
    return 'IX' in remarks or ('TERMINAL' in frm) or ('MCT' in frm and 'BOM' in remarks)

flight_rows = travel_df[travel_df.apply(is_flight_row, axis=1)].copy()

# ============================================================
# HEADER
# ============================================================
col_head1, col_head2 = st.columns([4, 1])
with col_head1:
    st.markdown(f"### 🛫 Trip to India — Welcome, **{current_user.title()}**")
    if not upcoming_df.empty:
        next_event_date = upcoming_df['_parsed_date'].iloc[0]
        days_to_go = (next_event_date.date() - today).days
        if days_to_go == 0:
            st.caption(f"🕐 Today · {_ist_now().strftime('%H:%M:%S')} IST")
        elif days_to_go == 1:
            st.caption(f"🕐 Tomorrow · {next_event_date.strftime('%d-%b-%Y')}")
        else:
            st.caption(f"🕐 {days_to_go} days until next event · {next_event_date.strftime('%d-%b-%Y')}")
    else:
        st.caption(f"🕐 {_ist_now().strftime('%H:%M:%S')} IST")

with col_head2:
    if st.button("🚪 Logout", use_container_width=True):
        st.session_state["authenticated"] = False
        st.rerun()

st.divider()

# ============================================================
# FLIGHTS SECTION
# ============================================================
if not flight_rows.empty:
    st.subheader("✈️ Your Flights")

    for _, flight in flight_rows.iterrows():
        flight_date = flight['_parsed_date']
        flight_date_str = flight_date.strftime('%d-%b-%Y') if pd.notna(flight_date) else flight['Date']
        from_time = str(flight['From Time']).strip()
        remarks = str(flight['REMARKS']).strip()

        flight_nums = [w.strip().rstrip(',') for w in remarks.split(',') if 'IX' in w.upper()]
        flight_num_display = ', '.join(flight_nums) if flight_nums else remarks
        flight_num_clean = flight_nums[0] if flight_nums else ""

        frm = str(flight['FROM PLACE']).strip()
        to = str(flight['TO PLACE']).strip()

        pnr = str(flight.get('PNR', '')).strip() if 'PNR' in flight else ''
        if not pnr:
            for part in str(flight.get('REMARKS', '')).split(','):
                part = part.strip()
                if part and not part.upper().startswith('IX') and len(part) >= 5:
                    pnr = part
                    break

        col_f1, col_f2 = st.columns([3, 1])

        with col_f1:
            pnr_badge = (
                f'<p style="margin: 8px 0 0 0; font-size: 15px; '
                f'background: rgba(255,255,255,0.25); padding: 8px 14px; '
                f'border-radius: 8px; display: inline-block; '
                f'font-family: monospace; letter-spacing: 1px;">'
                f'🎫 PNR: <b>{pnr}</b></p>'
            ) if pnr else ''

            st.markdown(f"""
            <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                        padding: 20px; border-radius: 15px; color: white;">
                <p style="margin: 0; font-size: 13px; opacity: 0.9;">✈️ FLIGHT</p>
                <h3 style="margin: 8px 0; font-size: 22px;">{frm} → {to}</h3>
                <p style="margin: 5px 0; font-size: 14px;">
                    📅 <b>{flight_date_str}</b> &nbsp;·&nbsp; 
                    🕐 <b>{from_time}</b> &nbsp;·&nbsp; 
                    🔖 <b>{flight_num_display}</b>
                </p>
                {pnr_badge}
                <p style="margin: 8px 0 0 0; font-size: 12px; opacity: 0.8;">
                    {remarks}
                </p>
            </div>
            """, unsafe_allow_html=True)

        with col_f2:
            if flight_num_clean:
                status_url = f"https://www.airindiaexpress.com/flight-status?flightNumber={flight_num_clean}"
                st.link_button(
                    "🔍 Flight Status",
                    status_url,
                    use_container_width=True
                )
            if pnr:
                pnr_url = "https://www.airindiaexpress.com/manage-booking"
                st.link_button(
                    "🎫 PNR Status",
                    pnr_url,
                    use_container_width=True
                )
            st.caption("Opens Air India Express")

    st.divider()

# ============================================================
# TODAY / NEXT EVENT
# ============================================================
if not today_df.empty:
    st.subheader("📅 Today's Events")

    for _, event in today_df.iterrows():
        from_time = str(event['From Time']).strip()
        to_time = str(event['To Time']).strip()
        frm = str(event['FROM PLACE']).strip()
        to = str(event['TO PLACE']).strip()
        remarks = str(event['REMARKS']).strip()

        st.markdown(f"""
        <div style="background: linear-gradient(135deg, #232526 0%, #414345 100%);
                    padding: 18px; border-radius: 12px; color: white;
                    margin-bottom: 10px; border-left: 5px solid #FFD700;">
            <p style="margin: 0; font-size: 14px; color: #FFD700;">
                🕐 {from_time} — {to_time}
            </p>
            <h4 style="margin: 8px 0; font-size: 18px;">
                📍 {frm} → {to}
            </h4>
            <p style="margin: 5px 0; font-size: 13px; opacity: 0.9;">
                {remarks}
            </p>
        </div>
        """, unsafe_allow_html=True)

elif not upcoming_df.empty:
    next_event = upcoming_df.iloc[0]
    next_date = next_event['_parsed_date']
    days_away = (next_date.date() - today).days

    st.subheader("📅 Next Event")

    from_time = str(next_event['From Time']).strip()
    to_time = str(next_event['To Time']).strip()
    frm = str(next_event['FROM PLACE']).strip()
    to = str(next_event['TO PLACE']).strip()
    remarks = str(next_event['REMARKS']).strip()
    date_str = next_date.strftime('%A, %d-%b-%Y')

    st.markdown(f"""
    <div style="background: linear-gradient(135deg, #232526 0%, #414345 100%);
                padding: 22px; border-radius: 12px; color: white;
                border-left: 5px solid #4facfe;">
        <p style="margin: 0; font-size: 14px; color: #4facfe;">
            📅 {date_str} &nbsp;·&nbsp; in {days_away} day{'s' if days_away != 1 else ''}
        </p>
        <p style="margin: 10px 0 0 0; font-size: 14px; color: #FFD700;">
            🕐 {from_time} — {to_time}
        </p>
        <h3 style="margin: 8px 0; font-size: 20px;">
            📍 {frm} → {to}
        </h3>
        <p style="margin: 5px 0; font-size: 13px; opacity: 0.9;">
            {remarks}
        </p>
    </div>
    """, unsafe_allow_html=True)

else:
    st.info("🎉 No upcoming events. Enjoy your free time!")

st.divider()

# ============================================================
# UPCOMING 7 DAYS
# ============================================================
st.subheader("🗓️ Upcoming Days (Next 7)")

if not upcoming_df.empty:
    date_groups = upcoming_df.groupby('_parsed_date')
    count = 0

    for date_val, group in date_groups:
        if count >= 7:
            break
        if date_val < today_ts:
            continue

        day_name = date_val.strftime('%A')
        date_display = date_val.strftime('%d-%b-%Y')
        days_away = (date_val.date() - today).days

        label = "TODAY" if days_away == 0 else ("TOMORROW" if days_away == 1 else f"in {days_away} days")

        with st.expander(f"📅 {day_name}, {date_display}  —  {label}", expanded=(count < 2)):
            for _, event in group.iterrows():
                from_time = str(event['From Time']).strip()
                to_time = str(event['To Time']).strip()
                frm = str(event['FROM PLACE']).strip()
                to = str(event['TO PLACE']).strip()
                remarks = str(event['REMARKS']).strip()

                st.markdown(f"""
                **🕐 {from_time} — {to_time}**  
                **📍 {frm} → {to}**  
                {remarks}
                """)
                st.markdown("---")

        count += 1
else:
    st.info("No upcoming events in the next 7 days.")

st.divider()

# ============================================================
# EDIT SCHEDULE
# ============================================================
st.subheader("✏️ Edit Travel Schedule")

with st.expander("🔧 Open Editor (writes to Google Sheet)", expanded=False):
    st.caption("Edit any cell. Click **Save Changes** to write back to your Google Sheet.")

    editable_df = travel_df[TRAVEL_HEADERS].copy()

    edited = st.data_editor(
        editable_df,
        column_config={
            "Date": st.column_config.TextColumn("Date", width="small"),
            "From Time": st.column_config.TextColumn("From Time", width="small"),
            "To Time": st.column_config.TextColumn("To Time", width="small"),
            "FROM PLACE": st.column_config.TextColumn("From Place", width="medium"),
            "TO PLACE": st.column_config.TextColumn("To Place", width="medium"),
            "REMARKS": st.column_config.TextColumn("Remarks", width="large"),
            "DAY": st.column_config.TextColumn("Day", width="small"),
            "PNR": st.column_config.TextColumn("PNR", width="small"),
        },
        num_rows="dynamic",
        hide_index=True,
        use_container_width=True,
        key="travel_editor"
    )

    col_save, col_discard = st.columns([1, 1])
    with col_save:
        if st.button("💾 Save Changes", use_container_width=True, type="primary"):
            save_travel(edited)
            st.success("✅ Saved to Google Sheet")
            st.rerun()
    with col_discard:
        if st.button("↩️ Discard Changes", use_container_width=True):
            st.rerun()

# ============================================================
# FULL ITINERARY
# ============================================================
st.divider()
st.subheader("📋 Full Itinerary")

display_full = travel_df[TRAVEL_HEADERS].copy()
st.dataframe(
    display_full,
    hide_index=True,
    use_container_width=True,
    height=500
)

st.download_button(
    "📥 Download Itinerary (CSV)",
    data=display_full.to_csv(index=False).encode('utf-8'),
    file_name=f"travel_plan_{today}.csv",
    mime="text/csv"
)

# ------------------------------------------------------------
# FOOTER
# ------------------------------------------------------------
st.divider()
st.caption("🛫 Travel Planner · Built by S. Mohapatra · Data stored in Google Sheets")
