from __future__ import annotations
from pathlib import Path
import xlsxwriter


def _safe(v):
    if v is None: return ""
    return str(v)


def create_inspection_report(path, payload: dict):
    path=Path(path)
    wb=xlsxwriter.Workbook(str(path))
    fmt_title=wb.add_format({"bold":True,"font_size":16,"font_color":"#FFFFFF","bg_color":"#1F4E78","align":"center","valign":"vcenter"})
    fmt_head=wb.add_format({"bold":True,"font_color":"#FFFFFF","bg_color":"#4472C4","border":1,"align":"center","valign":"vcenter"})
    fmt_label=wb.add_format({"bold":True,"bg_color":"#D9EAF7","border":1})
    fmt_cell=wb.add_format({"border":1,"valign":"top"})
    fmt_wrap=wb.add_format({"border":1,"valign":"top","text_wrap":True})
    fmt_pass=wb.add_format({"border":1,"bg_color":"#E2F0D9","font_color":"#006100","bold":True})
    fmt_fail=wb.add_format({"border":1,"bg_color":"#FCE4D6","font_color":"#9C0006","bold":True})

    summary=wb.add_worksheet("Summary")
    summary.merge_range("A1:D1","Label Inspection Report",fmt_title)
    summary.set_row(0,26)
    summary.set_column("A:A",24); summary.set_column("B:B",38); summary.set_column("C:D",24)
    info=[
        ("Overall",payload.get("overall","")),
        ("Software Version",payload.get("software_version","")),
        ("Profile",payload.get("profile","")),
        ("Model",payload.get("model","")),
        ("Label Type",payload.get("label_type","")),
        ("Label P/N",payload.get("label_pn","")),
        ("Spec Version",payload.get("spec_version","")),
        ("Source Spec",payload.get("source_spec","")),
        ("Artwork Verification",payload.get("artwork_verification_status","NOT_CONFIGURED")),
        ("Session ID",payload.get("session_id","")),
        ("Started At",payload.get("started_at","")),
        ("Completed At",payload.get("completed_at","")),
        ("Total Test Time (sec)",payload.get("elapsed_sec","")),
        ("Locked / Required",f"{payload.get('locked_count','')} / {payload.get('required_count','')}"),
        ("Work Order P/N",payload.get("work_order",{}).get("pn","")),
        ("Made in",payload.get("work_order",{}).get("made_in","")),
    ]
    for i,(k,v) in enumerate(info,2):
        summary.write(i-1,0,k,fmt_label)
        f=fmt_pass if k=="Overall" and str(v).upper()=="PASS" else (fmt_fail if k=="Overall" else fmt_cell)
        summary.write(i-1,1,_safe(v),f)

    ws=wb.add_worksheet("Inspection_Result")
    headers=["Item","Actual Value","Expected / Rule","State","Source","Lock Time","Message"]
    for c,h in enumerate(headers): ws.write(0,c,h,fmt_head)
    ws.freeze_panes(1,0)
    ws.set_column(0,0,42); ws.set_column(1,2,30); ws.set_column(3,3,16); ws.set_column(4,5,24); ws.set_column(6,6,48)
    locks=payload.get("locks",{})
    row=1
    for item,state in locks.items():
        values=[item,state.get("locked_value",""),payload.get("expected_map",{}).get(item,""),state.get("state",""),state.get("lock_source",""),state.get("lock_time",""),state.get("last_message","")]
        for c,v in enumerate(values):
            f=fmt_pass if c==3 and str(v)=="LOCK" else fmt_wrap
            ws.write(row,c,_safe(v),f)
        row+=1
    ws.autofilter(0,0,max(1,row-1),len(headers)-1)

    perf=wb.add_worksheet("Zone_Performance")
    ph=["Zone","Title","Attempts","OCR Avg ms","OCR Max ms","Last Sharpness","Locked Items","Total Items","Completed"]
    for c,h in enumerate(ph): perf.write(0,c,h,fmt_head)
    perf.freeze_panes(1,0)
    perf.set_column(0,1,28); perf.set_column(2,8,18)
    for r,(zid,z) in enumerate(payload.get("zone_stats",{}).items(),1):
        attempts=int(z.get("attempts",0)); total_ms=float(z.get("total_ocr_ms",0.0))
        avg=round(total_ms/attempts,1) if attempts else 0
        vals=[zid,z.get("title",""),attempts,avg,round(float(z.get("max_ocr_ms",0.0)),1),round(float(z.get("last_sharpness",0.0)),1),z.get("locked_items",0),z.get("total_items",0),"YES" if z.get("completed") else "NO"]
        for c,v in enumerate(vals): perf.write(r,c,v,fmt_cell)

    trace=wb.add_worksheet("Traceability")
    trace.set_column("A:A",28); trace.set_column("B:B",60)
    trace.write(0,0,"Field",fmt_head); trace.write(0,1,"Value",fmt_head)
    key_items={
        "S/N":"Variable: S/N Barcode Format",
        "MAC":"Variable: MAC Barcode Format",
        "GPON S/N":"Variable: GPON S/N Barcode Format",
        "SSID":"Variable: SSID Format",
        "Password":"Variable: Password Format",
        "WiFi Key":"Variable: WiFi Key Format",
        "WiFi QR":"Variable: WiFi QR Format",
    }
    r=1
    for label,item in key_items.items():
        trace.write(r,0,label,fmt_label); trace.write(r,1,_safe(locks.get(item,{}).get("locked_value","")),fmt_wrap); r+=1
    trace.write(r,0,"Profile",fmt_label); trace.write(r,1,_safe(payload.get("profile","")),fmt_wrap); r+=1
    trace.write(r,0,"Label Type",fmt_label); trace.write(r,1,_safe(payload.get("label_type","")),fmt_wrap); r+=1
    trace.write(r,0,"Source Spec",fmt_label); trace.write(r,1,_safe(payload.get("source_spec","")),fmt_wrap); r+=1
    trace.write(r,0,"Artwork Verification",fmt_label); trace.write(r,1,_safe(payload.get("artwork_verification_status","NOT_CONFIGURED")),fmt_wrap); r+=1
    trace.write(r,0,"Software Version",fmt_label); trace.write(r,1,_safe(payload.get("software_version","")),fmt_wrap)

    wb.close()
    return str(path)
