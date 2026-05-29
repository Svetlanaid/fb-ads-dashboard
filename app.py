import streamlit as st
import requests
import pandas as pd
import plotly.express as px
import os
import re
from dotenv import load_dotenv
from datetime import datetime, timedelta
from google.oauth2 import service_account
from googleapiclient.discovery import build

# 1. Загрузка настроек (Сначала из Secrets, если нет — из .env)
load_dotenv()
TOKEN = st.secrets.get("FB_ACCESS_TOKEN") or os.getenv("FB_ACCESS_TOKEN")
from supabase import create_client
supabase = create_client(
    st.secrets["SUPABASE_URL"],
    st.secrets["SUPABASE_KEY"]
)
# --- GOOGLE DRIVE ---
GDRIVE_COUNTRIES_ROOT_ID = "1r3dDnlhH3_2t2_5SmHsF_5W57UAwhRlH"

@st.cache_resource
def get_drive_service():
    try:
        creds = service_account.Credentials.from_service_account_info(
            st.secrets["gcp_service_account"],
            scopes=["https://www.googleapis.com/auth/drive.readonly"]
        )
        return build("drive", "v3", credentials=creds)
    except Exception as e:
        return None

@st.cache_data(ttl=3600)
def find_video_on_drive(creative_name):
    """Ищет видео на Google Drive по названию макета"""
    try:
        service = get_drive_service()
        if not service:
            return None

        def normalize_name(s):
            s = str(s or "").lower().strip()
            s = re.sub(r'\s+', ' ', s)
            return s

        def clean_for_drive(name):
            name = str(name or "").lower().strip()
            name = re.sub(r'\.(png|jpg|jpeg).*$', '', name, flags=re.IGNORECASE)
            name = re.sub(r'_\d{3,}', '', name)
            name = re.sub(r'\([^)]*\)', '', name)
            name = re.sub(r'\b\d{2,}\b', '', name)
            name = re.sub(r'(cost)[\s_\-]*[\d.,]+', r'\1', name, flags=re.IGNORECASE)
            name = re.sub(r'\s{2,}', ' ', name).strip()
            return name

        norm_creative = clean_for_drive(creative_name)

        # Получаем список папок стран внутри корневой
        country_folders = []
        page_token = None
        while True:
            resp = service.files().list(
                q=f"'{GDRIVE_COUNTRIES_ROOT_ID}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false",
                fields="nextPageToken, files(id, name)",
                pageSize=1000,
                pageToken=page_token
            ).execute()
            country_folders.extend(resp.get('files', []))
            page_token = resp.get('nextPageToken')
            if not page_token:
                break

        for country_folder in country_folders:
            # Ищем видео рекурсивно в папке страны
            result = search_video_in_folder(service, country_folder['id'], norm_creative, normalize_name)
            if result:
                return result

        return None
    except Exception as e:
        return None

def search_video_in_folder(service, folder_id, norm_creative, normalize_name):
    """Рекурсивный поиск видео в папке с пагинацией"""
    try:
        files = []
        page_token = None
        while True:
            resp = service.files().list(
                q=f"'{folder_id}' in parents and trashed=false",
                fields="nextPageToken, files(id, name, mimeType)",
                pageSize=1000,
                pageToken=page_token
            ).execute()
            files.extend(resp.get('files', []))
            page_token = resp.get('nextPageToken')
            if not page_token:
                break

        for f in files:
            if f['mimeType'] == 'application/vnd.google-apps.folder':
                result = search_video_in_folder(service, f['id'], norm_creative, normalize_name)
                if result:
                    return result
            elif f['mimeType'].startswith('video/'):
                file_name = re.sub(r'\.(mp4|mov|avi|webm|mkv|m4v).*$', '', f['name'], flags=re.IGNORECASE)
                file_clean = re.sub(r'\.(png|jpg|jpeg).*$', '', file_name, flags=re.IGNORECASE)
                file_clean = re.sub(r'_\d{3,}', '', file_clean)
                file_clean = re.sub(r'\([^)]*\)', '', file_clean)
                file_clean = re.sub(r'\b\d{2,}\b', '', file_clean)
                file_clean = re.sub(r'(cost)[\s_\-]*[\d.,]+', r'\1', file_clean, flags=re.IGNORECASE)
                file_clean = re.sub(r'\s{2,}', ' ', file_clean).strip().lower()
                if file_clean == norm_creative:
                    return f"https://drive.google.com/file/d/{f['id']}/preview"
        return None
    except Exception as e:
        print(f"Drive search error: {e}")
        return None

@st.cache_data(ttl=3600)
def find_image_on_drive(creative_name):
    """Ищет фото на Google Drive если видео не найдено"""
    try:
        service = get_drive_service()
        if not service:
            return None

        def clean_for_drive_img(name):
            name = str(name or "").lower().strip()
            name = re.sub(r'\.(png|jpg|jpeg|mp4|mov).*$', '', name, flags=re.IGNORECASE)
            name = re.sub(r'_\d{3,}', '', name)
            name = re.sub(r'\([^)]*\)', '', name)
            name = re.sub(r'\b\d{2,}\b', '', name)
            name = re.sub(r'(cost)[\s_\-]*[\d.,]+', r'\1', name, flags=re.IGNORECASE)
            name = re.sub(r'\s{2,}', ' ', name).strip()
            return name

        norm = clean_for_drive_img(creative_name)

        country_folders = []
        page_token = None
        while True:
            resp = service.files().list(
                q=f"'{GDRIVE_COUNTRIES_ROOT_ID}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false",
                fields="nextPageToken, files(id, name)",
                pageSize=1000,
                pageToken=page_token
            ).execute()
            country_folders.extend(resp.get('files', []))
            page_token = resp.get('nextPageToken')
            if not page_token:
                break

        def search_image_in_folder(folder_id):
            files = []
            page_token = None
            while True:
                resp = service.files().list(
                    q=f"'{folder_id}' in parents and trashed=false",
                    fields="nextPageToken, files(id, name, mimeType)",
                    pageSize=1000,
                    pageToken=page_token
                ).execute()
                files.extend(resp.get('files', []))
                page_token = resp.get('nextPageToken')
                if not page_token:
                    break
            for f in files:
                if f['mimeType'] == 'application/vnd.google-apps.folder':
                    result = search_image_in_folder(f['id'])
                    if result:
                        return result
                elif f['mimeType'].startswith('image/'):
                    fname = re.sub(r'\.(png|jpg|jpeg|webp)$', '', f['name'], flags=re.IGNORECASE)
                    fname = re.sub(r'_\d{3,}', '', fname)
                    fname = re.sub(r'\([^)]*\)', '', fname)
                    fname = re.sub(r'\b\d{2,}\b', '', fname)
                    fname = re.sub(r'(cost)[\s_\-]*[\d.,]+', r'\1', fname, flags=re.IGNORECASE)
                    fname = re.sub(r'\s{2,}', ' ', fname).strip().lower()
                    if fname == norm:
                        return f"https://drive.google.com/uc?id={f['id']}"
            return None

        for folder in country_folders:
            result = search_image_in_folder(folder['id'])
            if result:
                return result
        return None
    except:
        return None        
from streamlit_cookies_manager import EncryptedCookieManager

# --- БЛОК АВТОРИЗАЦИИ ---
if "users" in st.secrets:
    USERS = st.secrets["users"]

cookies = EncryptedCookieManager(
    prefix="fb_dashboard_",
    password=st.secrets.get("COOKIE_PASSWORD", "fallback_secret_key")
)
if not cookies.ready():
    st.stop()

if "authenticated" not in st.session_state:
    if cookies.get("authenticated") == "true":
        st.session_state["authenticated"] = True
    else:
        st.session_state["authenticated"] = False

def login_screen():
    st.markdown("<h2 style='text-align: center;'>Вход в систему</h2>", unsafe_allow_html=True)
    col_l, col_m, col_r = st.columns([1, 2, 1])
    with col_m:
        user = st.text_input("Логин", key="username")
        password = st.text_input("Пароль", type="password", key="password")
        if st.button("Войти", use_container_width=True):
            if user in USERS and str(USERS[user]) == str(password):
                st.session_state["authenticated"] = True
                cookies["authenticated"] = "true"
                cookies.save()
                st.rerun()
            else:
                st.error("Неверный логин или пароль")

if not st.session_state["authenticated"]:
    login_screen()
    st.stop()
# ------------------------------------------------
# ------------------------

st.set_page_config(page_title="FB Ads Dashboard", layout="wide")

# Восстанавливаем состояние из URL при перезагрузке
_params = st.query_params
if 'app_mode' not in st.session_state:
    st.session_state['app_mode'] = _params.get("app_mode", "📊 Общая статистика")
if 'main_tab' not in st.session_state:
    st.session_state['main_tab'] = _params.get("main_tab", "Водители")

# Синхронизируем URL с текущим состоянием
st.query_params["app_mode"] = st.session_state['app_mode']
st.query_params["main_tab"] = st.session_state['main_tab']

app_mode = st.session_state['app_mode']

# --- ВЕРХНЕЕ МЕНЮ ---
main_tab = st.session_state.get('main_tab', 'Водители')

if main_tab == "Клиенты":
    st.markdown("""
        <style>
        span[data-baseweb="tag"] { background-color: #1f77b4 !important; }
        div[data-testid="stSidebar"] div.stButton > button {
            background-color: #1f77b4 !important;
            color: white !important;
            border: none !important;
        }
        div[data-testid="stSidebar"] div.stButton > button:hover {
            background-color: #1565a8 !important;
        }
        </style>
    """, unsafe_allow_html=True)


    st.title("👥 Библиотека креативов — Клиенты")

    import openpyxl
    
    uploaded_file = st.file_uploader("Загрузите Excel файл с данными клиентов", type=["xlsx", "xls"])

    if not uploaded_file:
        with st.sidebar:
            st.divider()
            st.markdown("### 🧭 Навигация")
            if st.button("📊 Общая статистика", use_container_width=True, key="clnt_nav_stat_pre"):
                st.session_state['app_mode'] = "📊 Общая статистика"
                st.rerun()
            col_t1, col_t2 = st.columns(2)
            with col_t1:
                if st.button("🚗 Водители", use_container_width=True, key="tab_drivers_c_pre"):
                    st.session_state['main_tab'] = "Водители"
                    st.session_state['app_mode'] = "🖼️ Библиотека креативов"
                    st.rerun()
            with col_t2:
                if st.button("👥 Клиенты", use_container_width=True, key="tab_clients_c_pre"):
                    st.session_state['main_tab'] = "Клиенты"
                    st.rerun()
            st.divider()
            if st.button("🚪 Выйти", use_container_width=True, key="clnt_logout_pre"):
                st.session_state["authenticated"] = False
                cookies["authenticated"] = "false"
                cookies.save()
                st.rerun()

    if uploaded_file:
        df_clients = pd.read_excel(uploaded_file)
        
        # Нормализация названий кампаний
        def norm_campaign_clients(name):
            name = str(name or "")
            name = re.sub(r'\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)\b', '', name, flags=re.IGNORECASE)
            name = re.sub(r'\d{1,2}[./-]\d{1,2}', '', name)
            name = re.sub(r'\d{2,}', '', name)
            name = re.sub(r'\bcopy\b', '', name, flags=re.IGNORECASE)
            name = re.sub(r'[-–—.]', '', name)
            name = re.sub(r'\s{2,}', ' ', name).strip()
            return name

        def norm_adset_clients(name):
            name = str(name or "").lower().strip()
            if 'allcity' in name:
                return 'allcity'
            name = re.sub(r'\d{1,2}[./-]\d{1,2}', '', name)
            name = re.sub(r'\d+', '', name)
            name = re.sub(r'\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\b', '', name)
            name = re.sub(r'\b(copy|trg|target)\b', '', name)
            name = re.sub(r'[-–—_.]', ' ', name)
            return re.sub(r'\s{2,}', ' ', name).strip()

        df_clients['campaign_clean'] = df_clients['campaign_name'].apply(norm_campaign_clients)
        df_clients['adset_norm'] = df_clients['adset_name'].apply(norm_adset_clients)

        # Агрегация
        def safe_num(col):
            return pd.to_numeric(df_clients[col], errors='coerce').fillna(0) if col in df_clients.columns else 0

        df_clients['Показы'] = safe_num('impressions')
        df_clients['Клики'] = safe_num('clicks')
        df_clients['Результаты'] = safe_num('installs_count')
        df_clients['Затраты (RUB)'] = safe_num('cost_rubles_VAT')
        df_clients['Заказы'] = safe_num('bOrder_count')
        df_clients['Регистрации'] = safe_num('sLoginReady_unique')

        # Нормализация ad_name
        def clean_creative_name_local(name):
            if not name: return "Unknown creative"
            name = str(name).strip()
            name = re.sub(r'\([^)]*\)', '', name)
            name = re.sub(r'\.(png|jpg|jpeg).*$', '', name, flags=re.IGNORECASE)
            name = re.sub(r'[_-]?\d+\s*[xх]\s*\d+.*$', '', name, flags=re.IGNORECASE)
            name = re.sub(r'[xх]\d+.*$', '', name, flags=re.IGNORECASE)
            # Не режем если после числа идёт слово-количество
            name = re.sub(r'[_-]\d+(?!\s*(?:заказ|поездк|водител|клиент)).*$', '', name)
            name = re.sub(r'\d+\s*[кk]', '', name, flags=re.IGNORECASE)
            name = re.sub(r'[\d.,]*\s*млн\.?', '', name, flags=re.IGNORECASE)
            name = re.sub(r'\bмлн\b', '', name, flags=re.IGNORECASE)
            # Стираем только цифры и один пробел после cost/sal/fee, буквы не трогаем
            name = re.sub(r'(cost|sal|fee)\s*\d+\s*', lambda m: m.group(1) + ' ', name, flags=re.IGNORECASE)
            name = name.strip()
            name = re.sub(r'(exec)(O|0)(?=\b|_|\s)', r'\1O', name, flags=re.IGNORECASE)
            name = re.sub(r'[-_]{2,}', '_', name)
            name = re.sub(r'\s{2,}', ' ', name).strip()
            name = re.sub(r'[_-]+$', '', name)
            return name.strip() or "Unknown creative"

        def clean_cost(name):
            name = str(name or "")
            name = re.sub(r'\.(png|jpg|jpeg).*$', '', name, flags=re.IGNORECASE)
            name = re.sub(r'_\d{3,}', '', name)
            name = re.sub(r'\([^)]*\)', '', name)
            name = re.sub(r'(cost)\s*[\d.,]+\s*', lambda m: m.group(1) + ' ', name, flags=re.IGNORECASE)
            name = re.sub(r'(cost)\s*\.\d+\s*', lambda m: m.group(1) + ' ', name, flags=re.IGNORECASE)
            name = name.strip()
            name = re.sub(r'\b\d{2,}\b', '', name)
            name = re.sub(r'\s{2,}', ' ', name).strip()
            return name

        df_clients['Макет_raw'] = df_clients['ad_name'].apply(lambda x: clean_creative_name_local(str(x or "")))
        df_clients['Макет'] = df_clients['Макет_raw'].apply(clean_cost)
        df_clients = df_clients[
            df_clients['Макет'].notna() &
            (df_clients['Макет'].str.strip() != '') &
            (df_clients['Макет'].str.lower().str.strip() != 'nan') &
            (df_clients['Макет_raw'].str.lower().str.strip() != 'nan')
        ]

        # Фильтры в сайдбаре
        with st.sidebar:
            st.header("Настройки")
            all_camps_c = sorted(df_clients['campaign_clean'].unique().tolist())
            sel_camps_c = st.multiselect("Кампания:", all_camps_c, default=all_camps_c, key="clnt_camps")
            df_c_filtered = df_clients[df_clients['campaign_clean'].isin(sel_camps_c)]
            all_adsets_c = sorted(df_c_filtered['adset_norm'].unique().tolist())
            sel_adsets_c = st.multiselect("Группа (Ad Set):", all_adsets_c, default=all_adsets_c, key="clnt_adsets")

            if st.button("📊 Загрузить таблицы", use_container_width=True, key="clnt_tables"):
                st.session_state['clnt_table_loaded'] = True
                st.session_state['clnt_gallery_loaded'] = False
                st.rerun()

            if st.button("🖼️ Загрузить галерею", use_container_width=True, key="clnt_gallery"):
                st.session_state['clnt_gallery_loaded'] = True
                st.session_state['clnt_table_loaded'] = True
                st.rerun()

            st.divider()
            st.markdown("### 🧭 Навигация")
            if st.button("📊 Общая статистика", use_container_width=True, key="clnt_nav_stat"):
                st.session_state['app_mode'] = "📊 Общая статистика"
                st.rerun()
            col_t1, col_t2 = st.columns(2)
            with col_t1:
                if st.button("🚗 Водители", use_container_width=True, key="tab_drivers_c"):
                    st.session_state['main_tab'] = "Водители"
                    st.session_state['app_mode'] = "🖼️ Библиотека креативов"
                    st.rerun()
            with col_t2:
                if st.button("👥 Клиенты", use_container_width=True, key="tab_clients_c"):
                    st.session_state['main_tab'] = "Клиенты"
                    st.rerun()
            st.divider()
            if st.button("🚪 Выйти", use_container_width=True, key="clnt_logout"):
                st.session_state["authenticated"] = False
                cookies["authenticated"] = "false"
                cookies.save()
                st.rerun()
# Сбрасываем галерею если сменились фильтры
        filter_key_c = f"{sorted(sel_camps_c)}_{sorted(sel_adsets_c)}"
        if st.session_state.get('clnt_filter_key') != filter_key_c:
            st.session_state['clnt_filter_key'] = filter_key_c
            st.session_state['clnt_gallery_loaded'] = False
            st.session_state['clnt_table_loaded'] = False

        mask_c = df_c_filtered['adset_norm'].isin(sel_adsets_c)
        df_final = df_c_filtered[mask_c]

        if not st.session_state.get('clnt_table_loaded'):
            st.info("⬅️ Настройте фильтры и нажмите «Загрузить таблицы»")
        elif df_final.empty:
            st.warning("Нет данных по выбранным фильтрам.")
        else:
            import streamlit.components.v1 as components
            unique_camps_c = sorted(df_final['campaign_clean'].unique())
            all_tables_html_c = []

            for camp_name_c in unique_camps_c:
                df_cc = df_final[df_final['campaign_clean'] == camp_name_c].copy()

                
                table_c = df_cc.groupby('Макет').agg({
                    'Показы': 'sum',
                    'Клики': 'sum',
                    'Затраты (RUB)': 'sum',
                    'Результаты': 'sum',
                    'Заказы': 'sum',
                    'Регистрации': 'sum',
                    'adset_norm': lambda x: set(x.dropna().unique()),
                }).reset_index()
                table_c = table_c.rename(columns={'adset_norm': 'cities_set'})

                def format_cities_local(cities_set):
                    has_allcity = 'allcity' in cities_set
                    regular = len([c for c in cities_set if c != 'allcity' and c != ''])
                    if regular > 0 and has_allcity:
                        return f"{regular}+allcity"
                    elif regular > 0:
                        return str(regular)
                    elif has_allcity:
                        return "allcity"
                    return ""

                table_c['Города'] = table_c['cities_set'].apply(format_cities_local)
                table_c['Список городов'] = table_c['cities_set'].apply(
                    lambda x: ', '.join(sorted([c for c in x if c != '']))
                )
                table_c['CTR %'] = (table_c['Клики'] / table_c['Показы'] * 100).fillna(0)
                table_c['IPM'] = (table_c['Результаты'] / table_c['Показы'] * 1000).fillna(0)
                table_c['Цена за установку'] = (table_c['Затраты (RUB)'] / table_c['Результаты']).replace([float('inf'), float('nan')], 0)
                table_c['Цена за заказ'] = (table_c['Затраты (RUB)'] / table_c['Заказы']).replace([float('inf'), float('nan')], 0)
                table_c['Цена за регистрацию'] = (table_c['Затраты (RUB)'] / table_c['Регистрации']).replace([float('inf'), float('nan')], 0)

                # ИТОГО
                all_cities_c = set()
                for s in table_c['cities_set']:
                    all_cities_c.update(s)
                ttotals_c = pd.DataFrame([{
                    'Макет': 'ИТОГО',
                    'Показы': table_c['Показы'].sum(),
                    'Клики': table_c['Клики'].sum(),
                    'Затраты (RUB)': table_c['Затраты (RUB)'].sum(),
                    'Результаты': table_c['Результаты'].sum(),
                    'Заказы': table_c['Заказы'].sum(),
                    'Регистрации': table_c['Регистрации'].sum(),
                    'Города': format_cities_local(all_cities_c),
                    'Список городов': ', '.join(sorted([c for c in all_cities_c if c != ''])),
                    'CTR %': (table_c['Клики'].sum() / table_c['Показы'].sum() * 100) if table_c['Показы'].sum() > 0 else 0,
                    'IPM': (table_c['Результаты'].sum() / table_c['Показы'].sum() * 1000) if table_c['Показы'].sum() > 0 else 0,
                    'Цена за установку': (table_c['Затраты (RUB)'].sum() / table_c['Результаты'].sum()) if table_c['Результаты'].sum() > 0 else 0,
                    'Цена за заказ': (table_c['Затраты (RUB)'].sum() / table_c['Заказы'].sum()) if table_c['Заказы'].sum() > 0 else 0,
                    'Цена за регистрацию': (table_c['Затраты (RUB)'].sum() / table_c['Регистрации'].sum()) if table_c['Регистрации'].sum() > 0 else 0,
                }])

                full_c = pd.concat([table_c, ttotals_c], ignore_index=True)

                top3_c = set(
                    table_c[table_c['Регистрации'] > 0]
                    .nlargest(3, 'Регистрации')['Макет'].tolist()
                )

                full_c = full_c.rename(columns={'Результаты': 'Установки', 'Макет': camp_name_c})
                table_c_renamed = table_c.rename(columns={'Результаты': 'Установки'})
                top3_c = set(table_c_renamed[table_c_renamed['Регистрации'] > 0].nlargest(3, 'Регистрации')['Макет'].tolist())
                cols_c = [camp_name_c, 'Показы', 'Клики', 'CTR %', 'Установки', 'Цена за установку', 'IPM', 'Заказы', 'Цена за заказ', 'Регистрации', 'Цена за регистрацию', 'Города', 'Список городов']

                def fmt_c(col, val):
                    try:
                        if col in ['Показы', 'Клики', 'Установки', 'Заказы', 'Регистрации']:
                            return f"{int(float(val)):,}"
                        elif col == 'CTR %':
                            return f"{float(val):.2f}%"
                        elif col in ['Цена за установку', 'Цена за заказ', 'Цена за регистрацию']:
                            return f"{int(float(val)):,}"
                        elif col == 'IPM':
                            return f"{float(val):.2f}"
                        else:
                            return str(val) if val is not None else ''
                    except:
                        return str(val) if val is not None else ''

                html_rows_c = []
                header_c = ''.join([f'<th style="padding:6px 10px;text-align:left;border:1px solid var(--border-color);background:var(--header-bg);color:var(--text-color);font-weight:bold;white-space:nowrap;">{c}</th>' for c in cols_c])
                html_rows_c.append(f'<tr>{header_c}</tr>')

                for _, r in full_c[cols_c].iterrows():
                    nv = str(r[camp_name_c])
                    is_itogo = nv == 'ИТОГО'
                    is_top3 = nv in top3_c
                    if is_itogo:
                        row_style = 'font-weight:bold;background:var(--total-bg);color:var(--text-color);'
                        row_type = 'itogo'
                    elif is_top3:
                        row_style = 'background:var(--top3-bg);color:var(--text-color);'
                        row_type = 'top3'
                    else:
                        row_style = 'background:var(--row-bg);color:var(--text-color);'
                        row_type = 'normal'
                    cells = ''
                    for c in cols_c:
                        val = fmt_c(c, r[c])
                        align = 'left' if c in [camp_name_c, 'Список городов'] else 'right'
                        cells += f'<td style="padding:5px 10px;border:1px solid var(--border-color);color:var(--text-color);text-align:{align};white-space:nowrap;">{val}</td>'
                    html_rows_c.append(f'<tr data-rowtype="{row_type}" style="{row_style}">{cells}</tr>')

                all_tables_html_c.append((camp_name_c, ''.join(html_rows_c)))

                tbl_html_c = f"""
                <style>
                ::-webkit-scrollbar{{width:6px;height:6px}}
                ::-webkit-scrollbar-track{{background:transparent;border-radius:3px}}
                ::-webkit-scrollbar-thumb{{background:#444;border-radius:3px}}
                ::-webkit-scrollbar-thumb:hover{{background:#666}}
                </style>
                <script>
function applyThemeC() {{
  var dark = true;
  try {{
    var theme = window.parent.document.documentElement.getAttribute('data-theme');
    if (theme === 'light') {{ dark = false; }}
    else {{
      var bg = window.parent.getComputedStyle(window.parent.document.body).backgroundColor;
      var m = bg.match(/rgb\((\d+),\s*(\d+),\s*(\d+)\)/);
      if (m && (parseInt(m[1])+parseInt(m[2])+parseInt(m[3]))/3 > 200) dark = false;
    }}
  }} catch(e) {{}}
  var r = document.documentElement;
  r.style.setProperty('--row-bg', dark ? '#181818' : '#ffffff');
  r.style.setProperty('--total-bg', dark ? '#2a2a2a' : '#f0f0f0');
  r.style.setProperty('--top3-bg', dark ? '#1a3a1a' : '#d7ead9');
  r.style.setProperty('--header-bg', dark ? '#1e1e1e' : '#e8e8e8');
  r.style.setProperty('--border-color', dark ? '#444' : '#ccc');
  r.style.setProperty('--text-color', dark ? '#ddd' : '#111');
}}
applyThemeC();
setInterval(applyThemeC, 1500);
try {{
  new MutationObserver(applyThemeC).observe(window.parent.document.documentElement, {{attributes: true, attributeFilter: ['data-theme','class']}});
  new MutationObserver(applyThemeC).observe(window.parent.document.body, {{attributes: true, attributeFilter: ['class','style']}});
}} catch(e) {{}}
</script>
<button id="btnCopyC_{camp_name_c}" onclick="copyTableC()" style="margin-bottom:8px;margin-right:6px;padding:4px 12px;background:var(--btn-bg);color:var(--btn-color);border:1px solid var(--border-color);border-radius:5px;cursor:pointer;font-size:13px;">📋 Копировать</button>
                <button id="btnCopyBunkerC_{camp_name_c}" onclick="copyTableBunkerC()" style="margin-bottom:8px;padding:4px 12px;background:var(--btn-bg);color:var(--btn-color);border:1px solid var(--border-color);border-radius:5px;cursor:pointer;font-size:13px;">📋 Копировать для бункера</button>
                <script>
                function applyBtnThemeC() {{
                  var dark = true;
                  try {{
                    var theme = window.parent.document.documentElement.getAttribute('data-theme');
                    if (theme === 'light') {{ dark = false; }}
                    else {{
                      var bg = window.parent.getComputedStyle(window.parent.document.body).backgroundColor;
                      var m = bg.match(/rgb\((\d+),\s*(\d+),\s*(\d+)\)/);
                      if (m && (parseInt(m[1])+parseInt(m[2])+parseInt(m[3]))/3 > 200) dark = false;
                    }}
                  }} catch(e) {{}}
                  document.documentElement.style.setProperty('--btn-bg', dark ? '#2a2a2a' : '#f0f0f0');
                  document.documentElement.style.setProperty('--btn-color', dark ? '#aaa' : '#333');
                }}
                applyBtnThemeC();
                setInterval(applyBtnThemeC, 1500);

                function buildCleanCloneC(excludeCols) {{
                  var orig = document.getElementById('tbl_c_{camp_name_c}');
                  var clone = orig.cloneNode(true);
                  if (excludeCols && excludeCols.length > 0) {{
                    var headers = clone.querySelectorAll('tr')[0].querySelectorAll('th');
                    var colIndexes = [];
                    headers.forEach(function(th, i) {{
                      if (excludeCols.indexOf(th.innerText.trim()) !== -1) colIndexes.push(i);
                    }});
                    clone.querySelectorAll('tr').forEach(function(row) {{
                      var cells = row.querySelectorAll('th, td');
                      colIndexes.slice().reverse().forEach(function(i) {{
                        if (cells[i]) cells[i].remove();
                      }});
                    }});
                  }}
                  clone.querySelectorAll('tr').forEach(function(row) {{
                    var ths = row.querySelectorAll('th');
                    ths.forEach(function(th) {{
                      th.style.background = '#fff'; th.style.color = '#000';
                      th.style.border = '1px solid #ccc'; th.style.fontWeight = 'bold';
                    }});
                    var rowType = row.getAttribute('data-rowtype') || 'normal';
                    row.querySelectorAll('td').forEach(function(td) {{
                      td.style.border = '1px solid #ccc'; td.style.color = '#000';
                      if (rowType === 'itogo') {{ td.style.background = '#fff'; td.style.fontWeight = 'bold'; }}
                      else if (rowType === 'top3') {{ td.style.background = '#d7ead9'; }}
                      else {{ td.style.background = '#fff'; }}
                    }});
                  }});
                  return clone;
                }}
                function copyTableC() {{
                  var clone = buildCleanCloneC([]);
                  var blob = new Blob([clone.outerHTML], {{type: 'text/html'}});
                  navigator.clipboard.write([new ClipboardItem({{'text/html': blob}})]).then(function() {{
                    var btn = document.getElementById('btnCopyC_{camp_name_c}');
                    btn.innerText = '✅ Скопировано'; setTimeout(function() {{ btn.innerText = '📋 Копировать'; }}, 2000);
                  }}).catch(function(e) {{ alert('Ошибка: ' + e); }});
                }}
                function copyTableBunkerC() {{
                  var clone = buildCleanCloneC(['Заказы', 'Цена за заказ', 'Регистрации', 'Цена за регистрацию', 'Список городов']);
                  var blob = new Blob([clone.outerHTML], {{type: 'text/html'}});
                  navigator.clipboard.write([new ClipboardItem({{'text/html': blob}})]).then(function() {{
                    var btn = document.getElementById('btnCopyBunkerC_{camp_name_c}');
                    btn.innerText = '✅ Скопировано'; setTimeout(function() {{ btn.innerText = '📋 Копировать для бункера'; }}, 2000);
                  }}).catch(function(e) {{ alert('Ошибка: ' + e); }});
                }}
                </script>
                <div style="overflow-x:auto;margin-bottom:8px;">
                <table id="tbl_c_{camp_name_c}" style="border-collapse:collapse;font-size:13px;font-family:sans-serif;width:100%;">
                {''.join(html_rows_c)}
                </table></div>"""
                components.html(tbl_html_c, height=(len(full_c) + 2) * 30 + 48, scrolling=False)

                # ГАЛЕРЕЯ ЭТОЙ КАМПАНИИ — сразу под таблицей
                if st.session_state.get('clnt_gallery_loaded'):
                    st.write(f"#### Галерея: {camp_name_c}")
                    df_cc_gal = df_final[df_final['campaign_clean'] == camp_name_c].copy()
                    # Порядок из таблицы (без ИТОГО)
                    table_order_c = [x for x in full_c[camp_name_c].tolist() if x != 'ИТОГО']
                    raw_to_display_c = dict(zip(df_cc_gal['Макет_raw'], df_cc_gal['Макет']))
                    display_to_raw_c = {}
                    for raw, display in raw_to_display_c.items():
                        if display not in display_to_raw_c:
                            display_to_raw_c[display] = raw
                    # Сортируем по порядку таблицы
                    def sort_key_c(display):
                        try:
                            return table_order_c.index(display)
                        except ValueError:
                            return 9999
                    sorted_display = sorted(display_to_raw_c.keys(), key=sort_key_c)
                    unique_display_names_c = sorted_display
                    unique_ad_names_c = [display_to_raw_c[d] for d in sorted_display]

                    COUNTRY_TO_ACC = {
                        "AZ": ["24946866675014329"], "AR": ["509917460493340"],
                        "BY": ["2110787599718272"], "BG": ["1013441868511084"],
                        "BR": ["24948463558072461"], "VN": ["192474577136849"],
                        "GE": ["582893932494739"], "DO": ["817547549239841"],
                        "ID": ["1591493017715668", "257290219582370"],
                        "CO": ["351583944532627"], "MY": ["398026798982273"],
                        "PE": ["1323600845784691"], "TJ": ["209570214255009"],
                        "TH": ["2727239577416075"],
                        "TZ": ["2295720397582070", "351994210156217"],
                        "PH": ["2050316328716958", "1052629215643734"],
                        "ZA": ["830039013207696"], "LA": ["3710708579188840"],
                    }
                    def get_country_code_c(campaign_name):
                        name = str(campaign_name or "").strip().upper()
                        for code in COUNTRY_TO_ACC.keys():
                            if name.startswith(code + " ") or name.startswith(code + "_") or f" {code} " in name:
                                return code
                        return None

                    country_codes_c = set()
                    raw_camps_c = df_clients[df_clients['campaign_clean'] == camp_name_c]['campaign_name'].unique()
                    for raw in raw_camps_c:
                        code = get_country_code_c(raw)
                        if code:
                            country_codes_c.add(code)
                    all_acc_ids_c = []
                    for code in country_codes_c:
                        all_acc_ids_c.extend(COUNTRY_TO_ACC.get(code, []))

                    # Строим карту с тремя вариантами нормализации для максимального покрытия
                    unique_ad_names_clean_c = {}
                    for n in unique_ad_names_c:
                        unique_ad_names_clean_c[n.lower().strip()] = n
                        unique_ad_names_clean_c[clean_creative_name_local(n).lower().strip()] = n
                        unique_ad_names_clean_c[clean_cost(clean_creative_name_local(n)).lower().strip()] = n

                    ad_name_to_id_c = {}
                    with st.spinner(f"Ищем макеты кампании {camp_name_c}..."):
                        for acc_id_c in all_acc_ids_c:
                            try:
                                next_url = f"https://graph.facebook.com/v19.0/act_{acc_id_c}/ads?fields=name,id,adcreatives{{name}}&limit=500&access_token={TOKEN}"
                                total_ads_checked = 0
                                while next_url:
                                    search_res = requests.get(next_url, timeout=60).json()
                                    if 'error' in search_res:
                                        break
                                    ads_on_page = search_res.get('data', [])
                                    total_ads_checked += len(ads_on_page)
                                    for ad in ads_on_page:
                                        names_to_try = [ad.get('name', '')]
                                        for cr in ad.get('adcreatives', {}).get('data', []):
                                            names_to_try.append(cr.get('name', ''))
                                        for raw_name in names_to_try:
                                            if not raw_name:
                                                continue
                                            variants = [
                                                raw_name.lower().strip(),
                                                clean_creative_name_local(raw_name).lower().strip(),
                                                clean_cost(clean_creative_name_local(raw_name)).lower().strip(),
                                            ]
                                            for v in variants:
                                                if v in unique_ad_names_clean_c:
                                                    orig = unique_ad_names_clean_c[v]
                                                    if orig not in ad_name_to_id_c:
                                                        ad_name_to_id_c[orig] = ad['id']
                                                    break
                                    next_url = search_res.get('paging', {}).get('next')
                                pass
                            except:
                                pass

                    top3_gallery_c = top3_c

                    import json as json_lib
                    gallery_items_c = []
                    for ad_name, display_name in zip(unique_ad_names_c, unique_display_names_c):
                        if not display_name or str(display_name).strip().lower() == 'nan':
                            continue
                        ad_id = ad_name_to_id_c.get(ad_name)
                        if not ad_id:
                            gallery_items_c.append({'name': display_name, 'img_url': None, 'is_video': False, 'video_src': None})
                            continue
                        try:
                            ad_res = requests.get(
                                f"https://graph.facebook.com/v19.0/{ad_id}"
                                f"?fields=account_id,adcreatives{{image_hash,image_url,thumbnail_url,object_story_spec,asset_feed_spec}}"
                                f"&access_token={TOKEN}", timeout=30
                            ).json()
                            if 'error' in ad_res:
                                gallery_items_c.append({'name': display_name, 'img_url': None, 'is_video': False, 'video_src': None})
                                continue
                            acc_id = ad_res.get('account_id')
                            creative_data = ad_res.get('adcreatives', {}).get('data', [{}])[0]
                            creative_id = creative_data.get('id')
                            img_url = None; video_src = None; is_video_creative = False
                            if creative_id:
                                cr_full = requests.get(
                                    f"https://graph.facebook.com/v19.0/{creative_id}",
                                    params={"fields": "image_url,thumbnail_url,image_hash,object_story_spec,asset_feed_spec", "access_token": TOKEN},
                                    timeout=20
                                ).json()
                                oss = cr_full.get('object_story_spec', {})
                                is_video_creative = bool(oss.get('video_data', {}).get('video_id')) or bool(cr_full.get('asset_feed_spec', {}).get('videos'))
                                # Собираем все хэши изображений
                                all_hashes = []
                                if cr_full.get('image_hash'):
                                    all_hashes.append(cr_full['image_hash'])
                                if oss.get('link_data', {}).get('image_hash'):
                                    all_hashes.append(oss['link_data']['image_hash'])
                                if oss.get('video_data', {}).get('image_hash'):
                                    all_hashes.append(oss['video_data']['image_hash'])
                                for img_obj in cr_full.get('asset_feed_spec', {}).get('images', []):
                                    if img_obj.get('hash'):
                                        all_hashes.append(img_obj['hash'])
                                if all_hashes and acc_id:
                                    hr = requests.get(f"https://graph.facebook.com/v19.0/act_{acc_id}/adimages",
                                        params={"hashes": json_lib.dumps(list(set(all_hashes))), "fields": "url,original_width,original_height", "access_token": TOKEN}, timeout=20).json()
                                    if hr.get('data'):
                                        best = None
                                        for img_info in hr['data']:
                                            w = int(img_info.get('original_width', 0))
                                            h = int(img_info.get('original_height', 0))
                                            if w > 0 and h > 0 and 0.9 <= (w/h) <= 1.1:
                                                best = img_info.get('url')
                                                break
                                        img_url = best or hr['data'][0].get('url')
                                # Fallback: picture из link_data
                                if not img_url and oss.get('link_data', {}).get('picture'):
                                    img_url = oss['link_data']['picture']
                                video_id = oss.get('video_data', {}).get('video_id')
                                if not video_id and cr_full.get('asset_feed_spec', {}).get('videos'):
                                    video_id = cr_full['asset_feed_spec']['videos'][0].get('video_id')
                                if video_id:
                                    vr = requests.get(f"https://graph.facebook.com/v19.0/{video_id}?fields=picture,source&access_token={TOKEN}", timeout=20).json()
                                    if 'error' not in vr:
                                        video_src = vr.get('source')
                                        if not img_url and vr.get('picture'):
                                            img_url = re.sub(r'stp=[^&]*&?', '', vr['picture']).rstrip('?&') or None
                                if not img_url:
                                    thumb = cr_full.get('thumbnail_url') or cr_full.get('image_url')
                                    if thumb: img_url = re.sub(r'stp=[^&]*&?', '', thumb).rstrip('?&') or None
                            if is_video_creative and not video_src:
                                with st.empty():
                                    drive_url = find_video_on_drive(ad_name)
                                if drive_url:
                                    video_src = drive_url
                                else:
                                    with st.empty():
                                        img_from_drive = find_image_on_drive(ad_name)
                                    if img_from_drive and not img_url:
                                        img_url = img_from_drive
                            # Финальный fallback — ищем фото на Drive даже если не видео
                            if not img_url:
                                with st.empty():
                                    img_from_drive = find_image_on_drive(ad_name)
                                if img_from_drive:
                                    img_url = img_from_drive
                            gallery_items_c.append({'name': display_name, 'img_url': img_url, 'is_video': is_video_creative, 'video_src': video_src})
                        except:
                            gallery_items_c.append({'name': display_name, 'img_url': None, 'is_video': False, 'video_src': None})

                    cards_html_c = ""
                    for item in gallery_items_c:
                        is_leader = item['name'] in top3_gallery_c
                        border_style = 'border:3px solid #e53935;border-radius:12px;' if is_leader else ''
                        if item['img_url']:
                            if item['is_video'] and item.get('video_src'):
                                if 'drive.google.com' in item['video_src']:
                                    media_html = f"""<iframe src="{item['video_src']}" style="width:100%;aspect-ratio:1;border:none;border-radius:10px;" allowfullscreen></iframe>"""
                                else:
                                    media_html = f"""<div style="width:100%;aspect-ratio:1;border-radius:10px;overflow:hidden;background:#000;"><video src="{item['video_src']}" style="width:100%;height:100%;object-fit:cover;display:block;" controls preload="metadata" playsinline></video></div>"""
                            else:
                                overlay = ""
                                if item['is_video']:
                                    overlay = """<div style="position:absolute;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.25);display:flex;align-items:center;justify-content:center;border-radius:10px;"><div style="width:48px;height:48px;background:rgba(255,255,255,0.92);border-radius:50%;display:flex;align-items:center;justify-content:center;"><div style="width:0;height:0;margin-left:5px;border-top:10px solid transparent;border-bottom:10px solid transparent;border-left:18px solid #222;"></div></div></div>"""
                                media_html = f"""<div style="position:relative;width:100%;border-radius:10px;overflow:hidden;"><img src="{item['img_url']}" style="width:100%;height:auto;display:block;border-radius:10px;">{overlay}</div>"""
                            cards_html_c += f"""<div style="display:flex;flex-direction:column;gap:8px;{border_style}padding:{'4px' if is_leader else '0'}">{media_html}<div style="font-size:13px;color:#ccc;word-break:break-word;">{item['name']}</div></div>"""
                        else:
                            cards_html_c += f"""<div style="display:flex;flex-direction:column;gap:8px;{border_style}padding:{'4px' if is_leader else '0'}"><div style="width:100%;aspect-ratio:1;background:#2a2a2a;border-radius:10px;display:flex;align-items:center;justify-content:center;color:#666;">Нет фото</div><div style="font-size:13px;color:#ccc;word-break:break-word;">{item['name']}</div></div>"""
                    full_html_c = f"""<html><head><style>body{{margin:0;padding:0;background:transparent}}</style></head><body><div style="display:grid;grid-template-columns:repeat(5,1fr);gap:12px;margin-top:12px;font-family:sans-serif;">{cards_html_c}</div></body></html>"""
                    components.html(full_html_c, height=(len(gallery_items_c) // 5 + 1) * 260 + 50, scrolling=True)

            # Удалите старый блок "# Скачать все таблицы" и "# Галерея" после цикла

    st.stop()

if app_mode == "🖼️ Библиотека креативов":
    st.title("🖼️ Библиотека креативов")
else:
    st.title("📈 Аналитика рекламных кабинетов")
# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---
@st.cache_data(ttl=1800)
def load_insights_from_db(labels, start_date, end_date):
    """Читает статистику кампаний из Supabase с пагинацией (обход лимита 1000)"""
    try:
        all_rows = []
        page_size = 1000
        offset = 0
        while True:
            resp = supabase.table("fb_insights_daily")\
                .select("*")\
                .in_("country_label", list(labels))\
                .gte("date_start", str(start_date))\
                .lte("date_start", str(end_date))\
                .range(offset, offset + page_size - 1)\
                .execute()
            if not resp.data:
                break
            all_rows.extend(resp.data)
            if len(resp.data) < page_size:
                break
            offset += page_size
        if not all_rows:
            return None
        df = pd.DataFrame(all_rows)
        df['date_start'] = pd.to_datetime(df['date_start'])
        return df
    except Exception as e:
        st.error(f"Ошибка загрузки статистики из базы: {e}")
        return None

@st.cache_data(ttl=1800)
def load_reach_from_db(labels):
    try:
        resp = supabase.table("fb_reach_period")\
            .select("country_label,campaign_name,reach,period_days,period_until")\
            .in_("country_label", list(labels))\
            .order("period_until", desc=True)\
            .execute()
        if not resp.data:
            return None
        df = pd.DataFrame(resp.data)
        # Берём последнюю запись для каждой кампании
        df = df.drop_duplicates(subset=['country_label', 'campaign_name'], keep='first')
        return df
    except Exception as e:
        st.error(f"Ошибка загрузки охвата: {e}")
        return None

@st.cache_data(ttl=1800)
def load_creatives_from_db(labels, start_date, end_date):
    """Читает данные по макетам из Supabase с пагинацией (обход лимита 1000)"""
    try:
        all_rows = []
        page_size = 1000
        offset = 0
        while True:
            resp = supabase.table("fb_ads_creatives")\
                .select("*")\
                .in_("country_label", list(labels))\
                .gte("date_start", str(start_date))\
                .lte("date_start", str(end_date))\
                .range(offset, offset + page_size - 1)\
                .execute()
            if not resp.data:
                break
            all_rows.extend(resp.data)
            if len(resp.data) < page_size:
                break
            offset += page_size
        if not all_rows:
            return None
        return pd.DataFrame(all_rows)
    except Exception as e:
        st.error(f"Ошибка загрузки макетов из базы: {e}")
        return None
# Функция получения курса валют
@st.cache_data(ttl=3600)
def get_rates(base_currency):
    try:
        url = f"https://open.er-api.com/v6/latest/{base_currency}"
        response = requests.get(url)
        data = response.json()
        if data["result"] == "success":
            return data["rates"]
        return None
    except:
        return None

# Функция очистки названий (Схлопывание)
def clean_campaign_name(name):
    if not name:
        return name
    # Убираем даты типа 8.12 / 8-12
    short_date_pattern = r'\b\d{1,2}\s*[./-]\s*\d{1,2}\b'
    had_short_date = bool(re.search(short_date_pattern, name))
    cleaned = re.sub(short_date_pattern, " ", name)
    # Убираем длинные цифры, месяцы и "copy"
    cleaned = re.sub(r'\d{2,}', '', cleaned)
    months_regex = r'\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec|январь|февраль|март|апрель|май|июнь|июль|август|сентябрь|октябрь|ноябрь|декабрь)\b'
    cleaned = re.sub(months_regex, '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'copy', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'[-–—.]', '', cleaned)
    # Убираем одиночную цифру в конце, если была дата
    if had_short_date:
        cleaned = re.sub(r'\s+\d\b$', '', cleaned)
    cleaned = re.sub(r'\s{2,}', ' ', cleaned).strip()
    return cleaned if cleaned else name
# Функция очистки названий макетов
def clean_creative_name(name):
    if not name: return "Unknown creative"
    name = str(name).strip()
    name = re.sub(r'\.(png|jpg|jpeg).*$', '', name, flags=re.IGNORECASE)
    name = re.sub(r'_\d{3,}', '', name)
    name = re.sub(r'\([^)]*\)', '', name)
    # Не трогаем числа перед словами-количествами (заказов, поездок, водителей и т.д.)
    name = re.sub(r'\b\d{2,}\b(?!\s*(?:заказ|поездк|водител|клиент|пассажир|машин|авто))', '', name)
    name = re.sub(r'\.(png|jpg|jpeg).*$', '', name, flags=re.IGNORECASE)
    name = re.sub(r'[_-]?\d+\s*[xх]\s*\d+.*$', '', name, flags=re.IGNORECASE)
    name = re.sub(r'[xх]\d+.*$', '', name, flags=re.IGNORECASE)
    name = re.sub(r'[_-]\d+.*$', '', name)
    name = re.sub(r'\d+\s*[кk]', '', name, flags=re.IGNORECASE)
    name = re.sub(r'[\d.,]*\s*млн\.?', '', name, flags=re.IGNORECASE)
    name = re.sub(r'\bмлн\b', '', name, flags=re.IGNORECASE)
    name = re.sub(r'(заработок)\s*[\d.,]+(?:\s*[кkмm][а-я]*)?', r'\1', name, flags=re.IGNORECASE)
    # Стираем цифры после cost/sal/fee только если после них НЕ идут кириллические буквы вплотную
    name = re.sub(r'(cost|sal|fee)\s*\d+\s*', lambda m: m.group(1) + ' ', name, flags=re.IGNORECASE)
    name = name.strip()
    name = re.sub(r'(exec)(O|0)(?=\b|_|\s)', r'\1O', name, flags=re.IGNORECASE)
    name = re.sub(r'(?:до\s*)?\d[\d\s.,]*\s*(?:₽|руб\.?|р\.?)?\s*(?=в\s*(?:месяц|неделю|день|год|час|смену)\b)', '', name, flags=re.IGNORECASE)
    name = re.sub(r'[_ ,]+(Emalahleni|Mbombela|Middelburg|Kimberley|Potchefstroom|Bloemfontein|Klerksdorp|Cape\s*Town|Polokwane|Welkom)', '', name, flags=re.IGNORECASE)
    name = re.sub(r'[-_]{2,}', '_', name)
    name = re.sub(r'\s{2,}', ' ', name).strip()
    name = re.sub(r'[_-]+$', '', name)
    keep_with_china = ["Авто бонус за брендировку _китай", "Авто заработок в месяц девушка 4 _китай", "Авто заработок в месяц красный фон _китай", "Авто заработок в месяц аниме _китай"]
    if name not in keep_with_china:
        name = re.sub(r'_китай', '', name, flags=re.IGNORECASE)
    return name.strip() or "Unknown creative"
# --- ОСНОВНАЯ ЛОГИКА ---

if not TOKEN:
    st.error("Токен не найден! Проверьте файл .env")
else:
    # 1. КАРТА НДС
    # 1. КАРТА НДС (Аккаунт ID -> Множитель НДС)
    VAT_MAP = {
        # Азербайджан (БМ: Bellfast Baku Limited)
        "24946866675014329": 1.0,

        # Аргентина (БМ: Maxim_Indonesia)
        "509917460493340": 1.11,

        # Беларусь (БМ: Taxsee_Philippines)
        "2110787599718272": 1.0,

        # Болгария (БМ: AIST_Malaysia)
        "1013441868511084": 1.0,

        # Бразилия (БМ: Maxim_Brasil)
        "24948463558072461": 1 / (1 - 0.029 - 0.0925),

        # Вьетнам (БМ: Taxsee_Vietnam)
        "192474577136849": 1.0,

        # Грузия (БМ: Бункер-Медиа)
        "582893932494739": 1.0,

        # Грузия (БМ: Бункер-Медиа)
        "1013441868511084": 1.0,

        # Доминикана (БМ: Maxim_Indonesia)
        "817547549239841": 1.11,

        # Индонезия (БМ: Maxim_Indonesia)
        "1591493017715668": 1.11,
        "257290219582370": 1.11,

        # Колумбия (БМ: Maxim_Indonesia)
        "351583944532627": 1.0,

        # Малайзия (БМ: AIST_Malaysia)
        "398026798982273": 1.08,

        # Перу (БМ: AIST_PERU_SAC)
        "1323600845784691": 1.0,

        # Таджикистан (БМ: Бункер-Медиа)
        "209570214255009": 1.0,

        # Таиланд (БМ: Taxsee_Thailand)
        "2727239577416075": 1.07,

        # Танзания (БМ: Taxsee_Philippines)
        "2295720397582070": 1.18,

        # Танзания (БМ: Maxim_Indonesia)
        "351994210156217": 1.11,

        # Филиппины (БМ: Taxsee_Philippines)
        "2050316328716958": 1.0,
        "1052629215643734": 1.0,

        # ЮАР (БМ: AIST_South_Africa)
        "830039013207696": 1.15,

        # LA (БМ: LA)
        "3710708579188840": 1.10,

        # TZ GMT (БМ: AZ)
        "1236647761876144": 1.18,
    }

    # 2. ПОЛУЧЕНИЕ СПИСКА АККАУНТОВ (ОДИН РАЗ!)
    try:
        cutoff_date = "2026-01-01"
        today_str = datetime.now().strftime('%Y-%m-%d')
        
        accounts_url = f"https://graph.facebook.com/v19.0/me/adaccounts"
        acc_params = {
            "fields": f"name,account_id,currency,insights.time_range({{'since':'{cutoff_date}','until':'{today_str}'}}){{spend}}",
            "limit": 100,
            "access_token": TOKEN

        }
        
        # Сбрасываем кэш если наступил новый день
        cached_date = st.session_state.get('all_accounts_cache_date')
        today_date = datetime.now().strftime('%Y-%m-%d')
        if cached_date != today_date:
            st.session_state.pop('all_accounts_data', None)
            st.session_state['all_accounts_cache_date'] = today_date

        if not st.session_state.get('all_accounts_data'):
            all_accounts_data = []
            acc_response = requests.get(accounts_url, params=acc_params, timeout=120).json()
            if 'error' in acc_response:
                st.error(f"Ошибка токена FB: {acc_response['error'].get('message', '')}. Обновите токен в настройках.")
                st.stop()
            while True:
                if "data" in acc_response:
                    all_accounts_data.extend(acc_response["data"])
                if "paging" in acc_response and "next" in acc_response["paging"]:
                    acc_response = requests.get(acc_response["paging"]["next"], timeout=120).json()
                else:
                    break
            # Не кэшируем пустой результат
            if all_accounts_data:
                st.session_state['all_accounts_data'] = all_accounts_data
        else:
            all_accounts_data = st.session_state['all_accounts_data']

        accounts_dict = {}
        for acc in all_accounts_data:
            insights = acc.get("insights", {}).get("data", [])
            has_spend = insights and any(float(day.get('spend', 0)) > 0 for day in insights)
            
            # Если insights вообще не пришёл от FB — всё равно добавляем аккаунт
            # чтобы не терять его из-за сбоя API
            insights_missing = "insights" not in acc
            
            if has_spend or insights_missing:
                name = acc.get('name') or f"Unnamed ({acc['account_id']})"
                accounts_dict[name] = {
                    'id': acc['account_id'], 
                    'currency': acc.get('currency', 'USD')
                }

        if not accounts_dict:
            st.warning("FB API не вернул данные по аккаунтам.")
            if st.button("🔄 Сбросить кэш и повторить"):
                st.session_state.pop('all_accounts_data', None)
                st.rerun()
            st.stop()
        
    except Exception as e:
        st.error(f"Ошибка загрузки списка аккаунтов: {e}")
        st.stop()

    # 3. ОБЪЕДИНЕНИЕ СТРАН В САЙДБАРЕ
    merged_accounts = {}
    
    group_rules = {
        "Indonesia": ["Indonesia", "Indonesia exec"],
        "Philippines": ["PH exec", "PH usd", "Philippines"],
        "Belarus": ["Belarus", "Belarus usd"]
    }

    for acc_name, acc_info in accounts_dict.items():
        target_group = None
        for group_name, members in group_rules.items():
            if acc_name in members:
                target_group = group_name
                break
        
        if target_group:
            if target_group not in merged_accounts:
                merged_accounts[target_group] = {'ids': [], 'currency': acc_info['currency']}
            merged_accounts[target_group]['ids'].append(acc_info['id'])
        else:
            merged_accounts[acc_name] = {'ids': [acc_info['id']], 'currency': acc_info['currency']}
            ACCOUNT_DISPLAY_NAMES = {
        "AR": " Maxim Argentina",
        "Azerbaijan AZ": "Maxim Azerbaijan",
        "UZ": "Maxim Bulgaria",
        "Brasil": "Maxim Brasil",
        "Colombia": "Maxim Colombia",
        "Georgia": "Maxim Georgia",
        "Indonesia": "Maxim Indonesia",
        "Philippines": "Maxim Philippines",
        "Malaysia usd": "Maxim Malaysia",
        "PE USD": "Maxim Peru",
        "Thailand": "Maxim Thailand",
        "Tanzania GMT": "Tanzania",
        "Vietnam": "Maxim Vietnam",
        "South Africa ZA": "Maxim South Africa",
        "TH": "Maxim Dominican Republic",
    }
    merged_accounts = {ACCOUNT_DISPLAY_NAMES.get(k, k): v for k, v in merged_accounts.items()}

    # 4. НАСТРОЙКИ (САЙДБАР)
    with st.sidebar:
        st.header("Настройки")
        today = datetime.now()
        start_default = today - timedelta(days=30)
        date_range = st.date_input("Период:", value=(start_default, today), max_value=today, format="DD.MM.YYYY")

        if isinstance(date_range, tuple) and len(date_range) == 2:
            start_date, end_date = date_range
        else:
            st.info("Выберите дату окончания")
            st.stop()
        
        sorted_keys = sorted(list(merged_accounts.keys()))
        default_account = next((k for k in sorted_keys if k.startswith("AR") or "Argentina" in k), sorted_keys[0] if sorted_keys else None)
        selected_labels = st.multiselect(
            "Рекламный аккаунт:", 
            options=sorted_keys,
            default=[default_account] if default_account else []
        )
        
        if not selected_labels:
            st.warning("Выберите хотя бы один рекламный аккаунт.")
            st.stop()
            

        # Собираем все ID и проверяем валюты
        list_of_ids = []
        selected_currencies = set()
        
        for label in selected_labels:
            list_of_ids.extend(merged_accounts[label]['ids'])
            selected_currencies.add(merged_accounts[label]['currency'])
            
        # Если выбрана только одна валюта, мы можем ее показывать. Если больше - ставим заглушку
        curr = list(selected_currencies)[0] if len(selected_currencies) == 1 else "MIXED"

        # Категория в основном сайдбаре — только для раздела статистики
        category_options = {"Все": "", "Водители": "exec", "Клиенты": "clnt", "Smm": "smm", "Партнеры": "Prtn"}
        if app_mode != "🖼️ Библиотека креативов":
            selected_category_label = st.selectbox("Категория:", list(category_options.keys()))
        else:
            selected_category_label = "Все"  # заглушка, не используется в библиотеке
        category_substring = category_options[selected_category_label]

    st.markdown("""
        <style>
        /* Синий цвет для выбранных тегов в фильтрах */
        span[data-baseweb="tag"] {
            background-color: #1f77b4 !important;
        }
        /* Синий цвет для галочек и активных точек */
        div[data-baseweb="checkbox"] div[bg], 
        div[data-baseweb="radio"] div[bg] {
            background-color: #1f77b4 !important;
        }
        /* Синяя рамка вокруг активного фильтра при нажатии */
        div[data-baseweb="select"] > div:focus-within {
            border-color: #1f77b4 !important;
        }
        </style>
    """, unsafe_allow_html=True)
    
    # --- БИБЛИОТЕКА КРЕАТИВОВ ---
    if app_mode == "🖼️ Библиотека креативов":
        main_tab = st.session_state.get('main_tab', 'Водители')
        import json

        # Загружаем данные автоматически при входе или смене параметров
        cache_key = f"{selected_labels}_{start_date}_{end_date}"
        if st.session_state.get('gallery_cache_key') != cache_key:
            st.session_state['gallery_loaded'] = False
            st.session_state['gallery_images_loaded'] = False
            st.session_state['table_loaded'] = False
            st.session_state['gallery_cache_key'] = cache_key

        # Сбрасываем если старые данные без нужных колонок
        if st.session_state.get('gallery_loaded') and 'gallery_data' in st.session_state:
            if 'campaign_name_clean' not in st.session_state['gallery_data'].columns:
                st.session_state['gallery_loaded'] = False

        if 'gallery_loaded' not in st.session_state:
            st.session_state['gallery_loaded'] = False

        # --- ТЕПЕРЬ ЗАГРУЗКА ИДЕТ ТОЛЬКО ПО КНОПКЕ ---
        if not st.session_state['gallery_loaded']:
            with st.sidebar:
                if st.button("🚀 Загрузить данные из базы", use_container_width=True):
                    with st.spinner("Загрузка данных..."):
                        from collector import ACCOUNT_LABELS
                        selected_db_labels = set()
                        for label in selected_labels:
                            for acc_id in merged_accounts[label]['ids']:
                                db_label = ACCOUNT_LABELS.get(acc_id)
                                if db_label:
                                    selected_db_labels.add(db_label)

                        df_raw = load_creatives_from_db(selected_db_labels, start_date, end_date)

                        if df_raw is not None and not df_raw.empty:
                            # Исключаем кампании с нулевым расходом за весь период
                            camp_spend = df_raw.groupby('campaign_name')['spend_rub'].sum()
                            active_camps = camp_spend[camp_spend > 0].index
                            df_raw = df_raw[df_raw['campaign_name'].isin(active_camps)]

                            def normalize_adset(name):
                                if not name: return ''
                                name = str(name).lower().strip()
                                if 'allcity' in name: return 'allcity'
                                name = re.sub(r'\d{1,2}[./-]\d{1,2}', '', name)
                                name = re.sub(r'\d+', '', name)
                                name = re.sub(r'\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\b', '', name)
                                name = re.sub(r'\b(copy|trg|target)\b', '', name)
                                name = re.sub(r'\+?\s*truck', '', name)
                                name = re.sub(r'[-–—_.]', ' ', name)
                                return re.sub(r'\s{2,}', ' ', name).strip()

                            df_raw = df_raw.rename(columns={
                                'country_label': 'Страна',
                                'spend_rub':     'Затраты (RUB)',
                                'leads':         'Результаты',
                            })
                            df_raw['Затраты'] = df_raw['spend'].astype(float)
                            df_raw['Показы']  = df_raw['impressions'].astype(int)
                            df_raw['Клики']   = df_raw['clicks'].astype(int)
                            df_raw['adset_norm'] = df_raw['adset_name'].apply(normalize_adset)
                            df_raw['Макет'] = df_raw['ad_name'].apply(clean_creative_name)
                            df_raw['Название группы'] = df_raw['adset_name'].apply(clean_campaign_name)
                            df_raw['campaign_name_clean'] = df_raw['campaign_name'].apply(clean_campaign_name)

                            st.session_state['gallery_data'] = df_raw
                            st.session_state['gallery_loaded'] = True
                            st.rerun()
                        else:
                            st.warning("Нет данных в базе за этот период.")
                            st.stop()
                else:
                    with st.sidebar:
                        st.divider()
                        st.markdown("### 🧭 Навигация")
                        if st.button("📊 Общая статистика", use_container_width=True, key="drv_nav_stat_pre"):
                            st.session_state['app_mode'] = "📊 Общая статистика"
                            st.rerun()
                        col_t1, col_t2 = st.columns(2)
                        with col_t1:
                            if st.button("🚗 Водители", use_container_width=True, key="tab_drivers_pre"):
                                st.session_state['main_tab'] = "Водители"
                                st.rerun()
                        with col_t2:
                            if st.button("👥 Клиенты", use_container_width=True, key="tab_clients_pre"):
                                st.session_state['main_tab'] = "Клиенты"
                                st.session_state['app_mode'] = "🖼️ Библиотека креативов"
                                st.rerun()
                        st.divider()
                        if st.button("🚪 Выйти", use_container_width=True, key="drv_logout_pre"):
                            st.session_state["authenticated"] = False
                            cookies["authenticated"] = "false"
                            cookies.save()
                            st.rerun()
                    st.stop()

        # --- 2. БЛОК ФИЛЬТРОВ (появляется только после загрузки) ---
        df_ads = st.session_state['gallery_data']
        
        with st.sidebar:

            df_ads_cat = df_ads

            all_camps = sorted(df_ads_cat['campaign_name_clean'].unique().tolist())
            sel_camps = st.multiselect("Кампания:", all_camps, default=all_camps, key="lib_sel_c")
            
            filtered_for_adsets = df_ads_cat[df_ads_cat['campaign_name_clean'].isin(sel_camps)]
            all_adsets = sorted(filtered_for_adsets['Название группы'].unique().tolist())
            sel_adsets = st.multiselect("Группа (Ad Set):", all_adsets, default=all_adsets, key="lib_sel_a")
            
            if st.button("📊 Загрузить таблицы", use_container_width=True):
                st.session_state['table_loaded'] = True
                st.session_state['gallery_images_loaded'] = False
                st.rerun()
            
            if st.button("🔄 Загрузить галерею", use_container_width=True):
                st.session_state['gallery_images_loaded'] = True
                st.session_state['table_loaded'] = True
                st.rerun()

            st.divider()
            st.markdown("### 🧭 Навигация")
            if st.button("📊 Общая статистика", use_container_width=True, key="drv_nav_stat"):
                st.session_state['app_mode'] = "📊 Общая статистика"
                st.session_state['gallery_loaded'] = False
                st.session_state['gallery_images_loaded'] = False
                st.rerun()
            col_t1, col_t2 = st.columns(2)
            with col_t1:
                if st.button("🚗 Водители", use_container_width=True, key="tab_drivers"):
                    st.session_state['main_tab'] = "Водители"
                    st.rerun()
            with col_t2:
                if st.button("👥 Клиенты", use_container_width=True, key="tab_clients"):
                    st.session_state['main_tab'] = "Клиенты"
                    st.session_state['app_mode'] = "🖼️ Библиотека креативов"
                    st.rerun()
            st.divider()
            if st.button("🚪 Выйти", use_container_width=True, key="drv_logout"):
                st.session_state["authenticated"] = False
                cookies["authenticated"] = "false"
                cookies.save()
                st.rerun()

        # Применяем фильтрацию по очищенному столбцу
        mask = df_ads_cat['campaign_name_clean'].isin(sel_camps) & df_ads_cat['Название группы'].isin(sel_adsets)
        df_filtered = df_ads_cat[mask]

        # --- 3. ОТРИСОВКА: ТАБЛИЦА + МАКЕТЫ ---
        if df_filtered.empty:
            st.warning("Нет данных по выбранным фильтрам.")
        elif not st.session_state.get('table_loaded'):
            st.info("⬅️ Настройте фильтры и нажмите «Загрузить таблицы»")
        else:
            unique_camps = sorted(df_filtered['campaign_name_clean'].unique())
            all_tables_html = []
            for camp_name in unique_camps:
                df_c = df_filtered[df_filtered['campaign_name_clean'] == camp_name].copy()
                
                # 1. Агрегация для таблицы (Названия по вашему списку)
                # Агрегируем по МАКЕТУ (ad_id), а не по кампании
                table_data = df_c.groupby('Макет').agg({
                    'Показы': 'sum',
                    'Клики': 'sum',
                    'Затраты (RUB)': 'sum',
                    'Результаты': 'sum',
                    'adset_norm': lambda x: set(x.dropna().unique()),
                    'ad_id': 'first',
                }).reset_index()

                table_data = table_data.rename(columns={
                    'Макет': camp_name,
                    'adset_norm': 'cities_set'
                })

                def format_cities(cities_set):
                    has_allcity = 'allcity' in cities_set
                    regular = len([c for c in cities_set if c != 'allcity' and c != ''])
                    if regular > 0 and has_allcity:
                        return f"{regular}+allcity"
                    elif regular > 0:
                        return str(regular)
                    elif has_allcity:
                        return "allcity"
                    return ""

                table_data['Города'] = table_data['cities_set'].apply(format_cities)
                table_data['Список городов'] = table_data['cities_set'].apply(
                    lambda x: ', '.join(sorted([c for c in x if c != '' ]))
                )

                table_data['CTR %'] = (table_data['Клики'] / table_data['Показы'] * 100).fillna(0)
                table_data['LPM'] = (table_data['Результаты'] / table_data['Показы'] * 1000).fillna(0)
                table_data['Цена за результат'] = (
                    table_data['Затраты (RUB)'] / table_data['Результаты']
                ).replace([float('inf'), float('nan')], 0)
                
                # Создаем строку ИТОГО
                all_cities = set()
                for s in table_data['cities_set']:
                    all_cities.update(s)
                has_allcity_total = 'allcity' in all_cities
                regular_total = len([c for c in all_cities if c != 'allcity' and c != ''])
                if regular_total > 0 and has_allcity_total:
                    total_cities_str = f"{regular_total}+allcity"
                elif regular_total > 0:
                    total_cities_str = str(regular_total)
                elif has_allcity_total:
                    total_cities_str = "allcity"
                else:
                    total_cities_str = ""

                ttotals = pd.DataFrame([{
                    camp_name: 'ИТОГО',
                    'ad_id': None,
                    'Показы': table_data['Показы'].sum(),
                    'Клики': table_data['Клики'].sum(),
                    'Затраты (RUB)': table_data['Затраты (RUB)'].sum(),
                    'Результаты': table_data['Результаты'].sum(),
                    'Города': total_cities_str,
                    'Список городов': ', '.join(sorted([c for c in all_cities if c != 'allcity' and c != ''])),
                    'CTR %': (table_data['Клики'].sum() / table_data['Показы'].sum() * 100) if table_data['Показы'].sum() > 0 else 0,
                    'LPM': (table_data['Результаты'].sum() / table_data['Показы'].sum() * 1000) if table_data['Показы'].sum() > 0 else 0,
                    'Цена за результат': (table_data['Затраты (RUB)'].sum() / table_data['Результаты'].sum()) if table_data['Результаты'].sum() > 0 else 0,
                }])

                full_table = pd.concat([table_data, ttotals], ignore_index=True)
                
                csv_str = full_table[[camp_name, 'Показы', 'Клики', 'CTR %', 'Результаты', 'Цена за результат', 'LPM', 'Города', 'Список городов']].to_csv(sep='\t', index=False, decimal=',')                
                import streamlit.components.v1 as components

                top3_names = set(
                    table_data[table_data['Результаты'] > 0]
                    .nlargest(3, 'Результаты')[camp_name]
                    .tolist()
                )

                # Определяем тип кампании — CPM или обычная
                is_cpm_camp = 'cpm' in camp_name.lower() or 'cpm' in str(df_c['campaign_name_clean'].iloc[0] if len(df_c) > 0 else '').lower()

                if is_cpm_camp:
                    # Для CPM кампаний — отдельная агрегация с охватом
                    cpm_data = df_c.groupby('Макет').agg({
                        'Показы': 'sum',
                        'Клики': 'sum',
                        'Затраты (RUB)': 'sum',
                        'adset_norm': lambda x: set(x.dropna().unique()),
                        'ad_id': 'first',
                    }).reset_index()
                    
                    # Охват берём из оригинальных данных если есть
                    if 'reach' in df_c.columns:
                        df_c['reach'] = pd.to_numeric(df_c['reach'], errors='coerce').fillna(0)
                        reach_data = df_c.groupby('Макет')['reach'].sum().reset_index()
                        cpm_data = cpm_data.merge(reach_data, on='Макет', how='left')
                        cpm_data['Охват'] = cpm_data['reach'].fillna(0).astype(int)
                        cpm_data.drop(columns=['reach'], inplace=True)
                    else:
                        cpm_data['Охват'] = 0

                    cpm_data = cpm_data.rename(columns={'Макет': camp_name, 'adset_norm': 'cities_set'})
                    cpm_data['CTR %'] = (cpm_data['Клики'] / cpm_data['Показы'] * 100).fillna(0)
                    cpm_data['CPM'] = (cpm_data['Затраты (RUB)'] / cpm_data['Показы'] * 1000).replace([float('inf'), float('nan')], 0)

                    cpm_totals = pd.DataFrame([{
                        camp_name: 'ИТОГО',
                        'ad_id': None,
                        'Охват': cpm_data['Охват'].sum(),
                        'Показы': cpm_data['Показы'].sum(),
                        'Клики': cpm_data['Клики'].sum(),
                        'Затраты (RUB)': cpm_data['Затраты (RUB)'].sum(),
                        'CTR %': (cpm_data['Клики'].sum() / cpm_data['Показы'].sum() * 100) if cpm_data['Показы'].sum() > 0 else 0,
                        'CPM': (cpm_data['Затраты (RUB)'].sum() / cpm_data['Показы'].sum() * 1000) if cpm_data['Показы'].sum() > 0 else 0,
                        'cities_set': set(),
                    }])
                    full_cpm = pd.concat([cpm_data, cpm_totals], ignore_index=True)

                    top3_cpm = set(
                        cpm_data[cpm_data['Показы'] > 0]
                        .nlargest(3, 'Показы')[camp_name].tolist()
                    )

                    cols_cpm = [camp_name, 'Охват', 'Показы', 'Клики', 'CTR %', 'CPM']

                    def fmt_cpm(col, val):
                        try:
                            if col in ['Охват', 'Показы', 'Клики']:
                                return f"{int(float(val)):,}"
                            elif col == 'CTR %':
                                return f"{float(val):.2f}%"
                            elif col == 'CPM':
                                return f"{int(round(float(val))):,}"
                            else:
                                return str(val) if val is not None else ''
                        except:
                            return str(val) if val is not None else ''

                    cpm_html_rows = []
                    cpm_header = ''.join([f'<th style="padding:6px 10px;text-align:left;border:1px solid var(--border-color);background:var(--header-bg);color:var(--text-color);font-weight:bold;white-space:nowrap;">{c}</th>' for c in cols_cpm])
                    cpm_html_rows.append(f'<tr>{cpm_header}</tr>')

                    for _, r in full_cpm[cols_cpm].iterrows():
                        nv = str(r[camp_name])
                        is_itogo = nv == 'ИТОГО'
                        is_top3 = nv in top3_cpm
                        if is_itogo:
                            rs = 'font-weight:bold;background:var(--total-bg);color:var(--text-color);'
                            rt = 'itogo'
                        elif is_top3:
                            rs = 'background:var(--top3-bg);color:var(--text-color);'
                            rt = 'top3'
                        else:
                            rs = 'background:var(--row-bg);color:var(--text-color);'
                            rt = 'normal'
                        cells = ''
                        for c in cols_cpm:
                            val = fmt_cpm(c, r[c])
                            align = 'left' if c == camp_name else 'right'
                            cells += f'<td style="padding:5px 10px;border:1px solid var(--border-color);color:var(--text-color);text-align:{align};white-space:nowrap;">{val}</td>'
                        cpm_html_rows.append(f'<tr data-rowtype="{rt}" style="{rs}">{cells}</tr>')

                if is_cpm_camp:
                    cols_to_show = cols_cpm
                    html_rows = cpm_html_rows
                    full_table = full_cpm
                else:
                    cols_to_show = [camp_name, 'Показы', 'Клики', 'CTR %', 'Результаты', 'Цена за результат', 'LPM', 'Города', 'Список городов']

                def fmt_val(col, val):
                    try:
                        if col in ['Показы', 'Клики', 'Результаты', 'Охват']:
                            return f"{int(float(val)):,}"
                        elif col == 'CTR %':
                            return f"{float(val):.2f}%"
                        elif col == 'Цена за результат':
                            return f"{int(float(val)):,}"
                        elif col == 'CPM':
                            return f"{int(round(float(val))):,}"
                        elif col == 'LPM':
                            return f"{float(val):.2f}"
                        else:
                            return str(val) if val is not None else ''
                    except:
                        return str(val) if val is not None else ''

                # Строим HTML таблицу
                html_rows = []
                # Шапка
                header_cells = ''.join([f'<th style="padding:6px 10px;text-align:left;border:1px solid var(--border-color);background:var(--header-bg);color:var(--text-color);font-weight:bold;white-space:nowrap;">{c}</th>' for c in cols_to_show])
                html_rows.append(f'<tr>{header_cells}</tr>')

                for _, r in full_table[cols_to_show].iterrows():
                    name_val = str(r[camp_name])
                    is_itogo = name_val == 'ИТОГО'
                    is_top3 = name_val in top3_names

                    if is_itogo:
                        row_style = 'font-weight:bold;background:var(--total-bg);color:var(--text-color);'
                        row_type = 'itogo'
                    elif is_top3:
                        row_style = 'background:var(--top3-bg);color:var(--text-color);'
                        row_type = 'top3'
                    else:
                        row_style = 'background:var(--row-bg);color:var(--text-color);'
                        row_type = 'normal'

                    cells = ''
                    for c in cols_to_show:
                        val = fmt_val(c, r[c])
                        align = 'left' if c == camp_name or c == 'Список городов' else 'right'
                        cells += f'<td style="padding:5px 10px;border:1px solid var(--border-color);color:var(--text-color);text-align:{align};white-space:nowrap;">{val}</td>'
                    html_rows.append(f'<tr data-rowtype="{row_type}" style="{row_style}">{cells}</tr>')

                all_tables_html.append((camp_name, ''.join(html_rows)))

                table_html = f"""
                <style>
                ::-webkit-scrollbar{{width:6px;height:6px}}
                ::-webkit-scrollbar-track{{background:transparent;border-radius:3px}}
                ::-webkit-scrollbar-thumb{{background:#444;border-radius:3px}}
                ::-webkit-scrollbar-thumb:hover{{background:#666}}
                </style>
                <script>
                function applyTheme() {{
                  var dark = true;
                  try {{
                    var theme = window.parent.document.documentElement.getAttribute('data-theme');
                    if (theme === 'light') {{ dark = false; }}
                    else {{
                      var bg = window.parent.getComputedStyle(window.parent.document.body).backgroundColor;
                      var m = bg.match(/rgb\((\d+),\s*(\d+),\s*(\d+)\)/);
                      if (m && (parseInt(m[1])+parseInt(m[2])+parseInt(m[3]))/3 > 200) dark = false;
                    }}
                  }} catch(e) {{}}
                  var r = document.documentElement;
                  r.style.setProperty('--row-bg', dark ? '#181818' : '#ffffff');
                  r.style.setProperty('--total-bg', dark ? '#2a2a2a' : '#f0f0f0');
                  r.style.setProperty('--top3-bg', dark ? '#1a3a1a' : '#d7ead9');
                  r.style.setProperty('--header-bg', dark ? '#1e1e1e' : '#e8e8e8');
                  r.style.setProperty('--border-color', dark ? '#444' : '#ccc');
                  r.style.setProperty('--text-color', dark ? '#ddd' : '#111');
                  r.style.setProperty('--btn-bg', dark ? '#2a2a2a' : '#f0f0f0');
                  r.style.setProperty('--btn-color', dark ? '#aaa' : '#333');
                }}
                applyTheme();
                setInterval(applyTheme, 1500);
                try {{
                  new MutationObserver(applyTheme).observe(window.parent.document.documentElement, {{attributes: true, attributeFilter: ['data-theme','class']}});
                  new MutationObserver(applyTheme).observe(window.parent.document.body, {{attributes: true, attributeFilter: ['class','style']}});
                }} catch(e) {{}}

                function buildClone(excludeCols) {{
                  var orig = document.getElementById('tbl_{camp_name}');
                  var clone = orig.cloneNode(true);
                  if (excludeCols && excludeCols.length > 0) {{
                    var headers = clone.querySelectorAll('tr')[0].querySelectorAll('th');
                    var colIndexes = [];
                    headers.forEach(function(th, i) {{
                      if (excludeCols.indexOf(th.innerText.trim()) !== -1) colIndexes.push(i);
                    }});
                    clone.querySelectorAll('tr').forEach(function(row) {{
                      var cells = row.querySelectorAll('th, td');
                      colIndexes.slice().reverse().forEach(function(i) {{
                        if (cells[i]) cells[i].remove();
                      }});
                    }});
                  }}
                  clone.querySelectorAll('tr').forEach(function(row) {{
                    var ths = row.querySelectorAll('th');
                    ths.forEach(function(th) {{
                      th.style.background = '#fff'; th.style.color = '#000';
                      th.style.border = '1px solid #ccc'; th.style.fontWeight = 'bold';
                    }});
                    var rowType = row.getAttribute('data-rowtype') || 'normal';
                    row.querySelectorAll('td').forEach(function(td) {{
                      td.style.border = '1px solid #ccc'; td.style.color = '#000';
                      if (rowType === 'itogo') {{ td.style.background = '#fff'; td.style.fontWeight = 'bold'; }}
                      else if (rowType === 'top3') {{ td.style.background = '#d7ead9'; }}
                      else {{ td.style.background = '#fff'; }}
                    }});
                  }});
                  return clone;
                }}
                function copyTable() {{
                  var clone = buildClone([]);
                  var blob = new Blob([clone.outerHTML], {{type: 'text/html'}});
                  navigator.clipboard.write([new ClipboardItem({{'text/html': blob}})]).then(function() {{
                    var btn = document.getElementById('btnCopy_{camp_name}');
                    btn.innerText = '✅ Скопировано';
                    setTimeout(function() {{ btn.innerText = '📋 Копировать'; }}, 2000);
                  }}).catch(function(e) {{ alert('Ошибка: ' + e); }});
                }}
                function copyTableBunker() {{
                  var clone = buildClone(['Список городов']);
                  var blob = new Blob([clone.outerHTML], {{type: 'text/html'}});
                  navigator.clipboard.write([new ClipboardItem({{'text/html': blob}})]).then(function() {{
                    var btn = document.getElementById('btnBunker_{camp_name}');
                    btn.innerText = '✅ Скопировано';
                    setTimeout(function() {{ btn.innerText = '📋 Копировать для бункера'; }}, 2000);
                  }}).catch(function(e) {{ alert('Ошибка: ' + e); }});
                }}
                </script>
                <div style="margin-bottom:6px;">
                  <button id="btnCopy_{camp_name}" onclick="copyTable()" style="margin-right:6px;padding:4px 12px;background:var(--btn-bg);color:var(--btn-color);border:1px solid var(--border-color);border-radius:5px;cursor:pointer;font-size:13px;">📋 Копировать</button>
                  <button id="btnBunker_{camp_name}" onclick="copyTableBunker()" style="padding:4px 12px;background:var(--btn-bg);color:var(--btn-color);border:1px solid var(--border-color);border-radius:5px;cursor:pointer;font-size:13px;">📋 Копировать для бункера</button>
                </div>
                <div id="tbl_wrap_{camp_name}" style="overflow-x:auto;margin-bottom:4px;">
                <table id="tbl_{camp_name}" style="border-collapse:collapse;font-size:13px;font-family:sans-serif;width:100%;">
                {''.join(html_rows)}
                </table>
                </div>
                """

                components.html(table_html, height=(len(full_table) + 2) * 30 + 28, scrolling=False)

                # ГАЛЕРЕЯ ЭТОЙ КАМПАНИИ — сразу под таблицей
                if st.session_state.get('gallery_images_loaded'):
                    st.write(f"#### Галерея: {camp_name}")
                    # Сохраняем порядок как в таблице
                    table_order = list(full_table[camp_name].values[:-1])  # без ИТОГО
                    td = df_c.groupby('Макет').agg({'ad_id': 'first'}).reset_index()
                    td['_order'] = td['Макет'].apply(lambda x: table_order.index(x) if x in table_order else 9999)
                    td = td.sort_values('_order').drop(columns=['_order']).reset_index(drop=True)
                    gallery_items = []
# top3 для галереи — те же что и в таблице
                    top3_gallery = top3_names

                    for idx, row in td.iterrows():
                        if not row['ad_id']:
                            gallery_items.append({'name': row['Макет'], 'img_url': None, 'is_video': False, 'video_src': None})
                            continue
                        try:
                            ad_res = requests.get(
                                f"https://graph.facebook.com/v19.0/{row['ad_id']}"
                                f"?fields=account_id,adcreatives{{image_hash,image_url,thumbnail_url,object_story_spec,asset_feed_spec}}"
                                f"&access_token={TOKEN}", timeout=30
                            ).json()
                            acc_id = ad_res.get('account_id')
                            creative_data = ad_res.get('adcreatives', {}).get('data', [{}])[0]
                            img_url = None
                            video_id = None
                            video_src = None
                            oss = creative_data.get('object_story_spec', {})
                            is_video_creative = (
                                bool(oss.get('video_data', {}).get('video_id')) or
                                bool(creative_data.get('asset_feed_spec', {}).get('videos'))
                            )
                            hashes = []
                            if creative_data.get('image_hash'):
                                hashes.append(creative_data.get('image_hash'))
                            if 'asset_feed_spec' in creative_data:
                                for img_obj in creative_data['asset_feed_spec'].get('images', []):
                                    if img_obj.get('hash'):
                                        hashes.append(img_obj['hash'])
                            if hashes and acc_id:
                                hash_res = requests.get(
                                    f"https://graph.facebook.com/v19.0/act_{acc_id}/adimages",
                                    params={"hashes": json.dumps(list(set(hashes))), "fields": "url,original_width,original_height", "access_token": TOKEN},
                                    timeout=20
                                ).json()
                                if hash_res.get('data'):
                                    best = None
                                    for img_info in hash_res['data']:
                                        w = int(img_info.get('original_width', 0))
                                        h = int(img_info.get('original_height', 0))
                                        if w > 0 and h > 0 and 0.9 <= (w/h) <= 1.1:
                                            best = img_info.get('url')
                                            break
                                    img_url = best or hash_res['data'][0].get('url')
                            if not img_url:
                                video_image_hash = oss.get('video_data', {}).get('image_hash')
                                if video_image_hash and acc_id:
                                    try:
                                        hr2 = requests.get(
                                            f"https://graph.facebook.com/v19.0/act_{acc_id}/adimages",
                                            params={"hashes": json.dumps([video_image_hash]), "fields": "url", "access_token": TOKEN},
                                            timeout=20
                                        ).json()
                                        if hr2.get('data'):
                                            img_url = hr2['data'][0].get('url')
                                    except: pass
                            if oss.get('video_data', {}).get('video_id'):
                                video_id = oss['video_data']['video_id']
                            elif creative_data.get('asset_feed_spec'):
                                videos = creative_data['asset_feed_spec'].get('videos', [])
                                if videos:
                                    video_id = videos[0].get('video_id')
                            if video_id:
                                vid_res = requests.get(
                                    f"https://graph.facebook.com/v19.0/{video_id}?fields=picture,source&access_token={TOKEN}",
                                    timeout=20
                                ).json()
                                if 'error' not in vid_res:
                                    video_src = vid_res.get('source') or None
                                    if not img_url:
                                        raw_pic = vid_res.get('picture', '')
                                        if raw_pic:
                                            img_url = re.sub(r'stp=[^&]*&?', '', raw_pic).rstrip('?&') or None
                                else:
                                    if not img_url:
                                        raw_pic = creative_data.get('thumbnail_url') or creative_data.get('image_url') or ''
                                        if raw_pic:
                                            img_url = re.sub(r'stp=[^&]*&?', '', raw_pic).rstrip('?&') or None
                            if not img_url:
                                raw_fallback = creative_data.get('image_url') or creative_data.get('thumbnail_url') or ''
                                if raw_fallback:
                                    img_url = re.sub(r'stp=[^&]*&?', '', raw_fallback).rstrip('?&') or None
                            if is_video_creative and not video_src:
                                with st.empty():
                                    drive_url = find_video_on_drive(row['Макет'])
                                if drive_url:
                                    video_src = drive_url
                                else:
                                    with st.empty():
                                        img_from_drive = find_image_on_drive(row['Макет'])
                                    if img_from_drive and not img_url:
                                        img_url = img_from_drive
                            # Финальный fallback — ищем фото на Drive даже если не видео
                            if not img_url:
                                with st.empty():
                                    img_from_drive = find_image_on_drive(row['Макет'])
                                if img_from_drive:
                                    img_url = img_from_drive
                            gallery_items.append({'name': row['Макет'], 'img_url': img_url, 'is_video': is_video_creative, 'video_src': video_src})
                        except Exception as e:
                            gallery_items.append({'name': row['Макет'], 'img_url': None, 'is_video': False, 'video_src': None})

                    cards_html = ""
                    for item in gallery_items:
                        is_leader = item['name'] in top3_gallery
                        border_style = 'border:3px solid #e53935;border-radius:12px;' if is_leader else ''
                        if item['img_url']:
                            if item['is_video'] and item.get('video_src'):
                                if 'drive.google.com' in item['video_src']:
                                    media_html = f"""<iframe src="{item['video_src']}" style="width:100%;aspect-ratio:1;border:none;border-radius:10px;" allowfullscreen></iframe>"""
                                else:
                                    media_html = f"""<video src="{item['video_src']}" style="width:100%;height:auto;display:block;border-radius:10px;" controls preload="metadata" playsinline></video>"""
                            else:
                                overlay = ""
                                if item['is_video']:
                                    overlay = """<div style="position:absolute;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.25);display:flex;align-items:center;justify-content:center;border-radius:10px;"><div style="width:48px;height:48px;background:rgba(255,255,255,0.92);border-radius:50%;display:flex;align-items:center;justify-content:center;"><div style="width:0;height:0;margin-left:5px;border-top:10px solid transparent;border-bottom:10px solid transparent;border-left:18px solid #222;"></div></div></div>"""
                                media_html = f"""<div style="position:relative;width:100%;border-radius:10px;overflow:hidden;"><img src="{item['img_url']}" style="width:100%;height:auto;display:block;border-radius:10px;">{overlay}</div>"""
                            cards_html += f"""<div style="display:flex;flex-direction:column;gap:8px;{border_style}padding:{'4px' if is_leader else '0'}">{media_html}<div style="font-size:13px;color:#ccc;word-break:break-word;">{item['name']}</div></div>"""
                        else:
                            cards_html += f"""<div style="display:flex;flex-direction:column;gap:8px;{border_style}padding:{'4px' if is_leader else '0'}"><div style="width:100%;aspect-ratio:1;background:#2a2a2a;border-radius:10px;display:flex;align-items:center;justify-content:center;color:#666;">Нет фото</div><div style="font-size:13px;color:#ccc;">{item['name']}</div></div>"""
                    full_html = f"""<html><head><style>::-webkit-scrollbar{{width:6px}}::-webkit-scrollbar-track{{background:#1e1e1e;border-radius:3px}}::-webkit-scrollbar-thumb{{background:#444;border-radius:3px}}body{{margin:0;padding:0;background:transparent}}</style></head><body><div style="display:grid;grid-template-columns:repeat(5,1fr);gap:12px;margin-top:12px;font-family:sans-serif;">{cards_html}</div></body></html>"""
                    rows_count = (len(gallery_items) + 4) // 5
                    components.html(full_html, height=rows_count * 420 + 50, scrolling=True)

            # Удалите весь старый блок галереи после цикла (от "# Кнопка скачать все таблицы" до конца gallery_items)
        st.stop()

# 5. ЗАГРУЗКА ДАННЫХ ИЗ БАЗЫ
    try:
        from collector import ACCOUNT_LABELS
        selected_db_labels = set()
        for label in selected_labels:
            for acc_id in merged_accounts[label]['ids']:
                db_label = ACCOUNT_LABELS.get(acc_id)
                if db_label:
                    selected_db_labels.add(db_label)

        df_from_db = load_insights_from_db(selected_db_labels, start_date, end_date)

        if df_from_db is None or df_from_db.empty:
            st.warning("Нет данных в базе за выбранный период. Возможно коллектор ещё не запускался.")
            # Показываем когда последний раз обновлялись данные
            try:
                last_sync = supabase.table("fb_sync_log")\
                    .select("finished_at,status")\
                    .order("finished_at", desc=True)\
                    .limit(1).execute()
                if last_sync.data:
                    st.info(f"Последнее обновление: {last_sync.data[0]['finished_at'][:16]} — {last_sync.data[0]['status']}")
            except:
                pass
            st.stop()

        # Переименовываем колонки под старые названия
        df = df_from_db.rename(columns={
            'date_start':    'date_start',
            'country_label': 'Страна',
            'campaign_name': 'campaign_name',
            'impressions':   'impressions',
            'clicks':        'inline_link_clicks',
            'reach':         'reach',
            'spend':         'Затраты',
            'spend_vat':     'Затраты с НДС',
            'spend_rub':     'Затраты (RUB)',
            'spend_vat_rub': 'Затраты с НДС (RUB)',
        })

        if selected_category_label != "Все":
            df = df[df['campaign_name'].str.contains(category_substring, case=False, na=False)]

        if df.empty:
            st.warning(f"В категории '{selected_category_label}' нет данных")
            st.stop()

        df['Дата'] = pd.to_datetime(df['date_start'])
        df['Название кампании'] = df['campaign_name'].apply(clean_campaign_name)
        df = df.rename(columns={'impressions': 'Показы', 'inline_link_clicks': 'Клики', 'reach': 'Охват'})
        for col in ['Показы', 'Клики', 'Охват']:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0).astype(int)

        df_totals = df.groupby(['Страна', 'Название кампании']).agg({
            'Затраты': 'sum',
            'Затраты с НДС': 'sum',
            'Затраты (RUB)': 'sum',
            'Затраты с НДС (RUB)': 'sum',
            'Показы': 'sum',
            'Клики': 'sum',
        }).reset_index()

        # Охват — отдельной таблицей, БЕЗ суммирования по дням
        df_reach = load_reach_from_db(selected_db_labels)
        if df_reach is not None and not df_reach.empty:
            df_reach['campaign_clean'] = df_reach['campaign_name'].apply(clean_campaign_name)
            reach_agg = df_reach.groupby(['country_label', 'campaign_clean'])['reach'].sum().reset_index()
            reach_agg = reach_agg.rename(columns={'country_label': 'Страна', 'campaign_clean': 'Название кампании', 'reach': 'Охват'})
            df_totals = df_totals.merge(reach_agg, on=['Страна', 'Название кампании'], how='left')
            df_totals['Охват'] = df_totals['Охват'].fillna(0).astype(int)
        else:
            df_totals['Охват'] = 0

        all_campaigns = sorted(df_totals['Название кампании'].unique().tolist())

        with st.sidebar:
            st.divider()
            selected_campaigns = st.multiselect("3. Фильтр по кампаниям:", options=all_campaigns, default=all_campaigns)
            st.divider()
            for c in sorted(list(selected_currencies)):
                if c == "RUB":
                    st.info("Валюта: RUB")
                else:
                    sidebar_rates = get_rates(c)
                    sidebar_rub_rate = sidebar_rates.get("RUB") if sidebar_rates else None
                    if sidebar_rub_rate:
                        st.success(f"Курс: 1 {c} = {sidebar_rub_rate:.4f} RUB")
                    else:
                        st.info(f"Валюта: {c}")
            # Показываем время последнего обновления
            try:
                last_sync = supabase.table("fb_sync_log")\
                    .select("finished_at,status")\
                    .order("finished_at", desc=True)\
                    .limit(1).execute()
                if last_sync.data:
                    st.caption(f"🕐 Данные обновлены: {last_sync.data[0]['finished_at'][:16]}")
            except:
                pass
            if st.button('🔄 Обновить'): st.rerun()
            st.divider()
            st.markdown("### 🧭 Навигация")
            if st.button("🖼️ Библиотека креативов", use_container_width=True):
                st.session_state['app_mode'] = "🖼️ Библиотека креативов"
                st.rerun()
            st.divider()
            if st.button("🚪 Выйти"):
                st.session_state["authenticated"] = False
                cookies["authenticated"] = "false"
                cookies.save()
                st.rerun()

        df_totals_filtered = df_totals[df_totals['Название кампании'].isin(selected_campaigns)]
        df_daily_filtered  = df[df['Название кампании'].isin(selected_campaigns)]

        if df_totals_filtered.empty:
            st.warning("Выберите кампанию")
            st.stop()

        # --- ВЫВОД МЕТРИК ---
        st.divider()
        col_m = st.columns([1.3, 1.3, 1.5, 1, 1, 1])

        if curr == "MIXED":
            grouped_df = df_totals_filtered.groupby('Страна')[['Затраты', 'Затраты с НДС']].sum().reset_index()
            spend_lines = []
            nds_lines = []
            for _, row in grouped_df.iterrows():
                c_name = row['Страна']
                c_curr = merged_accounts.get(c_name, {}).get('currency', '')
                curr_text = f" ({c_curr})" if c_curr else ""
                spend_lines.append(f"{c_name}{curr_text} — <b>{row['Затраты']:,.2f}</b>")
                nds_lines.append(f"{c_name}{curr_text} — <b>{row['Затраты с НДС']:,.2f}</b>")
            col_m[0].markdown(f"<div style='font-size:14px;color:gray;margin-bottom:4px;'>Затраты (Лок.)</div><div style='font-size:14px;line-height:1.6;'>{'<br>'.join(spend_lines)}</div>", unsafe_allow_html=True)
            col_m[1].markdown(f"<div style='font-size:14px;color:gray;margin-bottom:4px;'>С НДС (Лок.)</div><div style='font-size:14px;line-height:1.6;'>{'<br>'.join(nds_lines)}</div>", unsafe_allow_html=True)
        else:
            col_m[0].metric(f"Затраты ({curr})", f"{df_totals_filtered['Затраты'].sum():,.2f}")
            col_m[1].metric(f"Затраты с НДС ({curr})", f"{df_totals_filtered['Затраты с НДС'].sum():,.2f}")

        col_m[2].metric("Затраты с НДС (RUB)", f"{df_totals_filtered['Затраты с НДС (RUB)'].sum():,.2f} ₽")
        col_m[3].metric("Показы", f"{df_totals_filtered['Показы'].sum():,}")
        col_m[4].metric("Клики", f"{df_totals_filtered['Клики'].sum():,}")
        col_m[5].metric("Охват", f"{df_totals_filtered['Охват'].sum():,}")

        st.divider()
        st.subheader("📈 Динамика расходов")
        col_g1, col_g2 = st.columns(2)
        unique_countries = sorted(df_totals_filtered['Страна'].unique())
        with col_g1:
            selected_plot_country = st.selectbox("1. Страна для графика:", ["Все выбранные страны (Сумма)"] + unique_countries)
        with col_g2:
            camps_for_plot = sorted(df_totals_filtered['Название кампании'].unique()) if selected_plot_country == "Все выбранные страны (Сумма)" else sorted(df_totals_filtered[df_totals_filtered['Страна'] == selected_plot_country]['Название кампании'].unique())
            selected_plot_camp = st.selectbox("2. Кампания для графика:", ["Все кампании (Сумма)"] + camps_for_plot)

        if selected_plot_country == "Все выбранные страны (Сумма)":
            d_data = df_daily_filtered if selected_plot_camp == "Все кампании (Сумма)" else df_daily_filtered[df_daily_filtered['Название кампании'] == selected_plot_camp]
        else:
            d_data = df_daily_filtered[df_daily_filtered['Страна'] == selected_plot_country] if selected_plot_camp == "Все кампании (Сумма)" else df_daily_filtered[(df_daily_filtered['Страна'] == selected_plot_country) & (df_daily_filtered['Название кампании'] == selected_plot_camp)]
        d_data = d_data.groupby('Дата').agg({'Затраты с НДС (RUB)': 'sum'}).reset_index()

        fig = px.line(d_data.sort_values('Дата'), x='Дата', y='Затраты с НДС (RUB)', markers=True, line_shape='spline')
        st.plotly_chart(fig, use_container_width=True)

        st.subheader("Детальная таблица")
        display_df = df_totals_filtered[['Страна', 'Название кампании', 'Показы', 'Клики', 'Охват', 'Затраты', 'Затраты с НДС', 'Затраты с НДС (RUB)']].copy()
        st.dataframe(display_df.style.format({
            'Затраты': "{:,.2f}", 'Затраты с НДС': "{:,.2f}",
            'Затраты с НДС (RUB)': "{:,.2f}", 'Показы': "{:,.0f}",
            'Клики': "{:,.0f}", 'Охват': "{:,.0f}"
        }), use_container_width=True)

    except Exception as e:
        st.error(f"Ошибка при обработке данных: {e}")
