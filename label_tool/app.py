from __future__ import annotations
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
import logging
import json
import threading
import queue
import os
import re
import traceback
import time
from datetime import datetime
import pathlib

import cv2
from PIL import Image, ImageTk

from . import __version__
from .core.engine import InspectionEngine
from .core.multi_image_inspection import MultiImageInspectionEngine
from .core.profile_manager import discover_profiles
from .core.golden_profile_manager import (build_dynamic_profile, validate_profile_structure, mark_validated, dynamic_identity_errors,
    _dynamic_item_rows, apply_editable_items, save_profile_identity_edits, STANDARD_LIBRARY, validation_readiness_errors)
from .core.camera_manager import CameraManager
from .core.live_engine import LiveFrameAnalyzer, LOCK_TO_FIELD
from .core.smart_lock import SmartLockEngine, IdentityGuard
from .core.live_session import LiveInspectionSession
from .core.fast_machine_reader import FastMachineReader
from .core.direct_guided_ocr import DirectGuidedOCR, GuidedItemScheduler, GuidedTarget, targets_from_profile
from .core.production_zone_ocr import MultiFieldZoneOCR, ProductionZoneScheduler, ProductionZone
from .core.ocr_runtime import OCRProcessService, OCRRuntimeError, OCRRuntimeTimeout, OCRRuntimeInitError
from .core.worker_bus import WorkerResultBus, WorkerEvent
from .logging_setup import setup_logging

log = logging.getLogger(__name__)

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"Label Auto Inspection Tool V{__version__}")
        self.minsize(1180,720)
        try:
            if os.name=='nt': self.state('zoomed')
        except Exception:
            pass
        self.geometry("1660x930")
        self.minsize(1300, 760)

        self.execution_log, self.debug_log = setup_logging()
        self.profiles = {}
        self.engine = None
        self.live_analyzer = None
        self.camera = CameraManager()
        self.locks = None
        self.identity_guard = IdentityGuard(3)
        self.live_session = None
        self.last_frame = None
        self.preview_job = None
        self.live_job = None
        self.live_active = False
        self.live_busy = False
        self.new_unit_prompted = False
        self.auto_saved = False
        self.live_cycle = 0
        self.dropped_busy_cycles = 0
        self.last_perf_log = 0.0
        self.zone_scheduler = None  # legacy/offline only; live V1.4 uses GuidedItemScheduler
        self.guided_ocr = None
        self.guided_scheduler = GuidedItemScheduler()
        self.zone_ocr = None
        self.production_scheduler = ProductionZoneScheduler()
        self.ocr_mode_var = tk.StringVar(value="Production 4-Zone")
        self.zone_items_var = tk.StringVar(value="")
        self.zone_stats = {}
        self.report_expected = {}
        self.guided_expected_var = tk.StringVar(value='Expected: --')
        self.guided_ocr_var = tk.StringVar(value='OCR: --')
        self.guided_quality_var = tk.StringVar(value='Target: --')
        self.ocr_runtime_var = tk.StringVar(value='OCR Engine: NOT READY')
        self.ocr_runtime_state = 'NOT_READY'
        self.ocr_runtime_busy = False
        self.ocr_service = OCRProcessService(init_timeout_sec=12.0, read_timeout_sec=6.0)
        self.target_zoom_photo = None
        self.target_border_state = 'IDLE'
        self.preview_last_size=(0,0)
        self.preview_min_width=560
        self.preview_min_height=240
        self.fast_reader = None
        self.machine_job = None
        self.machine_busy = False
        self.machine_cycle = 0
        self.machine_state_var = tk.StringVar(value='Fast Machine Read: STOPPED')
        self.worker_bus = WorkerResultBus(maxsize=96)
        self.worker_poll_job = None
        self.worker_poll_interval_ms = 30
        self.worker_event_count = 0
        self.zone_title_var = tk.StringVar(value='Current Zone: --')
        self.zone_instruction_var = tk.StringVar(value='')
        self.zone_progress_var = tk.StringVar(value='Zone Progress: --')

        self.profile_var = tk.StringVar()
        self.profile_info_var = tk.StringVar()
        self.image_path = tk.StringVar()
        self.image_paths = []
        self.multi_image_result = None
        self.image_batch_var = tk.StringVar(value="Images: 0 | Ready")
        self.image_progress_var = tk.StringVar(value="Idle")
        self.image_worker_thread = None
        self.image_worker_queue = queue.Queue()
        self.image_cancel_event = threading.Event()
        self.image_poll_job = None
        self.image_job_running = False
        self.image_manual_note_var = tk.StringVar(value="Visual inspection confirmed")
        self.expected_pn = tk.StringVar()
        self.expected_country = tk.StringVar()
        self.status_var = tk.StringVar(value="Ready")
        self.camera_var = tk.StringVar()
        self.live_state_var = tk.StringVar(value="Live: STOPPED")
        self.progress_var = tk.StringVar(value="0 / 0 LOCKED")
        self.scanner_var = tk.StringVar()
        self._preview_photo = None

        self._load_profiles()
        self._build_ui()
        if self.profiles:
            self.profile_var.set(next(iter(self.profiles)))
            self._apply_profile()
        self.worker_poll_job = self.after(self.worker_poll_interval_ms, self._poll_worker_results)

    def _import_golden_profile(self):
        if not self.profiles:
            messagebox.showerror("Import Golden","No baseline profile is available.")
            return
        source=filedialog.askopenfilename(
            title="Import Golden DOC / DOCX / Image",
            filetypes=[("Golden files","*.doc *.docx *.png *.jpg *.jpeg *.bmp *.webp"),("All files","*.*")])
        if not source:
            return
        base_name=self.profile_var.get() or next(iter(self.profiles))
        low_name=os.path.basename(source).lower()
        if 'inner' in low_name:
            for candidate in self.profiles:
                if 'inner' in candidate.lower():
                    base_name=candidate; break
        elif 'chassis' in low_name:
            for candidate in self.profiles:
                if 'chassis' in candidate.lower():
                    base_name=candidate; break
        base=self.profiles[base_name][1]
        try:
            # V1.9.8: identity is generated ONLY from imported Golden metadata.
            # Do not ask for / seed a model-dependent profile name here.
            path,profile=build_dynamic_profile(source,base)
            identity_errors=dynamic_identity_errors(profile,path)
            if identity_errors:
                raise RuntimeError('Imported Golden identity validation failed: ' + '; '.join(identity_errors))
            self._load_profiles()
            self.profile_combo['values']=list(self.profiles.keys())
            imported_key=''
            try:
                imported_resolved=Path(path).resolve()
                for key,(pp,_dd) in self.profiles.items():
                    if Path(pp).resolve() == imported_resolved:
                        imported_key=key; break
            except Exception:
                imported_key=''
            if not imported_key:
                imported_key=next((k for k,(_pp,dd) in self.profiles.items()
                                   if dd.get('profile_identity')==profile.get('profile_identity')), '')
            self.profile_var.set(imported_key or profile['profile_name'])
            self._apply_profile()
            log.info("GOLDEN_IMPORT profile=%s file=%s sha256=%s",profile['profile_name'],source,profile.get('golden_import',{}).get('source_sha256',''))
            messagebox.showinfo("Golden Imported",
                f"Draft profile created:\n{profile['profile_name']}\n{path.name}\n\n"
                f"Model: {profile.get('model','')}\nLabel Type: {profile.get('label_type','')}\nLabel P/N: {profile.get('label_pn','')}\n"
                f"Extracted fixed-text candidates: {len(profile.get('dynamic_fixed_texts',[]))}\n"
                f"Embedded images: {profile.get('golden_import',{}).get('embedded_image_count',0)}\n\n"
                "Please review the Summary / Checks tabs, then validate with known-good label photos before production use.")
            self._open_profile_manager()
        except Exception as exc:
            log.exception("GOLDEN_IMPORT_ERROR")
            messagebox.showerror("Import Golden",str(exc))

    def _open_profile_manager(self):
        name=self.profile_var.get()
        if not name or name not in self.profiles:
            messagebox.showinfo("Profile Manager","Select a profile first.")
            return
        path,data=self.profiles[name]
        working=json.loads(json.dumps(data))
        win=tk.Toplevel(self); win.title(f"Profile Manager - {name}"); win.geometry("1280x820")
        hdr=ttk.Frame(win,padding=8); hdr.pack(fill='x')
        status=str(working.get('profile_status','BUNDLED')).upper()
        title_var=tk.StringVar(value=f"Profile: {working.get('profile_name',name)} | Status: {status}")
        ttk.Label(hdr,textvariable=title_var,font=("Segoe UI",11,"bold")).pack(side='left')
        btns=ttk.Frame(hdr); btns.pack(side='right')

        nb=ttk.Notebook(win); nb.pack(fill='both',expand=True,padx=8,pady=(0,8))
        summary_tab=ttk.Frame(nb,padding=10); checks_tab=ttk.Frame(nb,padding=10); advanced_tab=ttk.Frame(nb,padding=6)
        nb.add(summary_tab,text='Summary / 摘要')
        nb.add(checks_tab,text='Inspection Items / 檢查項目')
        nb.add(advanced_tab,text='Advanced JSON / 工程設定')

        # ----- Summary -----
        summary_top=ttk.Frame(summary_tab); summary_top.pack(fill='x',pady=(0,6))
        ttk.Label(summary_top,text='Golden/Profile metadata. Dynamic profiles can be corrected here without editing Python.').pack(side='left')
        summary_holder=ttk.Frame(summary_tab); summary_holder.pack(fill='both',expand=True)
        summary=ttk.Treeview(summary_holder,columns=('field','value'),show='headings',height=18)
        summary.heading('field',text='Field'); summary.heading('value',text='Value')
        summary.column('field',width=230,anchor='w'); summary.column('value',width=880,anchor='w')
        sy=ttk.Scrollbar(summary_holder,orient='vertical',command=summary.yview); summary.configure(yscrollcommand=sy.set)
        summary.pack(side='left',fill='both',expand=True); sy.pack(side='right',fill='y')

        def refresh_summary():
            summary.delete(*summary.get_children())
            gi=working.get('golden_import',{}) or {}
            ff=working.get('fixed_fields',{}) or {}
            rows=[
                ('Profile Name',working.get('profile_name','')),('Internal Model',working.get('model','')),
                ('Customer Model / Alias',working.get('customer_model','')),('Model Aliases',', '.join(working.get('model_aliases',[]) or [])),
                ('Label Type',working.get('label_type','')),('Label P/N',working.get('label_pn','')),
                ('Profile Version',working.get('profile_version','')),('Status',working.get('profile_status','DRAFT')),
                ('Profile File',str(path)),('Golden Source',gi.get('source_file','')),('Golden SHA256',gi.get('source_sha256','')),
                ('Imported At',gi.get('imported_at','')),('Embedded Images',gi.get('embedded_image_count',0)),
                ('Golden image OCR chars',gi.get('image_ocr_text_length',0)),
                ('Inspection Items',len(_dynamic_item_rows(working))),
            ]
            id_errors=dynamic_identity_errors(working,path if pathlib.Path(path).stem==str((working.get('profile_identity') or {}).get('file_stem','')) else None)
            rows.append(('Identity Check','PASS' if not id_errors else 'REVIEW: ' + '; '.join(id_errors)))
            for k,v in rows: summary.insert('', 'end', values=(k,v))

        def edit_metadata():
            nonlocal path,working,name
            if not working.get('dynamic_profile'):
                messagebox.showinfo('Edit Metadata','Bundled engineering profiles are read-only. Import a Golden to create an editable Dynamic Profile.',parent=win); return
            d=tk.Toplevel(win); d.title('Edit Profile Metadata'); d.transient(win); d.grab_set(); d.resizable(False,False)
            frm=ttk.Frame(d,padding=12); frm.pack(fill='both',expand=True)
            fields=[
                ('Internal Model',tk.StringVar(value=working.get('model',''))),
                ('Customer Model / Alias',tk.StringVar(value=working.get('customer_model',''))),
                ('Label Type',tk.StringVar(value=working.get('label_type',''))),
                ('Label P/N',tk.StringVar(value=working.get('label_pn',''))),
            ]
            for r,(label,var) in enumerate(fields):
                ttk.Label(frm,text=label,width=24).grid(row=r,column=0,sticky='w',pady=4)
                ttk.Entry(frm,textvariable=var,width=48).grid(row=r,column=1,sticky='ew',pady=4)
            ttk.Label(frm,text='Example: Internal Model = GRG-4355u; Customer Model = PRT-7302',foreground='#666').grid(row=len(fields),column=0,columnspan=2,sticky='w',pady=(8,4))
            def save_meta():
                nonlocal path,working,name
                try:
                    new_path,new_data=save_profile_identity_edits(pathlib.Path(path),working,fields[0][1].get(),fields[2][1].get(),fields[3][1].get(),fields[1][1].get())
                    path,working=new_path,new_data; name=working['profile_name']
                    title_var.set(f"Profile: {working['profile_name']} | Status: DRAFT")
                    refresh_summary(); refresh_checks(); refresh_json(); d.destroy()
                except Exception as exc: messagebox.showerror('Edit Metadata',str(exc),parent=d)
            b=ttk.Frame(frm); b.grid(row=len(fields)+1,column=0,columnspan=2,sticky='e',pady=(10,0))
            ttk.Button(b,text='Save',command=save_meta).pack(side='left',padx=4); ttk.Button(b,text='Cancel',command=d.destroy).pack(side='left')
        ttk.Button(summary_top,text='Edit Metadata / 修改基本資料',command=edit_metadata).pack(side='right')

        # ----- Visual Inspection Item Editor -----
        toolbar=ttk.Frame(checks_tab); toolbar.pack(fill='x',pady=(0,6))
        ttk.Label(toolbar,text='Golden items are listed first. Standard checks are added only when needed through Add Item > Standard Library. Unknown Golden items remain visible as Needs Review.').pack(side='left')
        checks_holder=ttk.Frame(checks_tab); checks_holder.pack(fill='both',expand=True)
        cols=('item','type','role','required','threshold','expected','origin')
        checks=ttk.Treeview(checks_holder,columns=cols,show='headings',selectmode='browse')
        specs=[('item','Inspection Item',360),('type','Type',105),('role','Role',100),('required','Required',75),('threshold','Threshold',80),('expected','Expected / Golden Text',330),('origin','Source',100)]
        for c,t,w in specs: checks.heading(c,text=t); checks.column(c,width=w,anchor='w')
        cy=ttk.Scrollbar(checks_holder,orient='vertical',command=checks.yview); cx=ttk.Scrollbar(checks_holder,orient='horizontal',command=checks.xview)
        checks.configure(yscrollcommand=cy.set,xscrollcommand=cx.set)
        checks.grid(row=0,column=0,sticky='nsew'); cy.grid(row=0,column=1,sticky='ns'); cx.grid(row=1,column=0,sticky='ew')
        checks_holder.rowconfigure(0,weight=1); checks_holder.columnconfigure(0,weight=1)
        editable_rows=_dynamic_item_rows(working)

        def refresh_checks():
            nonlocal editable_rows
            checks.delete(*checks.get_children())
            editable_rows=_dynamic_item_rows(working)
            for idx,row in enumerate(editable_rows):
                checks.insert('', 'end', iid=str(idx), values=(row.get('item',''),row.get('type',''),row.get('role',''),
                    'Yes' if row.get('required') else 'No',row.get('threshold',''),row.get('expected',''),row.get('source',row.get('origin',''))))

        def item_editor(row=None,index=None):
            nonlocal editable_rows,working
            row=dict(row or {'item':'','type':'Golden Text','role':'DETAIL','required':True,'threshold':0.74,'expected':'','origin':'MANUAL'})
            d=tk.Toplevel(win); d.title('Edit Inspection Item' if index is not None else 'Add Inspection Item'); d.transient(win); d.grab_set(); d.resizable(False,False)
            f=ttk.Frame(d,padding=12); f.pack(fill='both',expand=True)
            item_v=tk.StringVar(value=row.get('item','')); type_v=tk.StringVar(value=row.get('type','Golden Text')); role_v=tk.StringVar(value=row.get('role','DETAIL'))
            req_v=tk.BooleanVar(value=bool(row.get('required',True))); thr_v=tk.StringVar(value=str(row.get('threshold',''))); exp_v=tk.StringVar(value=row.get('expected',''))
            ttk.Label(f,text='Inspection Item').grid(row=0,column=0,sticky='w',pady=4); ttk.Entry(f,textvariable=item_v,width=66).grid(row=0,column=1,sticky='ew',pady=4)
            ttk.Label(f,text='Type').grid(row=1,column=0,sticky='w',pady=4); ttk.Combobox(f,textvariable=type_v,values=['Standard','Golden Text','Golden Variable','Golden Barcode','Golden QR','Golden Artwork','Golden Choice','Needs Review'],state='readonly',width=22).grid(row=1,column=1,sticky='w',pady=4)
            ttk.Label(f,text='Photo Role').grid(row=2,column=0,sticky='w',pady=4); ttk.Combobox(f,textvariable=role_v,values=['BASIC','WIFI','IDENTITY','COMPLIANCE','DETAIL'],state='readonly',width=22).grid(row=2,column=1,sticky='w',pady=4)
            ttk.Label(f,text='Required').grid(row=3,column=0,sticky='w',pady=4); ttk.Checkbutton(f,variable=req_v).grid(row=3,column=1,sticky='w',pady=4)
            ttk.Label(f,text='Threshold').grid(row=4,column=0,sticky='w',pady=4); ttk.Entry(f,textvariable=thr_v,width=18).grid(row=4,column=1,sticky='w',pady=4)
            ttk.Label(f,text='Expected / Golden Text').grid(row=5,column=0,sticky='nw',pady=4); ttk.Entry(f,textvariable=exp_v,width=66).grid(row=5,column=1,sticky='ew',pady=4)
            ttk.Label(f,text="For 'Golden Text', Expected is required. Standard item names should use existing engine item names.",foreground='#666').grid(row=6,column=0,columnspan=2,sticky='w',pady=(8,4))
            def accept():
                nonlocal editable_rows,working
                item=item_v.get().strip(); typ=type_v.get().strip(); expected=exp_v.get().strip()
                if not item: messagebox.showerror('Inspection Item','Inspection Item cannot be blank.',parent=d); return
                if typ=='Golden Text' and not expected: messagebox.showerror('Inspection Item','Golden Text requires Expected text.',parent=d); return
                threshold=thr_v.get().strip()
                if typ=='Golden Text':
                    try:
                        tv=float(threshold or 0.74)
                        if not 0 < tv <= 1: raise ValueError
                        threshold=tv
                    except Exception:
                        messagebox.showerror('Inspection Item','Threshold must be between 0 and 1.',parent=d); return
                is_golden=(str(row.get('source','')).lower()=='golden' or str(row.get('origin',''))=='GOLDEN' or item.startswith('Golden #'))
                newrow=dict(row)
                newrow.update({'item':item,'type':typ,'role':role_v.get().strip() or 'DETAIL','required':req_v.get(),
                        'threshold':threshold,'expected':expected,'origin':'GOLDEN' if is_golden else 'MANUAL_EDIT',
                        'source':'Golden' if is_golden else 'Manual',
                        'manual_review_allowed':typ in ('Golden Text','Golden Artwork','Golden Choice','Needs Review')})
                rows=list(editable_rows)
                if index is None: rows.append(newrow)
                else: rows[index]=newrow
                working=apply_editable_items(working,rows)
                refresh_checks(); refresh_summary(); refresh_json(); title_var.set(f"Profile: {working.get('profile_name',name)} | Status: DRAFT")
                d.destroy()
            bf=ttk.Frame(f); bf.grid(row=7,column=0,columnspan=2,sticky='e',pady=(10,0))
            ttk.Button(bf,text='Apply',command=accept).pack(side='left',padx=4); ttk.Button(bf,text='Cancel',command=d.destroy).pack(side='left')

        def add_standard_library():
            nonlocal editable_rows,working
            d=tk.Toplevel(win); d.title('Add from Standard Library'); d.transient(win); d.grab_set(); d.geometry('760x560')
            f=ttk.Frame(d,padding=10); f.pack(fill='both',expand=True)
            ttk.Label(f,text='Select existing Legacy CAM / Image checks to add. These checks use the already validated engine logic.').pack(anchor='w',pady=(0,6))
            lb=tk.Listbox(f,selectmode='extended',font=('Segoe UI',10)); lb.pack(fill='both',expand=True)
            for row in STANDARD_LIBRARY:
                lb.insert('end',f"{row['label']}   [{row['item']}]")
            def add_selected():
                nonlocal editable_rows,working
                sels=list(lb.curselection())
                if not sels: return
                rows=list(editable_rows); existing={r.get('item') for r in rows}
                for i in sels:
                    lib=STANDARD_LIBRARY[i]
                    if lib['item'] in existing: continue
                    rows.append({'item':lib['item'],'type':'Standard','role':lib['role'],'required':True,'threshold':'','expected':'',
                                 'origin':'STANDARD_LIBRARY','source':'Standard Library','manual_review_allowed':False})
                working=apply_editable_items(working,rows); refresh_checks(); refresh_summary(); refresh_json();
                title_var.set(f"Profile: {working.get('profile_name',name)} | Status: DRAFT"); d.destroy()
            b=ttk.Frame(f); b.pack(fill='x',pady=(8,0))
            ttk.Button(b,text='Add Selected',command=add_selected).pack(side='right',padx=4)
            ttk.Button(b,text='Cancel',command=d.destroy).pack(side='right')

        def add_item():
            d=tk.Toplevel(win); d.title('Add Inspection Item'); d.transient(win); d.grab_set(); d.resizable(False,False)
            f=ttk.Frame(d,padding=14); f.pack(fill='both',expand=True)
            ttk.Label(f,text='Choose how to add the inspection item:',font=('Segoe UI',10,'bold')).pack(anchor='w',pady=(0,10))
            ttk.Button(f,text='From Standard Library / 既有檢查項目',width=42,command=lambda:(d.destroy(),add_standard_library())).pack(fill='x',pady=4)
            ttk.Button(f,text='Custom Item / 自訂項目',width=42,command=lambda:(d.destroy(),item_editor())).pack(fill='x',pady=4)
            ttk.Button(f,text='Cancel',command=d.destroy).pack(pady=(10,0))
        def edit_item():
            sel=checks.selection()
            if not sel: messagebox.showinfo('Edit Item','Select an inspection item first.',parent=win); return
            idx=int(sel[0]); item_editor(editable_rows[idx],idx)
        def delete_item():
            nonlocal editable_rows,working
            sel=checks.selection()
            if not sel: return
            idx=int(sel[0]); row=editable_rows[idx]
            if not messagebox.askyesno('Delete Item',f"Delete this inspection item?\n\n{row.get('item','')}",parent=win): return
            rows=[r for i,r in enumerate(editable_rows) if i!=idx]
            working=apply_editable_items(working,rows); refresh_checks(); refresh_summary(); refresh_json(); title_var.set(f"Profile: {working.get('profile_name',name)} | Status: DRAFT")
        ttk.Button(toolbar,text='Add Item',command=add_item).pack(side='right',padx=3)
        ttk.Button(toolbar,text='Edit Selected',command=edit_item).pack(side='right',padx=3)
        ttk.Button(toolbar,text='Delete Selected',command=delete_item).pack(side='right',padx=3)
        checks.bind('<Double-1>',lambda e: edit_item())

        # ----- Advanced JSON -----
        text=tk.Text(advanced_tab,wrap='none',font=('Consolas',9),undo=True)
        y=ttk.Scrollbar(advanced_tab,orient='vertical',command=text.yview); x=ttk.Scrollbar(advanced_tab,orient='horizontal',command=text.xview)
        text.configure(yscrollcommand=y.set,xscrollcommand=x.set)
        text.grid(row=0,column=0,sticky='nsew'); y.grid(row=0,column=1,sticky='ns'); x.grid(row=1,column=0,sticky='ew')
        advanced_tab.rowconfigure(0,weight=1); advanced_tab.columnconfigure(0,weight=1)
        ttk.Label(advanced_tab,text='Advanced engineering settings. Normal Golden setup should use Summary + Inspection Items.',foreground='#666').grid(row=2,column=0,sticky='w',pady=(4,0))
        def refresh_json():
            text.delete('1.0','end'); text.insert('1.0',json.dumps(working,ensure_ascii=False,indent=2))

        def save_working(close_after=False):
            nonlocal working,path,name
            try:
                # Advanced JSON is authoritative only if that tab is selected.
                if nb.select()==str(advanced_tab):
                    working=json.loads(text.get('1.0','end-1c'))
                working['profile_version']='1.9.8'
                working['profile_status']='DRAFT'
                errs=validate_profile_structure(working,pathlib.Path(path))
                if errs:
                    messagebox.showerror('Profile Validation','Cannot save Profile:\n- ' + '\n- '.join(errs),parent=win); return False
                pathlib.Path(path).write_text(json.dumps(working,ensure_ascii=False,indent=2),encoding='utf-8')
                self._load_profiles(); self.profile_combo['values']=list(self.profiles.keys())
                name=working.get('profile_name',name); self.profile_var.set(name); self._apply_profile()
                log.info('PROFILE_EDIT_SAVE profile=%s file=%s items=%s',name,path,len(_dynamic_item_rows(working)))
                if close_after: win.destroy()
                else: messagebox.showinfo('Profile Manager','Draft Profile saved. Validate only after known-good/known-NG label tests.',parent=win)
                return True
            except Exception as exc:
                messagebox.showerror('Profile Manager',str(exc),parent=win); return False

        def save_advanced():
            try:
                nonlocal working
                working=json.loads(text.get('1.0','end-1c'))
                working['profile_status']='DRAFT'; refresh_checks(); refresh_summary()
                save_working(False)
            except Exception as exc: messagebox.showerror('Profile Manager',str(exc),parent=win)

        ttk.Button(btns,text='Save Draft / 儲存草稿',command=lambda:save_working(False)).pack(side='left',padx=3)
        ttk.Button(btns,text='Save Advanced JSON',command=save_advanced).pack(side='left',padx=3)
        ttk.Button(btns,text='Close',command=win.destroy).pack(side='left',padx=3)
        refresh_summary(); refresh_checks(); refresh_json()

    def _validate_current_profile(self):
        name=self.profile_var.get()
        if not name or name not in self.profiles:
            messagebox.showinfo("Validate Profile","Select a profile first.")
            return
        path,data=self.profiles[name]
        errors=validate_profile_structure(data,path) + validation_readiness_errors(data)
        if errors:
            messagebox.showerror("Validate Profile","Profile cannot be validated:\n- " + "\n- ".join(errors))
            return
        if not data.get('dynamic_profile'):
            messagebox.showinfo("Validate Profile","This is a bundled engineering profile. No status change is required.")
            return
        if not messagebox.askyesno("Validate Profile",
            "Structural checks passed.\n\nMark this Golden Profile as VALIDATED?\n"
            "Only do this after checking the extracted items / thresholds and testing known-good label photos."):
            return
        try:
            updated=mark_validated(path,data)
            self._load_profiles(); self.profile_combo['values']=list(self.profiles.keys())
            self.profile_var.set(updated['profile_name']); self._apply_profile()
            log.info("PROFILE_VALIDATED profile=%s file=%s",updated['profile_name'],path)
            messagebox.showinfo("Validate Profile","Profile status = VALIDATED")
        except Exception as exc:
            messagebox.showerror("Validate Profile",str(exc))

    def _load_profiles(self):
        self.profiles={}
        for name,path,data in discover_profiles():
            errs=dynamic_identity_errors(data,path)
            if data.get('dynamic_profile') and errs:
                log.warning('PROFILE_SKIPPED_INVALID_IDENTITY file=%s errors=%s',path,'; '.join(errs))
                continue
            self.profiles[name]=(path,data)

    def _build_ui(self):
        prof = ttk.LabelFrame(self, text="Golden Profile", padding=8)
        prof.pack(fill="x", padx=8, pady=(8,4))
        ttk.Label(prof, text="Profile:").grid(row=0,column=0,sticky="w")
        self.profile_combo = ttk.Combobox(prof, textvariable=self.profile_var, state="readonly", width=38, values=list(self.profiles.keys()))
        self.profile_combo.grid(row=0,column=1,padx=5,sticky="w")
        self.profile_combo.bind("<<ComboboxSelected>>", lambda e:self._apply_profile())
        ttk.Button(prof,text="Reload Profiles",command=self._reload_profiles).grid(row=0,column=2,padx=5)
        ttk.Button(prof,text="Import Golden",command=self._import_golden_profile).grid(row=0,column=3,padx=5)
        ttk.Button(prof,text="Profile Manager",command=self._open_profile_manager).grid(row=0,column=4,padx=5)
        ttk.Button(prof,text="Validate Profile",command=self._validate_current_profile).grid(row=0,column=5,padx=5)
        ttk.Label(prof,textvariable=self.profile_info_var).grid(row=1,column=0,columnspan=8,sticky="w",pady=(5,0))

        wo = ttk.LabelFrame(self, text="Optional Work Order Data", padding=8)
        wo.pack(fill="x", padx=8, pady=(0,4))
        ttk.Label(wo,text="P/N").grid(row=0,column=0,sticky="w")
        ttk.Entry(wo,textvariable=self.expected_pn,width=22).grid(row=0,column=1,padx=(5,20))
        ttk.Label(wo,text="Made in").grid(row=0,column=2,sticky="w")
        ttk.Combobox(wo,textvariable=self.expected_country,width=16,values=["","China","Taiwan"]).grid(row=0,column=3,padx=5)

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=8, pady=4)
        self.live_tab = ttk.Frame(nb)
        self.image_tab = ttk.Frame(nb)
        nb.add(self.live_tab, text="Live Camera / Smart Lock")
        nb.add(self.image_tab, text="Image Label Inspection")
        self._build_live_tab()
        self._build_image_tab()

        bottom = ttk.Frame(self,padding=8); bottom.pack(fill="x")
        ttk.Label(bottom,textvariable=self.status_var).pack(side="left")
        ttk.Label(bottom,text=f"Execution Log: {self.execution_log}").pack(side="right")

    def _build_live_tab(self):
        ctl = ttk.Frame(self.live_tab,padding=8); ctl.pack(fill="x")
        ttk.Label(ctl,text="Camera:").pack(side="left")
        self.camera_combo = ttk.Combobox(ctl,textvariable=self.camera_var,state="readonly",width=18)
        self.camera_combo.pack(side="left",padx=5)
        ttk.Button(ctl,text="Scan Cameras",command=self.scan_cameras).pack(side="left",padx=3)
        self.camera_btn = ttk.Button(ctl,text="Start Camera",command=self.toggle_camera); self.camera_btn.pack(side="left",padx=3)
        ttk.Button(ctl,text="Auto Focus",command=self.autofocus).pack(side="left",padx=3)
        self.live_btn = ttk.Button(ctl,text="Start Live Scan",command=self.toggle_live); self.live_btn.pack(side="left",padx=12)
        ttk.Button(ctl,text="New Unit / Reset Locks",command=self.new_unit).pack(side="left",padx=3)
        ttk.Button(ctl,text="Unlock Selected",command=self.unlock_selected).pack(side="left",padx=3)
        ttk.Label(ctl,textvariable=self.live_state_var,font=("Segoe UI",10,"bold")).pack(side="right",padx=8)

        scan = ttk.LabelFrame(self.live_tab,text="HID Barcode Scanner (scan then Enter)",padding=6)
        scan.pack(fill="x",padx=8,pady=(0,4))
        ent = ttk.Entry(scan,textvariable=self.scanner_var,width=90)
        ent.pack(side="left",fill="x",expand=True)
        ent.bind("<Return>",self.on_scanner_enter)
        self.scanner_entry = ent
        ttk.Label(scan,text="Priority: HID Scanner > Full-frame Barcode/QR > OCR").pack(side="right",padx=8)
        ttk.Label(scan,textvariable=self.machine_state_var,font=("Segoe UI",10,"bold")).pack(side="right",padx=12)
        ttk.Button(scan,text="Retry OCR Engine",command=self.retry_ocr_runtime).pack(side="right",padx=5)
        ttk.Label(scan,textvariable=self.ocr_runtime_var,font=("Segoe UI",10,"bold")).pack(side="right",padx=8)
        self.ocr_mode_combo=ttk.Combobox(scan,textvariable=self.ocr_mode_var,state="readonly",width=20,values=["Production 4-Zone","Manual Item Debug"])
        self.ocr_mode_combo.pack(side="right",padx=8)
        self.ocr_mode_combo.bind("<<ComboboxSelected>>",lambda e:self._on_ocr_mode_change())
        ttk.Label(scan,text="OCR Mode:").pack(side="right")

        # V1.6.2: Camera Preview Priority Layout.
        # Keep the Camera pane in the expandable main area.  Zone guidance is
        # placed in the RIGHT pane so it can never consume the Camera's height.
        main = ttk.Panedwindow(self.live_tab,orient="horizontal")
        main.pack(fill="both",expand=True,padx=8,pady=4)
        left = ttk.Frame(main)
        right = ttk.Frame(main)
        main.add(left,weight=4)
        main.add(right,weight=6)

        zone = ttk.LabelFrame(right,text="Production Zone OCR / Manual Item Debug",padding=6)
        zone.pack(fill="x",padx=2,pady=(2,4))
        ttk.Label(zone,textvariable=self.zone_title_var,font=("Segoe UI",13,"bold")).grid(row=0,column=0,columnspan=4,sticky="w")
        ttk.Label(zone,textvariable=self.zone_instruction_var,font=("Segoe UI",9),wraplength=880).grid(row=1,column=0,columnspan=4,sticky="w",pady=(2,3))
        ttk.Label(zone,textvariable=self.zone_progress_var,font=("Segoe UI",10,"bold")).grid(row=2,column=0,sticky="w")
        ttk.Label(zone,textvariable=self.zone_items_var,font=("Consolas",9,"bold"),wraplength=880).grid(row=3,column=0,columnspan=4,sticky="w",pady=(3,0))
        self.guided_expected_label=ttk.Label(zone,textvariable=self.guided_expected_var,font=("Segoe UI",9,"bold"))
        self.guided_expected_label.grid(row=4,column=0,columnspan=4,sticky="w",pady=(1,0))
        self.guided_ocr_label=ttk.Label(zone,textvariable=self.guided_ocr_var,font=("Consolas",9),wraplength=880)
        self.guided_ocr_label.grid(row=5,column=0,columnspan=4,sticky="w")
        self.guided_quality_label=ttk.Label(zone,textvariable=self.guided_quality_var,font=("Segoe UI",9))
        self.guided_quality_label.grid(row=6,column=0,columnspan=4,sticky="w")
        ttk.Button(zone,text="Previous Zone",command=self.previous_guided_item).grid(row=2,column=1,padx=4)
        ttk.Button(zone,text="Retry Zone",command=self.retry_guided_item).grid(row=2,column=2,padx=4)
        ttk.Button(zone,text="Next Zone",command=self.next_guided_item).grid(row=2,column=3,padx=4)
        zone.columnconfigure(0,weight=1)
        self.camera_frame=ttk.LabelFrame(left,text="Live Camera - Full Frame 16:9",padding=4)
        self.camera_frame.pack(fill="both",expand=True,padx=4,pady=(4,2))
        self.live_preview=tk.Label(self.camera_frame,anchor="center",bg="black",fg="white",text="Camera stopped")
        self.live_preview.pack(fill="both",expand=True)
        self.ocr_zoom_frame=ttk.LabelFrame(left,text="OCR Target Zoom - Manual Item Debug only",padding=4)
        self.ocr_zoom_label=tk.Label(self.ocr_zoom_frame,text="OCR target preview",bg="black",fg="white",height=4,anchor="center")
        self.ocr_zoom_label.pack(fill="both",expand=True)
        self.preview_geometry_var=tk.StringVar(value="Preview: waiting for camera")
        self.preview_geometry_label=ttk.Label(left,textvariable=self.preview_geometry_var,font=("Segoe UI",9))
        self.preview_geometry_label.pack(fill="x",padx=6,pady=(0,2))
        self.progress_label=ttk.Label(left,textvariable=self.progress_var,font=("Segoe UI",13,"bold"))
        self.progress_label.pack(fill="x",pady=(2,4))
        self._sync_live_layout_for_mode()

        cols=("item","value","rule","state","message")
        self.live_tree=ttk.Treeview(right,columns=cols,show="headings",height=30)
        widths={"item":320,"value":260,"rule":270,"state":130,"message":300}
        for c in cols:
            self.live_tree.heading(c,text=c.title()); self.live_tree.column(c,width=widths[c],anchor="w")
        self.live_tree.pack(fill="both",expand=True)
        for tag,color in [("LOCK","#e8f5e9"),("VERIFY","#e3f2fd"),("SCANNING","#fff8e1"),("CONFIRMED_FAIL","#ffebee"),("VERIFY_FAIL","#fff3e0"),("RESOURCE_ERROR","#ffcdd2")]:
            self.live_tree.tag_configure(tag,background=color)

    def _build_image_tab(self):
        top=ttk.Frame(self.image_tab,padding=8); top.pack(fill="x")
        ttk.Label(top,text="Images:").grid(row=0,column=0,sticky="w")
        ttk.Entry(top,textvariable=self.image_path,width=80,state="readonly").grid(row=0,column=1,padx=5,sticky="ew")
        self.image_load_btn=ttk.Button(top,text="Load Images...",command=self.select_images); self.image_load_btn.grid(row=0,column=2,padx=4)
        self.image_add_btn=ttk.Button(top,text="Add Images",command=self.add_images); self.image_add_btn.grid(row=0,column=3,padx=4)
        self.image_run_btn=ttk.Button(top,text="Run / Analyze New",command=self.inspect_images); self.image_run_btn.grid(row=0,column=4,padx=4)
        self.image_recheck_btn=ttk.Button(top,text="Recheck Unresolved",command=self.recheck_unresolved); self.image_recheck_btn.grid(row=0,column=5,padx=4)
        self.image_force_btn=ttk.Button(top,text="Force Re-analyze All",command=self.force_reanalyze_images); self.image_force_btn.grid(row=0,column=6,padx=4)
        self.image_reset_btn=ttk.Button(top,text="Reset Session",command=self.reset_image_session); self.image_reset_btn.grid(row=0,column=7,padx=4)
        self.image_cancel_btn=ttk.Button(top,text="Cancel",command=self.cancel_image_inspection,state="disabled"); self.image_cancel_btn.grid(row=0,column=8,padx=4)
        ttk.Label(top,textvariable=self.image_batch_var,font=("Segoe UI",10,"bold")).grid(row=1,column=0,columnspan=9,sticky="w",pady=(5,0))
        ttk.Label(top,textvariable=self.image_progress_var).grid(row=2,column=0,columnspan=9,sticky="w",pady=(2,0))
        ttk.Label(top,text="V1.9.8 Dynamic Golden + operator-attention workflow: every non-PASS item is reviewable; Legacy CAM/Image auto decisions remain protected.",foreground="#555555").grid(row=3,column=0,columnspan=9,sticky="w",pady=(2,0))
        top.columnconfigure(1,weight=1)
        main=ttk.Panedwindow(self.image_tab,orient="horizontal"); main.pack(fill="both",expand=True,padx=8,pady=4)
        left=ttk.Frame(main); right=ttk.Frame(main); main.add(left,weight=3); main.add(right,weight=5)
        self.image_preview=ttk.Label(left,anchor="center",relief="sunken",text="Load one or more label photos"); self.image_preview.pack(fill="both",expand=True)
        self.image_overall=tk.Label(right,text="--",font=("Segoe UI",26,"bold")); self.image_overall.pack(fill="x")

        # V1.8.1 UI: keep Manual Review above the expandable result table.
        # On shorter screens the old layout let the Treeview consume the
        # available height first, pushing the review controls below the visible
        # area.  Packing this fixed-height operator panel first guarantees that
        # PASS/refresh controls remain reachable at all supported resolutions.
        manual=ttk.LabelFrame(right,text="Manual Review / 人工目檢輔助",padding=6)
        manual.pack(fill="x",pady=(2,6))
        ttk.Label(manual,text="All non-PASS items are listed here. Visual/Golden items can be manually overridden after Golden comparison; identity/barcode/consistency items are REVIEW-ONLY and remain traceable.",wraplength=980).grid(row=0,column=0,columnspan=5,sticky="w")
        list_frame=ttk.Frame(manual)
        list_frame.grid(row=1,column=0,columnspan=5,sticky="ew",pady=4)
        self.image_manual_list=tk.Listbox(list_frame,selectmode="browse",height=4,exportselection=False)
        manual_scroll=ttk.Scrollbar(list_frame,orient="vertical",command=self.image_manual_list.yview)
        self.image_manual_list.configure(yscrollcommand=manual_scroll.set)
        self.image_manual_list.pack(side="left",fill="x",expand=True)
        manual_scroll.pack(side="right",fill="y")
        ttk.Label(manual,text="Note:").grid(row=2,column=0,sticky="w")
        ttk.Entry(manual,textvariable=self.image_manual_note_var,width=44).grid(row=2,column=1,sticky="ew",padx=4)
        self.image_manual_pass_btn=ttk.Button(manual,text="Review with Golden / Golden對照復判",command=self.manual_review_selected,state="disabled")
        self.image_manual_pass_btn.grid(row=2,column=2,padx=4)
        self.image_manual_refresh_btn=ttk.Button(manual,text="Refresh Review List",command=self._refresh_manual_review_list,state="disabled")
        self.image_manual_refresh_btn.grid(row=2,column=3,padx=4)
        ttk.Label(manual,text="All review actions are logged",foreground="#555555").grid(row=2,column=4,sticky="e",padx=(8,0))
        manual.columnconfigure(1,weight=1)
        list_frame.columnconfigure(0,weight=1)

        results=ttk.Frame(right)
        results.pack(fill="both",expand=True)
        cols=("item","result","actual","expected","source","quality","message")
        self.image_tree=ttk.Treeview(results,columns=cols,show="headings",height=18)
        widths={"item":270,"result":120,"actual":190,"expected":210,"source":190,"quality":90,"message":320}
        for c in cols:
            self.image_tree.heading(c,text=c.title()); self.image_tree.column(c,width=widths[c],anchor="w")
        tree_y=ttk.Scrollbar(results,orient="vertical",command=self.image_tree.yview)
        tree_x=ttk.Scrollbar(results,orient="horizontal",command=self.image_tree.xview)
        self.image_tree.configure(yscrollcommand=tree_y.set,xscrollcommand=tree_x.set)
        self.image_tree.grid(row=0,column=0,sticky="nsew")
        tree_y.grid(row=0,column=1,sticky="ns")
        tree_x.grid(row=1,column=0,sticky="ew")
        results.rowconfigure(0,weight=1); results.columnconfigure(0,weight=1)

    def _reload_profiles(self):
        cur=self.profile_var.get(); self._load_profiles(); self.profile_combo['values']=list(self.profiles.keys())
        if cur in self.profiles:self.profile_var.set(cur)
        elif self.profiles:self.profile_var.set(next(iter(self.profiles)))
        self._apply_profile()

    def _apply_profile(self):
        name=self.profile_var.get()
        if not name or name not in self.profiles:return
        path,data=self.profiles[name]
        previous_identity=getattr(self,'_active_profile_identity','')
        new_identity=f"{path.resolve()}|{(data.get('golden_import') or {}).get('source_sha256','')}|{data.get('profile_version','')}"
        profile_changed=bool(previous_identity and previous_identity != new_identity)
        self._active_profile_identity=new_identity
        self.engine=InspectionEngine(data)
        self.multi_image_engine=MultiImageInspectionEngine(data, software_version=__version__)
        self.live_analyzer=LiveFrameAnalyzer(data)
        self.fast_reader=FastMachineReader(data)
        self.guided_ocr=DirectGuidedOCR(data, ocr_backend=self.ocr_service)
        self.zone_ocr=MultiFieldZoneOCR(data, ocr_backend=self.ocr_service)
        self.production_scheduler=ProductionZoneScheduler.from_profile(data)
        live_cfg=data.get('live',{})
        required=list(live_cfg.get('required_items',[]))
        self.locks=SmartLockEngine(required, int(live_cfg.get('pass_confirmations',2)), int(live_cfg.get('fail_confirmations',3)), float(live_cfg.get('candidate_ttl_sec',12)))
        self.identity_guard=IdentityGuard(int(live_cfg.get('identity_switch_confirmations',3)))
        self.zone_scheduler=None
        self.guided_scheduler=GuidedItemScheduler(targets_from_profile(data))
        self.zone_stats={}
        self.report_expected={}
        self.profile_info_var.set(
            f"Model: {data.get('model','')} | Label Type: {data.get('label_type','Chassis Label')} | "
            f"Label P/N: {data.get('label_pn','')} | Spec: {data.get('spec_version','')} | "
            f"Profile Ver: {data.get('profile_version','')} | Status: {data.get('profile_status','BUNDLED')} | File: {path.name}"
        )
        self._reset_live_tree()
        self._update_zone_ui()
        art_status=self.zone_ocr.artwork.resource_status()
        log.info('ARTWORK_RESOURCE_STATUS profile=%s status=%s',name,art_status)
        log.info('PROFILE_LOADED name=%s file=%s',name,path)
        if profile_changed:
            self._invalidate_image_result_after_profile_change(name)

    def _invalidate_image_result_after_profile_change(self, profile_name: str):
        """Never show/use evidence produced under a previously loaded Golden.

        Loaded photos may stay selected for convenience, but cached evidence,
        overall result and manual-review candidates are invalidated and must be
        re-analyzed under the newly selected Profile.
        """
        self.multi_image_result=None
        try:self._manual_review_items=[]; self._manual_review_modes=[]
        except Exception:pass
        if hasattr(self,'image_tree'):
            try:
                for x in self.image_tree.get_children(): self.image_tree.delete(x)
                self.image_overall.config(text='--',fg='black')
                self.image_manual_list.delete(0,'end')
                self.image_manual_pass_btn.config(state='disabled')
                self.image_manual_refresh_btn.config(state='disabled')
                n=len(getattr(self,'image_paths',[]) or [])
                self.image_batch_var.set(f"Profile changed to {profile_name} | previous evidence cleared | {n} image(s) may be re-analyzed")
                self.image_progress_var.set('Profile/Golden changed. Run / Analyze New before using results or Manual Review.')
            except Exception:pass
        log.info('IMAGE_SESSION_INVALIDATED profile=%s reason=PROFILE_OR_GOLDEN_CHANGED',profile_name)

    def _build_worker_snapshot(self, target):
        """MAIN THREAD ONLY: copy every worker input away from Tk/Tcl state."""
        expected_snapshot = dict(self._expected())
        known_snapshot = dict(self._locked_known_fields())
        known_snapshot["_required_items"] = list(self.locks.required_items)
        target_snapshot = {
            "item": str(target.item),
            "title": str(target.title),
            "instruction": str(target.instruction),
            "target_rect": tuple(float(v) for v in target.target_rect),
            "mode": str(target.mode),
            "expected": str(target.expected),
            "threshold": float(target.threshold),
        }
        return expected_snapshot, known_snapshot, target_snapshot

    def _expected(self):
        d={}
        if self.expected_pn.get().strip():d['pn']=self.expected_pn.get().strip()
        if self.expected_country.get().strip():d['made_in']=self.expected_country.get().strip()
        return d

    def _effective_required_items(self):
        items=list(self.engine.profile.get('live',{}).get('required_items',[]))
        if self.expected_pn.get().strip(): items.append('Work Order: P/N')
        if self.expected_country.get().strip(): items.append('Work Order: Made in')
        return items

    def _reset_live_tree(self):
        if not hasattr(self,'live_tree') or self.locks is None:return
        required=self._effective_required_items()
        self.locks.reset(required)
        self.identity_guard.reset()
        if self.guided_scheduler: self.guided_scheduler.reset()
        if self.production_scheduler: self.production_scheduler.reset()
        self.zone_stats={}
        self.report_expected={}
        for x in self.live_tree.get_children():self.live_tree.delete(x)
        for name in required:
            self.live_tree.insert('', 'end', iid=name, values=(name,'','', 'SCANNING',''), tags=('SCANNING',))
        self.progress_var.set(f"0 / {len(required)} LOCKED")
        self.auto_saved=False; self.new_unit_prompted=False

    def scan_cameras(self):
        self.status_var.set('Scanning cameras...'); self.update_idletasks()
        found=self.camera.scan(6)
        values=[f"Camera {i}" for i in found]
        self.camera_combo['values']=values
        if values:self.camera_var.set(values[0])
        self.status_var.set(f"Found {len(values)} camera(s)")

    def toggle_camera(self):
        if self.camera.cap is not None:
            self.stop_live(); self.camera.close(); self.camera_btn.config(text='Start Camera'); self.live_preview.config(image='',text='Camera stopped'); return
        if not self.camera_var.get():
            self.scan_cameras()
        if not self.camera_var.get():
            messagebox.showwarning('Camera','No camera found'); return
        idx=int(self.camera_var.get().split()[-1])
        cfg=self.engine.profile.get('live',{})
        if not self.camera.open(idx,int(cfg.get('camera_width',1920)),int(cfg.get('camera_height',1080))):
            messagebox.showerror('Camera','Unable to open camera'); return
        self.camera_btn.config(text='Stop Camera')
        log.info('CAMERA_OPEN index=%s backend=%s',idx,self.camera.backend_name)
        self._update_preview()


    def _target_state(self):
        if self.locks is None:
            return "SEARCHING"
        if self._production_mode():
            zone=self._current_production_zone()
            if zone is None:
                return "LOCKED"
            items=self.production_scheduler.effective_items(zone,self.locks)
            if items and all(self.locks.is_locked(x) for x in items):
                return "LOCKED"
            if any(x in self.locks.fields and self.locks.fields[x].state=="VERIFY" for x in items):
                return "DETECTED"
            return "SEARCHING"
        target=self._current_guided_target()
        if target is None:return "LOCKED"
        if target.item in self.locks.fields:
            state=self.locks.fields[target.item].state
            if state=="LOCK":return "LOCKED"
            if state=="VERIFY":return "DETECTED"
        return "SEARCHING"

    def _draw_target_overlay(self, display):
        rect,title=self._active_scan()
        if rect is None or display is None:return display

        # V1.7.4: Artwork guide is activated ONLY for a production zone that
        # actually contains Artwork items. Earlier OCR/Barcode zones keep the
        # lightweight rectangle path and are not charged artwork CPU time.
        if self._production_mode():
            zone=self._current_production_zone()
            if zone and any(str(x).startswith("Artwork: ") for x in zone.items):
                try:
                    return self.zone_ocr.artwork.draw_alignment_overlay(display)
                except Exception as exc:
                    if self.live_session:self.live_session.debug.exception('ARTWORK_OVERLAY_FAIL err=%s',exc)

        h,w=display.shape[:2]; x1,y1,x2,y2=rect
        p1=(int(x1*w),int(y1*h)); p2=(int(x2*w),int(y2*h))
        state=self._target_state()
        color=(0,0,255) if state=="SEARCHING" else ((0,220,255) if state=="DETECTED" else (0,200,0))
        cv2.rectangle(display,p1,p2,color,4)
        cx=(p1[0]+p2[0])//2; cy=(p1[1]+p2[1])//2
        cv2.line(display,(cx-45,cy),(cx+45,cy),color,2); cv2.line(display,(cx,cy-28),(cx,cy+28),color,2)
        cv2.rectangle(display,(10,10),(min(w-10,1210),82),(0,0,0),-1)
        prefix="ZONE" if self._production_mode() else "OCR"
        cv2.putText(display,f"{prefix}: {title} | Put target area inside box",(22,52),cv2.FONT_HERSHEY_SIMPLEX,0.78,color,2,cv2.LINE_AA)
        return display

    def _update_target_zoom(self, frame):
        rect,_=self._active_scan()
        if rect is None or frame is None or not hasattr(self,'ocr_zoom_label'):return
        try:
            from .core.direct_guided_ocr import crop_relative
            roi=crop_relative(frame,rect)
            if roi is None or roi.size==0:return
            zoom=roi.copy(); h,w=zoom.shape[:2]; state=self._target_state()
            color=(0,0,255) if state=="SEARCHING" else ((0,220,255) if state=="DETECTED" else (0,200,0))
            cv2.line(zoom,(w//2-35,h//2),(w//2+35,h//2),color,1); cv2.line(zoom,(w//2,h//2-20),(w//2,h//2+20),color,1)
            rgb=cv2.cvtColor(zoom,cv2.COLOR_BGR2RGB); img=Image.fromarray(rgb); zw,zh=self._zoom_box_size(); img.thumbnail((zw,zh))
            photo=ImageTk.PhotoImage(img); self.ocr_zoom_label.config(image=photo,text=''); self.ocr_zoom_label.image=photo; self.target_zoom_photo=photo
        except Exception as exc:
            if self.live_session:self.live_session.debug.exception("TARGET_ZOOM_FAIL err=%s",exc)

    @staticmethod
    def _fit_16_9(container_w:int, container_h:int, min_w:int=320, min_h:int=180):
        """Largest 16:9 rectangle that fits completely inside the container."""
        w=max(int(container_w),min_w)
        h=max(int(container_h),min_h)
        ratio=16/9
        if w/h > ratio:
            oh=h
            ow=int(round(h*ratio))
        else:
            ow=w
            oh=int(round(w/ratio))
        return max(min_w,ow), max(min_h,oh)

    def _preview_box_size(self):
        """Keep the COMPLETE camera frame visible, even on short displays."""
        try:
            self.update_idletasks()
            cw=max(self.camera_frame.winfo_width()-12,self.preview_min_width)
            screen_h=max(self.winfo_screenheight(),720)
            # Reserve enough vertical space for top controls, guided OCR status,
            # compact OCR zoom and Windows taskbar.
            max_h=max(280,min(int(screen_h*0.43),500))
            return self._fit_16_9(cw,max_h,self.preview_min_width,self.preview_min_height)
        except Exception:
            return 640,360

    def _zoom_box_size(self):
        try:
            self.update_idletasks()
            cw=max(self.ocr_zoom_frame.winfo_width()-12,420)
            screen_h=max(self.winfo_screenheight(),720)
            zh=max(95,min(int(screen_h*0.12),145))
            return min(cw,720),zh
        except Exception:
            return 640,120

    def _update_preview(self):
        ok,frame=self.camera.read()
        if ok:
            self.last_frame=frame.copy()
            display=frame.copy()
            display=self._draw_target_overlay(display)
            self._update_target_zoom(frame)

            rgb=cv2.cvtColor(display,cv2.COLOR_BGR2RGB)
            img=Image.fromarray(rgb)
            pw,ph=self._preview_box_size()
            img.thumbnail((pw,ph))
            photo=ImageTk.PhotoImage(img)
            self.live_preview.config(image=photo,text='')
            self.live_preview.image=photo
            self.preview_last_size=(img.width,img.height)
            self.preview_geometry_var.set(f'Preview: {img.width}x{img.height} | aspect {img.width/img.height:.3f} | FULL FRAME VISIBLE')
        if self.camera.cap is not None:
            self.preview_job=self.after(50,self._update_preview)

    def autofocus(self):
        started=time.perf_counter()
        ok,val,elapsed,err=self.camera.autofocus(True,retrigger=True)
        total=(time.perf_counter()-started)*1000.0
        log.info('AUTOFOCUS_RETRIGGER set_ok=%s readback=%s camera_ms=%.1f total_ms=%.1f err=%s',ok,val,elapsed,total,err)
        if self.live_session:
            self.live_session.execution.info('AUTOFOCUS_RETRIGGER set_ok=%s readback=%s camera_ms=%.1f total_ms=%.1f err=%s',ok,val,elapsed,total,err)
            self.live_session.debug.info('CAMERA_COMMAND autofocus_retrigger ok=%s readback=%s camera_ms=%.1f total_ms=%.1f err=%s',ok,val,elapsed,total,err)
        messagebox.showinfo('Auto Focus',f'Retrigger={ok}\nReadback={val}\nCamera time={elapsed:.0f} ms'+(f'\nError={err}' if err else ''))



    def _production_mode(self):
        return self.ocr_mode_var.get().startswith("Production")

    def _sync_live_layout_for_mode(self):
        """Protect Camera Preview height in Production mode.

        Production 4-Zone:
          - Camera is the primary left-pane content.
          - OCR Target Zoom is hidden.
          - Raw OCR/Expected diagnostic rows are hidden from the Zone panel.

        Manual Item Debug:
          - OCR Target Zoom and diagnostic rows are shown.
        """
        production=self._production_mode()
        try:
            if production:
                self.ocr_zoom_frame.pack_forget()
                self.guided_expected_label.grid_remove()
                self.guided_ocr_label.grid_remove()
            else:
                self.ocr_zoom_frame.pack(fill="x",padx=4,pady=(2,2),before=self.preview_geometry_label)
                self.guided_expected_label.grid()
                self.guided_ocr_label.grid()
        except Exception:
            log.exception("LIVE_LAYOUT_SYNC_FAIL mode=%s",self.ocr_mode_var.get())

    def _on_ocr_mode_change(self):
        if self.live_active:
            self.stop_live()
        self.live_busy=False
        self.guided_ocr_var.set("OCR: --")
        self.guided_quality_var.set("Target: mode changed")
        self._sync_live_layout_for_mode()
        self._update_zone_ui()
        log.info("OCR_MODE_CHANGED mode=%s",self.ocr_mode_var.get())

    def _current_production_zone(self):
        if not self.production_scheduler or self.locks is None:
            return None
        return self.production_scheduler.current_for_display(self.locks)

    def _active_scan(self):
        if self._production_mode():
            z=self._current_production_zone()
            if z: return z.target_rect,z.title
            return None,"COMPLETE"
        t=self._current_guided_target()
        if t: return t.target_rect,t.title
        return None,"COMPLETE"

    def _current_guided_target(self):
        if not self.guided_scheduler:
            return None
        return self.guided_scheduler.select_next_incomplete(self.locks)

    def _update_zone_ui(self):
        if self.locks is None:return
        if self._production_mode():
            zone=self._current_production_zone()
            if not zone:
                self.zone_title_var.set("Current Scan Zone: COMPLETE")
                self.zone_instruction_var.set("All production OCR zones are complete.")
                self.zone_progress_var.set("Zone Progress: COMPLETE")
                self.zone_items_var.set("✓ A  ✓ B  ✓ C  ✓ D")
                self.guided_expected_var.set("Expected: --")
                return
            locked,total=self.production_scheduler.progress(zone,self.locks)
            self.zone_title_var.set(f"Current Scan Zone: {zone.id} - {zone.title.replace('ZONE '+zone.id+' - ','')}")
            self.zone_instruction_var.set(zone.instruction)
            self.zone_progress_var.set(f"Zone Progress: {locked}/{total} LOCKED | Overall: {self.locks.locked_count()}/{len(self.locks.required_items)}")
            parts=[]
            for item in self.production_scheduler.effective_items(zone,self.locks):
                st=self.locks.status_text(item) if item in self.locks.fields else "--"
                icon="✓" if st=="LOCK" else ("●" if st.startswith("PASS") else "○")
                short=item.replace("Fixed: ","").replace("Variable: ","").replace(" Format","")
                parts.append(f"{icon} {short}: {st}")
            self.zone_items_var.set("  |  ".join(parts))
            self.guided_expected_var.set("Expected: each field uses the existing V1.5.3 rule / barcode ground truth")
            return

        target=self._current_guided_target()
        if not target:
            self.zone_title_var.set("Current OCR Item: COMPLETE"); self.zone_instruction_var.set("All printed-text OCR items are locked.")
            self.zone_progress_var.set("Printed Text: COMPLETE"); self.zone_items_var.set(""); self.guided_expected_var.set("Expected: --"); return
        guided_items=[t.item for t in self.guided_scheduler.targets if t.item in self.locks.fields]
        locked=sum(1 for x in guided_items if self.locks.is_locked(x))
        self.zone_title_var.set(f"Current OCR Item: {target.title}")
        self.zone_instruction_var.set("Manual Item Debug：請將目前單一文字完整放入中央掃描框。 "+target.instruction)
        self.zone_progress_var.set(f"Printed Text: {locked}/{len(guided_items)} LOCKED | Current: {self.locks.status_text(target.item)}")
        self.zone_items_var.set(f"Debug Item: {target.item}")
        known=self._locked_known_fields(); expected=target.expected
        if target.mode=="sn_text":expected=known.get("sn_barcode","") or "Waiting for S/N barcode"
        elif target.mode=="mac_text":expected=known.get("mac_barcode","") or "Waiting for MAC barcode"
        elif target.mode=="gpon_text":expected=known.get("gpon_sn_barcode","") or "Waiting for GPON barcode"
        elif target.mode=="wifi_key":expected=known.get("qr_wifi_key","") or "14 characters"
        elif target.mode=="ssid":
            expected=known.get("qr_ssid","")
            if not expected and known.get("mac_barcode"):expected=self.engine.profile.get("rules",{}).get("ssid_prefix","Telekom Slovenije_")+known["mac_barcode"][-6:]
            expected=expected or "Telekom Slovenije_XXXXXX"
        elif target.mode=="pn":expected=self.expected_pn.get().strip() or self.engine.profile.get("rules",{}).get("pn_display","738125-00X")
        elif target.mode=="made_in":expected=self.expected_country.get().strip() or "China / Taiwan"
        self.guided_expected_var.set(f"Expected: {expected or '--'}")

    def next_guided_item(self):
        if self._production_mode():
            z=self.production_scheduler.next(self.locks); self._update_zone_ui()
            if self.live_session and z:self.live_session.execution.info("ZONE_MANUAL_NEXT zone=%s",z.id)
        elif self.guided_scheduler:
            t=self.guided_scheduler.next(self.locks); self._update_zone_ui()
            if self.live_session and t:self.live_session.execution.info("GUIDED_MANUAL_NEXT item=%s",t.item)

    def previous_guided_item(self):
        if self._production_mode():
            z=self.production_scheduler.previous(); self._update_zone_ui()
            if self.live_session and z:self.live_session.execution.info("ZONE_MANUAL_PREVIOUS zone=%s",z.id)
        elif self.guided_scheduler:
            t=self.guided_scheduler.previous(); self._update_zone_ui()
            if self.live_session and t:self.live_session.execution.info("GUIDED_MANUAL_PREVIOUS item=%s",t.item)

    def retry_guided_item(self):
        self.guided_ocr_var.set("OCR: --"); self.guided_quality_var.set("Target: retry requested")
        if self._production_mode():
            z=self.production_scheduler.retry()
            reset=0
            if z and self.locks is not None:
                items=self.production_scheduler.effective_items(z,self.locks)
                reset=self.locks.retry_items(items)
                for name in items:
                    if name in self.locks.fields and not self.locks.is_locked(name) and self.live_tree.exists(name):
                        exp=self.__dict__.setdefault("report_expected",{}).get(name,"")
                        self.live_tree.item(name,values=(name,'',exp,self.locks.status_text(name),'Manual Retry Zone'),tags=('SCANNING',))
            self._update_zone_ui()
            if self.live_session and z:
                self.live_session.execution.info("ZONE_MANUAL_RETRY zone=%s reset_unfinished=%s",z.id,reset)
                self.live_session.debug.info("ZONE_MANUAL_RETRY_RESET zone=%s reset_unfinished=%s",z.id,reset)
        elif self.guided_scheduler:
            t=self.guided_scheduler.retry(); self._update_zone_ui()
            if self.live_session and t:self.live_session.execution.info("GUIDED_MANUAL_RETRY item=%s",t.item)

    def toggle_live(self):
        if self.live_active:self.stop_live(); return
        if self.camera.cap is None:
            messagebox.showwarning('Live Scan','Start camera first'); return
        # V1.1.1: Start/Stop Live Scan must NOT clear LOCK states.
        # Only New Unit / Reset Locks or explicit Unlock Selected may do so.
        if self.locks is None:
            self._reset_live_tree()
        self.live_session=LiveInspectionSession('live_records',self.profile_var.get())
        if self.last_frame is not None:self.live_session.save_image('first_frame.jpg',self.last_frame)
        self.live_active=True; self.live_btn.config(text='Stop Live Scan'); self.live_state_var.set('Live: SCANNING')
        if self._production_mode() and self.production_scheduler:
            self.production_scheduler.resume_auto()
        current=(self._current_production_zone().id if self._production_mode() and self._current_production_zone() else (self._current_guided_target().item if self._current_guided_target() else '-'))
        self.live_session.execution.info('LIVE_SCAN_START required=%d mode=%s current=%s',len(self.locks.required_items),self.ocr_mode_var.get(),current)
        self._update_zone_ui()
        self.machine_state_var.set('Fast Machine Read: RUNNING')
        self._write_runtime_self_checks()
        self._schedule_machine_read()
        self._start_ocr_preflight_async()

    def _build_session_report_payload(self, overall: str, completed=None):
        if not self.live_session or self.locks is None:
            return None
        completed = completed or datetime.now()
        elapsed=(completed-self.live_session.started_at).total_seconds()
        return {
            "overall":overall,
            "software_version":__version__,
            "profile":self.profile_var.get(),
            "model":self.engine.profile.get("model",""),
            "label_type":self.engine.profile.get("label_type",""),
            "label_pn":self.engine.profile.get("label_pn",""),
            "spec_version":self.engine.profile.get("spec_version",""),
            "source_spec":self.engine.profile.get("source_spec",""),
            "artwork_verification_status":self.engine.profile.get("artwork_verification",{}).get("status","NOT_CONFIGURED"),
            "session_id":self.live_session.session_id,
            "started_at":self.live_session.started_at.isoformat(timespec="seconds"),
            "work_order":self._expected(),
            "locks":self.locks.snapshot(),
            "locked_count":self.locks.locked_count(),
            "required_count":len(self.locks.required_items),
            "zone_stats":self.zone_stats,
            "expected_map":self.report_expected,
            "ocr_mode":self.ocr_mode_var.get(),
            "elapsed_sec":round(elapsed,1),
            "completed_at":completed.isoformat(timespec="seconds"),
            "confirmed_fail_items":self.locks.confirmed_fail_items(),
            "unlocked_items":self.locks.unlocked_items(),
        }

    def stop_live(self):
        # V1.7.6: every real inspection session gets traceable result + Excel,
        # even when the operator stops before all fields LOCK.  V1.7.5 only
        # wrote Excel on overall PASS, which is why the incomplete Chassis run
        # had no workbook while the Inner Box PASS run did.
        session_to_save=self.live_session
        should_save=bool(session_to_save and not self.auto_saved and self.locks is not None)
        if should_save:
            fails=self.locks.confirmed_fail_items()
            overall='CONFIRMED_FAIL' if fails else ('PASS' if self.locks.all_locked() else 'INCOMPLETE')
            payload=self._build_session_report_payload(overall)
            if self.last_frame is not None:
                session_to_save.save_image('final_stop.jpg',self.last_frame)
            if payload:
                session_to_save.save_result(payload)
                report=session_to_save.save_excel_report(payload)
                session_to_save.test.info('SESSION_REPORT_ON_STOP overall=%s locked=%s required=%s unlocked=%s report=%s',overall,payload.get('locked_count'),payload.get('required_count'),payload.get('unlocked_items'),report)
                self.auto_saved=True
        self.live_active=False; self.live_btn.config(text='Start Live Scan'); self.live_state_var.set('Live: STOPPED')
        if self.live_job:
            try:self.after_cancel(self.live_job)
            except Exception:pass
            self.live_job=None
        if self.machine_job:
            try:self.after_cancel(self.machine_job)
            except Exception:pass
            self.machine_job=None
        self.machine_state_var.set('Fast Machine Read: STOPPED')
        if self.live_session:self.live_session.execution.info('LIVE_SCAN_STOP')




    def _queue_worker_event(self, event: WorkerEvent):
        """Worker-thread safe. Never touches Tk widgets."""
        ok=self.worker_bus.put(event)
        session=self.live_session
        if session:
            try:
                session.debug.info(
                    "QUEUE_PUT kind=%s cycle=%s item=%s ok=%s qsize=%s dropped=%s",
                    event.kind,event.cycle_id,event.item,ok,
                    self.worker_bus.size(),self.worker_bus.dropped
                )
            except Exception:
                pass
        return ok

    def _log_main_thread_exception(self, stage, event, exc):
        tb = traceback.format_exc()
        cycle = getattr(event, "cycle_id", 0) if event is not None else 0
        item = getattr(event, "item", "") if event is not None else ""
        kind = getattr(event, "kind", "") if event is not None else ""
        msg = (
            f"{stage} kind={kind} cycle={cycle} item={item} "
            f"exc={type(exc).__name__}: {exc}"
        )
        log.exception(msg)
        if self.live_session:
            self.live_session.debug.error("%s\n%s", msg, tb)
            self.live_session.test.error("%s", msg)
            self.live_session.execution.error("%s", msg)
        try:
            self.guided_quality_var.set(
                f"Target: MERGE ERROR | {type(exc).__name__}: {exc}"
            )
        except Exception:
            pass

    def _dispatch_worker_event(self, event):
        """Tk MAIN THREAD ONLY. One event failure must never hide the root cause."""
        if self.live_session:
            self.live_session.debug.info(
                "MERGE_DISPATCH_START kind=%s cycle=%s item=%s",
                event.kind,event.cycle_id,event.item
            )

        if event.kind=="ocr_preflight_ok":
            self._ocr_preflight_done(True,event.payload,None)

        elif event.kind=="ocr_preflight_fail":
            self._ocr_preflight_done(False,None,event.payload)

        elif event.kind=="machine_result":
            self.machine_busy=False
            result,cycle_id=event.payload
            self._merge_machine_result(result,cycle_id)

        elif event.kind=="machine_error":
            self.machine_busy=False
            if self.live_session:
                self.live_session.debug.error(
                    "FAST_MACHINE_FAIL_MAIN cycle=%s err=%r",
                    event.cycle_id,event.payload
                )

        elif event.kind=="zone_result":
            self.live_busy=False
            result,frame,cycle_id=event.payload
            self._merge_zone_result(result,frame,cycle_id)

        elif event.kind=="guided_result":
            self.live_busy=False
            if self.live_session:
                self.live_session.debug.info(
                    "MERGE_PAYLOAD_BEGIN cycle=%s item=%s payload_type=%s",
                    event.cycle_id,event.item,type(event.payload).__name__
                )
            result,frame,cycle_id=event.payload
            if self.live_session:
                self.live_session.debug.info(
                    "MERGE_PAYLOAD_OK cycle=%s item=%s result_type=%s",
                    cycle_id,event.item,type(result).__name__
                )
            self._merge_guided_result(result,frame,cycle_id)

        elif event.kind=="ocr_runtime_problem":
            self.live_busy=False
            self._handle_ocr_runtime_problem(
                event.payload,event.cycle_id,event.item
            )

        elif event.kind=="guided_error":
            self.live_busy=False
            if self.live_session:
                self.live_session.debug.error(
                    "GUIDED_OCR_FAIL_MAIN cycle=%s item=%s err=%r",
                    event.cycle_id,event.item,event.payload
                )

        else:
            if self.live_session:
                self.live_session.debug.warning(
                    "QUEUE_UNKNOWN_EVENT kind=%s cycle=%s item=%s",
                    event.kind,event.cycle_id,event.item
                )

        if self.live_session:
            self.live_session.debug.info(
                "MERGE_DISPATCH_END kind=%s cycle=%s item=%s",
                event.kind,event.cycle_id,event.item
            )

    def _poll_worker_results(self):
        """Tk MAIN THREAD ONLY: drain worker events and merge into GUI/state."""
        try:
            events=self.worker_bus.drain(limit=48)
            for event in events:
                self.worker_event_count += 1
                if self.live_session:
                    self.live_session.debug.info(
                        "QUEUE_GET kind=%s cycle=%s item=%s age_ms=%.1f qsize=%s",
                        event.kind,event.cycle_id,event.item,
                        max(0.0,(time.time()-event.created_at)*1000.0),
                        self.worker_bus.size()
                    )
                try:
                    self._dispatch_worker_event(event)
                except Exception as exc:
                    self.live_busy=False
                    self.machine_busy=False
                    self._log_main_thread_exception(
                        "MERGE_FATAL",event,exc
                    )
        except Exception as exc:
            self._log_main_thread_exception(
                "WORKER_RESULT_POLL_FATAL",None,exc
            )
        finally:
            try:
                if self.winfo_exists():
                    self.worker_poll_job=self.after(
                        self.worker_poll_interval_ms,
                        self._poll_worker_results
                    )
            except Exception:
                log.exception("WORKER_RESULT_POLL_RESCHEDULE_FAIL")


    def _write_runtime_self_checks(self):
        if not self.live_session:
            return
        try:
            import zxingcpp
            self.live_session.test.info("ZXING_RUNTIME_PASS module=%s", getattr(zxingcpp,'__name__','zxingcpp'))
        except Exception as exc:
            self.live_session.test.exception("ZXING_RUNTIME_FAIL err=%s", exc)
        try:
            probe=SmartLockEngine(['probe'],2,3,12)
            probe.offer('probe','OK','PASS'); probe.offer('probe','OK','PASS')
            ok=probe.is_locked('probe')
            self.live_session.test.info("SMART_LOCK_RUNTIME_%s", 'PASS' if ok else 'FAIL')
        except Exception as exc:
            self.live_session.test.exception("SMART_LOCK_RUNTIME_FAIL err=%s", exc)
        try:
            stats=self.camera.stats()
            self.live_session.test.info("CAMERA_RUNTIME_PASS backend=%s stats=%s", self.camera.backend_name, stats)
        except Exception as exc:
            self.live_session.test.exception("CAMERA_RUNTIME_FAIL err=%s", exc)
        try:
            art_status=self.zone_ocr.artwork.resource_status()
            ok=not art_status.get("missing") and (not art_status.get("enabled") or art_status.get("golden_layout_loaded"))
            self.live_session.test.info("ARTWORK_RESOURCE_RUNTIME_%s status=%s", 'PASS' if ok else 'FAIL', art_status)
            self.live_session.debug.info("ARTWORK_RESOURCE_PATH_DUMP status=%s", art_status)
        except Exception as exc:
            self.live_session.test.exception("ARTWORK_RESOURCE_RUNTIME_FAIL err=%s", exc)

    @staticmethod
    def _ocr_smoke_image():
        import numpy as np
        img=np.full((180,1000,3),255,dtype=np.uint8)
        cv2.putText(img,'GPON VoIP Gateway',(35,115),cv2.FONT_HERSHEY_SIMPLEX,2.0,(0,0,0),4,cv2.LINE_AA)
        return img

    def _start_ocr_preflight_async(self, force=False):
        if self.ocr_runtime_busy:
            return
        if self.ocr_service.ready and not force:
            self.ocr_runtime_state='READY'
            self.ocr_runtime_var.set(f'OCR Engine: READY | PID {self.ocr_service.pid}')
            if self.live_active and self.live_job is None:
                self._schedule_live()
            return
        self.ocr_runtime_busy=True
        self.ocr_runtime_state='INITIALIZING'
        self.ocr_runtime_var.set('OCR Engine: INITIALIZING...')
        self.guided_quality_var.set('Target: waiting for OCR runtime preflight')
        if self.live_session:
            self.live_session.test.info('OCR_RUNTIME_LOAD_START force=%s',force)
            self.live_session.debug.info('OCR_RUNTIME_PREFLIGHT_START')
        threading.Thread(target=self._ocr_preflight_worker,args=(force,),daemon=True,name='OCRPreflightWorker').start()

    def _ocr_preflight_worker(self, force=False):
        try:
            if force:
                self.ocr_service.stop()
            img=self._ocr_smoke_image()
            cfg=self.engine.profile.get('live',{}) if self.engine else {}
            info=self.ocr_service.preflight(
                img,
                init_timeout_sec=float(cfg.get('ocr_init_timeout_sec',12)),
                read_timeout_sec=float(cfg.get('ocr_timeout_sec',6)),
            )
            self._queue_worker_event(
                WorkerEvent(kind="ocr_preflight_ok",payload=info,item="OCR_PREFLIGHT")
            )
        except Exception as exc:
            self._queue_worker_event(
                WorkerEvent(kind="ocr_preflight_fail",payload=exc,item="OCR_PREFLIGHT")
            )

    def _ocr_preflight_done(self, ok, info, exc):
        self.ocr_runtime_busy=False
        if ok:
            self.ocr_runtime_state='READY'
            self.ocr_runtime_var.set(
                f"OCR Engine: READY | load {info.get('load_ms',0):.0f} ms | infer {info.get('inference_ms',0):.0f} ms"
            )
            self.guided_quality_var.set('Target: OCR runtime READY - align current text')
            if self.live_session:
                self.live_session.test.info(
                    'OCR_RUNTIME_LOAD_PASS pid=%s load_ms=%.1f inference_ms=%.1f total_ms=%.1f lines=%s text=%r',
                    info.get('pid'),info.get('load_ms',0),info.get('inference_ms',0),
                    info.get('total_ms',0),info.get('line_count',0),info.get('text','')
                )
                self.live_session.debug.info('OCR_RUNTIME_PREFLIGHT_PASS info=%s',info)
            if self.live_active and self.live_job is None:
                self._schedule_live()
        else:
            self.ocr_runtime_state='FAIL'
            self.ocr_runtime_var.set('OCR Engine: FAIL - press Retry OCR Engine')
            self.guided_quality_var.set(f'Target: OCR ENGINE FAIL | {exc}')
            if self.live_session:
                self.live_session.test.exception('OCR_RUNTIME_LOAD_FAIL err=%r',exc)
                self.live_session.debug.exception('OCR_RUNTIME_PREFLIGHT_FAIL err=%r',exc)

    def retry_ocr_runtime(self):
        if self.live_session:
            self.live_session.execution.warning('OCR_RUNTIME_MANUAL_RETRY')
        self._start_ocr_preflight_async(force=True)

    def _handle_ocr_runtime_problem(self, exc, cycle_id, item):
        recovered=bool(getattr(exc,'recovered',False) and self.ocr_service.ready)
        self.ocr_runtime_state='READY' if recovered else 'FAIL'
        if recovered:
            self.ocr_runtime_var.set(f'OCR Engine: RECOVERED | restart #{self.ocr_service.restart_count}')
            self.guided_quality_var.set('Target: OCR timeout recovered - scanning resumes')
        else:
            self.ocr_runtime_var.set('OCR Engine: FAIL - press Retry OCR Engine')
            self.guided_quality_var.set(f'Target: OCR runtime error | {exc}')
        if self.live_session:
            self.live_session.test.error(
                'OCR_RUNTIME_PROBLEM cycle=%s item=%s recovered=%s restart_count=%s err=%r',
                cycle_id,item,recovered,self.ocr_service.restart_count,exc
            )

    def _locked_known_fields(self):
        known = {}
        if self.locks is None:
            return known
        for item_name, field_key in LOCK_TO_FIELD.items():
            if self.locks.is_locked(item_name):
                value = self.locks.locked_value(item_name)
                if value:
                    known[field_key] = value
        # WiFi QR contains two additional values required by Zone D cross-check.
        if known.get("wifi_qr"):
            try:
                from .core.parser import parse_decoded_fields
                q = parse_decoded_fields([known["wifi_qr"]])
                known.update({k:v for k,v in q.items() if v})
            except Exception:
                pass
        return known


    def _machine_items_remaining(self):
        names = (
            "Variable: S/N Barcode Format",
            "Variable: MAC Barcode Format",
            "Variable: GPON S/N Barcode Format",
            "Variable: WiFi QR Format",
        )
        return [n for n in names if n in self.locks.fields and not self.locks.is_locked(n)]

    def _schedule_machine_read(self):
        if not self.live_active:
            return

        remaining = self._machine_items_remaining()
        if not remaining:
            self.machine_state_var.set("Fast Machine Read: ALL LOCKED")
            return

        if not self.machine_busy and self.last_frame is not None:
            self.machine_busy = True
            self.machine_cycle += 1
            frame = self.last_frame.copy()
            threading.Thread(
                target=self._machine_worker,
                args=(frame, self.machine_cycle),
                daemon=True,
                name="FastMachineReader",
            ).start()

        interval = int(self.engine.profile.get("live", {}).get("machine_scan_interval_ms", 250))
        self.machine_job = self.after(interval, self._schedule_machine_read)

    def _machine_worker(self, frame, cycle_id):
        try:
            result = self.fast_reader.read(frame)
            self._queue_worker_event(
                WorkerEvent(
                    kind="machine_result",
                    payload=(result,cycle_id),
                    cycle_id=cycle_id,
                    item="FAST_MACHINE",
                )
            )
        except Exception as exc:
            if self.live_session:
                self.live_session.debug.exception(
                    "FAST_MACHINE_FAIL cycle=%s err=%s", cycle_id, exc
                )
            self._queue_worker_event(
                WorkerEvent(
                    kind="machine_error",payload=exc,
                    cycle_id=cycle_id,item="FAST_MACHINE"
                )
            )

    def _merge_machine_result(self, result, cycle_id):
        if not self.live_active:
            return

        if self.live_session:
            self.live_session.debug.info(
                "FAST_MACHINE cycle=%s elapsed_ms=%.1f decoded=%s values=%s",
                cycle_id, result.elapsed_ms, len(result.decoded_texts), result.decoded_texts
            )

        locked_now = 0
        for row in result.rows:
            if self.live_session:
                self.live_session.debug.info(
                    'MERGE_ROW_BEGIN cycle=%s row_name=%s status=%s',
                    cycle_id,getattr(row,'name',''),getattr(row,'status','')
                )
            name = row.name
            if name not in self.locks.fields or self.locks.is_locked(name):
                continue
            self.__dict__.setdefault("report_expected",{})[name]=row.expected
            state = self.locks.offer(
                name, row.actual, "PASS", row.message, source="Full-frame zxingcpp"
            )
            if self.live_tree.exists(name):
                self.live_tree.item(
                    name,
                    values=(name, row.actual, row.expected,
                            self.locks.status_text(name), row.message),
                    tags=(state,),
                )
            if self.live_session:
                self.live_session.debug.info(
                    "FAST_MACHINE_CANDIDATE item=%s state=%s value=%s",
                    name, state, row.actual
                )
                if state == "LOCK":
                    self.live_session.execution.info(
                        "FAST_MACHINE_LOCKED item=%s value=%s elapsed_ms=%.1f",
                        name, row.actual, result.elapsed_ms
                    )
                    self.live_session.lock_history.info(
                        "LOCK source=FastMachine item=%s value=%s",name,row.actual
                    )
            if state == "LOCK":
                locked_now += 1

        left = len(self._machine_items_remaining())
        self.machine_state_var.set(
            f"Fast Machine Read: {4-left}/4 LOCKED | {result.elapsed_ms:.0f} ms"
        )
        self.progress_var.set(
            f"{self.locks.locked_count()} / {len(self.locks.required_items)} LOCKED"
        )

        self._refresh_cross_checks()
        self._update_zone_ui()
        if self.last_frame is not None:
            self._update_live_overall(self.last_frame)

        # Identity can become known from the fast S/N barcode before OCR.
        sn_item = "Variable: S/N Barcode Format"
        if self.locks.is_locked(sn_item) and not self.identity_guard.current:
            self.identity_guard.set_current(self.locks.locked_value(sn_item))


    def _schedule_live(self):
        if not self.live_active:return
        if self.locks.all_locked():return
        if self.ocr_runtime_state!='READY' or not self.ocr_service.ready:
            self.live_job=None; return

        if self._production_mode():
            zone=self._current_production_zone()
            if zone is None:
                self._refresh_cross_checks(); interval=int(self.engine.profile.get('live',{}).get('zone_scan_interval_ms',500)); self.live_job=self.after(interval,self._schedule_live); return
            if not self.live_busy and self.last_frame is not None:
                self.live_busy=True; self.live_cycle+=1; frame=self.last_frame.copy()
                expected_snapshot=dict(self._expected()); known_snapshot=dict(self._locked_known_fields()); known_snapshot['_required_items']=list(self.locks.required_items)
                zone_snapshot=zone.snapshot()
                requested=[]
                for item in zone.items:
                    base_incomplete=item in self.locks.fields and not self.locks.is_locked(item)
                    dep_incomplete=(item=='Variable: P/N Format' and 'Work Order: P/N' in self.locks.fields and not self.locks.is_locked('Work Order: P/N')) or (item=='Variable: Made in Format' and 'Work Order: Made in' in self.locks.fields and not self.locks.is_locked('Work Order: Made in'))
                    if base_incomplete or dep_incomplete:requested.append(item)
                if self.live_session:self.live_session.debug.info('ZONE_WORKER_SNAPSHOT cycle=%s zone=%s requested=%s manual_hold=%s',self.live_cycle,zone.id,requested,self.production_scheduler.manual_hold)
                if requested:
                    threading.Thread(target=self._zone_worker,args=(frame,zone_snapshot,known_snapshot,expected_snapshot,requested,self.live_cycle),daemon=True,name='MultiFieldZoneOCRWorker').start()
                else:
                    self.live_busy=False
            elif self.live_busy:self.dropped_busy_cycles+=1
            interval=int(self.engine.profile.get('live',{}).get('zone_scan_interval_ms',500))
            self.live_job=self.after(interval,self._schedule_live); return

        target=self._current_guided_target()
        if target is None:
            self._refresh_cross_checks(); interval=int(self.engine.profile.get('live',{}).get('guided_scan_interval_ms',350)); self.live_job=self.after(interval,self._schedule_live); return
        if not self.live_busy and self.last_frame is not None:
            self.live_busy=True; self.live_cycle+=1; frame=self.last_frame.copy()
            expected_snapshot,known_snapshot,target_snapshot=self._build_worker_snapshot(target)
            if self.live_session:self.live_session.debug.info('WORKER_SNAPSHOT cycle=%s item=%s expected_keys=%s known_keys=%s',self.live_cycle,target_snapshot['item'],sorted(expected_snapshot.keys()),sorted(known_snapshot.keys()))
            threading.Thread(target=self._guided_worker,args=(frame,target_snapshot,known_snapshot,expected_snapshot,self.live_cycle),daemon=True,name='DirectGuidedOCRWorker').start()
        elif self.live_busy:self.dropped_busy_cycles+=1
        interval=int(self.engine.profile.get('live',{}).get('guided_scan_interval_ms',350)); self.live_job=self.after(interval,self._schedule_live)

    def _zone_worker(self, frame, zone_snapshot, known_fields, expected_snapshot, requested_items, cycle_id):
        zone=ProductionZone.from_snapshot(zone_snapshot); started=time.perf_counter()
        try:
            if self.live_session:
                self.live_session.debug.info('ZONE_WORKER_START cycle=%s zone=%s requested=%s runtime_pid=%s',cycle_id,zone.id,requested_items,self.ocr_service.pid)
                self.live_session.test.info('ZONE_OCR_CALL_START cycle=%s zone=%s',cycle_id,zone.id)
            min_sharp=float(self.engine.profile.get('live',{}).get('guided_min_sharpness',18))
            result=self.zone_ocr.analyze(frame,zone,dict(known_fields),dict(expected_snapshot),min_sharpness=min_sharp,requested_items=requested_items)
            if self.live_session:self.live_session.test.info('ZONE_OCR_CALL_END cycle=%s zone=%s wall_ms=%.1f raw_text=%r evaluated=%s pass_items=%s',cycle_id,zone.id,(time.perf_counter()-started)*1000.0,result.raw_text,result.evaluated_items,result.pass_items)
            self._queue_worker_event(WorkerEvent(kind='zone_result',payload=(result,frame,cycle_id),cycle_id=cycle_id,item=f'ZONE {zone.id}'))
        except OCRRuntimeTimeout as exc:
            if self.live_session:self.live_session.debug.exception('ZONE_OCR_TIMEOUT cycle=%s zone=%s err=%s',cycle_id,zone.id,exc)
            self._queue_worker_event(WorkerEvent(kind='ocr_runtime_problem',payload=exc,cycle_id=cycle_id,item=f'ZONE {zone.id}'))
        except (OCRRuntimeError,OCRRuntimeInitError) as exc:
            if self.live_session:self.live_session.debug.exception('ZONE_OCR_RUNTIME_FAIL cycle=%s zone=%s err=%s',cycle_id,zone.id,exc)
            self._queue_worker_event(WorkerEvent(kind='ocr_runtime_problem',payload=exc,cycle_id=cycle_id,item=f'ZONE {zone.id}'))
        except Exception as exc:
            if self.live_session:self.live_session.debug.exception('ZONE_OCR_FAIL cycle=%s zone=%s err=%s',cycle_id,zone.id,exc)
            self._queue_worker_event(WorkerEvent(kind='guided_error',payload=exc,cycle_id=cycle_id,item=f'ZONE {zone.id}'))

    def _guided_worker(self, frame, target_snapshot, known_fields, expected_snapshot, cycle_id):
        """BACKGROUND THREAD ONLY.

        This method must not access Tk/Tcl state.  All Tk-derived values are
        snapshotted on the main thread before this worker starts.
        """
        started=time.perf_counter()
        item=str(target_snapshot["item"])

        try:
            target=GuidedTarget(
                item=str(target_snapshot["item"]),
                title=str(target_snapshot["title"]),
                instruction=str(target_snapshot["instruction"]),
                target_rect=list(target_snapshot["target_rect"]),
                mode=str(target_snapshot["mode"]),
                expected=str(target_snapshot["expected"]),
                threshold=float(target_snapshot["threshold"]),
            )

            if self.live_session:
                self.live_session.debug.info(
                    "GUIDED_WORKER_START cycle=%s item=%s frame_shape=%s runtime_pid=%s snapshot=1",
                    cycle_id,item,getattr(frame,"shape",None),self.ocr_service.pid
                )
                self.live_session.test.info(
                    "OCR_CALL_START cycle=%s item=%s",cycle_id,item
                )

            min_sharp=float(
                self.engine.profile.get("live",{}).get("guided_min_sharpness",18)
            )
            result=self.guided_ocr.analyze(
                frame,
                target,
                dict(known_fields),
                dict(expected_snapshot),
                min_sharpness=min_sharp,
            )

            if self.live_session:
                self.live_session.test.info(
                    "OCR_CALL_END cycle=%s item=%s wall_ms=%.1f raw_text=%r",
                    cycle_id,item,
                    (time.perf_counter()-started)*1000.0,result.raw_text
                )

            self._queue_worker_event(
                WorkerEvent(
                    kind="guided_result",
                    payload=(result,frame,cycle_id),
                    cycle_id=cycle_id,
                    item=item,
                )
            )

        except OCRRuntimeTimeout as exc:
            if self.live_session:
                self.live_session.debug.exception(
                    "OCR_TIMEOUT cycle=%s item=%s err=%s",cycle_id,item,exc
                )
            self._queue_worker_event(
                WorkerEvent(
                    kind="ocr_runtime_problem",
                    payload=exc,
                    cycle_id=cycle_id,
                    item=item,
                )
            )
        except (OCRRuntimeError, OCRRuntimeInitError) as exc:
            if self.live_session:
                self.live_session.debug.exception(
                    "OCR_RUNTIME_FAIL cycle=%s item=%s err=%s",cycle_id,item,exc
                )
            self._queue_worker_event(
                WorkerEvent(
                    kind="ocr_runtime_problem",
                    payload=exc,
                    cycle_id=cycle_id,
                    item=item,
                )
            )
        except Exception as exc:
            if self.live_session:
                self.live_session.debug.exception(
                    "GUIDED_OCR_FAIL cycle=%s item=%s err=%s",cycle_id,item,exc
                )
            self._queue_worker_event(
                WorkerEvent(
                    kind="guided_error",
                    payload=exc,
                    cycle_id=cycle_id,
                    item=item,
                )
            )

    def _merge_zone_result(self,result,frame,cycle_id):
        if not self.live_active:return
        zid=result.zone_id; safe=f"ZONE_{zid}"
        st=self.zone_stats.setdefault(zid,{"title":result.zone_title,"attempts":0,"total_ocr_ms":0.0,"max_ocr_ms":0.0,"last_sharpness":0.0,"locked_items":0,"total_items":0,"completed":False})
        st["attempts"]+=1; st["total_ocr_ms"]+=float(result.elapsed_ms); st["max_ocr_ms"]=max(st["max_ocr_ms"],float(result.elapsed_ms)); st["last_sharpness"]=float(result.sharpness)
        if self.live_session:
            self.live_session.debug.info('ZONE_MERGE_ENTER cycle=%s zone=%s rows=%s ready=%s sharp=%.1f elapsed_ms=%.1f',cycle_id,zid,len(result.rows),result.ready,result.sharpness,result.elapsed_ms)
            self.live_session.performance.info('ZONE_PERF cycle=%s zone=%s elapsed_ms=%.1f sharp=%.1f evaluated=%s pass=%s',cycle_id,zid,result.elapsed_ms,result.sharpness,result.evaluated_items,result.pass_items)
            self.live_session.save_target_image(f'{safe}_last.jpg',result.target_image)
        shown=(result.raw_text or '').replace('\n',' | '); self.guided_ocr_var.set(f"OCR: {(shown[:240]+'...' if len(shown)>240 else shown) or '<empty>'}")
        pass_count=sum(1 for r in result.rows if r.status=='PASS')
        self.guided_quality_var.set(f"Target: {'READY / DETECTED' if pass_count else ('MOVE / FOCUS' if not result.ready else 'READING')} | Sharpness: {result.sharpness:.1f} | OCR time: {result.elapsed_ms:.0f} ms | PASS fields this cycle: {pass_count}")
        for row in result.rows:
            name=row.name
            if name not in self.locks.fields or self.locks.is_locked(name):continue
            value=self._candidate_value(row)
            self.__dict__.setdefault("report_expected",{})[name]=row.expected
            if self.live_session:
                self.live_session.debug.info('ZONE_RULE_EVAL cycle=%s zone=%s item=%s status=%s actual=%s expected=%s message=%s',cycle_id,zid,name,row.status,value,row.expected,row.message)
                if name.startswith('Artwork: '):
                    self.live_session.test.info('ARTWORK_CHECK cycle=%s zone=%s item=%s status=%s actual=%s expected=%s message=%s',cycle_id,zid,name,row.status,value,row.expected,row.message)
            if getattr(row,'error_code','')=='ART-TEMPLATE-MISSING':
                if self.live_tree.exists(name):
                    self.live_tree.item(name,values=(name,'RESOURCE ERROR',row.expected,'RESOURCE ERROR',row.message),tags=('RESOURCE_ERROR',))
                self.live_state_var.set('Live: RESOURCE ERROR - Golden Artwork missing/unreadable')
                if self.live_session:
                    self.live_session.execution.error('ARTWORK_RESOURCE_ERROR zone=%s item=%s message=%s',zid,name,row.message)
                    self.live_session.debug.error('ARTWORK_RESOURCE_ERROR zone=%s item=%s message=%s',zid,name,row.message)
                continue
            state=self.locks.offer(name,value,row.status,row.message,source=f'Zone OCR {zid}')
            if self.live_tree.exists(name):self.live_tree.item(name,values=(name,value,row.expected,self.locks.status_text(name),row.message),tags=(state,))
            if self.live_session:
                self.live_session.debug.info('ZONE_SMART_LOCK cycle=%s zone=%s item=%s state=%s value=%s',cycle_id,zid,name,state,value)
                if state=='LOCK':
                    self.live_session.execution.info('ZONE_ITEM_LOCKED zone=%s item=%s value=%s',zid,name,value)
                    self.live_session.lock_history.info('LOCK source=ZoneOCR-%s item=%s value=%s',zid,name,value)
        zone=next((z for z in self.production_scheduler.zones if z.id==zid),None)
        if zone:
            locked,total=self.production_scheduler.progress(zone,self.locks); st['locked_items']=locked; st['total_items']=total
            completed=self.production_scheduler.is_complete(zone,self.locks); st['completed']=completed
            if completed:
                if self.live_session:
                    self.live_session.execution.info('ZONE_COMPLETE zone=%s locked=%s total=%s',zid,locked,total)
                    self.live_session.save_target_image(f'{safe}_LOCK.jpg',result.target_image)
                if self.production_scheduler.current and self.production_scheduler.current.id==zid:
                    self.production_scheduler.advance_if_complete(self.locks)
                nxt=self.production_scheduler.select_next_incomplete(self.locks)
                if self.live_session:self.live_session.execution.info('ZONE_AUTO_ADVANCE next=%s',nxt.id if nxt else 'COMPLETE')
        self._refresh_cross_checks(); self._update_zone_ui(); self._update_live_overall(frame)
        if self.live_session:self.live_session.debug.info('ZONE_MERGE_END cycle=%s zone=%s',cycle_id,zid)

    def _merge_guided_result(self,result,frame,cycle_id):
        if self.live_session:
            self.live_session.debug.info(
                "MERGE_ENTER cycle=%s result_type=%s live_active=%s",
                cycle_id,type(result).__name__,self.live_active
            )

        if not self.live_active:
            if self.live_session:
                self.live_session.debug.warning(
                    "MERGE_SKIPPED cycle=%s reason=live_active_false",
                    cycle_id
                )
            return

        if result is None:
            raise ValueError("guided result is None")
        if not hasattr(result,"item"):
            raise TypeError(
                f"guided result missing item attribute: {type(result).__name__}"
            )
        if not hasattr(result,"rows"):
            raise TypeError(
                f"guided result missing rows attribute: {type(result).__name__}"
            )

        if self.live_session:
            self.live_session.debug.info(
                "MERGE_RESULT_VALID cycle=%s item=%s rows=%s ready=%s raw_len=%s",
                cycle_id,result.item,len(result.rows),getattr(result,"ready",None),
                len(getattr(result,"raw_text","") or "")
            )

        safe_name=re.sub(r"[^A-Za-z0-9_.-]+","_",str(result.item))[:80]
        if self.live_session:
            self.live_session.debug.info(
                "GUIDED_OCR cycle=%s item=%s ready=%s sharp=%.1f elapsed_ms=%.1f "
                "score=%.3f expected=%s raw_text=%r",
                cycle_id,result.item,result.ready,result.sharpness,result.elapsed_ms,
                result.match_score,result.expected_display,result.raw_text
            )
            self.live_session.test.info(
                "GUIDED_PERF cycle=%s item=%s elapsed_ms=%.1f sharp=%.1f score=%.3f",
                cycle_id,result.item,result.elapsed_ms,result.sharpness,result.match_score
            )
            self.live_session.performance.info(
                "GUIDED_PERF cycle=%s item=%s elapsed_ms=%.1f sharp=%.1f score=%.3f",
                cycle_id,result.item,result.elapsed_ms,result.sharpness,result.match_score
            )
            self.live_session.save_target_image(f"{safe_name}_last.jpg",result.target_image)

        shown=(result.raw_text or "").replace("\n"," | ")
        if len(shown)>180:
            shown=shown[:177]+"..."
        self.guided_ocr_var.set(f"OCR: {shown or '<empty>'}")
        state_text="READY / DETECTED" if any(r.status=="PASS" for r in result.rows) else (
            "MOVE / FOCUS" if not result.ready or not result.raw_text else "READING"
        )
        self.guided_quality_var.set(
            f"Target: {state_text} | Sharpness: {result.sharpness:.1f} | "
            f"OCR time: {result.elapsed_ms:.0f} ms | Match: {result.match_score:.3f}"
        )
        if result.expected_display:
            self.guided_expected_var.set(f"Expected: {result.expected_display}")

        for row in result.rows:
            name=row.name
            if name not in self.locks.fields or self.locks.is_locked(name):
                continue
            value=self._candidate_value(row)
            self.__dict__.setdefault("report_expected",{})[name]=row.expected
            if self.live_session:
                self.live_session.debug.info(
                    "RULE_EVAL cycle=%s item=%s status=%s actual=%s expected=%s message=%s",
                    cycle_id,name,row.status,value,row.expected,row.message
                )
            state=self.locks.offer(name,value,row.status,row.message,source="Direct Guided OCR")
            if self.live_session:
                self.live_session.debug.info(
                    "SMART_LOCK_RESULT cycle=%s item=%s state=%s value=%s",
                    cycle_id,name,state,value
                )
            if self.live_tree.exists(name):
                self.live_tree.item(
                    name,
                    values=(name,value,row.expected,self.locks.status_text(name),row.message),
                    tags=(state,)
                )
            if self.live_session:
                self.live_session.debug.info(
                    "GUIDED_CANDIDATE item=%s status=%s lock_state=%s actual=%s",
                    name,row.status,state,value
                )
                if state=="LOCK":
                    self.live_session.execution.info(
                        "GUIDED_ITEM_LOCKED item=%s value=%s",name,value
                    )
                    self.live_session.lock_history.info(
                        "LOCK source=DirectGuidedOCR item=%s value=%s",name,value
                    )
                    self.live_session.save_target_image(f"{safe_name}_LOCK.jpg",result.target_image)

        changed=self.guided_scheduler.advance_if_locked(self.locks)
        if changed and self.live_session:
            nxt=self._current_guided_target()
            self.live_session.execution.info(
                "GUIDED_AUTO_ADVANCE next=%s", nxt.item if nxt else "COMPLETE"
            )

        self._refresh_cross_checks()
        self._update_zone_ui()
        self._update_live_overall(frame)
        if self.live_session:
            self.live_session.debug.info(
                'MERGE_END cycle=%s item=%s',cycle_id,result.item
            )

    def _refresh_cross_checks(self):
        """Derived rules use only LOCKED source values.

        Since the inputs are already terminal/verified, PASS derived rules can
        lock deterministically without a second camera observation.
        """
        known=self._locked_known_fields()
        candidates=[
            "Consistency: S/N Text vs Barcode",
            "Consistency: MAC Text vs Barcode",
            "Consistency: GPON S/N Text vs Barcode",
            "Rule: SSID = MAC Last 6",
            "Rule: GPON S/N = Prefix + MAC Last 8",
            "Consistency: QR SSID vs Printed SSID",
            "Consistency: QR Key vs Printed WiFi Key",
        ]
        required=set(self.locks.required_items if self.locks else [])
        active=[name for name in candidates if name in required]
        if not active:
            return
        rows=self.live_analyzer.evaluate_known_fields(
            known,self._expected(),active
        )
        for row in rows:
            if row.name not in self.locks.fields or self.locks.is_locked(row.name):
                continue
            if row.status=="PASS" and row.actual:
                self.__dict__.setdefault("report_expected",{})[row.name]=row.expected
                state=self.locks.force_lock(row.name,row.actual,source="Derived Rule Engine")
                if self.live_tree.exists(row.name):
                    self.live_tree.item(
                        row.name,
                        values=(row.name,row.actual,row.expected,self.locks.status_text(row.name),row.message),
                        tags=(state,)
                    )
                if self.live_session:
                    self.live_session.execution.info(
                        "DERIVED_RULE_LOCKED item=%s actual=%s expected=%s",
                        row.name,row.actual,row.expected
                    )

    def _update_live_overall(self,frame):
        locked=self.locks.locked_count()
        total=len(self.locks.required_items)
        fails=self.locks.confirmed_fail_items()
        self.progress_var.set(f"{locked} / {total} LOCKED")
        if fails:
            self.live_state_var.set("Live: CONFIRMED FAIL")
        else:
            if self._production_mode():
                z=self._current_production_zone(); name=z.title if z else "Cross-check"
            else:
                t=self._current_guided_target(); name=t.title if t else "Cross-check"
            self.live_state_var.set(f"Live: SCANNING | {name} | {locked}/{total}")

        if self.locks.all_locked():
            self.live_state_var.set("Live: PASS - ALL REQUIRED LOCKED")
            if self.live_session and not self.auto_saved:
                self.auto_saved=True
                self.live_session.save_image("final_pass.jpg",frame)
                completed=datetime.now()
                payload=self._build_session_report_payload("PASS",completed)
                self.live_session.save_result(payload)
                report=self.live_session.save_excel_report(payload)
                if report:self.status_var.set(f"PASS | Excel Report: {report}")
            self.stop_live()

    @staticmethod
    def _candidate_value(row):
            # For presence checks actual="Present"; for consistency rows actual is the source value.
            return (row.actual or '').strip()

    def _merge_live_result(self,result,frame,cycle_id=0):
        """Legacy V1.3 ROI pipeline intentionally disabled for live V1.4."""
        if self.live_session:
            self.live_session.debug.warning(
                "LEGACY_LIVE_RESULT_IGNORED cycle=%s",cycle_id
            )

    def on_scanner_enter(self,event=None):
        raw=self.scanner_var.get().strip(); self.scanner_var.set('')
        if not raw:return 'break'
        if self.locks is None:self._reset_live_tree()
        results=self.live_analyzer.scanner_results(raw,self._expected())
        if self.live_session:self.live_session.execution.info('HID_SCAN received category_count=%d',len(results))
        for row in results:
            if row.name not in self.locks.fields:continue
            # Deterministic HID data can be locked directly after validation.
            self.__dict__.setdefault('report_expected',{})[row.name]=row.expected
            state=self.locks.force_lock(row.name,row.actual,source='HID Scanner')
            if self.live_tree.exists(row.name):
                self.live_tree.item(row.name,values=(row.name,row.actual,row.expected,self.locks.status_text(row.name),'HID Scanner'),tags=(state,))
            if self.live_session:self.live_session.execution.info('HID_ITEM item=%s state=%s value=%s',row.name,state,row.actual)
        self.progress_var.set(f"{self.locks.locked_count()} / {len(self.locks.required_items)} LOCKED")
        self.scanner_entry.focus_force(); return 'break'

    def unlock_selected(self):
        if self.locks is None:
            return
        selected=self.live_tree.selection()
        if not selected:
            messagebox.showinfo('Unlock Selected','Select one checklist row first.')
            return
        name=selected[0]
        if not messagebox.askyesno('Unlock Selected',f'Unlock this item?\n\n{name}'):
            return
        if self.locks.manual_unlock(name):
            self.live_tree.item(name,values=(name,'','',self.locks.status_text(name),'Manual engineering unlock'),tags=('SCANNING',))
            if self.live_session:
                self.live_session.execution.warning('MANUAL_UNLOCK item=%s',name)
            self.progress_var.set(f"{self.locks.locked_count()} / {len(self.locks.required_items)} LOCKED")

    def new_unit(self):
        self.stop_live(); self._reset_live_tree(); self.live_session=None
        self.live_state_var.set('Live: READY - NEW UNIT'); self.guided_ocr_var.set('OCR: --'); self.guided_quality_var.set('Target: --'); self._update_zone_ui()
        log.info('NEW_UNIT_RESET explicit=True')

    def _pick_images(self):
        return list(filedialog.askopenfilenames(
            title='Select Label Photos',
            filetypes=[('Images','*.jpg *.jpeg *.png *.bmp'),('All Files','*.*')]
        ))

    def select_images(self):
        paths=self._pick_images()
        if not paths:return
        self.image_paths=paths
        self.multi_image_result=None
        self.image_path.set(f"{len(paths)} image(s): {os.path.basename(paths[0])}")
        self.image_batch_var.set(f"Images: {len(paths)} | Initial batch ready | Guided 5-photo plan active")
        self._show_image(paths[0],self.image_preview)

    def add_images(self):
        paths=self._pick_images()
        if not paths:return
        self.image_paths.extend(paths)
        self.image_path.set(f"{len(self.image_paths)} image(s): {os.path.basename(self.image_paths[0])}")
        self.image_batch_var.set(f"Images: {len(self.image_paths)} | Added {len(paths)} image(s) | Run / Analyze New will reuse previous cache")
        self._show_image(paths[-1],self.image_preview)

    def _show_image(self,path,label):
        try:
            img=Image.open(path); img.thumbnail((700,650)); photo=ImageTk.PhotoImage(img); label.config(image=photo,text=''); label.image=photo
        except Exception as e:messagebox.showerror('Image Error',str(e))

    def _render_multi_image_result(self,result):
        color='green' if result.overall in ('PASS','PASS_WITH_MANUAL_REVIEW') else ('#B8860B' if result.overall=='NEED_MORE_IMAGE' else 'red')
        self.image_overall.config(text=result.overall,fg=color)
        for x in self.image_tree.get_children():self.image_tree.delete(x)
        try:self.image_manual_list.delete(0,"end"); self.image_manual_pass_btn.config(state="disabled"); self.image_manual_refresh_btn.config(state="disabled")
        except Exception:pass
        required=self.multi_image_engine._required_items()
        for item in required:
            if item in result.conflicts:
                self.image_tree.insert('', 'end',values=(item,'CONFLICT','','','Multiple images','','Conflicting evidence'))
                continue
            ev=result.evidence.get(item)
            if ev:
                self.image_tree.insert('', 'end',values=(item,ev.result,ev.actual,ev.expected,ev.source_image,f"{ev.quality_score:.3f}",ev.message))
            else:
                self.image_tree.insert('', 'end',values=(item,'NEED_MORE_IMAGE','','','','','No usable evidence'))
        self.image_batch_var.set(
            f"Images: {result.image_count} | Identity: {result.identity_status} | "
            f"Need more: {len(result.unresolved_items)} | Report: {result.report_path}"
        )
        self.status_var.set(f"Multi-image inspection {result.overall} | {result.session_dir}")
        self._refresh_manual_review_list()

    def _refresh_manual_review_list(self):
        try:
            self.image_manual_list.delete(0,"end")
        except Exception:
            return
        result=self.multi_image_result
        if result is None:
            try:self.image_manual_pass_btn.config(state="disabled"); self.image_manual_refresh_btn.config(state="disabled")
            except Exception:pass
            return
        candidates=[]
        required=self.multi_image_engine._required_items()
        for item in required:
            ev=result.evidence.get(item)
            auto="CONFLICT" if item in result.conflicts else (ev.result if ev else "NEED_MORE_IMAGE")
            if auto in ("PASS","MANUAL_PASS"):
                continue
            mode=self.multi_image_engine.manual_attention_mode(item)
            candidates.append((item,auto,mode))
        for item,auto,mode in candidates:
            label="MANUAL PASS OK" if mode=="OVERRIDE_ALLOWED" else "REVIEW ONLY"
            self.image_manual_list.insert("end",f"[{auto}] [{label}] {item}")
        self._manual_review_items=[x[0] for x in candidates]
        self._manual_review_modes=[x[2] for x in candidates]
        state="normal" if candidates and not self.image_job_running else "disabled"
        try:self.image_manual_pass_btn.config(state=state); self.image_manual_refresh_btn.config(state="normal")
        except Exception:pass

    def _manual_review_image_path(self, item: str) -> str:
        """Resolve the best source photo for the selected evidence item."""
        if self.multi_image_result is None:
            return ''
        ev=self.multi_image_result.evidence.get(item)
        source=str(ev.source_image if ev else '')
        for p in self.image_paths:
            if os.path.basename(p) and os.path.basename(p) in source:
                return p
        return self.image_paths[0] if self.image_paths else ''

    def _golden_review_image_path(self) -> str:
        try:
            profile=self.multi_image_engine.profile if self.multi_image_engine else {}
            gi=(profile or {}).get('golden_import',{}) or {}
            candidate=str(gi.get('candidate_layout_image',''))
            if candidate and os.path.exists(candidate):
                return candidate
            asset=str(gi.get('asset_dir',''))
            if asset and os.path.isdir(asset):
                files=[]
                for ext in ('*.png','*.jpg','*.jpeg','*.bmp','*.webp'):
                    files.extend(pathlib.Path(asset).rglob(ext))
                if files:
                    return str(max(files,key=lambda x:x.stat().st_size))
        except Exception:
            pass
        return ''

    def _show_manual_golden_review(self, items: list[str], note: str):
        """Golden-assisted review for one non-PASS item.

        Every non-PASS item can be inspected here. Only items explicitly
        classified OVERRIDE_ALLOWED expose Confirm PASS; traceability items
        remain REVIEW_ONLY and can be logged/kept/rechecked without silently
        changing machine identity data.
        """
        item=items[0]
        mode=self.multi_image_engine.manual_attention_mode(item)
        actual_path=self._manual_review_image_path(item)
        golden_path=self._golden_review_image_path()
        win=tk.Toplevel(self); win.title('Manual Review - Actual vs Golden / 人工復判對照'); win.geometry('1320x790'); win.transient(self)
        top=ttk.Frame(win,padding=8); top.pack(fill='x')
        ttk.Label(top,text=f'Inspection Item: {item}',font=('Segoe UI',11,'bold')).pack(anchor='w')
        ev=self.multi_image_result.evidence.get(item) if self.multi_image_result else None
        auto='CONFLICT' if (self.multi_image_result and item in self.multi_image_result.conflicts) else (ev.result if ev else 'NEED_MORE_IMAGE')
        actual=(ev.actual if ev else '')
        expected=(ev.expected if ev else '')
        ttk.Label(top,text=f"Mode: {mode}   |   Automatic: {auto}",foreground=('#8A5A00' if mode=='REVIEW_ONLY' else '#006400')).pack(anchor='w',pady=(3,0))
        ttk.Label(top,text=f"Actual: {actual or '-'}   |   Expected: {expected or '-'}",foreground='#444').pack(anchor='w',pady=(2,0))
        ttk.Label(top,text=f"Reason: {(ev.message if ev else 'No usable evidence')}",foreground='#555',wraplength=1260).pack(anchor='w',pady=(2,0))
        if mode=='REVIEW_ONLY':
            ttk.Label(top,text='REVIEW ONLY: this item is identity/barcode/consistency data and cannot be changed to PASS by a single visual click.',foreground='#A00000').pack(anchor='w',pady=(4,0))
        body=ttk.Frame(win,padding=8); body.pack(fill='both',expand=True)
        left=ttk.LabelFrame(body,text='Actual / 實拍',padding=6); right=ttk.LabelFrame(body,text='Golden Reference / Golden 對照',padding=6)
        left.pack(side='left',fill='both',expand=True,padx=(0,4)); right.pack(side='left',fill='both',expand=True,padx=(4,0))
        photos=[]
        def put_image(parent,path,empty):
            if not path or not os.path.exists(path):
                ttk.Label(parent,text=empty,anchor='center',wraplength=560).pack(fill='both',expand=True); return
            try:
                im=Image.open(path).convert('RGB'); im.thumbnail((620,560),Image.Resampling.LANCZOS)
                ph=ImageTk.PhotoImage(im); photos.append(ph)
                ttk.Label(parent,image=ph,anchor='center').pack(fill='both',expand=True)
                ttk.Label(parent,text=os.path.basename(path),foreground='#666').pack(anchor='center',pady=(4,0))
            except Exception as exc:
                ttk.Label(parent,text=f'Cannot open image: {exc}').pack(fill='both',expand=True)
        put_image(left,actual_path,'No evidence image is available for this item.')
        put_image(right,golden_path,'No Golden layout image is available. Review the Golden/Profile before manual decision.')
        win._review_photos=photos
        buttons=ttk.Frame(win,padding=8); buttons.pack(fill='x')
        ttk.Label(buttons,text=f'Note: {note}').pack(side='left')
        def save_action(action):
            try:
                self.multi_image_result=self.multi_image_engine.record_manual_review_action(self.multi_image_result,item,action,note)
                self._render_multi_image_result(self.multi_image_result)
                self.image_progress_var.set(f"Manual review logged | {item} | {action}")
                win.destroy()
            except Exception as exc:
                messagebox.showerror('Manual Review Error',str(exc),parent=win)
        def confirm_pass():
            try:
                self.multi_image_result=self.multi_image_engine.apply_manual_pass(self.multi_image_result,[item],note)
                self.multi_image_result.manual_reviews.append({
                    'timestamp':datetime.now().isoformat(timespec='seconds'),'item':item,'action':'CONFIRM_PASS',
                    'mode':mode,'auto_result':auto,'final_result':'MANUAL_PASS','note':note,
                    'source_image':actual_path,'actual':actual,'expected':expected,
                })
                self.multi_image_result.report_path=self.multi_image_engine._write_excel(self.multi_image_result,self.multi_image_result.expected_work_order or {})
                pathlib.Path(self.multi_image_result.session_dir,'result.json').write_text(json.dumps(self.multi_image_engine._serialize(self.multi_image_result),ensure_ascii=False,indent=2),encoding='utf-8')
                self._render_multi_image_result(self.multi_image_result)
                self.image_progress_var.set(f"Manual PASS saved | {item} | {self.multi_image_result.overall}")
                win.destroy()
            except Exception as exc:
                messagebox.showerror('Manual Review Error',str(exc),parent=win)
        ttk.Button(buttons,text='Keep Auto / 保留自動判定',command=lambda:save_action('KEEP_AUTO')).pack(side='right',padx=4)
        ttk.Button(buttons,text='Confirm FAIL / 人工確認FAIL',command=lambda:save_action('CONFIRM_FAIL')).pack(side='right',padx=4)
        ttk.Button(buttons,text='Recheck / 重新辨識',command=lambda:(save_action('REQUEST_RECHECK'), self.after(100,self.recheck_unresolved))).pack(side='right',padx=4)
        if mode=='OVERRIDE_ALLOWED':
            ttk.Button(buttons,text='Confirm PASS / 人工確認PASS',command=confirm_pass).pack(side='right',padx=4)

    def manual_review_selected(self):
        if self.image_job_running:
            messagebox.showinfo("Manual Review","Wait for image inspection to finish first."); return
        if self.multi_image_result is None:
            messagebox.showinfo("Manual Review","Run Image Label Inspection first."); return
        sels=list(self.image_manual_list.curselection())
        if not sels:
            messagebox.showwarning("Manual Review","Select one non-PASS item first."); return
        items=[self._manual_review_items[i] for i in sels if i < len(self._manual_review_items)]
        if not items:return
        items=items[:1]  # one Golden/actual decision at a time for traceability
        note=(self.image_manual_note_var.get() or "Visual inspection confirmed").strip()
        # V1.9.8: show actual evidence and Golden reference before the operator
        # decides. Automatic evidence/result remains unchanged unless PASS is
        # explicitly confirmed.
        self._show_manual_golden_review(items,note)

    def _set_image_controls_busy(self, busy: bool):
        self.image_job_running=bool(busy)
        state_busy="disabled" if busy else "normal"
        for btn in (self.image_load_btn,self.image_add_btn,self.image_run_btn,self.image_recheck_btn,self.image_force_btn,self.image_reset_btn):
            try: btn.config(state=state_busy)
            except Exception: pass
        try:self.image_cancel_btn.config(state="normal" if busy else "disabled")
        except Exception:pass
        # Freeze profile selection while a worker is evaluating a snapshot so
        # results cannot be rendered under a different label profile.
        try:self.profile_combo.config(state="disabled" if busy else "readonly")
        except Exception:pass
        if busy:
            try:self.image_manual_pass_btn.config(state="disabled"); self.image_manual_refresh_btn.config(state="disabled")
            except Exception:pass
        else:
            self._refresh_manual_review_list()

    def _image_progress_callback(self, event: dict):
        self.image_worker_queue.put(("progress",dict(event or {})))

    def _start_image_job(self, paths, previous_session=None, target_items=None, action="initial"):
        if self.image_job_running:
            messagebox.showinfo('Image Inspection','An image inspection is already running.'); return
        if not paths:
            messagebox.showwarning('No Images','Load one or more label images first.'); return
        profile_name=self.profile_var.get()
        if not profile_name or profile_name not in self.profiles:
            messagebox.showerror('Image Inspection','No valid profile selected.'); return
        profile=dict(self.profiles[profile_name][1])
        expected=dict(self._expected())
        worker_paths=list(paths)
        previous=previous_session
        targets=None if target_items is None else set(target_items)
        self.image_cancel_event.clear()
        self._set_image_controls_busy(True)
        self.image_progress_var.set(f"Starting {action} inspection | {len(worker_paths)} image(s)")
        self.status_var.set('Image inspection running in background...')

        def worker():
            try:
                engine=MultiImageInspectionEngine(profile, software_version=__version__)
                result=engine.inspect_batch(
                    worker_paths,'image_records',expected,previous_session=previous,
                    progress_callback=self._image_progress_callback,
                    cancel_event=self.image_cancel_event,target_items=targets,
                )
                self.image_worker_queue.put(("result",result))
            except Exception as exc:
                self.image_worker_queue.put(("error",(str(exc),traceback.format_exc())))

        self.image_worker_thread=threading.Thread(target=worker,name='ImageInspectionWorker',daemon=True)
        self.image_worker_thread.start()
        self._poll_image_worker()

    def _poll_image_worker(self):
        processed=False
        try:
            while True:
                kind,payload=self.image_worker_queue.get_nowait(); processed=True
                if kind=='progress':
                    stage=payload.get('stage','working')
                    idx=payload.get('index',0); total=payload.get('total',0)
                    name=payload.get('image','')
                    elapsed=payload.get('elapsed_ms')
                    suffix=f" | {elapsed:.0f} ms" if isinstance(elapsed,(int,float)) else ''
                    self.image_progress_var.set(f"{stage}: {idx}/{total} {name}{suffix}".strip())
                elif kind=='result':
                    self.multi_image_result=payload
                    self._render_multi_image_result(payload)
                    self.image_progress_var.set(f"Completed | {payload.image_count} image(s) | {payload.overall}")
                    self._set_image_controls_busy(False)
                elif kind=='error':
                    msg,tb=payload
                    log.error('MULTI_IMAGE_WORKER_ERROR %s\n%s',msg,tb)
                    self.image_progress_var.set('Inspection error')
                    self._set_image_controls_busy(False)
                    messagebox.showerror('Image Inspection Error',msg)
        except queue.Empty:
            pass
        if self.image_job_running:
            self.image_poll_job=self.after(100,self._poll_image_worker)
        elif processed:
            self.image_poll_job=None

    def cancel_image_inspection(self):
        if not self.image_job_running:return
        self.image_cancel_event.set()
        self.image_progress_var.set('Cancel requested; finishing current stage...')

    def inspect_images(self):
        # V1.8.2 incremental mode. After the first run we may pass the complete
        # selected list again: the engine fingerprints it and skips every image
        # already represented in the session. Only new content is analyzed.
        if self.multi_image_result is None:
            self._start_image_job(list(self.image_paths),previous_session=None,target_items=None,action='initial')
            return
        targets=set(self.multi_image_result.unresolved_items) | set(self.multi_image_result.conflicts.keys())
        self._start_image_job(
            list(self.image_paths), previous_session=self.multi_image_result,
            target_items=targets, action='incremental / cached',
        )

    def force_reanalyze_images(self):
        if not self.image_paths:
            messagebox.showwarning('Force Re-analyze','Load one or more label images first.'); return
        if not messagebox.askyesno(
            'Force Re-analyze All',
            'Re-analyze ALL loaded images from scratch?\n\nThis bypasses the V1.9.8 session cache and is intended for engineering verification.'
        ):
            return
        # New session deliberately discards prior automatic/manual decisions.
        self.multi_image_result=None
        self._start_image_job(list(self.image_paths),previous_session=None,target_items=None,action='force re-analyze all')

    def recheck_unresolved(self):
        if self.multi_image_result is None:
            messagebox.showinfo('Recheck','Run the initial batch first.'); return
        paths=self._pick_images()
        if not paths:return
        self.image_paths.extend(paths)
        targets=set(self.multi_image_result.unresolved_items) | set(self.multi_image_result.conflicts.keys())
        self._show_image(paths[-1],self.image_preview)
        self._start_image_job(paths,previous_session=self.multi_image_result,target_items=targets,action='recheck unresolved')

    def reset_image_session(self):
        self.image_paths=[]; self.multi_image_result=None; self.image_path.set('')
        self.image_batch_var.set('Images: 0 | Ready')
        self.image_progress_var.set('Idle')
        self.image_overall.config(text='--',fg='black')
        self.image_preview.config(image='',text='Load one or more label photos'); self.image_preview.image=None
        for x in self.image_tree.get_children():self.image_tree.delete(x)
        try:
            self.image_manual_list.delete(0,"end")
            self.image_manual_pass_btn.config(state="disabled")
            self.image_manual_refresh_btn.config(state="disabled")
        except Exception:pass

    def destroy(self):
        try:self.image_cancel_event.set()
        except Exception:pass
        try:self.stop_live()
        except Exception:pass
        try:
            if self.worker_poll_job:
                self.after_cancel(self.worker_poll_job)
                self.worker_poll_job=None
        except Exception:pass
        try:self.camera.close()
        except Exception:pass
        try:self.ocr_service.stop()
        except Exception:pass
        super().destroy()

def main():
    App().mainloop()
