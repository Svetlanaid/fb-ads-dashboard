"""
collector.py — Скрипт сбора данных из Facebook Ads → Supabase
Запускается автоматически 4 раза в день через GitHub Actions
"""

import os
from dotenv import load_dotenv
load_dotenv()
import re
import requests
from datetime import datetime, timedelta
from supabase import create_client

# ============================================================
# НАСТРОЙКИ — берутся из переменных окружения (GitHub Secrets)
# ============================================================
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]
FB_TOKEN     = os.environ["FB_ACCESS_TOKEN"]

# Создаём подключение к Supabase
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# ============================================================
# КАРТА НДС — точно такая же как в app.py
# ============================================================
VAT_MAP = {
    "24946866675014329": 1.0,        # Азербайджан
    "509917460493340":   1.11,       # Аргентина
    "2110787599718272":  1.0,        # Беларусь
    "1013441868511084":  1.0,        # Болгария
    "24948463558072461": 1 / (1 - 0.029 - 0.0925),  # Бразилия
    "192474577136849":   1.0,        # Вьетнам
    "582893932494739":   1.0,        # Грузия
    "817547549239841":   1.11,       # Доминикана
    "1591493017715668":  1.11,       # Индонезия
    "257290219582370":   1.11,       # Индонезия 2
    "351583944532627":   1.0,        # Колумбия
    "398026798982273":   1.08,       # Малайзия
    "1323600845784691":  1.0,        # Перу
    "209570214255009":   1.0,        # Таджикистан
    "2727239577416075":  1.07,       # Таиланд
    "2295720397582070":  1.18,       # Танзания
    "351994210156217":   1.11,       # Танзания 2
    "2050316328716958":  1.0,        # Филиппины
    "1052629215643734":  1.0,        # Филиппины 2
    "830039013207696":   1.15,       # ЮАР
    "3710708579188840":  1.10,       # LA
}

# Метки стран для каждого аккаунта
ACCOUNT_LABELS = {
    "24946866675014329": "Maxim Azerbaijan",
    "509917460493340":   "Maxim Argentina",
    "2110787599718272":  "Belarus",
    "1013441868511084":  "Maxim Bulgaria",
    "24948463558072461": "Maxim Brasil",
    "192474577136849":   "Maxim Vietnam",
    "582893932494739":   "Maxim Georgia",
    "817547549239841":   "Maxim Dominican Republic",
    "1591493017715668":  "Maxim Indonesia",
    "257290219582370":   "Maxim Indonesia",
    "351583944532627":   "Maxim Colombia",
    "398026798982273":   "Maxim Malaysia",
    "1323600845784691":  "Maxim Peru",
    "209570214255009":   "Maxim Tajikistan",
    "2727239577416075":  "Maxim Thailand",
    "2295720397582070":  "Tanzania",
    "351994210156217":   "Tanzania",
    "2050316328716958":  "Maxim Philippines",
    "1052629215643734":  "Maxim Philippines",
    "830039013207696":   "Maxim South Africa",
    "3710708579188840":  "LA",
}

# ============================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================

def get_rub_rate(currency: str) -> float:
    """Получает курс валюты к рублю"""
    try:
        resp = requests.get(
            f"https://open.er-api.com/v6/latest/{currency}",
            timeout=10
        ).json()
        if resp.get("result") == "success":
            return resp["rates"].get("RUB", 1.0)
    except Exception as e:
        print(f"  ⚠️ Ошибка получения курса {currency}: {e}")
    return 1.0


def get_all_account_ids() -> list:
    """Получает список всех аккаунтов из FB"""
    print("📋 Получаем список аккаунтов из Facebook...")
    account_ids = []
    try:
        url = "https://graph.facebook.com/v19.0/me/adaccounts"
        params = {
            "fields": "account_id,currency",
            "limit": 100,
            "access_token": FB_TOKEN
        }
        while url:
            resp = requests.get(url, params=params, timeout=60).json()
            if "error" in resp:
                print(f"  ❌ Ошибка FB API: {resp['error'].get('message')}")
                break
            for acc in resp.get("data", []):
                account_ids.append({
                    "id": acc["account_id"],
                    "currency": acc.get("currency", "USD")
                })
            url = resp.get("paging", {}).get("next")
            params = {}  # для следующих страниц параметры уже в URL
    except Exception as e:
        print(f"  ❌ Ошибка получения аккаунтов: {e}")
    print(f"  ✅ Найдено аккаунтов: {len(account_ids)}")
    return account_ids


def log_sync(started_at, status: str, message: str = ""):
    """Записывает лог синхронизации в базу"""
    try:
        supabase.table("fb_sync_log").insert({
            "started_at": started_at.isoformat(),
            "finished_at": datetime.now().isoformat(),
            "status": status,
            "message": message
        }).execute()
    except Exception as e:
        print(f"  ⚠️ Не удалось записать лог: {e}")


# ============================================================
# СБОР СТАТИСТИКИ ПО КАМПАНИЯМ (для раздела "Общая статистика")
# ============================================================

def collect_insights(account_id: str, currency: str, since: str, until: str):
    """
    Собирает статистику по кампаниям за указанный период
    и сохраняет в таблицу fb_insights_daily
    """
    vat_mult   = VAT_MAP.get(account_id, 1.0)
    label      = ACCOUNT_LABELS.get(account_id, account_id)
    rub_rate   = get_rub_rate(currency)

    print(f"  📊 Собираем статистику: {label} ({account_id}), курс {currency}={rub_rate:.2f}₽")

    rows_to_upsert = []
    url = f"https://graph.facebook.com/v19.0/act_{account_id}/insights"
    params = {
        "fields": "campaign_name,spend,impressions,clicks,inline_link_clicks,reach,actions,date_start",
        "time_range": f"{{'since':'{since}','until':'{until}'}}",
        "level": "campaign",
        "time_increment": 1,
        "action_attribution_windows": "['7d_click','1d_view']",
        "limit": 500,
        "access_token": FB_TOKEN
    }

    try:
        while url:
            resp = requests.get(url, params=params, timeout=120).json()
            if "error" in resp:
                print(f"    ⚠️ Ошибка insights: {resp['error'].get('message')}")
                break

            for row in resp.get("data", []):
                spend = float(row.get("spend", 0))
                impressions = int(row.get("impressions", 0))
                # Если в этот день не было ни расхода, ни показов — это атрибутивный хвост старой кампании, пропускаем
                if spend <= 0 and impressions <= 0:
                    continue
                leads_count = parse_leads(row.get("actions"), row.get("campaign_name", ""))

                rows_to_upsert.append({
                    "date_start":    row["date_start"],
                    "account_id":    account_id,
                    "country_label": label,
                    "campaign_name": row.get("campaign_name", ""),
                    "spend":         spend,
                    "spend_vat":     spend * vat_mult,
                    "spend_rub":     spend * rub_rate,
                    "spend_vat_rub": spend * vat_mult * rub_rate,
                    "impressions":   int(row.get("impressions", 0)),
                    "clicks":        int(row.get("inline_link_clicks", 0)),
                    "reach":         int(row.get("reach", 0)),
                    "currency":      currency,
                })

            url    = resp.get("paging", {}).get("next")
            params = {}

    except Exception as e:
        print(f"    ❌ Ошибка при сборе insights: {e}")
        return

    # Сохраняем в Supabase пачками по 500 строк
    if rows_to_upsert:
        try:
            batch_size = 500
            for i in range(0, len(rows_to_upsert), batch_size):
                batch = rows_to_upsert[i:i + batch_size]
                supabase.table("fb_insights_daily").upsert(
                    batch,
                    on_conflict="date_start,account_id,campaign_name"
                ).execute()
            print(f"    ✅ Сохранено строк статистики: {len(rows_to_upsert)}")
        except Exception as e:
            print(f"    ❌ Ошибка сохранения в Supabase: {e}")
    else:
        print(f"    ℹ️ Нет данных для сохранения")


# ============================================================
# СБОР ДАННЫХ ПО МАКЕТАМ (для раздела "Библиотека креативов")
# ============================================================

def parse_leads(actions, campaign_name: str = "") -> int:
    """Считает 'Результат' по правилам:
       - Если в названии кампании есть 'TD' → App promotion, берём инсталлы
       - Иначе → Leads, берём лиды из формы FB
    """
    if not isinstance(actions, list):
        return 0

    is_app_promo = "TD" in (campaign_name or "").upper()

    if is_app_promo:
        # App promotion: инсталлы. Берём максимум, т.к. FB иногда отдаёт
        # одно и то же под разными именами (app_install / mobile_app_install / omni_app_install).
        target_types = {"app_install", "mobile_app_install", "omni_app_install"}
        values = []
        for action in actions:
            if action.get("action_type") in target_types:
                try:
                    values.append(int(float(action.get("value", 0))))
                except (ValueError, TypeError):
                    continue
        return max(values) if values else 0
    else:
        # Leads: лид-формы FB. Берём 'lead' либо 'onsite_conversion.lead_grouped' (то что есть).
        target_types = {"lead", "onsite_conversion.lead_grouped"}
        values = []
        for action in actions:
            if action.get("action_type") in target_types:
                try:
                    values.append(int(float(action.get("value", 0))))
                except (ValueError, TypeError):
                    continue
        return max(values) if values else 0


def collect_creatives(account_id: str, currency: str, since: str, until: str):
    """
    Собирает данные по макетам (уровень ad) за указанный период
    и сохраняет в таблицу fb_ads_creatives
    """
    vat_mult = VAT_MAP.get(account_id, 1.0)
    label    = ACCOUNT_LABELS.get(account_id, account_id)
    rub_rate = get_rub_rate(currency)

    print(f"  🖼️  Собираем макеты: {label} ({account_id})")

    rows_to_upsert = []
    url = f"https://graph.facebook.com/v19.0/act_{account_id}/insights"
    params = {
        "fields": "campaign_name,adset_name,ad_name,ad_id,spend,impressions,clicks,inline_link_clicks,reach,actions,date_start",
        "time_range": f"{{'since':'{since}','until':'{until}'}}",
        "level": "ad",
        "time_increment": 1,
        "action_attribution_windows": "['7d_click','1d_view']",
        "limit": 200,
        "access_token": FB_TOKEN
    }

    try:
        while url:
            resp = requests.get(url, params=params, timeout=120).json()
            if "error" in resp:
                print(f"    ⚠️ Ошибка creatives: {resp['error'].get('message')}")
                break

            for row in resp.get("data", []):
                spend = float(row.get("spend", 0))
                impressions = int(row.get("impressions", 0))
                # Если в этот день не было ни расхода, ни показов — это атрибутивный хвост старой кампании, пропускаем
                if spend <= 0 and impressions <= 0:
                    continue
                leads_count = parse_leads(row.get("actions"), row.get("campaign_name", ""))

                rows_to_upsert.append({
                    "date_start":    row["date_start"],
                    "account_id":    account_id,
                    "country_label": label,
                    "campaign_name": row.get("campaign_name", ""),
                    "adset_name":    row.get("adset_name", ""),
                    "ad_name":       row.get("ad_name", ""),
                    "ad_id":         row.get("ad_id", ""),
                    "spend":         spend,
                    "spend_rub":     spend * vat_mult * rub_rate,
                    "impressions":   impressions,
                    "clicks":        int(row.get("inline_link_clicks", 0)),
                    "reach":         int(row.get("reach", 0)),
                    "leads":         leads_count,
                })

            url    = resp.get("paging", {}).get("next")
            params = {}

    except Exception as e:
        print(f"    ❌ Ошибка при сборе creatives: {e}")
        return

    # Сохраняем в Supabase
    if rows_to_upsert:
        try:
            batch_size = 500
            for i in range(0, len(rows_to_upsert), batch_size):
                batch = rows_to_upsert[i:i + batch_size]
                supabase.table("fb_ads_creatives").upsert(
                    batch,
                    on_conflict="date_start,account_id,ad_id"
                ).execute()
            print(f"    ✅ Сохранено строк по макетам: {len(rows_to_upsert)}")
        except Exception as e:
            print(f"    ❌ Ошибка сохранения в Supabase: {e}")
    else:
        print(f"    ℹ️ Нет данных по макетам")


# ============================================================
# ГЛАВНАЯ ФУНКЦИЯ
# ============================================================

def main():
    started_at = datetime.now()
    print(f"\n{'='*60}")
    print(f"🚀 Запуск сбора данных: {started_at.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}")

    # Период: последние 35 дней (с запасом чтобы не терять данные)
    until = datetime.now().strftime("%Y-%m-%d")
    since = (datetime.now() - timedelta(days=35)).strftime("%Y-%m-%d")
    print(f"📅 Период: {since} → {until}\n")

    # Получаем все аккаунты
    accounts = get_all_account_ids()

    if not accounts:
        msg = "Не удалось получить список аккаунтов"
        print(f"❌ {msg}")
        log_sync(started_at, "error", msg)
        return

    # Обрабатываем каждый аккаунт
    errors = []
    for acc in accounts:
        acc_id   = acc["id"]
        currency = acc["currency"]

        # Пропускаем аккаунты не из нашего списка
        if acc_id not in VAT_MAP:
            continue

        print(f"\n🔄 Аккаунт: {acc_id} ({ACCOUNT_LABELS.get(acc_id, '?')})")

        try:
            collect_insights(acc_id, currency, since, until)
        except Exception as e:
            errors.append(f"insights {acc_id}: {e}")
            print(f"  ❌ Ошибка insights: {e}")

        try:
            collect_creatives(acc_id, currency, since, until)
        except Exception as e:
            errors.append(f"creatives {acc_id}: {e}")
            print(f"  ❌ Ошибка creatives: {e}")

    # Итог
    print(f"\n{'='*60}")
    if errors:
        msg = f"Завершено с ошибками: {'; '.join(errors)}"
        print(f"⚠️ {msg}")
        log_sync(started_at, "partial", msg)
    else:
        print(f"✅ Сбор данных завершён успешно!")
        log_sync(started_at, "ok", f"Обработано аккаунтов: {len([a for a in accounts if a['id'] in VAT_MAP])}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
