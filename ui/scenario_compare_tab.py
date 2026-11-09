from pathlib import Path
from PySide6.QtCore import Qt, QObject, QThread, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QFileDialog,QMessageBox,QTableWidget,QTableWidgetItem,QDialog,QDialogButtonBox,QSplitter,QTreeWidget,QTreeWidgetItem,QHeaderView,QProgressDialog
from services.scenario_comparison_service import compare_scenarios
from services.comparison_excel_exporter import export_comparison
# AOKTS_COMPARE_DOUBLE_CLICK_V9
class TriggerComparisonDialog(QDialog):
    def __init__(self,item,parent=None):
        super().__init__(parent); self.item=item
        snap=item.modified or item.original
        name=snap.name if snap else 'Unnamed Trigger'
        self.setWindowTitle(f"Trigger [{item.trigger_id}] Comparison - {name}"); self.resize(1100,720)
        l=QVBoxLayout(self); h=QLabel(f"Trigger [{item.trigger_id}] {name}"); h.setStyleSheet("font-size:16px;font-weight:bold;"); l.addWidget(h)
        sp=QSplitter(Qt.Horizontal); sp.addWidget(self.build('Original Scenario',item.original,'original')); sp.addWidget(self.build('Modified Scenario',item.modified,'modified')); sp.setSizes([550,550]); l.addWidget(sp,1)
        b=QDialogButtonBox(QDialogButtonBox.Close); b.rejected.connect(self.reject); l.addWidget(b)
    def build(self,title,snap,side):
        w=QWidget(); l=QVBoxLayout(w); lab=QLabel(title); lab.setStyleSheet('font-weight:bold;font-size:14px;'); l.addWidget(lab)
        tree=QTreeWidget(); tree.setHeaderLabels(['Item / Field','Value','Change']); tree.header().setSectionResizeMode(0,QHeaderView.ResizeToContents); tree.header().setSectionResizeMode(1,QHeaderView.Stretch); tree.header().setSectionResizeMode(2,QHeaderView.ResizeToContents); l.addWidget(tree)
        if snap is None: tree.addTopLevelItem(QTreeWidgetItem(['Trigger does not exist','',''])); return w
        root=QTreeWidgetItem(['Trigger','','']); tree.addTopLevelItem(root)
        for fld,val in [('Name',snap.name),('Enabled',snap.enabled),('Looping',snap.looping)]: self.field(root,fld,val,side,'Trigger',None,fld)
        for section,items in [('Condition',snap.conditions),('Effect',snap.effects)]:
            top=QTreeWidgetItem([f"{section}s ({len(items)})",'', '']); tree.addTopLevelItem(top)
            for obj in items:
                n=QTreeWidgetItem([f"{obj.index}. {obj.type_name}",'','']); top.addChild(n); self.logic_status(n,side,section,obj.index)
                # AOKTS_COMPARE_SEMANTIC_INSPECTOR_V10
                for fld,val in self.visible_values(obj, section, obj.index):
                    self.field(n,fld,val,side,section,obj.index,fld)
        tree.expandAll(); return w
    def changes(self,section,index,field=None):
        out=[c for c in self.item.changes if c.section==section and c.item_index==index]
        if field is not None: out=[c for c in out if c.field.lower()==field.lower()]
        return out
    def paint(self,row,status,text):
        colors={'Added':'#183C2A','Removed':'#432326','Modified':'#463A1F'}; row.setText(2,text)
        for c in range(3): row.setBackground(c,QColor(colors[status])); row.setForeground(c,QColor('#F3F4F6'))
    def logic_status(self,row,side,section,index):
        cs=self.changes(section,index)
        item=next((c for c in cs if c.field=='Item'),None)
        if item:
            if item.modified=='Added' and side=='modified': self.paint(row,'Added','New')
            elif item.original=='Removed' and side=='original': self.paint(row,'Removed','Deleted')
        elif cs: self.paint(row,'Modified','Modified')
    def field(self,parent,label,value,side,section,index,field):
        row=QTreeWidgetItem([str(label),self.fmt(value),'']); parent.addChild(row); cs=self.changes(section,index,field)
        if not cs:return
        c=cs[0]
        if c.original is None and side=='modified': self.paint(row,'Added','New')
        elif c.modified is None and side=='original': self.paint(row,'Removed','Deleted')
        elif c.original is not None and c.modified is not None: self.paint(row,'Modified','Modified')
    def visible_values(self,obj,section,index):
        """Show active values plus every field involved in a detected change."""
        changed={c.field.lower() for c in self.changes(section,index) if c.field not in ('Item','Type')}
        visible=[]
        for field,value in obj.values:
            if field.lower() in changed or self.meaningful(field,value):
                visible.append((self.label(field),value))
        return visible

    @staticmethod
    def meaningful(field,value):
        # AoE2ScenarioParser commonly uses -1 / blank / None as inactive sentinels.
        if value is None or value == '' or value == -1:
            return False
        if isinstance(value,(tuple,list,dict)) and len(value)==0:
            return False
        # Keep 0 because it can be a legitimate AoE2 parameter. A changed field
        # is always retained regardless of its value by visible_values().
        return True

    @staticmethod
    def label(field):
        aliases={
            'trigger_id':'Target Trigger',
            'source_player':'Source Player',
            'target_player':'Target Player',
            'object_list_unit_id':'Unit ID',
            'object_list_unit_id_2':'Second Unit ID',
            'location_x':'Location X', 'location_y':'Location Y',
            'area_x1':'Area X1', 'area_y1':'Area Y1',
            'area_x2':'Area X2', 'area_y2':'Area Y2',
            'display_time':'Display Time', 'string_id':'String ID',
            'sound_name':'Sound', 'object_group':'Object Group',
            'object_type':'Object Type', 'object_state':'Object State',
            'attack_stance':'Attack Stance', 'visibility_state':'Visibility State',
            'ai_signal_value':'AI Signal Value', 'ai_script_goal':'AI Script Goal',
            'force_research_technology':'Force Research Technology',
        }
        return aliases.get(field,field.replace('_',' ').title())

    @staticmethod
    def fmt(v):
        if v is None:return ''
        if isinstance(v,bool):return 'Yes' if v else 'No'
        if isinstance(v,tuple):return ', '.join(str(x) for x in v)
        return str(v)

# AOKTS_COMPARE_PROGRESS_V16
class CompareWorker(QObject):
    finished=Signal(object)
    failed=Signal(str)
    def __init__(self,loader,original_path,modified_path):
        super().__init__(); self.loader=loader; self.original_path=original_path; self.modified_path=modified_path
    def run(self):
        try:
            original=self.loader(self.original_path)
            modified=self.loader(self.modified_path)
            self.finished.emit(compare_scenarios(original,modified,self.original_path,self.modified_path))
        except Exception as error:
            self.failed.emit(str(error))

class ScenarioCompareTab(QWidget):
    def __init__(self,loader,parent=None):
        super().__init__(parent); self.loader=loader; self.a=""; self.b=""; self.result=None
        l=QVBoxLayout(self); l.addWidget(QLabel("Scenario Comparison - READ ONLY")); self.la=QLabel("Original: not selected"); self.lb=QLabel("Modified: not selected"); l.addWidget(self.la); l.addWidget(self.lb)
        h=QHBoxLayout(); ba=QPushButton("Load Original Scenario..."); bb=QPushButton("Load Modified Scenario..."); bc=QPushButton("Compare"); self.be=QPushButton("Export to Excel..."); self.be.setEnabled(False)
        ba.clicked.connect(self.pick_a); bb.clicked.connect(self.pick_b); bc.clicked.connect(self.compare); self.be.clicked.connect(self.export)
        for x in (ba,bb,bc,self.be):h.addWidget(x)
        l.addLayout(h); self.table=QTableWidget(0,4); self.table.setHorizontalHeaderLabels(["Trigger ID","Original","Modified","Status"]); self.table.setEditTriggers(QTableWidget.NoEditTriggers); self.table.cellDoubleClicked.connect(self.show_trigger_comparison); l.addWidget(self.table); self.summary=QLabel("Select both scenarios. Double-click a trigger to inspect conditions and effects.");l.addWidget(self.summary)
    def pick(self,title): return QFileDialog.getOpenFileName(self,title,str(Path.home()),"AoE2 Scenario (*.aoe2scenario);;All Files (*)")[0]
    def pick_a(self):
        p=self.pick("Select Original Scenario")
        if p:self.a=p;self.la.setText("Original: "+p)
    def pick_b(self):
        p=self.pick("Select Modified Scenario")
        if p:self.b=p;self.lb.setText("Modified: "+p)
    def compare(self):
        if not self.a or not self.b:
            QMessageBox.warning(self,"Files Required","Select both scenario files first.")
            return
        self.compare_messages=[
            "Researching Loom... because safety first.",
            "Sending a Scout Cavalry to inspect the trigger IDs...",
            "Villagers are sorting triggers into neat little farms...",
            "Wololo! Converting scenario data into useful differences...",
            "Waiting for the Town Center to finish producing comparisons...",
            "Checking whether anyone deleted the Wonder...",
            "Tasking monks with comparing conditions and effects...",
            "Advancing to the Imperial Age of spreadsheet analysis...",
            "Trying not to get housed at 199/200 triggers...",
            "Polishing the trebuchets before presenting the results...",
        ]
        self.compare_message_index=0
        self.compare_progress=QProgressDialog(self.compare_messages[0],"",0,0,self)
        self.compare_progress.setWindowTitle("Comparing Scenarios")
        self.compare_progress.setCancelButton(None)
        self.compare_progress.setWindowModality(Qt.WindowModal)
        self.compare_progress.setMinimumDuration(0)
        self.compare_progress.setAutoClose(False)
        self.compare_progress.setMinimumWidth(520)
        self.compare_progress.show()

        self.compare_timer=QTimer(self)
        self.compare_timer.setInterval(2500)
        self.compare_timer.timeout.connect(self.rotate_compare_message)
        self.compare_timer.start()

        self.compare_thread=QThread(self)
        self.compare_worker=CompareWorker(self.loader,self.a,self.b)
        self.compare_worker.moveToThread(self.compare_thread)
        self.compare_thread.started.connect(self.compare_worker.run)
        self.compare_worker.finished.connect(self.finish_compare)
        self.compare_worker.failed.connect(self.fail_compare)
        self.compare_worker.finished.connect(self.compare_thread.quit)
        self.compare_worker.failed.connect(self.compare_thread.quit)
        self.compare_thread.finished.connect(self.compare_worker.deleteLater)
        self.compare_thread.finished.connect(self.compare_thread.deleteLater)
        self.compare_thread.start()

    def rotate_compare_message(self):
        progress=getattr(self,"compare_progress",None)
        if progress is None:return
        self.compare_message_index=(self.compare_message_index+1)%len(self.compare_messages)
        progress.setLabelText(self.compare_messages[self.compare_message_index])

    def stop_compare_progress(self):
        timer=getattr(self,"compare_timer",None)
        if timer is not None:timer.stop()
        progress=getattr(self,"compare_progress",None)
        if progress is not None:progress.close()
        self.compare_progress=None

    def fail_compare(self,message):
        self.stop_compare_progress()
        QMessageBox.critical(self,"Comparison Failed",message)

    def finish_compare(self,result):
        self.stop_compare_progress()
        self.result=result
        # AOKTS_COMPARE_COMPLETE_LIST_V7
        labels={"Added":"New Trigger","Removed":"Deleted Trigger","Modified":"Modified Trigger"}
        row_colors={"Added":"#183C2A","Removed":"#432326","Modified":"#463A1F"}
        status_colors={"Added":"#247A49","Removed":"#9A3E46","Modified":"#9A772A"}
        text_color=QColor("#F3F4F6")
        unchanged_text=QColor("#D3D7DC")
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setStyleSheet("QTableWidget { gridline-color: #3B3F45; }QTableWidget::item:selected { background-color: #365F86; color: #FFFFFF; }")
        # Service output is already the union of both scenarios in Trigger-ID order.
        rows=list(self.result.triggers)
        self.table.setRowCount(len(rows))
        counts={"Added":0,"Removed":0,"Modified":0}
        for r,x in enumerate(rows):
            raw=x.status.value
            if raw in counts: counts[raw]+=1
            status_label=labels.get(raw, "")
            vals=[str(x.trigger_id),x.original.name if x.original else "",x.modified.name if x.modified else "",status_label]
            for c,v in enumerate(vals):
                item=QTableWidgetItem(v)
                if raw in labels:
                    item.setForeground(text_color)
                    item.setBackground(QColor(status_colors[raw] if c==3 else row_colors[raw]))
                else:
                    # Unchanged triggers remain visible but deliberately unhighlighted.
                    item.setForeground(unchanged_text)
                self.table.setItem(r,c,item)
        self.summary.setText(f"Triggers: {len(rows)} | New: {counts['Added']} | Deleted: {counts['Removed']} | Modified: {counts['Modified']}")
        self.be.setEnabled(True); self.table.resizeColumnsToContents()
    def show_trigger_comparison(self,row,column=0):
        if self.result is None:return
        cell=self.table.item(row,0)
        if cell is None:return
        try: trigger_id=int(cell.text())
        except (TypeError,ValueError):return
        item=next((x for x in self.result.triggers if x.trigger_id==trigger_id),None)
        if item is not None: TriggerComparisonDialog(item,self).exec()
    def export(self):
        p=QFileDialog.getSaveFileName(self,"Export Comparison","scenario_comparison.xlsx","Excel Workbook (*.xlsx)")[0]
        if not p:return
        if not p.lower().endswith(".xlsx"):p+=".xlsx"
        try:export_comparison(self.result,p)
        except Exception as e:QMessageBox.critical(self,"Export Failed",str(e));return
        QMessageBox.information(self,"Export Complete","Comparison exported successfully.")
