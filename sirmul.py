
import base64
import json
import random
import re
import string
from datetime import datetime
from io import BytesIO
from pathlib import Path
from urllib.parse import unquote

import pandas as pd
import qrcode
import streamlit as st


# =========================
# GOOGLE SHEET CSV URL
# GANTI DENGAN LINK CSV EXPORT MASING-MASING
# =========================
USERS_SHEET_URL = "https://docs.google.com/spreadsheets/d/PASTE_USER_SHEET_ID/export?format=csv"

INTAKE_SHEET_URL = "https://docs.google.com/spreadsheets/d/PASTE_INTAKE_SHEET_ID/export?format=csv"


APP_DIR = Path(__file__).parent
DATA_DIR = APP_DIR / "data"

LOCAL_USERS_FILE = DATA_DIR / "data_user_sirsak.csv"
INTAKE_FILE = DATA_DIR / "data_intake_sirsak.csv"

LOGO_SIRSAK = APP_DIR / "gbr" / "sirsak.jpg"
LOGO_POLIJE = APP_DIR / "gbr" / "polije.png"


USER_COLUMNS = [
    "Id_User",
    "Nama",
    "No_HP",
    "Email",
    "No_Rek",
    "Sir_Point",
    "User_Type",
    "Source",
    "Created_At",
]

INTAKE_COLUMNS = [
    "transaction_code",
    "timestamp",
    "rvm_id",
    "location",
    "identity_method",
    "user_id",
    "nama",
    "no_hp",
    "email",
    "package_count",
    "capacity",
    "status",
    "payload",
]


DEFAULT_RVM = {
    "rvm_id": "RVM-POLIJE-001",
    "location": "Kampus 4 Politeknik Negeri Jember",
}


def now_text():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


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


def ensure_columns(df, columns):
    for column in columns:
        if column not in df.columns:
            df[column] = ""

    return df[columns].fillna("")


def read_local_users():
    if not LOCAL_USERS_FILE.exists():
        return pd.DataFrame(columns=USER_COLUMNS)

    return ensure_columns(
        pd.read_csv(LOCAL_USERS_FILE, dtype=str),
        USER_COLUMNS,
    )


@st.cache_data(ttl=60)
def load_users():
    local_df = read_local_users()

    try:
        sheet_df = pd.read_csv(USERS_SHEET_URL, dtype=str)
        sheet_df = ensure_columns(sheet_df, USER_COLUMNS)
        sheet_df["Source"] = sheet_df["Source"].where(
            sheet_df["Source"] != "",
            "google_sheet",
        )
    except Exception:
        sheet_df = pd.DataFrame(columns=USER_COLUMNS)

    df = pd.concat([sheet_df, local_df], ignore_index=True)

    df = ensure_columns(df, USER_COLUMNS)

    df["No_HP"] = df["No_HP"].apply(normalize)

    df = df.sort_values("Source").drop_duplicates(
        subset=["No_HP"],
        keep="last",
    )

    return df.reset_index(drop=True)


def save_local_user(user_data):
    DATA_DIR.mkdir(exist_ok=True)

    local_df = read_local_users()

    local_df = pd.concat(
        [local_df, pd.DataFrame([user_data])],
        ignore_index=True,
    )

    local_df = ensure_columns(local_df, USER_COLUMNS)

    local_df.to_csv(LOCAL_USERS_FILE, index=False)

    load_users.clear()


@st.cache_data(ttl=60)
def load_intakes_cloud():
    try:
        df = pd.read_csv(INTAKE_SHEET_URL, dtype=str)
        return ensure_columns(df, INTAKE_COLUMNS)
    except Exception:
        return pd.DataFrame(columns=INTAKE_COLUMNS)


def read_intakes():
    local_df = pd.DataFrame(columns=INTAKE_COLUMNS)

    if INTAKE_FILE.exists():
        local_df = pd.read_csv(INTAKE_FILE, dtype=str)

    cloud_df = load_intakes_cloud()

    df = pd.concat([cloud_df, local_df], ignore_index=True)

    return ensure_columns(df, INTAKE_COLUMNS)


def save_intake(intake):
    DATA_DIR.mkdir(exist_ok=True)

    intakes = read_intakes()

    intakes = pd.concat(
        [intakes, pd.DataFrame([intake])],
        ignore_index=True,
    )

    intakes = ensure_columns(intakes, INTAKE_COLUMNS)

    intakes.to_csv(INTAKE_FILE, index=False)


def generate_transaction_code():
    suffix = "".join(
        random.choices(string.ascii_uppercase + string.digits, k=6)
    )

    return f"TRX-{datetime.now().strftime('%Y%m%d')}-{suffix}"


def generate_user_id():
    suffix = "".join(
        random.choices(string.ascii_uppercase + string.digits, k=6)
    )

    return f"USR-{datetime.now().strftime('%Y%m%d')}-{suffix}"


def build_qr_buffer(data):
    qr = qrcode.make(data)

    buf = BytesIO()

    qr.save(buf)

    buf.seek(0)

    return buf


def encode_payload(payload):
    payload_json = json.dumps(
        payload,
        separators=(",", ":"),
        ensure_ascii=True,
    )

    return base64.urlsafe_b64encode(
        payload_json.encode("utf-8")
    ).decode("ascii")


def build_intake_payload(
    transaction_code,
    rvm_id,
    package_count,
    capacity,
):
    return {
        "transaction_code": transaction_code,
        "rvm_id": rvm_id,
        "package_count": int(package_count),
        "capacity": float(capacity),
    }


def build_package_code(transaction_code, index):
    return f"{transaction_code}-{index:03d}"


def find_user_by_phone(df, phone):
    phone = normalize(phone)

    if not phone:
        return None

    match = df[df["No_HP"] == phone]

    if match.empty:
        return None

    return match.iloc[0].to_dict()


def make_new_user(name, phone, email, location):
    return {
        "Id_User": generate_user_id(),
        "Nama": name.strip() or f"Nasabah {normalize(phone)}",
        "No_HP": normalize(phone),
        "Email": email.strip(),
        "No_Rek": "",
        "Sir_Point": location,
        "User_Type": "nasabah",
        "Source": "local_auto_create",
        "Created_At": now_text(),
    }


def render_header():
    logo_left, title_col, logo_right = st.columns(
        [1, 4, 1],
        vertical_alignment="center",
    )

    with logo_left:
        if LOGO_SIRSAK.exists():
            st.image(LOGO_SIRSAK, width=80)

    with title_col:
        st.markdown(
            "<h1 style='text-align: center;'>SircleBox - Package Intake</h1>",
            unsafe_allow_html=True,
        )

    with logo_right:
        if LOGO_POLIJE.exists():
            st.image(LOGO_POLIJE, width=80)


def render_stickers(transaction_code, package_count):
    st.subheader("Sticker Paket")

    cols = st.columns(min(package_count, 3))

    for index in range(1, package_count + 1):
        package_code = build_package_code(
            transaction_code,
            index,
        )

        sticker_payload = json.dumps(
            {
                "transaction_code": transaction_code,
                "package_code": package_code,
            },
            separators=(",", ":"),
        )

        with cols[(index - 1) % len(cols)]:
            st.caption(package_code)
            st.image(build_qr_buffer(sticker_payload), width=170)


def record_intake(
    identity_method,
    user_data,
    transaction_code,
    rvm_id,
    location,
    package_count,
    capacity,
    payload,
):
    intake = {
        "transaction_code": transaction_code,
        "timestamp": now_text(),
        "rvm_id": rvm_id,
        "location": location,
        "identity_method": identity_method,
        "user_id": user_data.get("Id_User", ""),
        "nama": user_data.get("Nama", ""),
        "no_hp": user_data.get("No_HP", ""),
        "email": user_data.get("Email", ""),
        "package_count": str(package_count),
        "capacity": str(capacity),
        "status": "intake_recorded",
        "payload": json.dumps(
            payload,
            separators=(",", ":"),
            ensure_ascii=True,
        ),
    }

    save_intake(intake)

    return intake


st.set_page_config(
    page_title="SircleBox Intake",
    page_icon="S",
    layout="centered",
)

render_header()

users_df = load_users()

with st.sidebar:
    st.header("RVM")

    rvm_id = st.text_input(
        "RVM ID",
        value=DEFAULT_RVM["rvm_id"],
    )

    location = st.text_input(
        "Lokasi",
        value=DEFAULT_RVM["location"],
    )

    capacity = st.slider(
        "Kapasitas terisi (%)",
        min_value=0,
        max_value=100,
        value=35,
    )

st.subheader("Intake Paket")

identity_method = st.radio(
    "Metode identitas",
    [
        "Phone Number",
        "Donate Anonymous",
        "QR Nasabah App",
    ],
    horizontal=True,
)

package_count = st.number_input(
    "Jumlah paket",
    min_value=1,
    max_value=20,
    value=1,
    step=1,
)

user_data = {}

phone = ""
email = ""
name = ""

can_record = True


if identity_method == "Phone Number":

    phone = st.text_input("No HP")

    email = st.text_input("Email (opsional)")

    if phone:

        phone = normalize(phone)

        existing_user = find_user_by_phone(users_df, phone)

        if existing_user:

            user_data = existing_user

            st.success(
                f"Nasabah ditemukan: {existing_user['Nama']}"
            )

        else:

            st.info(
                "Nomor belum terdaftar. "
                "Nasabah baru akan dibuat di CSV lokal simulasi."
            )

            name = st.text_input("Nama nasabah baru")

            can_record = bool(name.strip())

            if not can_record:
                st.warning(
                    "Isi nama nasabah baru untuk melanjutkan."
                )
    else:
        can_record = False

elif identity_method == "Donate Anonymous":

    user_data = {
        "Id_User": "DEFAULT-DONOR",
        "Nama": "Donasi Anonymous",
        "No_HP": "",
        "Email": "",
    }

    st.info(
        "Transaksi akan dicatat sebagai donasi anonymous."
    )

else:

    transaction_code = (
        st.session_state.get("qr_transaction_code")
        or generate_transaction_code()
    )

    st.session_state.qr_transaction_code = transaction_code

    payload = build_intake_payload(
        transaction_code,
        rvm_id,
        package_count,
        capacity,
    )

    encrypted_payload = encode_payload(payload)

    st.info(
        "QR ini mensimulasikan payload "
        "yang discan oleh aplikasi Nasabah."
    )

    st.image(build_qr_buffer(encrypted_payload), width=240)

    st.code(encrypted_payload)

    user_data = {
        "Id_User": "JWT-NASABAH-APP",
        "Nama": "Nasabah App",
        "No_HP": "",
        "Email": "",
    }


if identity_method != "QR Nasabah App":

    transaction_code = (
        st.session_state.get("transaction_code")
        or generate_transaction_code()
    )

    st.session_state.transaction_code = transaction_code

    payload = build_intake_payload(
        transaction_code,
        rvm_id,
        package_count,
        capacity,
    )

else:

    payload = build_intake_payload(
        st.session_state.qr_transaction_code,
        rvm_id,
        package_count,
        capacity,
    )

    transaction_code = st.session_state.qr_transaction_code


st.divider()

st.write(f"Transaction code: `{transaction_code}`")

record_label = "Catat Intake"

if identity_method == "QR Nasabah App":
    record_label = "Konfirmasi Scan Nasabah App"


if st.button(
    record_label,
    type="primary",
    disabled=not can_record,
):

    if identity_method == "Phone Number" and not user_data:

        user_data = make_new_user(
            name,
            phone,
            email,
            location,
        )

        save_local_user(user_data)

    intake = record_intake(
        identity_method=identity_method,
        user_data=user_data,
        transaction_code=transaction_code,
        rvm_id=rvm_id,
        location=location,
        package_count=package_count,
        capacity=capacity,
        payload=payload,
    )

    st.session_state.transaction_code = (
        generate_transaction_code()
    )

    st.session_state.qr_transaction_code = (
        generate_transaction_code()
    )

    sir_point = format_sir_point(location)

    st.success(
        f"Intake tercatat untuk {intake['nama']} "
        f"di SirclePoint {sir_point}. "
        "Tempel sticker pada paket sebelum memasukkan ke box."
    )

    render_stickers(
        transaction_code,
        int(package_count),
    )

    st.caption(
        f"Data intake disimpan ke {INTAKE_FILE}"
    )


with st.expander("Riwayat intake lokal"):

    intakes_df = read_intakes()

    if intakes_df.empty:
        st.info("Belum ada intake lokal.")
    else:
        st.dataframe(
            intakes_df.tail(10),
            use_container_width=True,
        )
