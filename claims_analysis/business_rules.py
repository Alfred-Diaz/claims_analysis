from __future__ import annotations

import re
from datetime import datetime
from typing import Any

import pandas as pd


SUPPLIER_CATEGORY_VALUES = [
    "HOSPITAL",
    "CLINICS",
    "PROFESSIONAL FEES",
    "DENTIST",
    "DENTAL CLINIC",
    "REIMBURSEMENT",
]


CREDIT_TERMS = {
    "ACE MED": "100K",
    "ALABANG MEDICAL CLINIC": "7 DAYS CREDIT TERM",
    "ASIAN HOSPITAL AND MEDICAL CENTER": "15 DAYS",
    "AUFMC MEDICAL CENTER": "15 DAYS",
    "BOROUGH MEDICAL CARE INTITUTE": "15 DAYS",
    "BOROUGH MEDICAL CLINIC": "15 DAYS",
    "CALAMBA MEDICAL CENTER": "500K",
    "CAPITOL MEDICAL CENTER": "15 DAYS",
    "CARDINAL MRI": "7 DAYS",
    "CHINESE GENERAL HOSPITAL": "200K REVOLVING",
    "CLINICA ANTIPOLO": "15 DAYS",
    "COLINAS VERDES HOSPITAL AND MANAGERS CORPORATION/CARDINAL SANTOS": "300K",
    "DANIEL MERCADO": "200K",
    "DELA SALLE MEDICAL CENTER": "15 DAYS",
    "EAST MANILA MANAGERS CORP": "100K",
    "OUR LADY OF LOURDES HOSPITAL": "100K",
    "FRIENDLYCARE MEDICAL CLINICS": "15 DAYS",
    "GLOBAL MEDICAL CENTER LAGUNA": "500K",
    "HEALTH GLOBAL INTERNATIONAL HOSPITAL INC": "300K",
    "HEALTHVIEW MRI CORPORATION": "15 DAYS",
    "HEALTHWAY": "15 DAYS",
    "HI-PRECISION": "15 DAYS",
    "HOLY ROSARY": "500K",
    "LAS PINAS CITY MED": "100K",
    "LIPA MEDIX": "500K",
    "MAKATI MEDICAL CENTER": "TOP 5",
    "MANILA EAST": "15 DAYS",
    "MARY MEDIATRIX": "100K",
    "MCU-HOSPITAL": "15 DAYS",
    "MANILA CENTRAL UNIVERSITY HOSPITAL": "15 DAYS",
    "MEDICAL CENTER MANILA": "15 DAYS",
    "MEDICAL CENTER MUNTINLUPA": "15 DAYS",
    "METRO CAVITE": "500K",
    "METROLIPA MEDICAL CENTER": "15 DAYS",
    "NL VILLA": "250K",
    "PATIENTS FIRST MEDICAL CENTER": "15 DAYS",
    "PHILIPPINE HEART CENTER": "15 DAYS",
    "PROSER": "15 DAYS",
    "PROSER HEALTH SERVICES": "15 DAYS",
    "ST. FRANCES CABRINI": "15 DAYS",
    "ST. JAMES HOSPITAL": "1M",
    "ST. LUKES GLOBAL": "TOP 5",
    "ST. LUKES MEDICAL CENTER": "TOP 5",
    "ST. RAPHAEL FOUNDATION AND MEDICAL CENTER": "15 DAYS",
    "TAGAYTAY MEDICAL CENTER": "15 DAYS",
    "THE MEDICAL CITY SOUTH LUZON": "200K",
    "THE MEDICAL CITY": "TOP 5",
    "UERM": "200K",
    "WORLD CITI MEDICAL CENTER": "100K",
}


TOP_HOSPITALS_CO_MPSU = {
    "MAKATI MEDICAL CENTER",
    "ST. LUKES GLOBAL",
    "ST. LUKES MEDICAL CENTER",
    "THE MEDICAL CITY",
}


def normalize_text(value: Any) -> str:
    return "" if pd.isna(value) else str(value).upper().strip()


def normalize_provider(value: Any) -> str:
    text = normalize_text(value)
    text = re.sub(r"\([^)]*\)", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def normalize_supplier_category(value: Any, documentation_type: Any = "") -> str:
    doc_type = normalize_text(documentation_type)
    raw = normalize_text(value)
    if doc_type == "REIMBURSEMENT" or "REIMBURSE" in raw:
        return "REIMBURSEMENT"
    if "DENTAL CLINIC" in raw:
        return "DENTAL CLINIC"
    if "DENTIST" in raw:
        return "DENTIST"
    if "PROF" in raw:
        return "PROFESSIONAL FEES"
    if "CLINIC" in raw:
        return "CLINICS"
    if "HOSP" in raw or raw == "":
        return "HOSPITAL"
    return raw if raw in SUPPLIER_CATEGORY_VALUES else raw


def credit_term_for_provider(provider: Any) -> str:
    provider_text = normalize_provider(provider)
    if not provider_text:
        return ""
    for key, term in CREDIT_TERMS.items():
        if key in provider_text or provider_text in key:
            return term
    return ""


def mpsu_tag_for_provider(provider: Any) -> str:
    provider_text = normalize_provider(provider)
    for key in TOP_HOSPITALS_CO_MPSU:
        if key in provider_text or provider_text in key:
            return "TOP HOSPITAL - C/O MPSU"
    return ""


def parse_any_date(value: Any):
    if pd.isna(value):
        return pd.NaT
    text = str(value).strip()
    if not text:
        return pd.NaT
    return pd.to_datetime(text, errors="coerce")


def aging_bucket(received_date: Any, as_of: datetime | None = None) -> str:
    date_value = parse_any_date(received_date)
    if pd.isna(date_value):
        return "NO RECEIVED DATE"
    as_of = as_of or datetime.today()
    age_days = max((as_of.date() - date_value.date()).days, 0)
    if age_days <= 30:
        return "0-30 DAYS"
    if age_days <= 60:
        return "31-60 DAYS"
    if age_days <= 90:
        return "61-90 DAYS"
    if age_days <= 120:
        return "91-120 DAYS"
    return "ABOVE 120 DAYS"


def aging_days(received_date: Any, as_of: datetime | None = None) -> int | None:
    date_value = parse_any_date(received_date)
    if pd.isna(date_value):
        return None
    as_of = as_of or datetime.today()
    return max((as_of.date() - date_value.date()).days, 0)
