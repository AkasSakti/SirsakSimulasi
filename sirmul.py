import streamlit as st
import pandas as pd
import qrcode
from io import BytesIO
import random
import string
import re
from pathlib import Path
from urllib.parse import unquote

# LINK CSV GOOGLE SHEET
SHEET_URL = "https://docs.google.com/spreadsheets/d/1k5WjvGAOv30qMrOaJaxlyNhjQaN-x5-yeUIbOCPC25s/export?format=csv&gid=782361382"
APP_DIR = Path(__file__).parent
LOGO_SIRSAK = APP_DIR / "gbr" / "sirsak.jpg"
LOGO_POLIJE = APP_DIR / "gbr" / "polije.png"

@st.cache_data(ttl=60)
def load_data():
    return pd.read_csv(SHEET_URL, dtype=str)

df = load_data()

logo_left, title_col, logo_right = st.columns([1, 4, 1], vertical_alignment="center")
with logo_left:
    st.image(LOGO_SIRSAK, width=80)
with title_col:
    st.markdown("<h1 style='text-align: center;'>SircleBox - QR Generator</h1>", unsafe_allow_html=True)
with logo_right:
    st.image(LOGO_POLIJE, width=80)

# ===== NORMALISASI NO HP =====
def normalize(phone):
    phone = str(phone).strip()
    phone = re.sub(r"\.0$", "", phone)
    phone = re.sub(r"\D", "", phone)
    if phone.startswith("62"):
        phone = "0" + phone[2:]
    elif phone and not phone.startswith("0"):
        phone = "0" + phone
    return phone

def format_sir_point(sir_point):
    if pd.isna(sir_point):
        return "lokasi belum tersedia"
    sir_point = str(sir_point).strip()
    if not sir_point or sir_point.lower() == "nan":
        return "lokasi belum tersedia"
    sir_point = sir_point.strip('"')
    match = re.search(r"/maps/place/([^/@?]+)", sir_point)
    if match:
        return unquote(match.group(1)).replace("+", " ")
    return sir_point

df['No_HP'] = df['No_HP'].astype(str).apply(normalize)

# ===== INPUT =====
phone = st.text_input("Masukkan No HP")

if phone:
    phone = normalize(phone)

    user = df[df['No_HP'] == phone]

    if user.empty:
        st.error("Nomor HP tidak terdaftar")
    else:
        user_data = user.iloc[0]

        # ===== BIAR QR TIDAK BERUBAH TERUS =====
        if "last_phone" not in st.session_state:
            st.session_state.last_phone = ""

        if phone != st.session_state.last_phone:
            st.session_state.token = ''.join(random.choices(string.ascii_letters + string.digits, k=10))
            st.session_state.last_phone = phone

        token = st.session_state.token

        # ===== DATA QR =====
        qr_data = f"https://smarttrash-api.com/scan?user_id={user_data['Id_User']}&token={token}"

        # ===== GENERATE QR =====
        qr = qrcode.make(qr_data)
        buf = BytesIO()
        qr.save(buf)
        buf.seek(0)

        sir_point = format_sir_point(user_data.get("Sir_Point", ""))
        st.success(f"Terimakasih {user_data['Nama']} telah membuang sampah di SirclePoint {sir_point}")
        _, qr_col, _ = st.columns([1, 2, 1])
        with qr_col:
            st.image(buf)

        # Optional debug
        st.caption(qr_data)
