import streamlit as st
import requests
import pandas as pd
import plotly.express as px
import os
import re
from dotenv import load_dotenv
from datetime import datetime, timedelta

# 1. Загрузка настроек (Сначала из Secrets, если нет — из .env)
load_dotenv()
TOKEN = st.secrets.get("FB_ACCESS_TOKEN") or os.getenv("FB_ACCESS_TOKEN")

# --- БЛОК АВТОРИЗАЦИИ (Берем данные из облака) ---
if "users" in st.secrets:
    USERS = st.secrets["users"]
else:
    # Заглушка для локального запуска (логин: admin, пароль: admin)
    USERS = {"admin": "admin"}

if "authenticated" not in st.session_state:
    st.session_state["authenticated"] = False

def login_screen():
    st.markdown("<h2 style='text-align: center;'>Вход в систему</h2>", unsafe_allow_html=True)
    col_l, col_m, col_r = st.columns([1, 2, 1])
    with col_m:
        # Добавили key, чтобы ввод не «слетал»
        user = st.text_input("Логин", key="username")
        password = st.text_input("Пароль", type="password", key="password")
        if st.button("Войти", use_container_width=True):
            # Переводим всё в строку str(), чтобы сравнение было точным
            if user in USERS and str(USERS[user]) == str(password):
                st.session_state["authenticated"] = True
                st.rerun()
            else:
                st.error("Неверный логин или пароль")

if not st.session_state["authenticated"]:
    login_screen()
    st.stop()
# ------------------------------------------------
# ------------------------

st.set_page_config(page_title="FB Ads Dashboard", layout="wide")
st.title("📈 Аналитика рекламных кабинетов")

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---

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

# --- ОСНОВНАЯ ЛОГИКА ---

if not TOKEN:
    st.error("Токен не найден! Проверьте файл .env")
else:
    # --- ВСТАВИТЬ СЮДА (начало блока else) ---
    VAT_MAP = {
        "509917460493340": 1.11,      # Indonesia AR
        "817547549239841": 1.11,      # TH
        "1591493017715668": 1.11,     # Indonesia
        "257290219582370": 1.11,      # Indonesia exec
        "398026798982273": 1.08,      # Malaysia usd
        "2727239577416075": 1.07,     # Thailand
        "2295720397582070": 1.18,     # Tanzania
        "830039013207696": 1.15,      # South Africa ZA
        "24948463558072461": 1 / (1 - 0.029 - 0.0925), # Brasil
    }
# 1. Получение списка АКТИВНЫХ аккаунтов (с 01.01.2026)
    try:
        cutoff_date = "2026-01-01"
        today_str = datetime.now().strftime('%Y-%m-%d')
        
        accounts_url = f"https://graph.facebook.com/v19.0/me/adaccounts"
        # В поля (fields) добавляем запрос инсайтов за период, чтобы проверить Spend
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

        # ФИЛЬТРАЦИЯ: Оставляем только те, где были траты в 2026 году
        accounts_dict = {}
        for acc in all_accounts_data:
            insights = acc.get("insights", {}).get("data", [])
            # Если есть хоть какая-то запись о тратах в этом периоде
            if insights and any(float(day.get('spend', 0)) > 0 for day in insights):
                name = acc.get('name') or f"Unnamed ({acc['account_id']})"
                accounts_dict[name] = {
                    'id': acc['account_id'], 
                    'currency': acc.get('currency', 'USD')
                }

        if not accounts_dict:
            st.warning("Не найдено аккаунтов с тратами начиная с 01.01.2026.")
            st.stop()
        
    except Exception as e:
        st.error(f"Ошибка загрузки списка аккаунтов: {e}")
        st.stop()

    # --- БЛОК ОБЪЕДИНЕНИЯ АККАУНТОВ ---
    # Этот блок теперь выровнен правильно (на одном уровне с except и with st.sidebar)
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
    # ----------------------------------

    # 2. Сайдбар: Настройки
    with st.sidebar:

    # 2. Сайдбар: Настройки
    with st.sidebar:
        st.header("Настройки")
        today = datetime.now()
        start_default = today - timedelta(days=30)
        date_range = st.date_input("Период:", value=(start_default, today), max_value=today, format="DD.MM.YYYY")

        if isinstance(date_range, tuple) and len(date_range) == 2:
            start_date, end_date = date_range
        else:
            st.info("Выберите дату окончания в календаре")
            st.stop()

        # Заменяем старый selectbox на новый
        selected_label = st.selectbox("Рекламный аккаунт:", sorted(list(merged_accounts.keys())))
        
        # Теперь у нас может быть список ID
        list_of_ids = merged_accounts[selected_label]['ids']
        curr = merged_accounts[selected_label]['currency']
        
        # Налог берем по первому ID в группе (обычно он одинаковый для страны)
        vat_mult = VAT_MAP.get(list_of_ids[0], 1.0)

        # НОВЫЙ БЛОК: Выбор категории
        category_options = {
            "Все": "",
            "Водители": "exec",
            "Клиенты": "clnt",
            "Smm": "smm",
            "Партнеры": "Prtn"
        }
        selected_category_label = st.selectbox("Категория:", list(category_options.keys()))
        category_substring = category_options[selected_category_label]

    # 3. CSS: Красим фильтры в синий
    st.markdown("<style>span[data-baseweb='tag'] {background-color: #1f77b4 !important;}</style>", unsafe_allow_html=True)

    try:
        all_data = []
        
        # ЦИКЛ ПО ВСЕМ ID В ГРУППЕ
        for single_id in list_of_ids:
            temp_acc_id = f"act_{single_id}"
            insights_url = f"https://graph.facebook.com/v19.0/{temp_acc_id}/insights"
            params = {
                "fields": "campaign_name,spend,impressions,inline_link_clicks,reach,date_start",
                "time_range": f"{{'since':'{start_date}','until':'{end_date}'}}",
                "level": "campaign",
                "time_increment": 1, 
                "limit": 500,
                "access_token": TOKEN
            }
            
            response = requests.get(insights_url, params=params).json()
            
            # Собираем страницы данных для ЭТОГО аккаунта
            while True:
                if "data" in response:
                    all_data.extend(response["data"])
                if "paging" in response and "next" in response["paging"]:
                    response = requests.get(response["paging"]["next"]).json()
                else:
                    break
        

        if len(all_accounts_data) > 0:
            df = pd.DataFrame(all_data)
            
            # 1. Фильтрация по категории (делаем сразу)
            if selected_category_label != "Все":
                df = df[df['campaign_name'].str.contains(category_substring, case=False, na=False)]
            
            if df.empty:
                st.warning(f"В категории '{selected_category_label}' нет данных")
                st.stop()

            # 2. Основные расчеты (строго по порядку)
            df['Дата'] = pd.to_datetime(df['date_start'])
            df['Затраты'] = df['spend'].astype(float) # Создаем базу
            df['Затраты с НДС'] = df['Затраты'] * vat_mult # Считаем НДС
            
            # 3. Работа с курсом (один раз)
            rates = get_rates(curr)
            rub_rate = rates.get("RUB") if rates else None
            
            if rub_rate:
                df['Затраты (RUB)'] = (df['Затраты'] * rub_rate).round(0).astype(int)
                df['Затраты с НДС (RUB)'] = (df['Затраты с НДС'] * rub_rate).round(0).astype(int)
            else:
                df['Затраты (RUB)'] = 0
                df['Затраты с НДС (RUB)'] = 0

            # 4. Чистка имен и объединение стран
            df['Название кампании'] = df['campaign_name'].apply(clean_campaign_name)
            
            mapping = {
                "Indonesia exec": "Indonesia",
                "PH exec": "Philippines",
                "PH usd": "Philippines",
                "Belarus usd": "Belarus"
            }
            df['Название кампании'] = df['Название кампании'].replace(mapping)

            # 5. Типы данных и переименование
            df = df.rename(columns={'impressions': 'Показы', 'inline_link_clicks': 'Клики', 'reach': 'Охват'})
            for col in ['Показы', 'Клики', 'Охват']:
                df[col] = df[col].astype(int)

            # 6. Группировка (собираем все нужные колонки)
            df_totals = df.groupby('Название кампании').agg({
                'Затраты': 'sum',
                'Затраты с НДС': 'sum',
                'Затраты (RUB)': 'sum',
                'Затраты с НДС (RUB)': 'sum',
                'Показы': 'sum',
                'Клики': 'sum',
                'Охват': 'sum'
            }).reset_index()

            # Фильтр кампаний в сайдбаре
            all_campaigns = sorted(df_totals['Название кампании'].unique().tolist())
            with st.sidebar:
                st.divider()
                selected_campaigns = st.multiselect("3. Фильтр по кампаниям:", options=all_campaigns, default=all_campaigns)
                
                st.divider()
                if curr == "RUB":
                    st.info("Валюта: RUB")
                elif rub_rate:
                    st.success(f"Курс: 1 {curr} = {rub_rate:.4f} RUB")
                
                if st.button('🔄 Обновить данные'):
                    st.rerun()

                st.divider()
                if st.button("🚪 Выйти"):
                    st.session_state["authenticated"] = False
                    st.rerun()

            # Применяем фильтр
            df_totals_filtered = df_totals[df_totals['Название кампании'].isin(selected_campaigns)]
            df_daily_filtered = df[df['Название кампании'].isin(selected_campaigns)]

            if df_totals_filtered.empty:
                st.warning("Выберите хотя бы одну кампанию")
                st.stop()

            # --- ВЫВОД ДАННЫХ ---
            st.divider()
            col_m = st.columns(6) # Теперь 6 колонок
            
            col_m[0].metric(f"Всего ({curr})", f"{df_totals_filtered['Затраты'].sum():,.0f}")
            col_m[1].metric(f"С НДС ({curr})", f"{df_totals_filtered['Затраты с НДС'].sum():,.0f}")
            col_m[2].metric("RUB + НДС", f"{df_totals_filtered['Затраты с НДС (RUB)'].sum():,.0f} ₽")
            
            col_m[3].metric("Показы", f"{df_totals_filtered['Показы'].sum():,}")
            col_m[4].metric("Клики", f"{df_totals_filtered['Клики'].sum():,}")
            col_m[5].metric("Охват", f"{df_totals_filtered['Охват'].sum():,}")

            # --- ГРАФИК ДИНАМИКИ (Вместо столбчатого) ---
            st.divider()
            st.subheader("📈 Динамика расходов по дням")
            
            # Получаем список уникальных (схлопнутых) имен из отфильтрованных данных
            current_campaigns = list(df_totals_filtered['Название кампании'].unique())

            # Исключение: "Все кампании" появляется только если выбрано > 1 кампании
            if len(selected_campaigns) > 1:
                campaign_options = ["Все кампании"] + current_campaigns
            else:
                campaign_options = current_campaigns

            campaign_to_plot = st.selectbox("Выберите кампанию для анализа динамики:", options=campaign_options)

            if campaign_to_plot == "Все кампании":
                # Группируем все данные по дате
                daily_data = df_daily_filtered.groupby('Дата').agg({'Затраты (RUB)': 'sum'}).reset_index()
                title_text = "Общая динамика расходов (RUB) по всем выбранным кампаниям"
            else:
                # Отрисовка конкретной кампании
                daily_data = df_daily_filtered[df_daily_filtered['Название кампании'] == campaign_to_plot].copy()
                daily_data = daily_data.groupby('Дата').agg({'Затраты (RUB)': 'sum'}).reset_index()
                title_text = f"Ежедневный расход (RUB): {campaign_to_plot}"

            daily_data = daily_data.sort_values('Дата')

            if not daily_data.empty:
                fig_daily = px.line(daily_data, 
                                   x='Дата', 
                                   y='Затраты (RUB)', 
                                   title=title_text,
                                   markers=True, 
                                   line_shape='spline',
                                   color_discrete_sequence=['#1f77b4'])
                
                fig_daily.update_layout(hovermode="x unified")
                st.plotly_chart(fig_daily, use_container_width=True)
            else:
                st.info("Нет данных для отображения графика.")

            # --- ТАБЛИЦА (теперь сразу под графиком) ---
            st.subheader("Детальная таблица")
            st.dataframe(df_totals_filtered[['Название кампании', 'Показы', 'Клики', 'Охват', 'Затраты', 'Затраты (RUB)']], use_container_width=True)

        else:
            st.warning("Нет данных за выбранный период.")

    except Exception as e:
        st.error(f"Ошибка при обработке данных: {e}")