from dataclasses import dataclass, field, asdict, is_dataclass
from enum import Enum
from typing import Any, Mapping

class ChangeStatus(str, Enum): SAME="Same"; MODIFIED="Modified"; ADDED="Added"; REMOVED="Removed"; MOVED="Moved"
@dataclass(frozen=True)
class LogicSnapshot: index:int; type_name:str; values:tuple
@dataclass(frozen=True)
class TriggerSnapshot: trigger_id:int; position:int; name:str; enabled:bool; looping:bool; conditions:tuple; effects:tuple
@dataclass(frozen=True)
class FieldChange: section:str; item_index:int|None; item_type:str; field:str; original:Any; modified:Any
@dataclass(frozen=True)
class TriggerComparison: trigger_id:int; status:ChangeStatus; original:TriggerSnapshot|None; modified:TriggerSnapshot|None; changes:tuple=field(default_factory=tuple)
@dataclass(frozen=True)
class ScenarioComparison:
    original_path:str; modified_path:str; triggers:tuple
    def counts(self):
        out={s.value:0 for s in ChangeStatus}
        for x in self.triggers: out[x.status.value]+=1
        return out

def _scalar(v):
    if v is None or isinstance(v,(str,int,float,bool)): return v
    if isinstance(v,Enum): return v.value
    if isinstance(v,(list,tuple)): return tuple(_scalar(x) for x in v)
    if isinstance(v,Mapping): return tuple(sorted((str(k),_scalar(x)) for k,x in v.items()))
    return str(v)

def _values(o):
    raw=asdict(o) if is_dataclass(o) else vars(o) if hasattr(o,"__dict__") else {}
    return tuple(sorted((k,_scalar(v)) for k,v in raw.items() if not k.startswith("_") and not callable(v) and isinstance(v,(str,int,float,bool,type(None),Enum,list,tuple,dict))))
# AOKTS_COMPARE_LOGIC_NAMES_V11
def _logic(o,i):
    condition_type=getattr(o,"condition_type",None)
    effect_type=getattr(o,"effect_type",None)
    t=condition_type if condition_type is not None else effect_type

    name=getattr(t,"name",None)
    if not name:
        # AoE2ScenarioParser objects may expose a numeric type while the
        # Python class itself carries the semantic name. Prefer that class
        # name before falling back to the raw numeric value.
        class_name=type(o).__name__
        cleaned=(class_name.replace("Condition","").replace("Effect","")
                 .replace("_"," ").strip())
        # Convert CamelCase into words without adding a dependency.
        words=[]
        current=""
        for ch in cleaned:
            if ch.isupper() and current and not current[-1].isupper():
                words.append(current); current=ch
            else:
                current+=ch
        if current: words.append(current)
        candidate=" ".join(words).strip()
        if candidate and candidate.lower() not in ("effect","condition","object"):
            name=candidate

    # Known AoE2 effect IDs used when the parser class is generic.
    if not name or name.replace(".","",1).isdigit():
        effect_names={
            2: "Research Technology",
        }
        if effect_type is not None:
            try: name=effect_names.get(int(effect_type),name)
            except (TypeError,ValueError): pass

    return LogicSnapshot(i,name or str(t or type(o).__name__),_values(o))
def snapshot_scenario(s):
    m=getattr(s,"trigger_manager",None)
    if m is None: raise ValueError("Scenario has no trigger_manager")
    out=[]
    for p,t in enumerate(list(getattr(m,"triggers",())),start=1):
        out.append(TriggerSnapshot(int(t.trigger_id),p,(getattr(t,"name","") or "Unnamed Trigger").strip(),bool(getattr(t,"enabled",True)),bool(getattr(t,"looping",False)),tuple(_logic(x,i) for i,x in enumerate(getattr(t,"conditions",()),1)),tuple(_logic(x,i) for i,x in enumerate(getattr(t,"effects",()),1))))
    ids=[x.trigger_id for x in out]
    if len(ids)!=len(set(ids)): raise ValueError("Duplicate trigger IDs found")
    return tuple(sorted(out,key=lambda x:x.trigger_id))
def _logic_changes(section,a,b):
    changes=[]
    for z in range(max(len(a),len(b))):
        i=z+1; old=a[z] if z<len(a) else None; new=b[z] if z<len(b) else None
        if old is None: changes.append(FieldChange(section,i,new.type_name,"Item",None,"Added")); continue
        if new is None: changes.append(FieldChange(section,i,old.type_name,"Item","Removed",None)); continue
        if old.type_name!=new.type_name: changes.append(FieldChange(section,i,new.type_name,"Type",old.type_name,new.type_name))
        ov,nv=dict(old.values),dict(new.values)
        for f in sorted(set(ov)|set(nv)):
            if ov.get(f)!=nv.get(f): changes.append(FieldChange(section,i,new.type_name,f,ov.get(f),nv.get(f)))
    return changes
# AOKTS_COMPARE_THREE_STATUSES_V6
def _changes(a,b):
    c=[]
    # Position is ignored: trigger order is normalised by trigger ID.
    for f in ("name","enabled","looping"):
        x,y=getattr(a,f),getattr(b,f)
        if x!=y:c.append(FieldChange("Trigger",None,"",f.title(),x,y))
    c+=_logic_changes("Condition",a.conditions,b.conditions); c+=_logic_changes("Effect",a.effects,b.effects)
    return tuple(c)
def compare_scenarios(a,b,ap="",bp=""):
    A={x.trigger_id:x for x in snapshot_scenario(a)}; B={x.trigger_id:x for x in snapshot_scenario(b)}; rows=[]
    for i in sorted(set(A)|set(B)):
        x,y=A.get(i),B.get(i)
        if x is None: rows.append(TriggerComparison(i,ChangeStatus.ADDED,None,y)); continue
        if y is None: rows.append(TriggerComparison(i,ChangeStatus.REMOVED,x,None)); continue
        c=_changes(x,y)
        # AOKTS_COMPARE_COMPLETE_LIST_V7
        # Keep every matched Trigger ID in the result. SAME is displayed normally;
        # only New / Deleted / Modified receive visible status labels/colouring.
        st=ChangeStatus.MODIFIED if c else ChangeStatus.SAME
        rows.append(TriggerComparison(i,st,x,y,c))
    return ScenarioComparison(ap,bp,tuple(rows))
