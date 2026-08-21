import io
import os
import re
import pandas as pd
import pypdf
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import (
    HRFlowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
import streamlit as st

st.set_page_config(
    page_title="Artwork & Master Data Verifier", layout="wide", page_icon="📦"
)


# ----------------------------------------------------
# PARSING ENGINE
# ----------------------------------------------------
def clean_text(val):
  if pd.isna(val) or val is None:
    return ""
  val = str(val).replace("\xa0", " ")
  return re.sub(r"\s+", " ", val).strip()


def normalize_item_no(val):
  if pd.isna(val) or val is None:
    return ""
  return re.sub(r"[\s\-_:]", "", str(val).strip().upper())


def parse_pdf_page(raw_text, page_num=1):
  raw_text = (raw_text or "").replace("\xa0", " ")

  # 1. Item No
  item_no = None
  m_wrd = re.search(
      r":\s*([A-Za-z0-9\-_]+)\s*Item\s*No", raw_text, re.IGNORECASE
  )
  if (
      m_wrd
      and m_wrd.group(1).upper()
      not in ["DESCRIPTION", "SIZE", "QTY", "UNKNOWN"]
  ):
    item_no = m_wrd.group(1).strip().upper()

  if not item_no:
    m_pad = re.search(
        r"Item\s*No\.?\s*[:\s]*([A-Za-z0-9\-_]+)", raw_text, re.IGNORECASE
    )
    if (
        m_pad
        and m_pad.group(1).upper()
        not in ["DESCRIPTION", "SIZE", "QTY", "UNKNOWN"]
    ):
      item_no = m_pad.group(1).strip().upper()

  if not item_no or item_no in ["DESCRIPTION", "SIZE", "QTY"]:
    m_code = re.search(
        r"\b(PAD\d+|WRD\d+|SND[-_\s]?\d+|POT\d+)\b", raw_text, re.IGNORECASE
    )
    item_no = (
        m_code.group(1).strip().upper() if m_code else f"UNKNOWN_P{page_num}"
    )

  # 2. Size
  size_m = re.search(
      r"Size\s*\n?\s*[:\.]?\s*([^\n\r]+)", raw_text, re.IGNORECASE
  )
  size = ""
  if size_m:
    size = re.sub(r"[:]+", "", size_m.group(1).strip()).strip()
    size = re.sub(r"^(?:Size|Qty)\s*", "", size, flags=re.IGNORECASE).strip()

  # 3. Quantity
  qty = None
  m_std = re.search(
      r"\b(?:TTL\s*QTY|TTL\s*Qty|QTY|Qty)\s*[:\.]?\s*(\d+(?:\.\d+)?)",
      raw_text,
      re.IGNORECASE,
  )
  if m_std:
    qty = float(m_std.group(1))
  else:
    m_rev = re.search(
        r":\s*(\d+(?:\.\d+)?)\s*(?:PCS|pcs|SETS|sets|SET|set)\s*TTL\s*Qty",
        raw_text,
        re.IGNORECASE,
    )
    if m_rev:
      qty = float(m_rev.group(1))
    else:
      m_fallback = re.search(
          r":\s*(\d+(?:\.\d+)?)\s*(?:PCS|pcs|SETS|sets|SET|set)\b",
          raw_text,
          re.IGNORECASE,
      )
      if m_fallback:
        qty = float(m_fallback.group(1))

  # 4. Description
  desc = ""
  d_inline = re.search(
      r"Description\s*:\s*([^\n\r]+)", raw_text, re.IGNORECASE
  )
  if (
      d_inline
      and d_inline.group(1).strip()
      and not d_inline.group(1).lower().startswith("size")
  ):
    d_block = re.search(
        r"Description\s*:\s*(.*?)(?=\n\s*Size|\n\s*TTL|\n\s*Nt|\n\s*MEAS|$)",
        raw_text,
        re.DOTALL | re.IGNORECASE,
    )
    desc = (
        d_block.group(1).strip().replace("\n", " ")
        if d_block
        else d_inline.group(1).strip()
    )

  if not desc:
    d_alsahah = re.search(
        r"ALSAHAH\s*CO\.?\s*\n(.*?)(?=\n\s*(?:Front marking|Back marking|BOTH"
        r" SIDE|MADE IN INDIA|P\s*AD|PAD|\d+)\b|$)",
        raw_text,
        re.DOTALL | re.IGNORECASE,
    )
    if d_alsahah and d_alsahah.group(1).strip():
      desc = d_alsahah.group(1).strip().replace("\n", " ")

  desc = re.sub(r"\bSTRIP\s+E\b", "STRIPE", desc, flags=re.IGNORECASE)
  return {
      "item_no": item_no,
      "description": clean_text(desc),
      "size": clean_text(size),
      "qty": qty,
  }


# ----------------------------------------------------
# PDF REPORT GENERATOR (IN-MEMORY)
# ----------------------------------------------------
def generate_pdf_report_bytes(report_data, pdf_name, csv_name):
  buffer = io.BytesIO()
  doc = SimpleDocTemplate(
      buffer,
      pagesize=letter,
      rightMargin=36,
      leftMargin=36,
      topMargin=36,
      bottomMargin=36,
  )
  styles = getSampleStyleSheet()

  title_style = ParagraphStyle(
      "TitleStyle",
      parent=styles["Heading1"],
      fontSize=16,
      leading=20,
      textColor=colors.HexColor("#1A365D"),
  )
  sub_style = ParagraphStyle(
      "SubStyle",
      parent=styles["Normal"],
      fontSize=9,
      leading=12,
      textColor=colors.HexColor("#4A5568"),
  )
  hdr_cell_style = ParagraphStyle(
      "HdrCell",
      parent=styles["Normal"],
      fontSize=8,
      leading=10,
      textColor=colors.white,
      fontName="Helvetica-Bold",
  )
  cell_style = ParagraphStyle(
      "Cell",
      parent=styles["Normal"],
      fontSize=7.5,
      leading=9.5,
      textColor=colors.HexColor("#2D3748"),
  )
  match_style = ParagraphStyle(
      "MatchCell",
      parent=styles["Normal"],
      fontSize=7.5,
      leading=9.5,
      textColor=colors.HexColor("#2F855A"),
      fontName="Helvetica-Bold",
  )
  disc_style = ParagraphStyle(
      "DiscCell",
      parent=styles["Normal"],
      fontSize=7.5,
      leading=9.5,
      textColor=colors.HexColor("#C53030"),
      fontName="Helvetica-Bold",
  )

  story = [
      Paragraph("Shipping Mark vs Master Data Comparison Report", title_style),
      Paragraph(f"<b>PDF:</b> {pdf_name} | <b>Master:</b> {csv_name}", sub_style),
      Spacer(1, 10),
  ]

  matches_count = sum(1 for r in report_data if "MATCHED" in r["Status"])
  disc_count = len(report_data) - matches_count

  sum_data = [
      [
          Paragraph("<b>Total Items</b>", sub_style),
          Paragraph("<b>Exact Matches</b>", sub_style),
          Paragraph("<b>Discrepancies</b>", sub_style),
      ],
      [
          Paragraph(str(len(report_data)), title_style),
          Paragraph(str(matches_count), match_style),
          Paragraph(str(disc_count), disc_style),
      ],
  ]
  sum_table = Table(sum_data, colWidths=[180, 180, 180])
  sum_table.setStyle(
      TableStyle([
          ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F7FAFC")),
          ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
          ("ALIGN", (0, 0), (-1, -1), "CENTER"),
          ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
          ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
          ("TOPPADDING", (0, 0), (-1, -1), 6),
      ])
  )
  story.append(sum_table)
  story.append(Spacer(1, 12))
  story.append(
      HRFlowable(
          width="100%",
          thickness=1,
          color=colors.HexColor("#CBD5E0"),
          spaceAfter=10,
      )
  )

  t_data = [[
      Paragraph("Page", hdr_cell_style),
      Paragraph("Item Key", hdr_cell_style),
      Paragraph("Status", hdr_cell_style),
      Paragraph("PDF Artwork Details", hdr_cell_style),
      Paragraph("Master Data Details", hdr_cell_style),
  ]]

  for item in report_data:
    st_style = match_style if "MATCHED" in item["Status"] else disc_style
    t_data.append([
        Paragraph(str(item["Page"]), cell_style),
        Paragraph(str(item["Item Key"]), cell_style),
        Paragraph(str(item["Status"]), st_style),
        Paragraph(str(item["PDF_HTML"]), cell_style),
        Paragraph(str(item["CSV_HTML"]), cell_style),
    ])

  main_table = Table(t_data, colWidths=[35, 65, 140, 150, 150])
  main_table.setStyle(
      TableStyle([
          ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1A365D")),
          ("VALIGN", (0, 0), (-1, -1), "TOP"),
          ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
          (
              "ROWBACKGROUNDS",
              (0, 1),
              (-1, -1),
              [colors.white, colors.HexColor("#F8FAFC")],
          ),
          ("TOPPADDING", (0, 0), (-1, -1), 4),
          ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
      ])
  )
  story.append(main_table)
  doc.build(story)
  return buffer.getvalue()


# ----------------------------------------------------
# STREAMLIT UI & DRILL-DOWN
# ----------------------------------------------------
st.title("📦 Shipping Mark & Master Data Verification Portal")
st.caption("Real-time discrepancy analyzer, visual audit, and report generator")

with st.sidebar:
  st.header("📂 Data Source")
  uploaded_pdf = st.file_uploader("Upload Shipping Mark PDF", type=["pdf"])
  uploaded_master = st.file_uploader(
      "Upload Master Data File", type=["csv", "xlsx", "xls"]
  )

  st.markdown("---")
  st.header("⚙️ Comparison Filters")
  ignore_case = st.checkbox("Ignore Letter Case", value=True)
  ignore_special_chars = st.checkbox("Ignore Symbols (-, &, /)", value=True)

if uploaded_pdf and uploaded_master:
  if uploaded_master.name.endswith(".csv"):
    csv_df = pd.read_csv(uploaded_master)
  else:
    csv_df = pd.read_excel(uploaded_master)

  reader = pypdf.PdfReader(uploaded_pdf)
  pdf_records = []
  for page_num, page in enumerate(reader.pages, start=1):
    txt = page.extract_text() or ""
    rec = parse_pdf_page(txt, page_num)
    rec["Page"] = page_num
    rec["Match_Key"] = normalize_item_no(rec["item_no"])
    pdf_records.append(rec)
  pdf_df = pd.DataFrame(pdf_records)

  csv_item_col = next(
      (c for c in csv_df.columns if "ITEM" in c.upper()), csv_df.columns[0]
  )
  csv_desc_col = next((c for c in csv_df.columns if "DESC" in c.upper()), None)
  csv_size_col = next((c for c in csv_df.columns if "SIZE" in c.upper()), None)
  csv_qty_col = next((c for c in csv_df.columns if "QTY" in c.upper()), None)

  csv_df["CSV_Order"] = csv_df.index
  csv_df["Match_Key"] = csv_df[csv_item_col].apply(normalize_item_no)

  merged = pd.merge(
      csv_df, pdf_df, on="Match_Key", suffixes=("_Master", "_PDF"), how="outer"
  )
  merged["CSV_Order"] = merged["CSV_Order"].fillna(99999)
  merged = merged.sort_values("CSV_Order")

  comparison_results = []
  raw_grid_data = []

  for _, row in merged.iterrows():
    item_key = (
        row["Match_Key"]
        if pd.notna(row["Match_Key"])
        else row.get(csv_item_col, "")
    )
    page_num = row.get("Page")

    in_pdf = pd.notna(page_num)
    in_csv = pd.notna(row.get(csv_item_col))

    raw_pdf_desc = clean_text(row.get("description", ""))
    raw_csv_desc = (
        clean_text(row.get(csv_desc_col, "")) if csv_desc_col else ""
    )

    raw_pdf_size = clean_text(row.get("size", ""))
    raw_csv_size = (
        clean_text(row.get(csv_size_col, "")) if csv_size_col else ""
    )

    qty_pdf = float(row["qty"]) if pd.notna(row.get("qty")) else None
    qty_csv = (
        float(re.findall(r"\d+", str(row.get(csv_qty_col, "")))[0])
        if csv_qty_col and re.findall(r"\d+", str(row.get(csv_qty_col, "")))
        else None
    )

    if not in_pdf:
      status = "Missing in PDF Artwork"
      mismatches = ["Missing in PDF"]
      pdf_art_html = "-"
      csv_master_html = (
          f"{raw_csv_desc}<br/>Size: {raw_csv_size} | Qty:"
          f" {clean_text(row.get(csv_qty_col, ''))}"
      )
    elif not in_csv:
      status = "Missing in Master Data"
      mismatches = ["Missing in CSV"]
      pdf_art_html = (
          f"{raw_pdf_desc}<br/>Size: {raw_pdf_size} | Qty:"
          f" {str(row.get('qty', ''))}"
      )
      csv_master_html = "-"
    else:
      p_desc, c_desc = raw_pdf_desc, raw_csv_desc
      p_size, c_size = raw_pdf_size, raw_csv_size

      if ignore_case:
        p_desc, c_desc = p_desc.upper(), c_desc.upper()
        p_size, c_size = p_size.upper(), c_size.upper()
      if ignore_special_chars:
        p_desc = re.sub(r"[\W_]+", " ", p_desc).strip()
        c_desc = re.sub(r"[\W_]+", " ", c_desc).strip()
        p_size = re.sub(r"[\W_]+", " ", p_size).strip()
        c_size = re.sub(r"[\W_]+", " ", c_size).strip()

      mismatches = []
      desc_diff = p_desc != c_desc
      size_diff = p_size != c_size
      qty_diff = qty_pdf != qty_csv

      if desc_diff:
        mismatches.append("Desc Mismatch")
      if size_diff:
        mismatches.append("Size Mismatch")
      if qty_diff:
        mismatches.append("Qty Mismatch")

      status = "MATCHED" if not mismatches else f"DISCREPANCY ({', '.join(mismatches)})"

      disp_pdf_desc = (
          f'<font color="#C53030"><b>{raw_pdf_desc or "[EMPTY]"}</b></font>'
          if desc_diff
          else raw_pdf_desc
      )
      disp_pdf_size = (
          f'<font color="#C53030"><b>{raw_pdf_size}</b></font>'
          if size_diff
          else raw_pdf_size
      )
      disp_pdf_qty = (
          f'<font color="#C53030"><b>{row.get("qty", "")}</b></font>'
          if qty_diff
          else str(row.get("qty", ""))
      )

      pdf_art_html = (
          f"{disp_pdf_desc}<br/>Size: {disp_pdf_size} | Qty: {disp_pdf_qty}"
      )
      csv_master_html = (
          f"{raw_csv_desc}<br/>Size: {raw_csv_size} | Qty:"
          f" {clean_text(row.get(csv_qty_col, ''))}"
      )

    report_row = {
        "Page": int(page_num) if pd.notna(page_num) else "-",
        "Item Key": item_key,
        "Status": status,
        "PDF_HTML": pdf_art_html,
        "CSV_HTML": csv_master_html,
    }
    comparison_results.append(report_row)

    raw_grid_data.append({
        "Page": int(page_num) if pd.notna(page_num) else "-",
        "Item Key": item_key,
        "Status": "✅ MATCHED" if "MATCHED" in status else f"❌ {status}",
        "Issue_Type": (
            "Exact Match" if "MATCHED" in status else "Discrepancy"
        ),
        "PDF Description": raw_pdf_desc if in_pdf else "-",
        "CSV Description": raw_csv_desc if in_csv else "-",
        "PDF Size": raw_pdf_size if in_pdf else "-",
        "CSV Size": raw_csv_size if in_csv else "-",
        "PDF Qty": row.get("qty", "-"),
        "CSV Qty": row.get(csv_qty_col, "-"),
    })

  grid_df = pd.DataFrame(raw_grid_data)

  # Top KPI Metrics Cards
  exact_m = (grid_df["Issue_Type"] == "Exact Match").sum()
  disc_m = (grid_df["Issue_Type"] == "Discrepancy").sum()

  kpi1, kpi2, kpi3, kpi4 = st.columns(4)
  kpi1.metric("Total Items Processed", len(grid_df))
  kpi2.metric("Exact Matches", exact_m)
  kpi3.metric("Discrepancies", disc_m, delta=-disc_m, delta_color="inverse")
  kpi4.metric(
      "Compliance Rate",
      f"{(exact_m / len(grid_df) * 100):.1f}%" if len(grid_df) else "0%",
  )

  st.markdown("---")

  # Dynamic Filter Controls
  f_col1, f_col2 = st.columns([1, 2])
  with f_col1:
    filter_choice = st.radio(
        "Filter View:",
        ["Show All", "Only Discrepancies (Issues)", "Only Matches"],
        horizontal=True,
    )
  with f_col2:
    search_query = st.text_input("🔍 Search Item Key / Description:")

  view_df = grid_df.copy()
  if filter_choice == "Only Discrepancies (Issues)":
    view_df = view_df[view_df["Issue_Type"] == "Discrepancy"]
  elif filter_choice == "Only Matches":
    view_df = view_df[view_df["Issue_Type"] == "Exact Match"]

  if search_query:
    view_df = view_df[
        view_df["Item Key"]
        .astype(str)
        .str.contains(search_query, case=False, na=False)
        | view_df["PDF Description"]
        .astype(str)
        .str.contains(search_query, case=False, na=False)
        | view_df["CSV Description"]
        .astype(str)
        .str.contains(search_query, case=False, na=False)
    ]

  def highlight_status(val):
    if "MATCHED" in str(val):
      return "background-color: #D1E7DD; color: #0F5132; font-weight: bold;"
    elif "❌" in str(val):
      return "background-color: #F8D7DA; color: #842029; font-weight: bold;"
    return ""

  style_func = getattr(view_df.style, "map", None) or getattr(
      view_df.style, "applymap"
  )
  styled_df = style_func(
      highlight_status, subset=["Status"]
  ).hide(axis="columns", subset=["Issue_Type"])
  st.dataframe(styled_df, use_container_width=True, height=420)

  # Download Action Bar
  st.markdown("---")
  st.subheader("📥 Export Audit Reports")
  d_col1, d_col2, d_col3 = st.columns(3)

  # 1. PDF Report Download
  with d_col1:
    pdf_report_bytes = generate_pdf_report_bytes(
        comparison_results, uploaded_pdf.name, uploaded_master.name
    )
    st.download_button(
        label="📑 Download PDF Comparison Report",
        data=pdf_report_bytes,
        file_name="comparison_report.pdf",
        mime="application/pdf",
        use_container_width=True,
    )

  # 2. Excel Download
  with d_col2:
    excel_buffer = io.BytesIO()
    with pd.ExcelWriter(excel_buffer) as writer:
      grid_df.drop(columns=["Issue_Type"]).to_excel(
          writer, index=False, sheet_name="Audit_Summary"
      )
    st.download_button(
        label="📊 Download Excel Spreadsheet (.xlsx)",
        data=excel_buffer.getvalue(),
        file_name="comparison_report.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )

  # 3. CSV Download
  with d_col3:
    csv_bytes = (
        grid_df.drop(columns=["Issue_Type"]).to_csv(index=False).encode("utf-8")
    )
    st.download_button(
        label="📄 Download Clean CSV (.csv)",
        data=csv_bytes,
        file_name="comparison_report.csv",
        mime="text/csv",
        use_container_width=True,
    )
else:
  st.info(
      "👈 Upload your Shipping Mark PDF and Master Data file in the sidebar to"
      " begin verification."
  )
