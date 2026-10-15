"""
PDF Report Generator for Production Reports
Generates PDF files matching Flutter App / Web App format.
- generate_pdf(): matches ReportDetailPanel format from Flutter app
- generate_audit_pdf(): matches PO audit format from web OrdersScreen
"""

import os
import io
import json
from datetime import datetime
from pathlib import Path
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch, mm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload


def report_to_dict(report) -> dict:
    """Build the ``report_data`` dict expected by ``generate_pdf`` from a ``ProductionReport``."""
    data = {
        "id": getattr(report, "id", ""),
        "report_date": report.report_date or "",
        "shift_name": report.shift_name or "",
        "machine_name": report.machine_name or "",
        "operator_name": report.operator_name or "",
        "po_number": report.po_number or "",
        "lot_number": report.lot_number or "",
        "shift_time_range": report.shift_time_range or "",
        "box_type": report.box_type or 0,
        "diameter": report.diameter or 0,
        "length": report.length or 0,
        "pd": report.pd or 0,
        "cu": getattr(report, "cu", 0) or 0,
        "weight": report.weight or 0,
        "boxes_produced": report.boxes_produced or 0,
        "produced_rods": report.produced_rods or 0,
        "machine_counter": report.machine_counter or 0,
        "difference": report.difference or 0,
        "diff_percent": report.diff_percent or "0%",
        "waste_kg": report.waste_kg or 0,
        "machine_efficiency": report.machine_efficiency or 0,
        "total_acetate": report.total_acetate or 0,
        "total_paper": report.total_paper or 0,
        "total_pva": report.total_pva or 0,
        "total_hm": report.total_hm or 0,
        "total_triacetin": report.total_triacetin or 0,
        "remarks": report.remarks or "",
        "acetate_list": [],
        "paper_list": [],
        "pva_list": [],
        "hm_list": [],
        "tri_list": [],
    }
    try:
        if report.materials_json:
            parsed = json.loads(report.materials_json)
            for key, field in (("acetate_list", "acetate_list"), ("paper_list", "paper_list"),
                               ("pva_list", "pva_list"), ("hm_list", "hm_list"),
                               ("tri_list", "tri_list")):
                data[field] = parsed.get(key, []) if isinstance(parsed.get(key), list) else []
    except Exception:
        pass
    return data


_FONT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")
_DEJAVU_REGULAR = "DejaVu"
_DEJAVU_BOLD = "DejaVu-Bold"
_FONT_REGISTERED = False

# Official Quality Certificate parameter matrix (fixed order + units).
_PARAM_META = [
    ("length", "Length", "mm"),
    ("diameter", "Diameter", "mm"),
    ("pd", "Pressure drop", "mm WG"),
    ("hardness", "Hardness", "%"),
    ("weight", "Weight", "mg"),
]


def _register_dejavu_fonts() -> None:
    """Register a Unicode TTF (DejaVu Sans) so Ukrainian/Hungarian/Latin render."""
    global _FONT_REGISTERED
    if _FONT_REGISTERED:
        return
    _FONT_REGISTERED = True
    pairs = [
        (os.path.join(_FONT_DIR, "DejaVuSans.ttf"), _DEJAVU_REGULAR),
        (os.path.join(_FONT_DIR, "DejaVuSans-Bold.ttf"), _DEJAVU_BOLD),
    ]
    try:
        if all(os.path.isfile(p) for p, _ in pairs):
            for path, name in pairs:
                pdfmetrics.registerFont(TTFont(name, path))
            pdfmetrics.registerFontFamily(
                "DejaVu", normal=_DEJAVU_REGULAR, bold=_DEJAVU_BOLD,
                italic=_DEJAVU_REGULAR, boldItalic=_DEJAVU_BOLD)
            return
    except Exception:
        pass
    try:  # fall back to matplotlib's bundled copy
        import matplotlib
        ttf = os.path.join(os.path.dirname(matplotlib.__file__), "mpl-data", "fonts", "ttf")
        reg = os.path.join(ttf, "DejaVuSans.ttf")
        bold = os.path.join(ttf, "DejaVuSans-Bold.ttf")
        if os.path.isfile(reg):
            pdfmetrics.registerFont(TTFont(_DEJAVU_REGULAR, reg))
        if os.path.isfile(bold):
            pdfmetrics.registerFont(TTFont(_DEJAVU_BOLD, bold))
        pdfmetrics.registerFontFamily(
            "DejaVu", normal=_DEJAVU_REGULAR, bold=_DEJAVU_BOLD,
            italic=_DEJAVU_REGULAR, boldItalic=_DEJAVU_BOLD)
    except Exception:
        pass


def _fmt_num(value) -> str:
    if value is None or value == "":
        return "-"
    try:
        f = float(value)
    except (TypeError, ValueError):
        return str(value)
    if f != f:  # NaN
        return "-"
    if f == int(f):
        return str(int(f))
    return f"{f:.4f}".rstrip("0").rstrip(".")


def _flag(v) -> str:
    if v is None:
        return "-"
    return "OK" if v else "FAIL"


def _trend_chart(values, lower, upper, nominal, width=500, height=130):
    """Render a rod-index vs value line chart with spec-limit lines (vector).

    Returns a ``reportlab.graphics.shapes.Drawing`` or ``None`` when there is too
    little data (or the chart module is unavailable).
    """
    if not values or len(values) < 2:
        return None
    try:
        from reportlab.graphics.charts.lineplots import LinePlot
        from reportlab.graphics.shapes import Drawing
    except ImportError:  # pragma: no cover
        return None

    n = len(values)
    data = [[(i, v) for i, v in enumerate(values)]]
    for limit in (lower, upper, nominal):
        if limit is not None:
            data.append([(0, limit), (n - 1, limit)])

    try:
        lp = LinePlot()
        lp.x = 46
        lp.y = 24
        lp.width = width - 60
        lp.height = height - 40
        lp.data = data
        lp.xValueAxis.valueMin = 0
        lp.xValueAxis.valueMax = n - 1
        lp.xValueAxis.valueStep = max(1, (n - 1) // 12)
        lp.xValueAxis.labels.fontName = "DejaVu"
        lp.xValueAxis.labels.fontSize = 6
        lp.yValueAxis.labels.fontName = "DejaVu"
        lp.yValueAxis.labels.fontSize = 6
        lp.lines[0].strokeColor = colors.HexColor("#2c3e50")
        lp.lines[0].strokeWidth = 1.2
        for i in range(1, len(data)):
            lp.lines[i].strokeColor = colors.HexColor("#c0392b")
            lp.lines[i].strokeWidth = 0.8
            lp.lines[i].strokeDashArray = [2, 2]

        d = Drawing(width, height)
        d.add(lp)
        return d
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Branded purple theme (shared by Order Summary + audit reports)
# ---------------------------------------------------------------------------
_PURPLE = colors.HexColor('#673AB7')
_PURPLE_TINT = colors.HexColor('#F3EFFF')
_GRID_GREY = colors.HexColor('#E5E7EB')

_STATUS_COLORS = {
    'PASS': colors.HexColor('#16A34A'),
    'WARNING': colors.HexColor('#F59E0B'),
    'FAIL': colors.HexColor('#DC2626'),
    'NO_DATA': colors.HexColor('#9CA3AF'),
}


def _status_badge(status) -> Table:
    """Rounded pill badge for PASS / WARNING / FAIL / NO_DATA."""
    label = (status or '-').replace('_', ' ')
    bg = _STATUS_COLORS.get(str(status or '').upper(), _STATUS_COLORS['NO_DATA'])
    p = Paragraph(
        f'<b>{label}</b>',
        ParagraphStyle('BadgeText', fontName='Helvetica-Bold', fontSize=9,
                       leading=11, textColor=colors.white, alignment=TA_CENTER),
    )
    t = Table([[p]], colWidths=[32 * mm])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), bg),
        ('ROUNDEDCORNERS', [8, 8, 8, 8]),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
    ]))
    return t


def render_order_summary_pdf(po, reports, quality) -> bytes:
    """Render the consolidated Order Summary using the branded audit template.

    Reuses ``PDFReportGenerator.generate_audit_pdf`` (the ``Production System.pdf``
    layout: Report Entries, Production Summary, Materials Consumption) and appends
    the Consolidated Quality section.

    ``po`` / ``reports`` are the PurchaseOrder + ProductionReport model instances;
    ``quality`` is the consolidated order-quality dict ({certificate, rods_total,
    rods_rejected, status}).
    """
    consolidated = {
        "certificate": quality.get("certificate") or [],
        "rods_total": quality.get("rods_total"),
        "rods_rejected": quality.get("rods_rejected"),
        "status": quality.get("status"),
    }
    gen = PDFReportGenerator()
    result = gen.generate_audit_pdf(po, reports, consolidated_quality=consolidated)
    if not result.get("success"):
        return None
    try:
        with open(result["path"], "rb") as fh:
            return fh.read()
    except OSError:
        return None


def render_shift_quality_pdf(data: dict) -> bytes:
    """Render the Shift Quality Report (certificate-style) as PDF bytes.

    ``data`` keys:
        header:         {po_number, spec_string, machine, date, interval, operator}
        certificate:    [{parameter, nominal, lower, upper, mean, sd, ...}]
        manual_checks:  [{time, operator, length_mm, weight_g, glue_seam,
                          cut_quality, visual, notes}]
        remarks:        str
    """
    _register_dejavu_fonts()

    header = data.get("header") or {}
    certificate = data.get("certificate") or []
    manual_checks = data.get("manual_checks") or []
    remarks = (data.get("remarks") or "").strip()
    cert_by_param = {str(r.get("parameter")): r for r in certificate if isinstance(r, dict)}

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4, topMargin=15 * mm, bottomMargin=15 * mm,
        leftMargin=14 * mm, rightMargin=14 * mm)

    title_style = ParagraphStyle("QRTitle", fontSize=15, leading=18,
                                 alignment=TA_CENTER, fontName="DejaVu-Bold", spaceAfter=10)
    section_style = ParagraphStyle("QRSection", fontSize=10, leading=13,
                                   fontName="DejaVu-Bold", spaceBefore=8, spaceAfter=4)
    cell = ParagraphStyle("QRCell", fontSize=8.5, leading=11, fontName="DejaVu")
    cell_bold = ParagraphStyle("QRCellBold", fontSize=8.5, leading=11, fontName="DejaVu-Bold")

    story = [Paragraph("QUALITY REPORT", title_style)]

    # --- Header ---
    story.append(Paragraph("Header", section_style))
    hdr_rows = [
        ("MO Number", str(header.get("po_number") or "-")),
        ("Lot Number", str(header.get("lot_number") or "-")),
        ("Specification", str(header.get("spec_string") or "-")),
        ("Machine", str(header.get("machine") or "-")),
        ("Date", str(header.get("date") or "-")),
        ("Shift Interval", str(header.get("interval") or "-")),
        ("Operator", str(header.get("operator") or "-")),
    ]
    hdr = Table(
        [[Paragraph(k, cell_bold), Paragraph(v, cell)] for k, v in hdr_rows],
        colWidths=[32 * mm, None])
    hdr.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 1),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
    ]))
    story.append(hdr)

    # --- Measurement Results ---
    story.append(Paragraph("Measurement Results", section_style))
    t_header = ["#", "Parameter", "Measure", "Nominal", "Lower SL", "Upper SL", "Mean", "SD"]
    t_rows = [t_header]
    for idx, (key, label, unit) in enumerate(_PARAM_META, start=1):
        row = cert_by_param.get(key) or {}
        t_rows.append([
            str(idx), label, unit,
            _fmt_num(row.get("nominal")), _fmt_num(row.get("lower")), _fmt_num(row.get("upper")),
            _fmt_num(row.get("mean")), _fmt_num(row.get("sd")),
        ])
    tbl = Table(t_rows, repeatRows=1, colWidths=[8 * mm, None, 15 * mm, 14 * mm, 14 * mm, 14 * mm, 14 * mm, 14 * mm])
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#333333")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("FONTNAME", (0, 0), (-1, -1), "DejaVu"),
        ("FONTNAME", (0, 0), (-1, 0), "DejaVu-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("ALIGN", (3, 1), (-1, -1), "RIGHT"),
        ("ALIGN", (0, 0), (0, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(tbl)

    # --- Manual checks log ---
    story.append(Paragraph("In-Process Manual Checks", section_style))
    m_header = ["#", "Time", "Weight (g)", "Length (mm)", "Hardness (%)",
                "Glue Seam", "Cut Quality", "Visual", "Notes"]
    m_rows = [m_header]
    if not manual_checks:
        m_rows.append(["", "No manual checks recorded for this shift", "", "", "", "", "", "", ""])
    else:
        for idx, c in enumerate(manual_checks, start=1):
            m_rows.append([
                str(idx),
                str(c.get("time") or "-"),
                _fmt_num(c.get("weight_g")),
                _fmt_num(c.get("length_mm")),
                _fmt_num(c.get("hardness")),
                _flag(c.get("glue_seam")),
                _flag(c.get("cut_quality")),
                _flag(c.get("visual")),
                str(c.get("notes") or ""),
            ])

    # Summary footer: mean of Weight / Length / Hardness across manual checks.
    if manual_checks:
        def _mean(vals):
            vals = [v for v in vals if isinstance(v, (int, float))]
            return (sum(vals) / len(vals)) if vals else None
        m_rows.append([
            "", "Mean",
            _fmt_num(_mean([c.get("weight_g") for c in manual_checks])),
            _fmt_num(_mean([c.get("length_mm") for c in manual_checks])),
            _fmt_num(_mean([c.get("hardness") for c in manual_checks])),
            "", "", "", "",
        ])

    mtbl = Table(m_rows, repeatRows=1, colWidths=[8 * mm, 14 * mm, 15 * mm, 15 * mm, 15 * mm, 17 * mm, 17 * mm, 16 * mm, None])
    mtbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#333333")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("FONTNAME", (0, 0), (-1, -1), "DejaVu"),
        ("FONTNAME", (0, 0), (-1, 0), "DejaVu-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("ALIGN", (0, 0), (0, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    story.append(mtbl)

    # --- Trend charts (diameter + pressure drop, spec limits) ---
    series = data.get("series") or {}
    charts = []
    for key, label in (("diameter", "Diameter"), ("pd", "Pressure Drop")):
        values = series.get(key) or []
        if len(values) < 2:
            continue
        spec = cert_by_param.get(key) or {}
        chart = _trend_chart(
            values, spec.get("lower"), spec.get("upper"), spec.get("nominal"))
        if chart is not None:
            charts.append((f"{label} trend", chart))
    if charts:
        story.append(Paragraph("Trend Charts", section_style))
        for label, chart in charts:
            story.append(Paragraph(label, cell_bold))
            story.append(chart)
            story.append(Spacer(1, 4))

    if remarks:
        story.append(Paragraph("Remarks", section_style))
        story.append(Paragraph(remarks, cell))

    doc.build(story)
    return buf.getvalue()


class PDFReportGenerator:
    """Generate PDF reports from production data"""

    # Class variable to track Google Drive availability
    google_drive_available = False
    google_drive_error_message = None

    def __init__(self, archive_path: str = None):
        if archive_path is None:
            archive_path = os.getenv('LOCAL_PDF_ARCHIVE_PATH', r"C:\src\production_log\pdf_archive")
        self.archive_path = archive_path
        self.styles = getSampleStyleSheet()
        self._setup_custom_styles()

    def _setup_custom_styles(self):
        """Setup custom paragraph styles"""
        self.styles.add(ParagraphStyle(
            name='CustomTitle',
            parent=self.styles['Heading1'],
            fontSize=16,
            textColor=colors.HexColor('#1a1a1a'),
            spaceAfter=12,
            alignment=TA_CENTER,
            fontName='Helvetica-Bold'
        ))

        self.styles.add(ParagraphStyle(
            name='CustomHeading',
            parent=self.styles['Heading2'],
            fontSize=12,
            textColor=colors.HexColor('#333333'),
            spaceAfter=8,
            fontName='Helvetica-Bold'
        ))

        self.styles.add(ParagraphStyle(
            name='SectionTitle',
            parent=self.styles['Heading2'],
            fontSize=11,
            textColor=colors.HexColor('#673AB7'),  # deepPurple
            spaceAfter=6,
            fontName='Helvetica-Bold',
            borderPadding=4,
        ))

        self.styles.add(ParagraphStyle(
            name='CellNormal',
            parent=self.styles['Normal'],
            fontSize=9,
            leading=12,
        ))

        self.styles.add(ParagraphStyle(
            name='CellBold',
            parent=self.styles['Normal'],
            fontSize=9,
            leading=12,
            fontName='Helvetica-Bold',
        ))

        self.styles.add(ParagraphStyle(
            name='TableHeader',
            parent=self.styles['Normal'],
            fontSize=8,
            leading=10,
            fontName='Helvetica-Bold',
            textColor=colors.black,
        ))

    def _get_pdf_path(self, report_data: dict) -> tuple:
        """
        Generate PDF file path and name
        Returns: (full_path, filename)
        """
        report_date = report_data.get('report_date', datetime.now().strftime('%Y-%m-%d'))
        machine_name = report_data.get('machine_name', 'Unknown')
        shift_name = report_data.get('shift_name', 'Unknown')

        # Parse date
        try:
            date_obj = datetime.strptime(report_date.split('T')[0], '%Y-%m-%d')
        except:
            date_obj = datetime.now()

        year = date_obj.strftime('%Y')
        month = date_obj.strftime('%m')
        date_str = date_obj.strftime('%Y.%m.%d')

        # Create folder structure
        folder_path = Path(self.archive_path) / year / month
        folder_path.mkdir(parents=True, exist_ok=True)

        # Generate filename with shift number
        base_filename = f"{date_str} Production reports {machine_name} {shift_name}"
        filename = f"{base_filename}.pdf"
        full_path = folder_path / filename

        # Handle duplicates (add #2, #3, etc.)
        counter = 2
        while full_path.exists():
            filename = f"{base_filename} #{counter}.pdf"
            full_path = folder_path / filename
            counter += 1

        return str(full_path), filename

    def _get_audit_pdf_path(self, po_number: str) -> tuple:
        """Generate audit PDF file path."""
        now = datetime.now()
        year = now.strftime('%Y')
        month = now.strftime('%m')
        date_str = now.strftime('%Y.%m.%d_%H%M%S')

        folder_path = Path(self.archive_path) / year / month
        folder_path.mkdir(parents=True, exist_ok=True)

        safe_po = (po_number or "MO").replace("/", "_").replace("\\", "_")
        base = f"{date_str} PO_Audit_{safe_po}"
        filename = f"{base}.pdf"
        full_path = folder_path / filename

        counter = 2
        while full_path.exists():
            filename = f"{base} #{counter}.pdf"
            full_path = folder_path / filename
            counter += 1

        return str(full_path), filename

    # ------------------------------------------------------------------
    # Helper: build a key-value table (left column bold, right column normal)
    # ------------------------------------------------------------------
    def _build_kv_table(self, data: list, col_widths: list = None) -> Table:
        """Build a two-column key-value table with grey background on label column."""
        if col_widths is None:
            col_widths = [2*inch, 4*inch]

        table_data = []
        for label, value in data:
            table_data.append([
                Paragraph(str(label), self.styles['CellBold']),
                Paragraph(str(value), self.styles['CellNormal']),
            ])

        t = Table(table_data, colWidths=col_widths)
        t.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#e8e8e8')),
            ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
            ('GRID', (0, 0), (-1, -1), 1, colors.grey),
        ]))
        return t

    # ------------------------------------------------------------------
    # Helper: add a section title
    # ------------------------------------------------------------------
    def _add_section(self, story: list, title: str):
        story.append(Spacer(1, 0.15*inch))
        story.append(Paragraph(title, self.styles['SectionTitle']))
        story.append(Spacer(1, 0.05*inch))

    # ------------------------------------------------------------------
    # Build material breakdown table (matching Flutter ReportDetailPanel)
    # ------------------------------------------------------------------
    def _build_material_breakdown(self, title: str, items: list) -> Table:
        """Build a material breakdown table with Type/Batch/Start/Stop/Used columns."""
        if not items:
            return None

        headers = ['Type', 'Batch', 'Start', 'Stop', 'Used']
        table_data = [headers]
        total = 0.0

        for it in items:
            if not isinstance(it, dict):
                continue
            type_name = str(it.get('type', '-'))
            batch = str(it.get('batch', '')) or 'No Batch'
            start = str(it.get('start', '-'))
            stop = str(it.get('stop', '-'))
            used = 0.0
            if 'used' in it and it['used'] is not None:
                used = float(it['used'] or 0)
            else:
                s = float(it.get('start', 0) or 0)
                e = float(it.get('stop', 0) or 0)
                used = s - e
            total += used
            table_data.append([type_name, batch, start, stop, f"{used:.2f}"])

        # Total row
        table_data.append(['', 'Total', '', '', f"{total:.2f}"])

        col_widths = [1.5*inch, 1.3*inch, 0.8*inch, 0.8*inch, 0.9*inch]
        t = Table(table_data, colWidths=col_widths)

        # Style: header row grey, total rows highlighted
        style = [
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#e0e0e0')),
            ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('ALIGN', (4, 0), (4, -1), 'RIGHT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            # Bold the total row (last row)
            ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
            ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#f0f0f0')),
        ]
        t.setStyle(TableStyle(style))
        return t

    # ==================================================================
    # generate_pdf — matches Flutter ReportDetailPanel format
    # ==================================================================
    def generate_pdf(self, report_data: dict) -> dict:
        """
        Generate PDF from report data matching Flutter app ReportDetailPanel layout.
        Sections: General Info, Technical Specification, Production Output,
        Materials Used (Total), Material Breakdown, Remarks.
        Returns: {success: bool, path: str, filename: str, error: str}
        """
        try:
            pdf_path, filename = self._get_pdf_path(report_data)

            # Create PDF document
            doc = SimpleDocTemplate(pdf_path, pagesize=A4,
                                    leftMargin=0.6*inch, rightMargin=0.6*inch,
                                    topMargin=0.5*inch, bottomMargin=0.5*inch)
            story = []

            # --- Title ---
            report_id = report_data.get('id', '')
            title = Paragraph(
                f"Production Report{' — #' + str(report_id) if report_id else ''}",
                self.styles['CustomTitle']
            )
            story.append(title)
            story.append(Spacer(1, 0.15*inch))

            # === General Info ===
            self._add_section(story, 'General Info')
            general = [
                ['Operator', report_data.get('operator_name', 'N/A')],
                ['Date', report_data.get('report_date', 'N/A')],
                ['Shift', f"{report_data.get('shift_name', 'N/A')} ({report_data.get('shift_time_range', '')})"],
                ['Machine', report_data.get('machine_name', 'N/A')],
                ['PO Number', report_data.get('po_number', 'N/A')],
            ]
            story.append(self._build_kv_table(general))
            story.append(Spacer(1, 0.1*inch))

            # === Technical Specification ===
            self._add_section(story, 'Technical Specification')
            cu_val = report_data.get('cu', 0) or 0
            tech = [
                ['Lot Number', str(report_data.get('lot_number', 'N/A'))],
                ['Box Type', str(report_data.get('box_type', 'N/A'))],
                ['Diameter / Length', f"{report_data.get('diameter', 'N/A')} / {report_data.get('length', 'N/A')}"],
                ['PD / Weight', f"{report_data.get('pd', 'N/A')} / {report_data.get('weight', 'N/A')}"],
                ['CU', str(cu_val)],
            ]
            story.append(self._build_kv_table(tech))
            story.append(Spacer(1, 0.1*inch))

            # === Production Output ===
            self._add_section(story, 'Production Output')
            output = [
                ['Boxes Produced', str(report_data.get('boxes_produced', 'N/A'))],
                ['Produced Rods', str(report_data.get('produced_rods', 'N/A'))],
                ['Machine Counter', str(report_data.get('machine_counter', 'N/A'))],
                ['Difference', f"{report_data.get('difference', 'N/A')} ({report_data.get('diff_percent', 'N/A')})"],
                ['Waste (kg)', str(report_data.get('waste_kg', 'N/A'))],
                ['Efficiency (%)', str(report_data.get('machine_efficiency', 'N/A'))],
            ]
            story.append(self._build_kv_table(output))
            story.append(Spacer(1, 0.1*inch))

            # === Materials Used (Total) ===
            self._add_section(story, 'Materials Used (Total)')
            mats = [
                ['Acetate', f"{report_data.get('total_acetate', 0):.2f}"],
                ['Paper', f"{report_data.get('total_paper', 0):.2f}"],
                ['PVA Glue', f"{report_data.get('total_pva', 0):.2f}"],
                ['Hot Melt Glue', f"{report_data.get('total_hm', 0):.2f}"],
                ['Triacetin', f"{report_data.get('total_triacetin', 0):.2f}"],
            ]
            story.append(self._build_kv_table(mats))
            story.append(Spacer(1, 0.1*inch))

            # === Material Breakdown ===
            mat_lists = {
                'Acetate': report_data.get('acetate_list', []),
                'Paper': report_data.get('paper_list', []),
                'PVA Glue': report_data.get('pva_list', []),
                'Hot Melt Glue': report_data.get('hm_list', []),
                'Triacetin': report_data.get('tri_list', []),
            }
            has_any_mats = any(isinstance(v, list) and len(v) > 0 for v in mat_lists.values())
            if has_any_mats:
                self._add_section(story, 'Material Breakdown')
                for mat_title, items in mat_lists.items():
                    if not isinstance(items, list) or len(items) == 0:
                        continue
                    # Section sub-title
                    story.append(Paragraph(
                        f"<b>{mat_title}</b>",
                        self.styles['CellNormal']
                    ))
                    story.append(Spacer(1, 0.03*inch))
                    tbl = self._build_material_breakdown(mat_title, items)
                    if tbl:
                        story.append(tbl)
                        story.append(Spacer(1, 0.08*inch))

            # === Remarks ===
            self._add_section(story, 'Remarks')
            remarks = report_data.get('remarks', '')
            story.append(Paragraph(
                remarks if remarks.strip() else 'No comments.',
                self.styles['CellNormal']
            ))

            # Build PDF
            doc.build(story)

            return {
                'success': True,
                'path': pdf_path,
                'filename': filename,
                'folder': f"{report_data.get('report_date', '').split('T')[0].replace('-', '/')}"
            }

        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }

    # ==================================================================
    # generate_audit_pdf — matches Web App PO Audit format
    # ==================================================================
    def generate_pdf_bytes(self, report_data: dict):
        """Render the Production Report PDF and return its bytes (for Odoo attach).

        Reuses ``generate_pdf`` (identical layout); the PDF is archived to the normal
        folder and read back as bytes. Returns ``None`` on failure.
        """
        result = self.generate_pdf(report_data)
        if not result.get("success"):
            return None
        try:
            with open(result["path"], "rb") as fh:
                return fh.read()
        except OSError:
            return None

    def generate_audit_pdf(self, po, reports: list, consolidated_quality: dict = None) -> dict:
        """
        Generate an audit PDF for a Purchase Order matching the web app format.
        Includes: Report Entries table, Production Summary, Materials Consumption.
        po: PurchaseOrder model instance
        reports: list of ProductionReport model instances
        """
        try:
            pdf_path, filename = self._get_audit_pdf_path(po.po_number)

            doc = SimpleDocTemplate(pdf_path, pagesize=A4,
                                    leftMargin=0.5*inch, rightMargin=0.5*inch,
                                    topMargin=0.5*inch, bottomMargin=0.5*inch)
            story = []

            # --- Header ---
            story.append(Paragraph(
                "MANUFACTURING ORDER AUDIT REPORT",
                self.styles['CustomTitle']
            ))
            story.append(Spacer(1, 0.1*inch))
            story.append(Paragraph(
                f"<b>PO Number:</b> {po.po_number}",
                self.styles['CellNormal']
            ))
            story.append(Paragraph(
                f"Specification: {po.diameter} × {po.length}  PD {po.pd}  CU {po.cu}",
                self.styles['CellNormal']
            ))
            story.append(Paragraph(
                f"Target Quantity: {po.target_qty} pcs",
                self.styles['CellNormal']
            ))
            report_date_str = datetime.now().strftime('%d.%m.%Y %H:%M')
            story.append(Paragraph(
                f"Report generated: {report_date_str}",
                self.styles['CellNormal']
            ))
            story.append(Spacer(1, 0.2*inch))

            # --- Report Entries ---
            story.append(Paragraph(
                "<b>Report Entries</b>",
                self.styles['CustomHeading']
            ))

            # Build report entries table
            headers = ['Date', 'Time', 'Operator', 'Rods Produced', 'Machine Counter', 'Difference', 'Scrap']
            table_data = [headers]

            total_rods = 0
            total_machine_counter = 0
            total_diff = 0.0
            total_waste = 0.0

            for r in reports:
                date_str = (r.report_date or '-')[:10]
                time_str = (r.shift_time_range or r.shift_name or '-')[:10]
                op_str = r.operator_name or '-'
                rods = r.produced_rods or 0
                counter = r.machine_counter or 0
                diff = r.difference or 0.0
                diff_pct = r.diff_percent or '0%'
                waste = r.waste_kg or 0.0

                total_rods += rods
                total_machine_counter += counter
                total_diff += diff
                total_waste += waste

                table_data.append([
                    date_str,
                    time_str,
                    op_str,
                    str(rods),
                    str(counter),
                    f"{diff:.0f} ({diff_pct})",
                    f"{waste:.2f}",
                ])

            # TOTAL row
            if reports:
                total_diff_pct = (total_diff / total_machine_counter * 100) if total_machine_counter > 0 else 0.0
                table_data.append([
                    'TOTAL', '', '',
                    str(total_rods),
                    str(total_machine_counter),
                    f"{total_diff:.0f} ({total_diff_pct:.2f}%)",
                    f"{total_waste:.2f}",
                ])

            col_widths = [1.0*inch, 0.8*inch, 1.2*inch, 0.9*inch, 0.9*inch, 1.1*inch, 0.7*inch]
            t = Table(table_data, colWidths=col_widths)
            style = [
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#d0d0d0')),
                ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 7),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
                ('TOPPADDING', (0, 0), (-1, -1), 3),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                ('ALIGN', (3, 0), (6, -1), 'RIGHT'),
            ]
            # Bold TOTAL row
            if reports:
                style.append(('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'))
                style.append(('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#e8e8e8')))
            t.setStyle(TableStyle(style))
            story.append(t)
            story.append(Spacer(1, 0.2*inch))

            # --- Production Summary ---
            story.append(Paragraph(
                "<b>Production Summary</b>",
                self.styles['CustomHeading']
            ))

            diff_pcs = total_machine_counter - total_rods
            diff_pct_summary = (diff_pcs / total_machine_counter * 100) if total_machine_counter > 0 else 0.0
            remaining = po.target_qty - total_rods

            # Count total boxes
            total_boxes = sum(r.boxes_produced or 0 for r in reports)

            summary = [
                ['Total rods produced', f"{total_rods} pcs"],
                ['Remaining to produce', f"{remaining} pcs"],
                ['Boxes submitted', str(total_boxes)],
                ['Machine counter', str(total_machine_counter)],
                ['Difference', f"{diff_pcs:.0f} pcs ({diff_pct_summary:.2f}%)"],
                ['Total scrap waste', f"{total_waste:.1f} kg"],
            ]
            story.append(self._build_kv_table(summary, col_widths=[2.2*inch, 4*inch]))
            story.append(Spacer(1, 0.2*inch))

            # --- Materials Consumption Details ---
            # Aggregate from reports
            mat_categories = {
                'Acetate': {'total': 0.0, 'unit': 'kg'},
                'Paper': {'total': 0.0, 'unit': 'Bob'},
                'PVA Glue': {'total': 0.0, 'unit': 'kg'},
                'Hot Melt Glue': {'total': 0.0, 'unit': 'kg'},
                'Triacetin': {'total': 0.0, 'unit': 'kg'},
            }
            for r in reports:
                mat_categories['Acetate']['total'] += r.total_acetate or 0.0
                mat_categories['Paper']['total'] += r.total_paper or 0.0
                mat_categories['PVA Glue']['total'] += r.total_pva or 0.0
                mat_categories['Hot Melt Glue']['total'] += r.total_hm or 0.0
                mat_categories['Triacetin']['total'] += r.total_triacetin or 0.0

            has_mats = any(v['total'] > 0 for v in mat_categories.values())
            if has_mats:
                story.append(Paragraph(
                    "<b>Materials Consumption Details</b>",
                    self.styles['CustomHeading']
                ))

                mat_data = [['Category', 'Total Used']]
                for cat_name, info in mat_categories.items():
                    if info['total'] > 0:
                        mat_data.append([cat_name, f"{info['total']:.2f} {info['unit']}"])

                mt = Table(mat_data, colWidths=[2*inch, 3*inch])
                mt.setStyle(TableStyle([
                    ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#d0d0d0')),
                    ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                    ('FONTSIZE', (0, 0), (-1, -1), 8),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
                    ('TOPPADDING', (0, 0), (-1, -1), 4),
                    ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                ]))
                story.append(mt)

                # Material breakdown from materials_json
                material_breakdown = {}
                for r in reports:
                    try:
                        if r.materials_json:
                            parsed = json.loads(r.materials_json)
                            for key, map_key in [
                                ("acetate_list", "Acetate"),
                                ("paper_list", "Paper"),
                                ("pva_list", "PVA Glue"),
                                ("hm_list", "Hot Melt Glue"),
                                ("tri_list", "Triacetin"),
                            ]:
                                items = parsed.get(key, [])
                                for item in items:
                                    if isinstance(item, dict):
                                        batch = item.get("batch", "No Batch")
                                        used = float(item.get("used", 0) or 0)
                                        if map_key not in material_breakdown:
                                            material_breakdown[map_key] = {}
                                        if batch not in material_breakdown[map_key]:
                                            material_breakdown[map_key][batch] = 0.0
                                        material_breakdown[map_key][batch] += used
                    except Exception:
                        pass

                if material_breakdown:
                    story.append(Spacer(1, 0.1*inch))
                    story.append(Paragraph(
                        "<b>Material Breakdown</b>",
                        self.styles['CustomHeading']
                    ))

                    bd_data = [['Category', 'Batch', 'Used']]
                    for cat_name, batches in material_breakdown.items():
                        cat_total = sum(batches.values())
                        for batch, used in batches.items():
                            bd_data.append([cat_name, batch, f"{used:.2f}"])
                        bd_data.append([f'Total {cat_name}', '', f"{cat_total:.2f}"])

                    bt = Table(bd_data, colWidths=[2*inch, 2*inch, 1.5*inch])
                    bt_style = [
                        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#d0d0d0')),
                        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                        ('FONTSIZE', (0, 0), (-1, -1), 7),
                        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
                        ('TOPPADDING', (0, 0), (-1, -1), 3),
                        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                        ('ALIGN', (2, 0), (2, -1), 'RIGHT'),
                    ]
                    # Bold rows starting with "Total"
                    for i, row_data in enumerate(bd_data):
                        if i > 0 and row_data[0].startswith('Total '):
                            bt_style.append(('FONTNAME', (0, i), (-1, i), 'Helvetica-Bold'))
                            bt_style.append(('BACKGROUND', (0, i), (-1, i), colors.HexColor('#f0f0f0')))
                    bt.setStyle(TableStyle(bt_style))
                    story.append(bt)

            # --- Consolidated Quality ---
            if consolidated_quality:
                self._add_consolidated_quality(story, consolidated_quality)

            # Build PDF
            doc.build(story)

            return {
                'success': True,
                'path': pdf_path,
                'filename': filename,
            }

        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }

    def _add_consolidated_quality(self, story: list, quality: dict):
        """Append the Consolidated Quality matrix + status footer (purple card style)."""
        from app.quality_stats import CERTIFICATE_PARAMS

        _register_dejavu_fonts()
        story.append(Spacer(1, 0.2 * inch))
        story.append(Paragraph("<b>Consolidated Quality</b>", self.styles['CustomHeading']))
        cert = quality.get("certificate") or []
        cert_by_param = {str(r.get("parameter")): r for r in cert if isinstance(r, dict)}
        qh = ["Parameter", "Unit", "Nominal", "Lower SL", "Upper SL", "Mean", "SD", "Sample Count (N)"]
        qrows = [qh]
        for param, label, unit in CERTIFICATE_PARAMS:
            r = cert_by_param.get(param) or {}
            qrows.append([
                label, r.get("unit") or unit,
                _fmt_num(r.get("nominal")), _fmt_num(r.get("lower")), _fmt_num(r.get("upper")),
                _fmt_num(r.get("mean")), _fmt_num(r.get("sd")),
                str(r.get("n") or ""),
            ])
        qt = Table(qrows, repeatRows=1)
        qt.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), _PURPLE),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, _PURPLE_TINT]),
            ("GRID", (0, 0), (-1, -1), 0.25, _GRID_GREY),
            ("FONTNAME", (0, 0), (-1, -1), "DejaVu"),
            ("FONTNAME", (0, 0), (-1, 0), "DejaVu-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("ALIGN", (3, 1), (-1, -1), "RIGHT"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(qt)
        story.append(Spacer(1, 8))

        footer = Table([[
            Paragraph("Tested Rods", self.styles['CellBold']),
            Paragraph(str(quality.get("rods_total") or 0), self.styles['CellNormal']),
            Paragraph("Rejected Rods", self.styles['CellBold']),
            Paragraph(str(quality.get("rods_rejected") or 0), self.styles['CellNormal']),
            Paragraph("Quality Status", self.styles['CellBold']),
            _status_badge(quality.get("status") or "NO_DATA"),
        ]], colWidths=[28 * mm, 20 * mm, 30 * mm, 20 * mm, 32 * mm, 34 * mm])
        footer.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), _PURPLE_TINT),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("ROUNDEDCORNERS", [6, 6, 6, 6]),
        ]))
        story.append(footer)

    @classmethod
    def _get_oauth_credentials(cls):
        """
        Authenticate using OAuth 2.0 Desktop Client ID flow.
        Handles both first-time authentication and token refresh.
        Works in headless/WSL environments by printing the authorization URL to console.
        """
        try:
            creds_path = os.getenv('GOOGLE_CREDENTIALS_PATH', './credentials.json')
            token_path = os.getenv('GOOGLE_TOKEN_PATH', './token.json')

            if not os.path.exists(creds_path):
                return None, f"Credentials file not found at {creds_path}"

            # If we have a saved token, try to use it
            if os.path.exists(token_path):
                credentials = Credentials.from_authorized_user_file(token_path, scopes=['https://www.googleapis.com/auth/drive'])

                # Refresh token if expired
                if credentials.expired and credentials.refresh_token:
                    credentials.refresh(Request())

                return credentials, None

            # No saved token, run OAuth flow
            flow = InstalledAppFlow.from_client_secrets_file(
                creds_path,
                scopes=['https://www.googleapis.com/auth/drive']
            )

            # Use run_local_server with open_browser=False for headless/WSL environments
            # This will print the authorization URL to console instead of trying to open a browser
            print("\n" + "="*80)
            print("🔐 GOOGLE DRIVE AUTHENTICATION REQUIRED")
            print("="*80)
            print("\nNo saved Google Drive token found. Starting OAuth flow...")
            print("\nA local server will be started to receive the authorization callback.")
            print("Please follow the instructions below:\n")

            credentials = flow.run_local_server(port=0, open_browser=False)

            print("\n✅ Authorization successful!")
            print("="*80 + "\n")

            # Save the token for future use
            with open(token_path, 'w') as token_file:
                token_file.write(credentials.to_json())

            return credentials, None

        except Exception as e:
            return None, f"OAuth authentication failed: {str(e)}"

    @classmethod
    def validate_google_credentials_at_startup(cls):
        """
        Validate Google Drive credentials at server startup.
        Sets class variables to track availability.
        This is called once when the server starts.
        """
        try:
            credentials, error = cls._get_oauth_credentials()

            if error or credentials is None:
                cls.google_drive_available = False
                cls.google_drive_error_message = error or "Failed to authenticate"
                return False

            # Try to build service to verify credentials work
            service = build('drive', 'v3', credentials=credentials)

            # If we got here, credentials are valid
            cls.google_drive_available = True
            cls.google_drive_error_message = None
            return True

        except Exception as e:
            cls.google_drive_available = False
            cls.google_drive_error_message = f"Failed to authenticate with Google Drive: {str(e)}"
            return False

    def _get_google_drive_service(self):
        """Authenticate and return Google Drive service using OAuth flow"""
        try:
            credentials, error = PDFReportGenerator._get_oauth_credentials()

            if error or credentials is None:
                return None, error or "Failed to authenticate"

            service = build('drive', 'v3', credentials=credentials)
            return service, None
        except Exception as e:
            return None, f"Failed to authenticate with Google Drive: {str(e)}"

    def _get_or_create_folder(self, service, parent_id: str, folder_name: str) -> str:
        """Get or create a folder in Google Drive"""
        try:
            # Search for existing folder
            query = f"name='{folder_name}' and mimeType='application/vnd.google-apps.folder' and '{parent_id}' in parents and trashed=false"
            results = service.files().list(q=query, spaces='drive', fields='files(id)', pageSize=1).execute()

            if results.get('files'):
                return results['files'][0]['id']

            # Create new folder
            file_metadata = {
                'name': folder_name,
                'mimeType': 'application/vnd.google-apps.folder',
                'parents': [parent_id]
            }
            folder = service.files().create(body=file_metadata, fields='id').execute()
            return folder.get('id')
        except Exception as e:
            raise Exception(f"Failed to get/create folder: {str(e)}")

    def upload_to_google_drive(self, pdf_path: str, filename: str, report_data: dict) -> dict:
        """Upload PDF to Google Drive"""
        # Check if Google Drive is available (validated at startup)
        if not PDFReportGenerator.google_drive_available:
            return {
                'success': False,
                'error': f"Google Drive not available: {PDFReportGenerator.google_drive_error_message}"
            }

        try:
            service, error = self._get_google_drive_service()
            if error:
                return {'success': False, 'error': error}

            # Get root folder ID from env
            root_folder_id = os.getenv('GOOGLE_DRIVE_FOLDER_ID')
            if not root_folder_id:
                return {'success': False, 'error': 'GOOGLE_DRIVE_FOLDER_ID not set in .env'}

            # Parse date for folder structure
            report_date = report_data.get('report_date', datetime.now().strftime('%Y-%m-%d'))
            try:
                date_obj = datetime.strptime(report_date.split('T')[0], '%Y-%m-%d')
            except:
                date_obj = datetime.now()

            year = date_obj.strftime('%Y')
            month = date_obj.strftime('%m')

            # Create folder structure: Production log/YYYY/MM/
            production_log_id = self._get_or_create_folder(service, root_folder_id, 'Production log')
            year_folder_id = self._get_or_create_folder(service, production_log_id, year)
            month_folder_id = self._get_or_create_folder(service, year_folder_id, month)

            # Upload file
            file_metadata = {
                'name': filename,
                'parents': [month_folder_id]
            }

            media = MediaFileUpload(pdf_path, mimetype='application/pdf')
            file = service.files().create(body=file_metadata, media_body=media, fields='id, webViewLink').execute()

            return {
                'success': True,
                'file_id': file.get('id'),
                'web_link': file.get('webViewLink')
            }
        except Exception as e:
            return {
                'success': False,
                'error': f"Google Drive upload failed: {str(e)}"
            }

    def generate_pdf_with_upload(self, report_data: dict) -> dict:
        """Generate PDF and upload to Google Drive"""
        # First, generate PDF locally
        pdf_result = self.generate_pdf(report_data)

        if not pdf_result['success']:
            return pdf_result

        # Then, upload to Google Drive
        upload_result = self.upload_to_google_drive(
            pdf_result['path'],
            pdf_result['filename'],
            report_data
        )

        # Return combined result
        return {
            'success': pdf_result['success'] and upload_result['success'],
            'local_path': pdf_result['path'],
            'filename': pdf_result['filename'],
            'google_drive_link': upload_result.get('web_link') if upload_result['success'] else None,
            'google_drive_error': upload_result.get('error') if not upload_result['success'] else None
        }