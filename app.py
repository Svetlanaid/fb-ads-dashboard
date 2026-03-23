import streamlit as st
import requests
import pandas as pd
import plotly.express as px
import os
import re
from dotenv import load_dotenv
from datetime import datetime, timedelta

# 1. Загрузка настроек
load_dotenv()
TOKEN = st.secrets.get("FB_ACCESS_TOKEN") or os.getenv("FB_ACCESS_TOKEN")

# --- БЛОК АВТОРИЗАЦИИ ---
if "users" in st.secrets:
    USERS = st.secrets["users"]
else:
    USERS = {"admin": "admin"}

if "authenticated" not in st.session_state:
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
                st.rerun()
            else:
                st.error("Неверный логин или пароль")

if not st.session_state["authenticated"]:
    login_screen()
    st.stop()

st.set_page_config(page_title="FB Ads Dashboard", layout="wide")
st.title("📈 Аналитика рекламных кабинетов")

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---

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

def clean_campaign_name(name):
    if not name: return name
    short_date_pattern = r'\b\d{1,2}\s*[./-]\s*\d{1,2}\b'
    had_short_date = bool(re.search(short_date_pattern, name))
    cleaned = re.sub(short_date_pattern, " ", name)
    cleaned = re.sub(r'\d{2,}', '', cleaned)
    months_regex = r'\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec|январь|февраль|март|апрель|май|июнь|июль|август|сентябрь|октябрь|ноябрь|декабрь)\b'
    cleaned = re.sub(months_regex, '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'copy', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'[-–—.]', '', cleaned)
    if had_short_date:
        cleaned = re.sub(r'\s+\d\b$', '', cleaned)
    cleaned = re.sub(r'\s{2,}', ' ', cleaned).strip()
    return cleaned if cleaned else name

# --- ОСНОВНАЯ ЛОГИКА ---

if not TOKEN:
    st.error("Токен не найден!")
else:
    # 1. Получение списка активных аккаунтов (с 01.01.2026)
    try:
        cutoff_date = "2026-01-01"
        today_str = datetime.now().strftime('%Y-%m-%d')
        
        accounts_url = f"https://graph.facebook.com/v19.0/me/adaccounts"
        # Запрашиваем инсайты (затраты) прямо в списке аккаунтов за нужный период
        acc_params = {
            "fields": f"name,account_id,currency,insights.time_range({{'since':'{cutoff_date}','until':'{today_str}'}}){{spend}}",
            "limit": 100,
            "access_token": TOKEN
        }
        
        all_accounts_data = []
        acc_response = requests.get(accounts_url, params=acc_params).json()
        
        while True:
            if "data" in acc_response:
                all_accounts_data.extend(acc_response["data"])
            if "paging" in acc_response and "next" in acc_response["paging"]:
                acc_response = requests.get(acc_response["paging"]["next"]).json()
            else:
                break

        # Фильтруем: оставляем только те, где spend > 0 за период с 1 января
        accounts_dict = {}
        for acc in all_accounts_data:
            has_spend = False
            insights = acc.get("insights", {}).get("data", [])
            if insights:
                total_spend = sum(float(day.get('spend', 0)) for day in insights)
                if total_spend > 0:
                    has_spend = True
            
            if has_spend:
                name = acc.get('name') or f"Unnamed ({acc['account_id']})"
                accounts_dict[name] = {
                    'id': acc['account_id'], 
                    'currency': acc.get('currency', 'USD')
                }

        if not accounts_dict:
            st.warning("Не найдено аккаунтов с активной рекламой начиная с 01.01.2026.")
            st.stop()
        
    except Exception as e:
        st.error(f"Ошибка загрузки списка аккаунтов: {e}")
        st.stop()

    # 2. Сайдбар: Настройки
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

        selected_acc_name = st.selectbox("Рекламный аккаунт:", sorted(list(accounts_dict.keys())))
        acc_id = f"act_{accounts_dict[selected_acc_name]['id']}"
        curr = accounts_dict[selected_acc_name]['currency']

        category_options = {"Все": "", "Водители": "exec", "Клиенты": "clnt", "Smm": "smm", "Партнеры": "Prtn"}
        selected_category_label = st.selectbox("Категория:", list(category_options.keys()))
        category_substring = category_options[selected_category_label]

    st.markdown("<style>span[data-baseweb='tag'] {background-color: #1f77b4 !important;}</style>", unsafe_allow_html=True)

    # 4. Загрузка данных (Insights)
    try:
        insights_url = f"https://graph.facebook.com/v19.0/{acc_id}/insights"
        params = {
            "fields": "campaign_name,spend,impressions,inline_link_clicks,reach,date_start",
            "time_range": f"{{'since':'{start_date}','until':'{end_date}'}}",
            "level": "campaign",
            "time_increment": 1, 
            "limit": 500,
            "access_token": TOKEN
        }
        
        all_data = []
        response = requests.get(insights_url, params=params).json()
        
        while True:
            if "data" in response:
                all_data.extend(response["data"])
            if "paging" in response and "next" in response["paging"]:
                response = requests.get(response["paging"]["next"]).json()
            else:
                break

        if len(all_data) > 0:
            df = pd.DataFrame(all_data)
            if selected_category_label != "Все":
                df = df[df['campaign_name'].str.contains(category_substring, case=False, na=False)]
            
            if df.empty:
                st.warning(f"В категории '{selected_category_label}' нет данных")
                st.stop()

            df['Дата'] = pd.to_datetime(df['date_start'])
            df['Затраты'] = df['spend'].astype(float)
            df['Название кампании'] = df['campaign_name'].apply(clean_campaign_name)
            df = df.rename(columns={'impressions': 'Показы', 'inline_link_clicks': 'Клики', 'reach': 'Охват'})
            
            # Конвертация валют
            rates = get_rates(curr)
            rub_rate = rates.get("RUB") if rates else None
            df['Затраты (RUB)'] = (df['Затраты'] * rub_rate).round(0).astype(int) if rub_rate else 0

            df_totals = df.groupby('Название кампании').agg({
                'Затраты': 'sum', 'Затраты (RUB)': 'sum', 'Показы': 'sum', 'Клики': 'sum', 'Охват': 'sum'
            }).reset_index()

            all_campaigns = sorted(df_totals['Название кампании'].unique().tolist())
            with st.sidebar:
                st.divider()
                selected_campaigns = st.multiselect("3. Фильтр кампаний:", options=all_campaigns, default=all_campaigns)
                
                if st.button('🔄 Обновить данные'): st.rerun()
                if st.button("🚪 Выйти"):
                    st.session_state["authenticated"] = False
                    st.rerun()

            df_totals_filtered = df_totals[df_totals['Название кампании'].isin(selected_campaigns)]
            df_daily_filtered = df[df['Название кампании'].isin(selected_campaigns)]

            if df_totals_filtered.empty:
                st.warning("Выберите кампанию")
                st.stop()

            # Метрики
            st.divider()
            m_col = st.columns(5)
            m_col[0].metric(f"Затраты ({curr})", f"{df_totals_filtered['Затраты'].sum():,.0f}")
            m_col[1].metric("Затраты (RUB)", f"{df_totals_filtered['Затраты (RUB)'].sum():,.0f} ₽")
            m_col[2].metric("Показы", f"{df_totals_filtered['Показы'].sum():,}")
            m_col[3].metric("Клики", f"{df_totals_filtered['Клики'].sum():,}")
            m_col[4].metric("Охват", f"{df_totals_filtered['Охват'].sum():,}")

            # График
            st.divider()
            st.subheader("📈 Динамика расходов")
            current_camps = list(df_totals_filtered['Название кампании'].unique())
            camp_opts = (["Все кампании"] + current_camps) if len(selected_campaigns) > 1 else current_camps
            camp_to_plot = st.selectbox("Кампания для графика:", options=camp_opts)

            if camp_to_plot == "Все кампании":
                d_data = df_daily_filtered.groupby('Дата').agg({'Затраты (RUB)': 'sum'}).reset_index()
            else:
                d_data = df_daily_filtered[df_daily_filtered['Название кампании'] == camp_to_plot].groupby('Дата').agg({'Затраты (RUB)': 'sum'}).reset_index()

            fig = px.line(d_data.sort_values('Дата'), x='Дата', y='Затраты (RUB)', markers=True, line_shape='spline')
            st.plotly_chart(fig, use_container_width=True)

            st.subheader("Детальная таблица")
            st.dataframe(df_totals_filtered[['Название кампании', 'Показы', 'Клики', 'Охват', 'Затраты', 'Затраты (RUB)']], use_container_width=True)

        else:
            st.warning("Нет данных за выбранный период.")

    except Exception as e:
        st.error(f"Ошибка: {e}")