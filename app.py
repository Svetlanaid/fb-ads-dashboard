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
    # 1. КАРТА НДС
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
        
        all_accounts_data = []
        acc_response = requests.get(accounts_url, params=acc_params).json()
        
        while True:
            if "data" in acc_response:
                all_accounts_data.extend(acc_response["data"])
            if "paging" in acc_response and "next" in acc_response["paging"]:
                acc_response = requests.get(acc_response["paging"]["next"]).json()
            else:
                break

        accounts_dict = {}
        for acc in all_accounts_data:
            insights = acc.get("insights", {}).get("data", [])
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
        
        # СТАЛО:
        selected_labels = st.multiselect(
            "Рекламный аккаунт:", 
            options=sorted(list(merged_accounts.keys())),
            default=[sorted(list(merged_accounts.keys()))[0]] if merged_accounts else [] # По умолчанию выбираем первый
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

        category_options = {"Все": "", "Водители": "exec", "Клиенты": "clnt", "Smm": "smm", "Партнеры": "Prtn"}
        selected_category_label = st.selectbox("Категория:", list(category_options.keys()))
        category_substring = category_options[selected_category_label]

    st.markdown("<style>span[data-baseweb='tag'] {background-color: #1f77b4 !important;}</style>", unsafe_allow_html=True)
        
# 5. ЗАГРУЗКА И ОБРАБОТКА ДАННЫХ
    try:
        all_data = []
        
        # --- ИЗМЕНЕНИЕ: Идем по выбранным странам, чтобы запомнить, к какой из них относятся данные ---
        for label in selected_labels:
            for single_id in merged_accounts[label]['ids']:
                current_vat_mult = VAT_MAP.get(single_id, 1.0)
                
                temp_acc_id = f"act_{single_id}"
                insights_url = f"https://graph.facebook.com/v19.0/{temp_acc_id}/insights"
                params = {
                    "fields": "account_currency,campaign_name,spend,impressions,inline_link_clicks,reach,date_start",
                    "time_range": f"{{'since':'{start_date}','until':'{end_date}'}}",
                    "level": "campaign",
                    "time_increment": 1, 
                    "limit": 500,
                    "access_token": TOKEN
                }
                
                response = requests.get(insights_url, params=params).json()
                
                temp_data = []
                while True:
                    if "data" in response:
                        temp_data.extend(response["data"])
                    if "paging" in response and "next" in response["paging"]:
                        response = requests.get(response["paging"]["next"]).json()
                    else:
                        break
                        
                if temp_data:
                    df_temp = pd.DataFrame(temp_data)
                    
                    # Сохраняем название страны (ID, MY, Indonesia) в отдельную колонку!
                    df_temp['Страна'] = label 
                    
                    df_temp['Затраты'] = df_temp['spend'].astype(float)
                    df_temp['Затраты с НДС'] = df_temp['Затраты'] * current_vat_mult
                    
                    acc_curr = df_temp['account_currency'].iloc[0] if 'account_currency' in df_temp.columns else "USD"
                    
                    rates = get_rates(acc_curr)
                    rub_rate = rates.get("RUB") if rates else None
                    
                    if rub_rate:
                        df_temp['Затраты (RUB)'] = (df_temp['Затраты'] * rub_rate).round(0).astype(int)
                        df_temp['Затраты с НДС (RUB)'] = (df_temp['Затраты с НДС'] * rub_rate).round(0).astype(int)
                    else:
                        df_temp['Затраты (RUB)'] = 0
                        df_temp['Затраты с НДС (RUB)'] = 0
                        
                    cols_to_keep = ['date_start', 'campaign_name', 'Страна', 'impressions', 'inline_link_clicks', 'reach', 'Затраты', 'Затраты с НДС', 'Затраты (RUB)', 'Затраты с НДС (RUB)']
                    for c in cols_to_keep:
                        if c not in df_temp.columns:
                             df_temp[c] = 0 if c not in ['date_start', 'campaign_name', 'Страна'] else None
                             
                    all_data.append(df_temp[cols_to_keep])

        if len(all_data) > 0:
            df = pd.concat(all_data, ignore_index=True)
            
            # 1. Сначала фильтруем по категории (ищем "exec", "smm" в оригинальных названиях)
            if selected_category_label != "Все":
                df = df[df['campaign_name'].str.contains(category_substring, case=False, na=False)]
            
            if df.empty:
                st.warning(f"В категории '{selected_category_label}' нет данных")
                st.stop()

            # 2. Форматирование дат
            df['Дата'] = pd.to_datetime(df['date_start'])
            
            # 3. МАГИЯ ЗДЕСЬ: Переименовываем все кампании в название Страны!
            # Теперь весь дашборд будет группироваться по странам, а не по отдельным кампаниям.
            df['Название кампании'] = df['Страна'] 

            df = df.rename(columns={'impressions': 'Показы', 'inline_link_clicks': 'Клики', 'reach': 'Охват'})
            for col in ['Показы', 'Клики', 'Охват']:
                df[col] = df[col].astype(int)

            # Группируем данные в df_totals по Стране И Кампании
            df_totals = df.groupby(['Страна', 'Название кампании']).agg({
                'Затраты': 'sum',
                'Затраты с НДС': 'sum',
                'Затраты (RUB)': 'sum',
                'Затраты с НДС (RUB)': 'sum',
                'Показы': 'sum',
                'Клики': 'sum',
                'Охват': 'sum'
            }).reset_index()

            # Вот она, наша переменная all_campaigns!
            all_campaigns = sorted(df_totals['Название кампании'].unique().tolist())
            
            with st.sidebar:
                st.divider()
                selected_campaigns = st.multiselect("3. Фильтр:", options=all_campaigns, default=all_campaigns)
                
                st.divider()
                if curr == "MIXED":
                    st.info("Выбраны разные валюты")
                elif curr == "RUB":
                    st.info("Валюта: RUB")
                else:
                    # Специально для сайдбара запрашиваем актуальный курс
                    sidebar_rates = get_rates(curr)
                    sidebar_rub_rate = sidebar_rates.get("RUB") if sidebar_rates else None
                    
                    if sidebar_rub_rate:
                        st.success(f"Курс: 1 {curr} = {sidebar_rub_rate:.4f} RUB")
                    else:
                        st.info(f"Валюта: {curr}")
                
                if st.button('🔄 Обновить'): st.rerun()
                st.divider()
                if st.button("🚪 Выйти"):
                    st.session_state["authenticated"] = False
                    st.rerun()

            df_totals_filtered = df_totals[df_totals['Название кампании'].isin(selected_campaigns)]
            df_daily_filtered = df[df['Название кампании'].isin(selected_campaigns)]

            if df_totals_filtered.empty:
                st.warning("Выберите кампанию")
                st.stop()

            if df_totals_filtered.empty:
                st.warning("Выберите кампанию")
                st.stop()

            # --- ВЫВОД МЕТРИК ---
            # --- ВЫВОД МЕТРИК ---
            st.divider()
            col_m = st.columns(6)
            
            if curr == "MIXED":
                # Группируем суммы по СТРАНАМ
                grouped_df = df_totals_filtered.groupby('Страна')[['Затраты', 'Затраты с НДС']].sum().reset_index()
                
                spend_lines = []
                nds_lines = []
                
                for _, row in grouped_df.iterrows():
                    c_name = row['Страна'] # Берем имя страны!
                    # Находим валюту
                    c_curr = merged_accounts.get(c_name, {}).get('currency', '')
                    curr_text = f" ({c_curr})" if c_curr else ""
                    
                    # Формируем строчки списка
                    spend_lines.append(f"{c_name}{curr_text} — <b>{row['Затраты']:,.0f}</b>")
                    nds_lines.append(f"{c_name}{curr_text} — <b>{row['Затраты с НДС']:,.0f}</b>")
                
                # Склеиваем строки
                spend_html = "<br>".join(spend_lines)
                nds_html = "<br>".join(nds_lines)
                
                col_m[0].markdown(f"<div style='font-size: 14px; color: gray; margin-bottom: 4px;'>Затраты (Лок.)</div><div style='font-size: 14px; line-height: 1.6;'>{spend_html}</div>", unsafe_allow_html=True)
                col_m[1].markdown(f"<div style='font-size: 14px; color: gray; margin-bottom: 4px;'>С НДС (Лок.)</div><div style='font-size: 14px; line-height: 1.6;'>{nds_html}</div>", unsafe_allow_html=True)
            else:
                col_m[0].metric(f"Затраты ({curr})", f"{df_totals_filtered['Затраты'].sum():,.0f}")
                col_m[1].metric(f"Затраты с НДС ({curr})", f"{df_totals_filtered['Затраты с НДС'].sum():,.0f}")
                
            col_m[2].metric("Затраты с НДС (RUB)", f"{df_totals_filtered['Затраты с НДС (RUB)'].sum():,.0f} ₽")
            col_m[3].metric("Показы", f"{df_totals_filtered['Показы'].sum():,}")
            col_m[4].metric("Клики", f"{df_totals_filtered['Клики'].sum():,}")
            col_m[5].metric("Охват", f"{df_totals_filtered['Охват'].sum():,}")

            # Графики и таблица
            st.divider()
            st.subheader("📈 Динамика расходов")
            current_camps = list(df_totals_filtered['Название кампании'].unique())
            camp_opts = (["Все кампании"] + current_camps) if len(selected_campaigns) > 1 else current_camps
            camp_to_plot = st.selectbox("Выбор для графика:", options=camp_opts)

            if camp_to_plot == "Все кампании":
                d_data = df_daily_filtered.groupby('Дата').agg({'Затраты с НДС (RUB)': 'sum'}).reset_index()
            else:
                d_data = df_daily_filtered[df_daily_filtered['Название кампании'] == camp_to_plot].groupby('Дата').agg({'Затраты с НДС (RUB)': 'sum'}).reset_index()

            fig = px.line(d_data.sort_values('Дата'), x='Дата', y='Затраты с НДС (RUB)', markers=True, line_shape='spline')
            st.plotly_chart(fig, use_container_width=True)

            st.subheader("Детальная таблица")
            
            # Получаем список уникальных стран, которые остались после фильтрации
            unique_countries = sorted(df_totals_filtered['Страна'].unique())
            
            for c_name in unique_countries:
                # Если выбрано несколько стран, добавляем заголовок перед таблицей
                if len(unique_countries) > 1:
                    st.markdown(f"#### {c_name}")
                
                # Достаем валюту конкретно для этой страны
                c_curr = merged_accounts.get(c_name, {}).get('currency', 'USD')
                
                # Фильтруем кампании только для текущей страны
                country_df = df_totals_filtered[df_totals_filtered['Страна'] == c_name]
                
                # Подготавливаем таблицу к выводу
                display_df = country_df[['Название кампании', 'Показы', 'Клики', 'Охват', 'Затраты', 'Затраты с НДС', 'Затраты с НДС (RUB)']].copy()
                
                display_df['Затраты'] = display_df['Затраты'].round(0).astype(int)
                display_df['Затраты с НДС'] = display_df['Затраты с НДС'].round(0).astype(int)
                
                col_name_zatraty = f'Затраты ({c_curr})'
                col_name_nds = f'Затраты с НДС ({c_curr})'
                
                display_df = display_df.rename(columns={
                    'Затраты': col_name_zatraty,
                    'Затраты с НДС': col_name_nds
                })
                
                # Выводим таблицу
                st.dataframe(
                    display_df.style.format({
                        col_name_zatraty: "{:,.0f}",
                        col_name_nds: "{:,.0f}",
                        'Затраты с НДС (RUB)': "{:,.0f}",
                        'Показы': "{:,.0f}",
                        'Клики': "{:,.0f}",
                        'Охват': "{:,.0f}"
                    }), 
                    use_container_width=True
                )
        else:
            st.warning("Нет данных за выбранный период.")

    except Exception as e:
        st.error(f"Ошибка при обработке данных: {e}")