import streamlit as st
import pandas as pd
import qrcode
from io import BytesIO
import random
import string

# LINK CSV GOOGLE SHEET
SHEET_URL = "https://docs.google.com/spreadsheets/d/1k5WjvGAOv30qMrOaJaxlyNhjQaN-x5-yeUIbOCPC25s/export?format=csv&gid=782361382"

@st.cache_data
def load_data():
    return pd.read_csv(SHEET_URL, dtype=str)

df = load_data()

st.title("Smart Trash - QR Generator")

# ===== NORMALISASI NO HP =====
def normalize(phone):
    phone = str(phone).replace("+62", "0").strip()
    return phone

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

        st.success(f"User: {user_data['Nama']}")
        st.image(buf)

        # Optional debug
        st.caption(qr_data)
