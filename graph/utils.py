import ast
from datetime import datetime, timezone
import io
import json
import os
import re
from typing import Optional , Union
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

from models.models import Branch, RequestCounter, db

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



# ── خريطة ربط الـ (page_id) بـ ID الفرع في جدول branches ──────────────────────
PAGE_TO_BRANCH_ID = {
    # 🏢 الفرع الأول (فيكتوريا) -> branch_id = 1
    "222497324699829": 1,
    "222497324699829@lid": 1,
    os.environ.get("WAHA1_PAGE_ID", ""): 1,

    # 🏢 الفرع الثاني (باكوس) -> branch_id = 2
    os.environ.get("WAHA2_PAGE_ID", "session_number2"): 2,
}

def get_source_label(platform_name=None, platform_id=None, page_id=None) -> str:
    """إرجاع اسم وعنوان الفرع ديناميكياً من قاعدة البيانات."""
    p_name = str(platform_name or "").lower()
    pid_str = str(page_id or "").strip()

    if p_name == "whatsapp" or platform_id == 2 or str(platform_id) == "2":
        try:
            # جلب كل الفروع المسجلة في الداشبورد بالترتيب
            branches = Branch.query.order_by(Branch.id.asc()).all()
            
            # 🏢 تحديد هل هو الفرع الأول أم الثاني:
            is_branch_1 = "222497324699829" in pid_str or pid_str == os.environ.get("WAHA1_PAGE_ID", "")

            if is_branch_1 and len(branches) >= 1:
                return f"واتساب ({branches[0].address})"
            elif not is_branch_1 and len(branches) >= 2:
                return f"واتساب ({branches[1].address})"
            elif branches:
                return f"واتساب ({branches[0].address})"
        except Exception as e:
            print(f"[get_source_label] Error fetching branch: {e}")

        # احتياطي إذا تعذر جلب الفروع من الداتابيز
        if "222497324699829" in pid_str:
            return "واتساب - فرع فيكتوريا (30 شارع الجلاء)"
        return "واتساب - فرع باكوس (86 شارع الفتح - ترام باكوس)"

    if p_name == "facebook" or platform_id == 1 or str(platform_id) == "1":
        return "فيسبوك"

    return str(platform_name or "أخرى")

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
    date: str,
    details: str,
    reference_id: str,
    address: str,
    phone_number1: str = "",
    phone_number2: str = "",
    age: Optional[int | str] = None,
    total_price: Optional[float | int | str] = None,
    phone: str = "",  # Backward compatibility
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
    logo_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logo.jpg")
    if os.path.exists(logo_path):
        logo = Image(logo_path, width=42 * mm, height=26 * mm)
    else:
        logo = Paragraph("", _ps("empty", font, 1))

    title_table = Table(
        [
            [Paragraph(_ar("مجموعة معامل"), _ps("clinic1", font, 13, colors.HexColor("#D79A29"), align=2))],
            [Paragraph(_ar("الدكتور صفوت شاكر"), _ps("clinic2", font, 22, colors.HexColor("#D79A29"), align=2))],
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

    # 💰 حساب الإجمالي تلقائياً إذا لم يتم تمريره
    if total_price is None and details:
        try:
            from models.models import LabService
            
            # 1. تقسيم أسماء التحاليل بفواصل الأسطر، والنقاط، والـ Bullet Points، والفواصل
            raw_parts = re.split(r'[\n\r•]+', str(details))
            test_queries = []
            for part in raw_parts:
                part = part.strip()
                if not part:
                    continue
                sub_parts = re.split(r'[,،]+', part)
                for sp in sub_parts:
                    clean_q = re.sub(r'^\d+[\.\-\)]\s*', '', sp).strip()
                    clean_q = re.sub(r'^(تحليل|فحص|اختبار|test|analysis)\s+', '', clean_q, flags=re.IGNORECASE).strip()
                    if clean_q:
                        test_queries.append(clean_q)

            # 2. جلب جميع خدمات المعمل المتاحة
            all_services = LabService.query.all()
            matched_service_ids = set()
            calc_total = 0.0

            for q in test_queries:
                q_lower = q.lower()
                q_nodots = re.sub(r'\.', '', q_lower).strip()
                matched_svc = None

                # أ) البحث بالتطابق التام بالاسم
                for svc in all_services:
                    if svc.id in matched_service_ids or not svc.price:
                        continue
                    s_name = (svc.name or '').strip().lower()
                    s_nodots = re.sub(r'\.', '', s_name).strip()
                    if s_name == q_lower or s_nodots == q_nodots:
                        matched_svc = svc
                        break

                # ب) البحث في الأسماء البديلة (alias_names)
                if not matched_svc:
                    for svc in all_services:
                        if svc.id in matched_service_ids or not svc.price:
                            continue
                        aliases = parse_alias_names(svc.alias_names) if hasattr(svc, 'alias_names') else []
                        for alias in aliases:
                            a_lower = alias.strip().lower()
                            a_nodots = re.sub(r'\.', '', a_lower).strip()
                            if a_lower == q_lower or a_nodots == q_nodots:
                                matched_svc = svc
                                break
                        if matched_svc:
                            break

                # ج) البحث الجزئي المتبادل
                if not matched_svc:
                    for svc in all_services:
                        if svc.id in matched_service_ids or not svc.price:
                            continue
                        s_name = (svc.name or '').strip().lower()
                        s_nodots = re.sub(r'\.', '', s_name).strip()
                        if len(s_nodots) >= 3:
                            pat = r'\b' + re.escape(s_nodots) + r'\b'
                            if re.search(pat, q_nodots) or (s_nodots in q_nodots):
                                matched_svc = svc
                                break

                # د) البحث الجزئي داخل الـ aliases المتبادلة
                if not matched_svc:
                    for svc in all_services:
                        if svc.id in matched_service_ids or not svc.price:
                            continue
                        aliases = parse_alias_names(svc.alias_names) if hasattr(svc, 'alias_names') else []
                        for alias in aliases:
                            a_nodots = re.sub(r'\.', '', alias.strip().lower()).strip()
                            if len(a_nodots) >= 3 and (a_nodots in q_nodots or q_nodots in a_nodots):
                                matched_svc = svc
                                break
                        if matched_svc:
                            break

                # هـ) مطابقة الكلمات المفتاحية أو search_text
                if not matched_svc and len(q_nodots) >= 3:
                    for svc in all_services:
                        if svc.id in matched_service_ids or not svc.price:
                            continue
                        search_txt = (svc.search_text or '').lower()
                        if q_nodots in search_txt:
                            matched_svc = svc
                            break

                if matched_svc and matched_svc.price:
                    calc_total += matched_svc.price
                    matched_service_ids.add(matched_svc.id)

            if calc_total > 0:
                total_price = int(calc_total) if calc_total.is_integer() else calc_total

        except Exception as e:
            print(f"[generate_booking_pdf] Error calculating total: {e}")

    price_display = f"{total_price} ج.م (بدون رسوم الزيارة)" if total_price is not None else "يتم تأكيده مع خدمة العملاء"

    # ── حساب سنة الميلاد والسن ────────────────────────────────────────────────
    main_phone = phone_number1 or phone or "—"
    second_phone = phone_number2 or "—"

    current_year = datetime.now().year
    birth_year = None
    age_clean = None

    if age is not None and str(age).strip():
        m_age = re.search(r'\d+', str(age))
        if m_age:
            val = int(m_age.group())
            # إذا كتب المريض سنة ميلاده خطأ مكان السن (مثل 1995)
            if val >= 1900 and val <= current_year:
                birth_year = val
                age_clean = current_year - birth_year
            # إذا كتب السن الطبيعي (مثل 25)
            elif 0 <= val < 130:
                age_clean = val
                birth_year = current_year - age_clean

    if age_clean is not None and birth_year is not None:
        age_display = f"{age_clean} سنة (مواليد {birth_year})"
    elif age:
        age_display = f"{age} سنة" if str(age).isdigit() else str(age)
    else:
        age_display = "—"

    # ── Info Table (الحقول كاملة مع السن وسنة الميلاد) ─────────────────────────
    fields = [
        ("Patient Name", "اسم المريض", name),
        ("Age / Birth Year", "السن / سنة الميلاد", age_display),
        ("Primary Phone", "رقم الهاتف الأساسي", main_phone),
        ("Secondary Phone", "رقم هاتف إضافي", second_phone),
        ("Estimated Total", "الإجمالي التقديري", price_display),
        ("Visit Date", "تاريخ الزيارة", date),
        ("Required Analysis", "التحاليل المطلوبة", details),
        ("Address", "العنوان التفصيلي", address),
    ]

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
    
    table_styles = [
        ("BACKGROUND", (0, 0), (-1, -1), WHITE),
        ("LINEBELOW", (0, 0), (-1, -2), 0.5, colors.HexColor("#DDE3EE")),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]
    for r_idx in range(len(rows)):
        if r_idx % 2 == 0:
            table_styles.append(("BACKGROUND", (0, r_idx), (-1, r_idx), LIGHT_ROW))
    info.setStyle(TableStyle(table_styles))
    story.append(info)
    story.append(Spacer(1, 6 * mm))

    # Footer
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#C5D0E0")))
    story.append(Spacer(1, 3 * mm))
    issued = datetime.now(timezone.utc).strftime("%B %d, %Y %H:%M UTC")
    footer_table = Table(
        [[
            Paragraph(f"Issued: {issued}", _ps("fl", font, 8, MUTED, align=0)),
            Paragraph(_ar("سيتم التواصل معكم لتأكيد الموعد النهائي ورسوم الزيارة"), _ps("fr", font, 8, MUTED, align=2)),
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
    date: str,
    details: str,
    reference_id: str,
    address: str,
    phone_number1: str = "",
    phone_number2: str = "",
    age: Optional[int | str] = None,
    total_price: Optional[float | int | str] = None,
    phone: str = "",
    dpi: int = 200,
) -> bytes:
    """يولد بطاقة الحجز كصورة PNG ويحفظ نفس نسخة الـ PDF للطباعة لاحقاً."""
    
    # 1. توليد الـ PDF بالسعر المظبوط (200 ج.م مثلاً)
    pdf_bytes = generate_booking_pdf(
        name=name,
        date=date,
        details=details,
        reference_id=reference_id,
        address=address,
        phone_number1=phone_number1,
        phone_number2=phone_number2,
        age=age,
        total_price=total_price,
        phone=phone,
    )

    # 💾 2. حفظ نفس ملف الـ PDF على السيرفر حتى يكون هو نفسه تماماً عند الطباعة
    try:
        base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        tickets_dir = os.path.join(base_dir, "static", "tickets")
        os.makedirs(tickets_dir, exist_ok=True)
        pdf_path = os.path.join(tickets_dir, f"{reference_id}.pdf")
        with open(pdf_path, "wb") as f:
            f.write(pdf_bytes)
        print(f"[generate_booking_image] ✅ Ticket PDF saved: {pdf_path}")
    except Exception as e:
        print(f"[generate_booking_image] ⚠️ Could not save PDF ticket: {e}")

    # 3. تحويل نفس الـ PDF لصورة PNG لإرسالها في الشات
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