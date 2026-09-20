# -*- coding: utf-8 -*-
"""Normalización del extractor contrastado, sin importar el ERP ni sus secretos."""
import datetime as dt
import math
import re

def txt(value):
    return '' if value is None else str(value).replace('\x00',' ').strip()

def num(value):
    try:
        value=float(value or 0)
        return value if math.isfinite(value) else 0.0
    except (TypeError,ValueError):
        return 0.0

def iso(value):
    return value.isoformat() if isinstance(value,(dt.date,dt.datetime)) else ''

def clean_plate(value):
    key=re.sub(r'[^0-9A-Z]','',txt(value).upper())
    return '' if key in {'','0','000000','SINVEHICULO','SINASIGNAR'} else key

def display_plate(value):
    raw=txt(value).upper()
    key=clean_plate(raw)
    if not key: return 'SIN VEHÍCULO'
    if re.fullmatch(r'\d{4}[A-Z]{3}',key): return key[:4]+'-'+key[4:]
    if re.fullmatch(r'[A-Z]\d{4}[A-Z]{3}',key): return key[:1]+'-'+key[1:5]+'-'+key[5:]
    return raw or key

def invoice_plate(line):
    direct=txt(line.get('MATRICULA'))
    if clean_plate(direct): return clean_plate(direct),display_plate(direct)
    for pattern in (r'(?<![0-9A-Z])([0-9]{4}[- ]?[A-Z]{3})(?![0-9A-Z])',r'(?<![0-9A-Z])([A-Z][- ]?[0-9]{4}[- ]?[A-Z]{3})(?![0-9A-Z])',r'(?<![0-9A-Z])(R[- ]?[0-9]{4}[- ]?[A-Z]{3})(?![0-9A-Z])'):
        match=re.search(pattern,txt(line.get('CONCEPTO')),re.IGNORECASE)
        if match: return clean_plate(match.group(1)),display_plate(match.group(1))
    return '','SIN VEHÍCULO'
