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
import requests
import streamlit as st

try:
    import gspread
    from google.oauth2.service_account import Credentials
except ImportError:
    gspread = None
    Credentials = None


# Default Google Sheet: data_simulsak
DEFAULT_SPREADSHEET_ID = "1MqVCR_cWp2Gvk_JEgZymDpmpdciFI9lOvDIk4RubgvY"
DEFAULT_USER_WORKSHEET = "data_user_sirsak"
DEFAULT_INTAKE_WORKSHEET = "data_intake_sirsak"
USER_CSV_URL = (
    "https://docs.google.com/spreadsheets/d/"
    f"{DEFAULT_SPREADSHEET_ID}/export?format=csv&gid=1994936668"
)

APP_DIR = Path(__file__).parent
DATA_DIR = APP_DIR / "data"
LOCAL_USERS_FILE = DATA_DIR / "data_user_sirsak.csv"
INTAKE_FILE = DATA_DIR / "data_intake_sirsak.csv"
LOGO_SIRSAK = APP_DIR / "gbr" / "sirsak.jpg"
LOGO_POLIJE = APP_DIR / "gbr" / "polije.png"

GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

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


def get_secret_value(section, key, default=""):
    try:
        return st.secrets.get(section, {}).get(key, default)
    except Exception:
        return default


def google_sheets_enabled():
    return bool(
        gspread
        and Credentials
        and get_secret_value("google_sheets", "enable_service_account", "false").lower() == "true"
        and get_secret_value("gcp_service_account", "client_email")
    )


def apps_script_enabled():
    return bool(get_secret_value("apps_script", "web_app_url"))


@st.cache_resource
def get_google_client():
    service_account_info = dict(st.secrets["gcp_service_account"])
    if "private_key" in service_account_info:
        service_account_info["private_key"] = service_account_info["private_key"].replace("\\n", "\n")
    credentials = Credentials.from_service_account_info(
        service_account_info,
        scopes=GOOGLE_SCOPES,
    )
    return gspread.authorize(credentials)


def get_google_worksheet(kind, columns):
    spreadsheet_id = get_secret_value("google_sheets", "spreadsheet_id", DEFAULT_SPREADSHEET_ID)
    worksheet_key = f"{kind}_worksheet"
    default_worksheet = DEFAULT_USER_WORKSHEET if kind == "user" else DEFAULT_INTAKE_WORKSHEET
    worksheet_name = get_secret_value("google_sheets", worksheet_key, default_worksheet)

    spreadsheet = get_google_client().open_by_key(spreadsheet_id)
    try:
        worksheet = spreadsheet.worksheet(worksheet_name)
    except gspread.WorksheetNotFound:
        worksheet = spreadsheet.add_worksheet(
            title=worksheet_name,
            rows=1000,
            cols=max(len(columns), 1),
        )
        worksheet.append_row(columns)

    header = worksheet.row_values(1)
    if not header:
        worksheet.append_row(columns)
    elif header != columns:
        worksheet.update("A1", [columns])
    return worksheet


def read_google_sheet(kind, columns):
    worksheet = get_google_worksheet(kind, columns)
    records = worksheet.get_all_records()
    if not records:
        return pd.DataFrame(columns=columns)
    return ensure_columns(pd.DataFrame(records, dtype=str), columns)


def append_google_row(kind, row, columns):
    worksheet = get_google_worksheet(kind, columns)
    worksheet.append_row([row.get(column, "") for column in columns], value_input_option="USER_ENTERED")


def append_apps_script_row(kind, row):
    url = get_secret_value("apps_script", "web_app_url")
    secret = get_secret_value("apps_script", "secret", "")
    payload = {
        "kind": kind,
        "secret": secret,
        "row": row,
    }
    response = requests.post(url, json=payload, timeout=15)
    response.raise_for_status()
    data = response.json()
    if not data.get("ok"):
        raise RuntimeError(data.get("error", "Apps Script write failed"))


def storage_label():
    if apps_script_enabled():
        return "Google Sheets via Apps Script"
    if google_sheets_enabled():
        spreadsheet_id = get_secret_value("google_sheets", "spreadsheet_id", DEFAULT_SPREADSHEET_ID)
        worksheet = get_secret_value("google_sheets", "intake_worksheet", DEFAULT_INTAKE_WORKSHEET)
        return f"Google Sheets `{spreadsheet_id}` / worksheet `{worksheet}`"
    return f"CSV lokal `{INTAKE_FILE}`"


def read_local_users():
    if not LOCAL_USERS_FILE.exists():
        return pd.DataFrame(columns=USER_COLUMNS)
    return ensure_columns(pd.read_csv(LOCAL_USERS_FILE, dtype=str), USER_COLUMNS)


@st.cache_data(ttl=60)
def load_users():
    local_df = read_local_users()
    if google_sheets_enabled():
        try:
            sheet_df = read_google_sheet("user", USER_COLUMNS)
            sheet_df["Source"] = sheet_df["Source"].where(sheet_df["Source"] != "", "google_sheets")
        except Exception as exc:
            st.warning(f"Gagal membaca Google Sheets, memakai data lokal. Detail: {exc}")
            sheet_df = pd.DataFrame(columns=USER_COLUMNS)
    else:
        sheet_df = pd.DataFrame(columns=USER_COLUMNS)

    if sheet_df.empty:
        try:
            sheet_df = pd.read_csv(USER_CSV_URL, dtype=str)
            sheet_df = ensure_columns(sheet_df, USER_COLUMNS)
            sheet_df["Source"] = sheet_df["Source"].where(sheet_df["Source"] != "", "google_sheet_csv")
        except Exception:
            sheet_df = pd.DataFrame(columns=USER_COLUMNS)

    df = pd.concat([sheet_df, local_df], ignore_index=True)
    df = ensure_columns(df, USER_COLUMNS)
    df["No_HP"] = df["No_HP"].apply(normalize)
    df = df.sort_values("Source").drop_duplicates(subset=["No_HP"], keep="last")
    return df.reset_index(drop=True)


def save_user(user_data):
    if apps_script_enabled():
        try:
            append_apps_script_row("user", user_data)
            load_users.clear()
            return
        except Exception as exc:
            st.warning(f"Gagal menyimpan user ke Apps Script, memakai CSV lokal. Detail: {exc}")
    elif google_sheets_enabled():
        try:
            append_google_row("user", user_data, USER_COLUMNS)
            load_users.clear()
            return
        except Exception as exc:
            st.warning(f"Gagal menyimpan user ke Google Sheets, memakai CSV lokal. Detail: {exc}")

    save_local_user(user_data)
    load_users.clear()


def save_local_user(user_data):
    DATA_DIR.mkdir(exist_ok=True)
    local_df = read_local_users()
    local_df = pd.concat([local_df, pd.DataFrame([user_data])], ignore_index=True)
    local_df = ensure_columns(local_df, USER_COLUMNS)
    local_df.to_csv(LOCAL_USERS_FILE, index=False)


def read_intakes():
    if google_sheets_enabled():
        try:
            return read_google_sheet("intake", INTAKE_COLUMNS)
        except Exception as exc:
            st.warning(f"Gagal membaca intake Google Sheets, memakai CSV lokal. Detail: {exc}")

    if not INTAKE_FILE.exists():
        return pd.DataFrame(columns=INTAKE_COLUMNS)
    return ensure_columns(pd.read_csv(INTAKE_FILE, dtype=str), INTAKE_COLUMNS)


def save_intake(intake):
    if apps_script_enabled():
        try:
            append_apps_script_row("intake", intake)
            return
        except Exception as exc:
            st.warning(f"Gagal menyimpan intake ke Apps Script, memakai CSV lokal. Detail: {exc}")

    if google_sheets_enabled():
        try:
            append_google_row("intake", intake, INTAKE_COLUMNS)
            return
        except Exception as exc:
            st.warning(f"Gagal menyimpan intake ke Google Sheets, memakai CSV lokal. Detail: {exc}")

    DATA_DIR.mkdir(exist_ok=True)
    intakes = read_intakes()
    intakes = pd.concat([intakes, pd.DataFrame([intake])], ignore_index=True)
    intakes = ensure_columns(intakes, INTAKE_COLUMNS)
    intakes.to_csv(INTAKE_FILE, index=False)


def generate_transaction_code():
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
    return f"TRX-{datetime.now().strftime('%Y%m%d')}-{suffix}"


def generate_user_id():
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
    return f"USR-{datetime.now().strftime('%Y%m%d')}-{suffix}"


def build_qr_buffer(data):
    qr = qrcode.make(data)
    buf = BytesIO()
    qr.save(buf)
    buf.seek(0)
    return buf


def encode_payload(payload):
    payload_json = json.dumps(payload, separators=(",", ":"), ensure_ascii=True)
    return base64.urlsafe_b64encode(payload_json.encode("utf-8")).decode("ascii")


def build_intake_payload(transaction_code, rvm_id, package_count, capacity):
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
    logo_left, title_col, logo_right = st.columns([1, 4, 1], vertical_alignment="center")
    with logo_left:
        st.image(LOGO_SIRSAK, width=80)
    with title_col:
        st.markdown(
            "<h1 style='text-align: center;'>SircleBox - Package Intake</h1>",
            unsafe_allow_html=True,
        )
    with logo_right:
        st.image(LOGO_POLIJE, width=80)


def render_stickers(transaction_code, package_count):
    st.subheader("Sticker Paket")
    cols = st.columns(min(package_count, 3))
    for index in range(1, package_count + 1):
        package_code = build_package_code(transaction_code, index)
        sticker_payload = json.dumps(
            {"transaction_code": transaction_code, "package_code": package_code},
            separators=(",", ":"),
        )
        with cols[(index - 1) % len(cols)]:
            st.caption(package_code)
            st.image(build_qr_buffer(sticker_payload), width=170)


def record_intake(identity_method, user_data, transaction_code, rvm_id, location, package_count, capacity, payload):
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
        "payload": json.dumps(payload, separators=(",", ":"), ensure_ascii=True),
    }
    save_intake(intake)
    return intake


st.set_page_config(page_title="SircleBox Intake", page_icon="S", layout="centered")
render_header()

users_df = load_users()

with st.sidebar:
    st.header("RVM")
    rvm_id = st.text_input("RVM ID", value=DEFAULT_RVM["rvm_id"])
    location = st.text_input("Lokasi", value=DEFAULT_RVM["location"])
    capacity = st.slider("Kapasitas terisi (%)", min_value=0, max_value=100, value=35)
    st.caption(f"Storage: {storage_label()}")

st.subheader("Intake Paket")
identity_method = st.radio(
    "Metode identitas",
    ["Phone Number", "Donate Anonymous", "QR Nasabah App"],
    horizontal=True,
)
package_count = st.number_input("Jumlah paket", min_value=1, max_value=20, value=1, step=1)

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
            st.success(f"Nasabah ditemukan: {existing_user['Nama']}")
        else:
            st.info("Nomor belum terdaftar. Nasabah baru akan dibuat di storage aktif.")
            name = st.text_input("Nama nasabah baru")
            can_record = bool(name.strip())
            if not can_record:
                st.warning("Isi nama nasabah baru untuk melanjutkan.")
    else:
        can_record = False

elif identity_method == "Donate Anonymous":
    user_data = {
        "Id_User": "DEFAULT-DONOR",
        "Nama": "Donasi Anonymous",
        "No_HP": "",
        "Email": "",
    }
    st.info("Transaksi akan dicatat sebagai donasi anonymous.")

else:
    transaction_code = st.session_state.get("qr_transaction_code") or generate_transaction_code()
    st.session_state.qr_transaction_code = transaction_code
    payload = build_intake_payload(transaction_code, rvm_id, package_count, capacity)
    encrypted_payload = encode_payload(payload)

    st.info("QR ini mensimulasikan payload yang discan oleh aplikasi Nasabah.")
    st.image(build_qr_buffer(encrypted_payload), width=240)
    st.code(encrypted_payload)

    user_data = {
        "Id_User": "JWT-NASABAH-APP",
        "Nama": "Nasabah App",
        "No_HP": "",
        "Email": "",
    }

if identity_method != "QR Nasabah App":
    transaction_code = st.session_state.get("transaction_code") or generate_transaction_code()
    st.session_state.transaction_code = transaction_code
    payload = build_intake_payload(transaction_code, rvm_id, package_count, capacity)
else:
    payload = build_intake_payload(st.session_state.qr_transaction_code, rvm_id, package_count, capacity)
    transaction_code = st.session_state.qr_transaction_code

st.divider()
st.write(f"Transaction code: `{transaction_code}`")

record_label = "Catat Intake"
if identity_method == "QR Nasabah App":
    record_label = "Konfirmasi Scan Nasabah App"

if st.button(record_label, type="primary", disabled=not can_record):
    if identity_method == "Phone Number" and not user_data:
        user_data = make_new_user(name, phone, email, location)
        save_user(user_data)

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

    st.session_state.transaction_code = generate_transaction_code()
    st.session_state.qr_transaction_code = generate_transaction_code()

    sir_point = format_sir_point(location)
    st.success(
        f"Intake tercatat untuk {intake['nama']} di SirclePoint {sir_point}. "
        "Tempel sticker pada paket sebelum memasukkan ke box."
    )
    render_stickers(transaction_code, int(package_count))
    st.caption(f"Data intake disimpan ke {storage_label()}")

with st.expander("Riwayat intake"):
    intakes_df = read_intakes()
    if intakes_df.empty:
        st.info("Belum ada intake di storage aktif.")
    else:
        st.dataframe(intakes_df.tail(10), use_container_width=True)
