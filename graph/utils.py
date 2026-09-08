import ast
from datetime import datetime, timezone
import io
import json
import os
import re
from typing import Optional
import unicodedata

import arabic_reshaper
from bidi.algorithm import get_display
import pymupdf  # 👈 استخدام pymupdf الحديث بدلاً من fitz لتجنب الـ Warnings
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    HRFlowable,
    Image,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from models.models import RequestCounter, db


# ── Text & Platform Helpers ───────────────────────────────────────────────────

def strip_tags(text: str) -> str:
    """Remove all XML-style tags injected by LLM prompts from a reply string."""
    text = re.sub(r"<SUMMARY>.*?</SUMMARY>", "", text, flags=re.DOTALL)
    text = re.sub(r"<INTENT>.*?</INTENT>", "", text, flags=re.DOTALL)
    text = re.sub(r"<LAST_BOT_MESSAGE>.*?</LAST_BOT_MESSAGE>", "", text, flags=re.DOTALL)
    text = re.sub(r"<[^>]+>", "", text)
    return text.strip()


def detect_language_fallback(user_message: str, arabic: str, default: str) -> str:
    """Return `arabic` if the user message contains Arabic characters, otherwise return `default`."""
    if any("\u0600" <= c <= "\u06ff" for c in user_message):
        return arabic
    return default


PLATFORM_MAP = {
    1: "Facebook",
    2: "WhatsApp",
}


def get_platform_name(platform_id) -> str:
    """Convert platform_id to platform name string."""
    if not platform_id:
        return "unknown"
    try:
        key = int(platform_id)
        return PLATFORM_MAP.get(key, str(platform_id))
    except ValueError:
        return str(platform_id)


def count_request():
    """Decrement the global request counter."""
    try:
        counter = RequestCounter.query.first()
        if counter:
            counter.decrement()
    except Exception as e:
        print(f"[count_request] Error decrementing counter: {e}")


# ── Colours & Fonts ───────────────────────────────────────────────────────────
NAVY = colors.HexColor("#1B4B8A")
CREAM = colors.HexColor("#F5F0E8")
LIGHT_ROW = colors.HexColor("#EAF0FA")
WHITE = colors.white
MUTED = colors.HexColor("#6B7280")
DARK = colors.HexColor("#1F2937")

_FONT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Cairo.ttf")
_FONT_GLYPHS = set()


def _register_font() -> str:
    global _FONT_GLYPHS
    if os.path.exists(_FONT_PATH):
        try:
            font = TTFont("Cairo", _FONT_PATH)
            pdfmetrics.registerFont(font)
            try:
                _FONT_GLYPHS = set(font.face.charToGlyph.keys())
            except Exception as e:
                print(f"[Font Warning] Could not read glyph map: {e}")
                _FONT_GLYPHS = set()
            return "Cairo"
        except Exception as e:
            print(f"[Font Error] Failed to register Cairo: {e}")
    else:
        print(f"[Font Warning] {_FONT_PATH} not found! Falling back.")
    return "Helvetica"


def _fix_missing_glyphs(text: str) -> str:
    """يستبدل الحروف المنعزلة التي ليس لها رسمة ببديلها الأصلي لتفادي اختفاء الحروف."""
    if not _FONT_GLYPHS:
        return text
    result = []
    for ch in text:
        if ord(ch) in _FONT_GLYPHS or ch in (" ", "\u00A0"):
            result.append(ch)
            continue
        fallback = unicodedata.normalize("NFKC", ch)
        if fallback and all(ord(c) in _FONT_GLYPHS for c in fallback):
            result.append(fallback)
        else:
            result.append(ch)
    return "".join(result)


def _is_arabic(text: str) -> bool:
    return any("\u0600" <= c <= "\u06FF" for c in (text or ""))


def _ps(name_: str, font: str, size: int, color=DARK, align: int = 0) -> ParagraphStyle:
    return ParagraphStyle(
        name_,
        fontName=font,
        fontSize=size,
        textColor=color,
        alignment=align,
        leading=size * 1.45,
    )


def _ar(text) -> str:
    if not text:
        return ""
    try:
        str_text = str(text).strip()
        if not str_text:
            return ""
        reshaped = arabic_reshaper.reshape(str_text)
        displayed = get_display(reshaped)
        displayed = _fix_missing_glyphs(displayed)
        return "\u00A0" + displayed + "\u00A0"
    except Exception:
        return str(text)


# ── Booking PDF & Image Generation ────────────────────────────────────────────

def generate_booking_pdf(
    name: str,
    phone: str,
    date: str,
    details: str,
    reference_id: str,
    address: str,
) -> bytes:
    font = _register_font()
    buffer = io.BytesIO()

    margin = 15 * mm
    usable_w = A4[0] - (margin * 2)

    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=margin,
        rightMargin=margin,
        topMargin=10 * mm,
        bottomMargin=10 * mm,
    )

    story = []

    # Header / Logo
    logo_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logo.png")
    if os.path.exists(logo_path):
        logo = Image(logo_path, width=42 * mm, height=26 * mm)
    else:
        print(f"[generate_booking_pdf] WARNING: logo missing at {logo_path} — ticket generated without it (reference_id={reference_id})")
        logo = Paragraph("", _ps("empty", font, 1))

    title_table = Table(
        [
            [Paragraph(_ar("مجموعة معامل"), _ps("clinic1", font, 13, colors.HexColor("#D79A29"), align=2))],
            [Paragraph(_ar("الدكتور ماجد صفوت شاكر"), _ps("clinic2", font, 22, colors.HexColor("#D79A29"), align=2))],
        ],
        colWidths=[usable_w - 50 * mm],
    )

    header = Table([[logo, title_table]], colWidths=[45 * mm, usable_w - 45 * mm])
    header.setStyle(
        TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ])
    )
    story.append(header)
    story.append(Spacer(1, 6 * mm))

    # Title Bar
    ttl = Table(
        [[
            Paragraph("Home Visit Confirmation", _ps("en", font, 11, WHITE, align=0)),
            Paragraph(_ar("تأكيد حجز زيارة منزلية"), _ps("ar", font, 12, WHITE, align=2)),
        ]],
        colWidths=[usable_w / 2, usable_w / 2],
    )
    ttl.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), NAVY),
            ("TOPPADDING", (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ("LEFTPADDING", (0, 0), (-1, -1), 10),
            ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ])
    )
    story.append(ttl)

    # Reference Code
    ref = Table(
        [[Paragraph(f"Reference ID: {reference_id}", _ps("ref", font, 10, NAVY, align=1))]],
        colWidths=[usable_w],
    )
    ref.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), CREAM),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ])
    )
    story.append(ref)
    story.append(Spacer(1, 6 * mm))

    # ── Info Table (5 Fields) ─────────────────────────────────────────────────
    fields = [
        ("Patient Name", "اسم المريض", name),
        ("Phone", "رقم الهاتف", phone),
        ("Visit Date", "تاريخ الزيارة", date),
        ("Required Analysis", "التحاليل المطلوبة", details),
        ("Address", "العنوان التفصيلي", address),
    ]
    missing_fields = [en_lbl for en_lbl, _, val in fields if not val]
    if missing_fields:
        print(f"[generate_booking_pdf] WARNING: empty field(s) {missing_fields} for reference_id={reference_id} — will render as '—'")

    label_col_w = 78 * mm
    val_col_w = usable_w - label_col_w

    rows = []
    for i, (en_lbl, ar_lbl, val) in enumerate(fields):
        lbl_text = f"{en_lbl} / {_ar(ar_lbl)}"
        lbl_cell = Paragraph(lbl_text, _ps(f"l_{i}", font, 9, MUTED, align=0))

        val_str = str(val or "—")
        val_is_ar = _is_arabic(val_str)
        val_text = _ar(val_str) if val_is_ar else val_str
        val_align = 2 if val_is_ar else 0

        val_cell = Paragraph(val_text, _ps(f"v_{i}", font, 10, DARK, align=val_align))
        rows.append([lbl_cell, val_cell])

    info = Table(rows, colWidths=[label_col_w, val_col_w])
    info.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), WHITE),
            ("BACKGROUND", (0, 0), (-1, 0), LIGHT_ROW),
            ("BACKGROUND", (0, 2), (-1, 2), LIGHT_ROW),
            ("BACKGROUND", (0, 4), (-1, 4), LIGHT_ROW),
            ("LINEBELOW", (0, 0), (-1, -2), 0.5, colors.HexColor("#DDE3EE")),
            ("TOPPADDING", (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ])
    )
    story.append(info)
    story.append(Spacer(1, 8 * mm))

    # Footer
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#C5D0E0")))
    story.append(Spacer(1, 3 * mm))

    issued = datetime.now(timezone.utc).strftime("%B %d, %Y %H:%M UTC")
    footer_table = Table(
        [[
            Paragraph(f"Issued: {issued}", _ps("fl", font, 8, MUTED, align=0)),
            Paragraph(_ar("سيتم التواصل معكم لتأكيد الموعد النهائي"), _ps("fr", font, 8, MUTED, align=2)),
        ]],
        colWidths=[usable_w / 2, usable_w / 2],
    )
    footer_table.setStyle(
        TableStyle([
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ])
    )
    story.append(footer_table)

    doc.build(story)
    return buffer.getvalue()


def generate_booking_image(
    name: str,
    phone: str,
    date: str,
    details: str,
    reference_id: str,
    address: str,
    dpi: int = 200,
) -> bytes:
    """يولد بطاقة الحجز كصورة PNG عالية الجودة باستخدام pymupdf."""
    pdf_bytes = generate_booking_pdf(
        name=name,
        phone=phone,
        date=date,
        details=details,
        reference_id=reference_id,
        address=address,
    )

    # تحويل الـ PDF لـ PNG بـ pymupdf
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    page = doc[0]
    zoom = dpi / 72
    pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom))
    png_bytes = pix.tobytes("png")
    doc.close()

    return png_bytes


# ── Parsing Helpers ───────────────────────────────────────────────────────────
#
# alias_names و keywords بقوا متخزنين كـ JSON list في MySQL (db.JSON)، يعني
# SQLAlchemy بيرجعهم كـ list بايثون جاهز من غير أي حاجة تتعمل. الدوال دي
# لسه موجودة كطبقة أمان بسيطة فقط (لو القيمة جت None أو بشكل غير متوقع)،
# مش عشان تفك تنسيق نصي معقد زي الأول.
#
# ملحوظة: AliasNames اتشالت من knowledge.schemas — alias_names بقى flat
# list بسيط، فمفيش تمييز بين "alias" أساسي و"aliases" فرعية بعد كده.
# أي كود تاني كان بيقرأ .alias أو .aliases من الناتج، لازم يتعدّل يتعامل
# مع list عادي بدل كده.

def parse_alias_names(value) -> list[str]:
    """يتأكد إن القيمة list[str] صالحة، مهما كان شكلها الخام."""
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]

    if isinstance(value, dict):
        # توافقية مع أي صف قديم لسه متخزن بالشكل القديم {alias, aliases}
        merged = []
        if value.get("alias"):
            merged.append(str(value["alias"]).strip())
        for v in value.get("aliases", []) or []:
            v = str(v).strip()
            if v and v not in merged:
                merged.append(v)
        return merged

    if not isinstance(value, str) or not value.strip():
        return []

    value = value.strip()

    # توافقية مع نص JSON قديم
    if value.startswith("[") or value.startswith("{"):
        try:
            parsed = json.loads(value)
            return parse_alias_names(parsed)
        except json.JSONDecodeError:
            try:
                parsed = ast.literal_eval(value)
                return parse_alias_names(parsed)
            except Exception:
                pass

    # توافقية مع نص CSV قديم
    return [v.strip() for v in value.split(",") if v.strip()]


def parse_keywords(value) -> list[str]:
    """يحول القيمة المخزنة لـ list[str]"""
    if isinstance(value, list):
        return [str(k).strip() for k in value if str(k).strip()]
    if not isinstance(value, str) or not value.strip():
        return []

    value = value.strip()

    if value.startswith("["):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return [str(k).strip() for k in parsed if str(k).strip()]
        except json.JSONDecodeError:
            try:
                parsed = ast.literal_eval(value)
                if isinstance(parsed, list):
                    return [str(k).strip() for k in parsed if str(k).strip()]
            except Exception:
                pass

    return [k.strip() for k in value.split(",") if k.strip()]