# AOKTS_COMPARE_EXPANDABLE_EXCEL_V12
"""Excel export for read-only scenario comparisons.

The Trigger Details worksheet uses Excel outline levels. Each trigger is a
visible summary row; its properties, conditions, effects and values are hidden
beneath it and can be expanded with Excel's + outline control.
"""
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Border, Side, Alignment
from openpyxl.utils import get_column_letter

LABELS = {
    "Added": "New Trigger",
    "Removed": "Deleted Trigger",
    "Modified": "Modified Trigger",
    "Same": "",
}
STATUS_COLOURS = {
    "New Trigger": "C6EFCE",
    "Deleted Trigger": "FFC7CE",
    "Modified Trigger": "FFEB9C",
}
DARK_STATUS_COLOURS = {
    "New Trigger": "247A49",
    "Deleted Trigger": "9A3E46",
    "Modified Trigger": "9A772A",
}
THIN_GREY = Side(style="thin", color="D9E1F2")


def _finish_sheet(sheet, freeze="A2", filter_rows=True):
    if freeze:
        sheet.freeze_panes = freeze
    if filter_rows and sheet.max_row >= 1:
        sheet.auto_filter.ref = sheet.dimensions
    for cell in sheet[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="1F4E78")
        cell.alignment = Alignment(vertical="center")
    for column in sheet.columns:
        width = min(max(len(str(cell.value or "")) for cell in column) + 2, 52)
        sheet.column_dimensions[get_column_letter(column[0].column)].width = width


def _status_label(item):
    return LABELS.get(item.status.value, "")


def _meaningful(value):
    if value is None or value == "" or value == -1:
        return False
    if isinstance(value, (tuple, list, dict)) and len(value) == 0:
        return False
    return True


def _field_label(field):
    aliases = {
        "trigger_id": "Target Trigger",
        "source_player": "Source Player",
        "target_player": "Target Player",
        "object_list_unit_id": "Unit ID",
        "object_list_unit_id_2": "Second Unit ID",
        "location_x": "Location X",
        "location_y": "Location Y",
        "area_x1": "Area X1",
        "area_y1": "Area Y1",
        "area_x2": "Area X2",
        "area_y2": "Area Y2",
        "display_time": "Display Time",
        "string_id": "String ID",
        "sound_name": "Sound",
        "object_group": "Object Group",
        "object_type": "Object Type",
        "object_state": "Object State",
        "attack_stance": "Attack Stance",
        "visibility_state": "Visibility State",
        "ai_signal_value": "AI Signal Value",
        "ai_script_goal": "AI Script Goal",
        "force_research_technology": "Force Research Technology",
    }
    return aliases.get(field, field.replace("_", " ").title())


def _format_value(value):
    if value is None:
        return ""
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, tuple):
        return ", ".join(str(item) for item in value)
    return str(value)


def _changed_fields(item, section, item_index):
    return {
        change.field.lower()
        for change in item.changes
        if change.section == section
        and change.item_index == item_index
        and change.field not in ("Item", "Type")
    }


def _visible_values(item, logic, section):
    changed = _changed_fields(item, section, logic.index)
    return [
        (field, value)
        for field, value in logic.values
        if field.lower() in changed or _meaningful(value)
    ]


def _logic_change_status(item, section, index):
    changes = [
        change for change in item.changes
        if change.section == section and change.item_index == index
    ]
    item_change = next((change for change in changes if change.field == "Item"), None)
    if item_change is not None:
        if item_change.modified == "Added":
            return "New"
        if item_change.original == "Removed":
            return "Deleted"
    if changes:
        return "Modified"
    return ""


def _append_detail(sheet, level, trigger_id, side, section, item_no,
                   item_name, field, value, change=""):
    sheet.append([
        trigger_id, side, section, item_no, item_name,
        field, _format_value(value), change,
    ])
    row = sheet.max_row
    sheet.row_dimensions[row].outlineLevel = level
    sheet.row_dimensions[row].hidden = True
    if change:
        colour = {
            "New": "C6EFCE", "Deleted": "FFC7CE", "Modified": "FFEB9C"
        }.get(change, "FFEB9C")
        for cell in sheet[row]:
            cell.fill = PatternFill("solid", fgColor=colour)
    return row


def _append_snapshot_details(sheet, item, snapshot, side):
    if snapshot is None:
        _append_detail(
            sheet, 1, item.trigger_id, side, "Trigger", "", "",
            "Availability", "Trigger does not exist", "",
        )
        return

    trigger_changes = {
        change.field.lower(): change
        for change in item.changes if change.section == "Trigger"
    }
    for field, value in (
        ("Name", snapshot.name),
        ("Enabled", snapshot.enabled),
        ("Looping", snapshot.looping),
    ):
        change = "Modified" if field.lower() in trigger_changes else ""
        _append_detail(
            sheet, 1, item.trigger_id, side, "Trigger", "", "",
            field, value, change,
        )

    for section, collection in (
        ("Condition", snapshot.conditions),
        ("Effect", snapshot.effects),
    ):
        for logic in collection:
            logic_status = _logic_change_status(item, section, logic.index)
            _append_detail(
                sheet, 1, item.trigger_id, side, section, logic.index,
                logic.type_name, "", "", logic_status,
            )
            for field, value in _visible_values(item, logic, section):
                changed = field.lower() in _changed_fields(
                    item, section, logic.index
                )
                _append_detail(
                    sheet, 2, item.trigger_id, side, section, logic.index,
                    logic.type_name, _field_label(field), value,
                    "Modified" if changed else "",
                )


def export_comparison(comparison, output_path):
    workbook = Workbook()

    summary = workbook.active
    summary.title = "Summary"
    summary.append(["Metric", "Value"])
    summary.append(["Original Scenario", comparison.original_path])
    summary.append(["Modified Scenario", comparison.modified_path])
    counts = {"New Trigger": 0, "Deleted Trigger": 0, "Modified Trigger": 0}
    for item in comparison.triggers:
        label = _status_label(item)
        if label:
            counts[label] += 1
    summary.append(["Total Triggers", len(comparison.triggers)])
    for label, count in counts.items():
        summary.append([label, count])
    _finish_sheet(summary)

    triggers = workbook.create_sheet("Trigger Comparison")
    triggers.append([
        "Status", "Trigger ID", "Original Name", "Modified Name",
        "Original Position", "Modified Position", "Change Count",
    ])
    for item in comparison.triggers:
        label = _status_label(item)
        triggers.append([
            label,
            item.trigger_id,
            item.original.name if item.original else "",
            item.modified.name if item.modified else "",
            item.original.position if item.original else "",
            item.modified.position if item.modified else "",
            len(item.changes),
        ])
        row = triggers.max_row
        if label:
            for cell in triggers[row]:
                cell.fill = PatternFill("solid", fgColor=STATUS_COLOURS[label])
    _finish_sheet(triggers)

    # AOKTS_COMPARE_REMOVE_TRIGGER_DETAILS_V13
    # AOKTS_COMPARE_FULL_DETAILED_EXPORT_V14
    changes = workbook.create_sheet("Detailed Changes")
    changes.append([
        "Trigger ID", "Trigger Name", "Status", "Scenario", "Section",
        "Item Index", "Item Type", "Field", "Value", "Changed",
    ])

    def append_detail(item, scenario_side, section, item_index, item_type,
                      field, value, changed=""):
        name=(item.modified.name if item.modified else item.original.name)
        label=_status_label(item)
        changes.append([
            item.trigger_id, name, label, scenario_side, section,
            item_index or "", item_type, field, _format_value(value), changed,
        ])
        row=changes.max_row
        if label:
            colour=STATUS_COLOURS.get(label)
            if colour:
                for cell in changes[row]:
                    cell.fill=PatternFill("solid",fgColor=colour)

    def changed_field_names(item, section, index):
        return {
            c.field.lower() for c in item.changes
            if c.section==section and c.item_index==index
            and c.field not in ("Item","Type")
        }

    def logic_item_status(item, section, index):
        for c in item.changes:
            if c.section==section and c.item_index==index and c.field=="Item":
                if c.modified=="Added": return "New"
                if c.original=="Removed": return "Deleted"
        if any(c.section==section and c.item_index==index for c in item.changes):
            return "Modified"
        return ""

    def export_snapshot(item, snapshot, side):
        if snapshot is None:
            return
        # Trigger-level properties are included for changed/new/deleted triggers.
        trigger_changed={
            c.field.lower() for c in item.changes if c.section=="Trigger"
        }
        for field,value in (
            ("Name",snapshot.name),
            ("Enabled",snapshot.enabled),
            ("Looping",snapshot.looping),
        ):
            append_detail(
                item, side, "Trigger", "", "", field, value,
                "Yes" if field.lower() in trigger_changed else "",
            )

        for section,collection in (
            ("Condition",snapshot.conditions),
            ("Effect",snapshot.effects),
        ):
            for logic in collection:
                status=logic_item_status(item,section,logic.index)
                changed_names=changed_field_names(item,section,logic.index)
                # Only include logic objects relevant to a changed trigger when the
                # trigger itself is Modified. For a New/Deleted trigger, include all.
                if item.status.value=="Modified" and not status:
                    continue
                append_detail(
                    item, side, section, logic.index, logic.type_name,
                    "Item", logic.type_name, status,
                )
                for field,value in logic.values:
                    # Same semantic filtering as the in-app inspector: inactive parser
                    # sentinels are omitted unless the field itself changed.
                    if field.lower() not in changed_names and not _meaningful(value):
                        continue
                    append_detail(
                        item, side, section, logic.index, logic.type_name,
                        _field_label(field), value,
                        "Yes" if field.lower() in changed_names else "",
                    )

    for item in comparison.triggers:
        if item.status.value not in ("Added","Removed","Modified"):
            continue
        export_snapshot(item,item.original,"Original")
        export_snapshot(item,item.modified,"Modified")

    _finish_sheet(changes)
    changes.column_dimensions["B"].width=30
    changes.column_dimensions["G"].width=28
    changes.column_dimensions["H"].width=30
    changes.column_dimensions["I"].width=32

    workbook.save(output_path)
