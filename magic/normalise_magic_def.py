#!/usr/bin/env python3
import argparse, json, os, re, sys
from decimal import Decimal
from pathlib import Path

NAME = r'[^\s();+]+'


PDK_FALLBACK_LAYERS = {
    "sky130A": ["met1", "met2", "met3", "met4", "met5"],
    "sky130B": ["met1", "met2", "met3", "met4", "met5"],
    "gf180mcuD": ["Metal1", "Metal2", "Metal3", "Metal4", "Metal5"],
    # SG13G2 has TopMetal1/2, but the normal OpenROAD signal-routing stack
    # defaults to Metal1..Metal5.  Explicit obs selectors may still name top metals.
    "ihp-sg13g2": ["Metal1", "Metal2", "Metal3", "Metal4", "Metal5"],
    "ihp-sg13cmos5l": ["Metal1", "Metal2", "Metal3", "Metal4", "Metal5"],
}

def parse_csv_layers(value):
    xs=[x.strip() for x in value.split(",")]
    if not xs or any(not x for x in xs): die("empty layer in --metal-layers")
    return xs

def pdk_from_mag(mag_text):
    m=re.search(r'(?mi)^\s*tech\s+(\S+)\s*$',mag_text)
    return m.group(1) if m else None

def find_pdk_dir(root, pdk):
    if not root or not pdk: return None
    root=Path(root).expanduser()
    for q in (root/pdk, root/"share"/"pdk"/pdk, root/"pdks"/pdk):
        if q.is_dir(): return q
    return None

def layers_from_librelane_config(pdk_dir):
    candidates=[]
    for rel in ("libs.tech/librelane/config.tcl", "libs.tech/openlane/config.tcl"):
        q=pdk_dir/rel
        if q.is_file(): candidates.append(q)
    for q in candidates:
        try: t=q.read_text(errors="replace")
        except OSError: continue
        m=re.search(r'(?m)^\s*set\s+::env\(METAL_LAYER_NAMES\)\s+[\"{]([^\"}]+)[\"}]',t)
        if m:
            xs=m.group(1).split()
            if xs: return xs,q
    return None,None

def layers_from_tech_lef(pdk_dir):
    roots=[pdk_dir/"libs.tech"/"openroad", pdk_dir/"libs.tech"/"lef", pdk_dir/"libs.ref"]
    candidates=[]
    for r in roots:
        if not r.is_dir(): continue
        try:
            for q in r.rglob("*.lef"):
                n=q.name.lower()
                if "tech" in n or "technology" in n: candidates.append(q)
        except OSError: pass
    for q in candidates[:100]:
        try: t=q.read_text(errors="replace")
        except OSError: continue
        xs=[]
        for m in re.finditer(r'(?mis)^\s*LAYER\s+(\S+)\s*(.*?)^\s*END\s+\1\s*$',t):
            if re.search(r'(?mi)^\s*TYPE\s+ROUTING\s*;',m.group(2)): xs.append(m.group(1))
        if xs: return xs,q
    return None,None

def discover_metal_layers(pdk, pdk_root, override=None):
    if override:
        return parse_csv_layers(override),"--metal-layers"
    pdir=find_pdk_dir(pdk_root,pdk)
    if pdir:
        xs,src=layers_from_librelane_config(pdir)
        if xs: return xs,str(src)
        xs,src=layers_from_tech_lef(pdir)
        if xs: return xs,str(src)
    if pdk in PDK_FALLBACK_LAYERS:
        return list(PDK_FALLBACK_LAYERS[pdk]),f"built-in {pdk} fallback"
    die(f"cannot determine metal layers for PDK {pdk!r}; use --metal-layers")

def find_magic_tech(pdk_dir,pdk,override=None):
    if override:
        q=Path(override).expanduser()
        if not q.is_file(): die(f"Magic tech file not found: {q}")
        return q
    if not pdk_dir: return None
    for rel in (f"libs.tech/magic/{pdk}.tech", f"libs.tech/magic/{pdk.replace('-','_')}.tech"):
        q=pdk_dir/rel
        if q.is_file(): return q
    qs=list((pdk_dir/"libs.tech"/"magic").glob("*.tech")) if (pdk_dir/"libs.tech"/"magic").is_dir() else []
    return qs[0] if len(qs)==1 else None

def tech_nm_per_lambda(tech_path):
    if not tech_path: return None
    t=Path(tech_path).read_text(errors="replace")
    # Prefer cifoutput scalefactor because it defines physical output scaling.
    m=re.search(r'(?mis)^\s*cifoutput\b.*?^\s*scalefactor\s+([0-9.]+)(?:\s+(nanometers|angstroms))?',t)
    if not m: return None
    v=Decimal(m.group(1)); unit=(m.group(2) or "centimicrons").lower()
    if unit=="nanometers": return v
    if unit=="angstroms": return v/Decimal(10)
    return v*Decimal(10)  # 1 centimicron = 10 nm

def parse_magscale(mag_text):
    m=re.search(r'(?mi)^\s*magscale\s+(\d+)\s+(\d+)\s*$',mag_text)
    if not m: return Decimal(1),Decimal(1)
    n,d=map(Decimal,m.groups())
    if not n or not d: die("invalid zero magscale")
    return n,d

def mag_units_to_um(mag_text,tech_path,override=None):
    if override is not None:
        v=Decimal(str(override))
        if v<=0: die("--mag-unit-um must be > 0")
        return v,"--mag-unit-um"
    nm=tech_nm_per_lambda(tech_path)
    if nm is None:
        die("cannot determine physical Magic coordinate scale; provide --magic-tech or --mag-unit-um")
    n,d=parse_magscale(mag_text)
    # .mag file coordinates are scaled by n/d relative to the technology lambda.
    return (nm/Decimal(1000))*(n/d),str(tech_path)

def parse_obs_spec(spec,all_layers,where):
    place=False; route=set(); power=set()
    selectors=spec.split(";")
    if not selectors or any(not x.strip() for x in selectors): die(f"{where}: empty obs selector")
    for raw in selectors:
        x=raw.strip()
        m=re.fullmatch(r'(place|route|power|all)\s*(?:\(\s*([^()]*)\s*\))?',x)
        if not m: die(f"{where}: invalid obs selector {x!r}")
        kind,inside=m.groups()
        if kind=="place" and inside is not None: die(f"{where}: place does not take a layer list")
        if inside is None: layers=list(all_layers)
        else:
            layers=[z.strip() for z in inside.split(",")]
            if not layers or any(not z for z in layers): die(f"{where}: empty layer list in {x!r}")
        if kind in ("place","all"): place=True
        if kind in ("route","all"): route.update(layers)
        if kind in ("power","all"): power.update(layers)
    return place,route,power

def parse_mag_obstructions(mag_path,all_layers,unit_um):
    t=mag_path.read_text(errors="replace"); out=[]
    in_labels=False
    for lineno,line in enumerate(t.splitlines(),1):
        if re.match(r'^\s*<<\s*labels\s*>>\s*$',line,re.I): in_labels=True; continue
        if re.match(r'^\s*<<.*>>\s*$',line): in_labels=False; continue
        if not in_labels: continue
        m=re.match(r'^\s*(?:f|r)?label\s+space\s+(.*)$',line)
        if not m: continue
        rest=m.group(1)
        # rlabel: x1 y1 x2 y2 pos text; flabel adds font/size/rotation/offsets.
        nums=re.match(r'(?:s\s+)?(-?\d+)\s+(-?\d+)\s+(-?\d+)\s+(-?\d+)\s+(.*)$',rest)
        if not nums: continue
        x1,y1,x2,y2,tail=nums.groups()
        idx=tail.find("obs:")
        if idx<0: continue
        spec=tail[idx+4:].strip()
        place,route,power=parse_obs_spec(spec,all_layers,f"{mag_path}:{lineno}")
        vals=[Decimal(x1)*unit_um,Decimal(y1)*unit_um,Decimal(x2)*unit_um,Decimal(y2)*unit_um]
        llx,urx=sorted((vals[0],vals[2])); lly,ury=sorted((vals[1],vals[3]))
        if llx==urx or lly==ury: die(f"{mag_path}:{lineno}: zero-area obstruction label")
        out.append({"line":lineno,"spec":spec,"rect_um":(llx,lly,urx,ury),"place":place,"route":route,"power":power})
    return out

def fmt_decimal(x):
    s=format(x,'f')
    if '.' in s: s=s.rstrip('0').rstrip('.')
    return s or '0'

def def_dbu_per_um(text):
    m=re.search(r'(?mi)^\s*UNITS\s+DISTANCE\s+MICRONS\s+(\d+)\s*;',text)
    if not m: die("missing DEF UNITS DISTANCE MICRONS")
    return Decimal(m.group(1))

def um_to_dbu(x,dbu):
    v=x*dbu
    if v!=v.to_integral_value(): die(f"obstruction coordinate {x}um is not on DEF database grid ({dbu} DBU/um)")
    return int(v)

def render_def_blockages(obs,text):
    dbu=def_dbu_per_um(text); items=[]
    for o in obs:
        x1,y1,x2,y2=(um_to_dbu(v,dbu) for v in o["rect_um"])
        if o["place"]: items.append(f"    - PLACEMENT\n      RECT ( {x1} {y1} ) ( {x2} {y2} ) ;")
        for layer in sorted(o["route"],key=natural_key):
            items.append(f"    - LAYER {layer}\n      RECT ( {x1} {y1} ) ( {x2} {y2} ) ;")
    return "\n".join([f"BLOCKAGES {len(items)} ;"]+items+["END BLOCKAGES"]),len(items)

def natural_key(s):
    return [int(x) if x.isdigit() else x.lower() for x in re.split(r'(\d+)',s)]

def librelane_fragment(obs):
    fp=[]; routing=[]; pdn=[]
    for o in obs:
        r=[fmt_decimal(v) for v in o["rect_um"]]
        coords=" ".join(r)
        if o["place"]: fp.append(coords)
        for layer in sorted(o["route"],key=natural_key): routing.append(f"{layer} {coords}")
        for layer in sorted(o["power"],key=natural_key): pdn.append(f"{layer} {coords}")
    d={}
    if fp: d["FP_OBSTRUCTIONS"]=fp
    if routing: d["ROUTING_OBSTRUCTIONS"]=routing
    if pdn: d["PDN_OBSTRUCTIONS"]=pdn
    return d

def die(s):
    print("ERROR:", s, file=sys.stderr); raise SystemExit(2)
def warn(s):
    print("WARNING:", s, file=sys.stderr)

def get_section(text, name):
    lines=text.splitlines(True); a=None; count=None
    sr=re.compile(rf'^\s*{re.escape(name)}(?:\s+(\d+))?\s*;',re.I)
    er=re.compile(rf'^\s*END\s+{re.escape(name)}\s*$',re.I)
    for i,l in enumerate(lines):
        m=sr.match(l.rstrip())
        if m:
            if a is not None: die(f"multiple {name} sections")
            a=i; count=int(m.group(1)) if m.group(1) else None
        elif a is not None and er.match(l.rstrip()):
            return lines,a,i,count,"".join(lines[a:i+1])
    if a is not None: die(f"{name} has no END {name}")
    return None

def replace_section(text,name,repl):
    s=get_section(text,name)
    if not s: return text
    lines,a,b,_,_=s
    r="" if repl is None else repl.rstrip()+"\n"
    return "".join(lines[:a])+r+"".join(lines[b+1:])

def insert_before(text,name,payload):
    s=get_section(text,name)
    if not s: die(f"missing {name}; cannot insert SPECIALNETS")
    lines,a,_,_,_=s
    return "".join(lines[:a])+payload.rstrip()+"\n\n"+"".join(lines[a:])

def entries(sec_text):
    body="\n".join(sec_text.splitlines()[1:-1]); out=[]; pos=0
    while True:
        m=re.search(r'(?m)^\s*-\s+',body[pos:])
        if not m: break
        a=pos+m.start(); z=body.find(";",a)
        if z<0: die("unterminated section entry")
        out.append(body[a:z+1]); pos=z+1
    return out

def normalise_nets(text):
    s=get_section(text,"NETS")
    if not s: die("no NETS section; run 'extract all' before Magic 'def write'")
    _,_,_,decl,st=s; es=entries(st)
    if decl is not None and decl!=len(es): warn(f"NETS declares {decl}, parsed {len(es)}")
    names=[]; lines=[]
    for e in es:
        c=" ".join(e.split())
        m=re.match(rf'-\s+({NAME})\s+(.*);$',c)
        if not m: die(f"cannot parse NETS entry: {c}")
        n,rest=m.groups(); conn=rest.split("+",1)[0].strip()
        ts=re.findall(r'\(\s*[^()]+\s*\)',conn)
        if not ts: die(f"net {n} has no connectivity tuple")
        residue=conn
        for t in ts: residue=residue.replace(t,"",1)
        if residue.strip(): die(f"unexpected connectivity syntax on {n}: {residue}")
        names.append(n); lines.append(f"   - {n} {' '.join(ts)} + USE SIGNAL ;")
    new=f"NETS {len(lines)} ;\n"+"\n".join(lines)+"\nEND NETS"
    return replace_section(text,"NETS",new),names,len(es)

def parse_special(text):
    s=get_section(text,"SPECIALNETS")
    if not s:return []
    _,_,_,decl,st=s; out=[]
    for e in entries(st):
        c=" ".join(e.split()); m=re.match(rf'-\s+({NAME})\b(.*);$',c)
        if not m: die(f"cannot parse SPECIALNETS entry: {c}")
        n,tail=m.groups(); u=re.search(r'\+\s+USE\s+(GROUND|POWER)\b',tail,re.I)
        if not u: die(f"SPECIALNET {n} has no supported USE GROUND/POWER")
        out.append((n,u.group(1).upper()))
    if decl is not None and decl!=len(out): warn(f"SPECIALNETS declares {decl}, parsed {len(out)}")
    return out

def merge_special(xs):
    d={}; order=[]
    for n,u in xs:
        if n in d and d[n]!=u: die(f"{n} requested as both {d[n]} and {u}")
        if n not in d: order.append(n)
        d[n]=u
    return [(n,d[n]) for n in order]

def render_special(xs):
    return "\n".join([f"SPECIALNETS {len(xs)} ;"]+
                     [f"    - {n} + USE {u} ;" for n,u in xs]+["END SPECIALNETS"])

def round_bus_names(text):
    # identifier immediately followed by (digits), unlike DEF tuple/coordinate syntax
    return sorted(set(re.findall(r'\b[A-Za-z_.$/][A-Za-z0-9_.$/\[\]-]*\(\d+\)',text)))

def pin_info(text):
    s=get_section(text,"PINS")
    if not s:return None,[],[]
    _,_,_,decl,st=s; es=entries(st); names=[]; issues=[]
    for e in es:
        m=re.match(rf'\s*-\s+({NAME})',e); n=m.group(1) if m else "?"
        names.append(n)
        for prop in ("DIRECTION","USE","PORT"):
            if not re.search(rf'\+\s+{prop}\b',e,re.I): issues.append(f"pin {n} lacks {prop}")
    if decl is not None and decl!=len(es): issues.append(f"PINS declares {decl}, parsed {len(es)}")
    return decl,names,issues

def main():
    ap=argparse.ArgumentParser(description="Normalise a Magic-generated DEF.")
    ap.add_argument("input",type=Path); ap.add_argument("output",type=Path)
    ap.add_argument("--design",help="DESIGN name (default: output filename stem)")
    ap.add_argument("--specialnets-from",type=Path,metavar="DEF")
    ap.add_argument("--ground",action="append",default=[],metavar="NET")
    ap.add_argument("--power",action="append",default=[],metavar="NET")
    ap.add_argument("--no-default-specialnets",action="store_true")
    fmt=ap.add_mutually_exclusive_group()
    fmt.add_argument("--format-like-source", dest="format_like_source", action="store_true", default=True, help="format close to TinyTapeout source.def for minimal diffs (default)")
    fmt.add_argument("--no-format-like-source", dest="format_like_source", action="store_false", help="disable source-like canonical formatting")
    ap.add_argument("-V", "--verbose", action="store_true", help="print resolved option/configuration summary, including implicit defaults")
    ap.add_argument("--mag-source", type=Path, help="Magic .mag source for obs: labels (default: input DEF with .mag suffix)")
    ap.add_argument("--def-blockages", action="store_true", help="emit DEF BLOCKAGES from obs: labels")
    ap.add_argument("--librelane-obstructions", type=Path, metavar="JSON", help="write LibreLane obstruction config fragment")
    ap.add_argument("--pdk", help="PDK name (default: $PDK, then .mag tech line)")
    ap.add_argument("--pdk-root", type=Path, help="PDK root (default: $PDK_ROOT)")
    ap.add_argument("--magic-tech", type=Path, help="override Magic technology file used for coordinate scaling")
    ap.add_argument("--metal-layers", help="comma-separated expansion for bare route/power/all")
    ap.add_argument("--mag-unit-um", type=Decimal, help="override physical size of one .mag file coordinate unit, in microns")
    a=ap.parse_args()
    if a.input.resolve()==a.output.resolve(): die("input and output must differ")
    if not a.input.is_file(): die(f"not found: {a.input}")
    text=a.input.read_text()
    obs=[]; obs_meta=None
    if a.def_blockages or a.librelane_obstructions:
        mag_path=a.mag_source or a.input.with_suffix(".mag")
        if not mag_path.is_file(): die(f"Magic source not found: {mag_path}")
        mag_text=mag_path.read_text(errors="replace")
        pdk=a.pdk or os.environ.get("PDK") or pdk_from_mag(mag_text)
        if not pdk: die("cannot determine PDK; use --pdk or set $PDK")
        pdk_root=a.pdk_root or (Path(os.environ["PDK_ROOT"]) if os.environ.get("PDK_ROOT") else None)
        layers,layer_source=discover_metal_layers(pdk,pdk_root,a.metal_layers)
        pdir=find_pdk_dir(pdk_root,pdk)
        tech=find_magic_tech(pdir,pdk,a.magic_tech)
        unit_um,scale_source=mag_units_to_um(mag_text,tech,a.mag_unit_um)
        obs=parse_mag_obstructions(mag_path,layers,unit_um)
        obs_meta=(mag_path,pdk,layers,layer_source,unit_um,scale_source)
    if a.verbose:
        print("Options:")
        print(f"  input: {a.input}")
        print(f"  output: {a.output}")
        print(f"  design: {a.design or a.output.stem} ({'explicit' if a.design else 'output filename stem'})")
        print(f"  format-like-source: {'yes' if a.format_like_source else 'no'}")
        print(f"  specialnets-from: {a.specialnets_from if a.specialnets_from else '(none)'}")
        print(f"  ground nets: {', '.join(a.ground) if a.ground else '(none explicit)'}")
        print(f"  power nets: {', '.join(a.power) if a.power else '(none explicit)'}")
        default_sp = not (a.specialnets_from or a.ground or a.power or a.no_default_specialnets)
        print(f"  default special nets: {'VGND=GROUND, VPWR=POWER' if default_sp else 'disabled/not applicable'}")
        print(f"  DEF blockages: {'yes' if a.def_blockages else 'no'}")
        print(f"  LibreLane obstructions: {a.librelane_obstructions if a.librelane_obstructions else '(disabled)'}")
        if obs_meta:
            mag_path,pdk,layers,layer_source,unit_um,scale_source=obs_meta
            print(f"  mag source: {mag_path} ({'explicit' if a.mag_source else 'implicit from input DEF'})")
            if a.pdk: pdk_origin='--pdk'
            elif os.environ.get('PDK'): pdk_origin='$PDK'
            else: pdk_origin='.mag tech declaration'
            print(f"  PDK: {pdk} ({pdk_origin})")
            root = a.pdk_root or (Path(os.environ['PDK_ROOT']) if os.environ.get('PDK_ROOT') else None)
            root_origin = '--pdk-root' if a.pdk_root else ('$PDK_ROOT' if os.environ.get('PDK_ROOT') else 'not set')
            print(f"  PDK root: {root if root else '(none)'} ({root_origin})")
            print(f"  metal layers: {', '.join(layers)} ({layer_source})")
            print(f"  Magic coordinate unit: {fmt_decimal(unit_um)} um ({scale_source})")
        else:
            print("  mag/PDK/layer/scale resolution: not needed (obstruction output disabled)")
        print()
    bad=round_bus_names(text)
    if bad: die("round-parenthesis bus-like names found; refusing BUSBITCHARS change: "+", ".join(bad))
    ndr=bool(get_section(text,"NONDEFAULTRULES"))
    text,nets,nc=normalise_nets(text)
    text=replace_section(text,"NONDEFAULTRULES",None)
    xs=[]; explicit=bool(a.specialnets_from or a.ground or a.power)
    if a.specialnets_from:
        if not a.specialnets_from.is_file(): die(f"not found: {a.specialnets_from}")
        xs += parse_special(a.specialnets_from.read_text())
    xs += [(n,"GROUND") for n in a.ground]+[(n,"POWER") for n in a.power]
    if not explicit and not a.no_default_specialnets: xs += [("VGND","GROUND"),("VPWR","POWER")]
    xs=merge_special(xs)
    sp=render_special(xs)
    text=replace_section(text,"SPECIALNETS",sp) if get_section(text,"SPECIALNETS") else insert_before(text,"NETS",sp)
    design=a.design or a.output.stem
    dm=re.search(r'(?mi)^\s*DESIGN\s+(\S+)\s*;',text)
    if not dm: die("missing DESIGN")
    olddesign=dm.group(1)
    text=re.sub(r'(?mi)^(\s*DESIGN\s+)\S+(\s*;)',rf'\g<1>{design}\2',text,count=1)
    bm=re.search(r'(?mi)^\s*BUSBITCHARS\s+"([^"]*)"\s*;',text)
    if not bm: die("missing BUSBITCHARS")
    oldbus=bm.group(1)
    text=re.sub(r'(?mi)^(\s*BUSBITCHARS\s+)"[^"]*"(\s*;)',r'\g<1>"[]"\2',text,count=1)
    def_blockage_count=0
    if a.def_blockages:
        btxt,def_blockage_count=render_def_blockages(obs,text)
        if get_section(text,"BLOCKAGES"): text=replace_section(text,"BLOCKAGES",btxt)
        else: text=insert_before(text,"NETS",btxt)
    if a.format_like_source:
        text=re.sub(r'(?mi)^\s*VERSION\s+\S+\s*;', 'VERSION 5.8 ;', text, count=1)
        text=re.sub(r'(?mi)^\s*NAMESCASESENSITIVE\b[^;]*;\s*\n?', '', text)
        text=re.sub(r'(?mi)^\s*TECHNOLOGY\b[^;]*;\s*\n?', '', text)
        text=replace_section(text,"VIAS",None)
        ps=get_section(text,"PINS")
        if not ps: die("missing PINS")
        pout=[]
        for e in entries(ps[4]):
            c=" ".join(e.split())
            m=re.match(rf'-\s+({NAME})\s+\+\s+NET\s+({NAME})\s+\+\s+DIRECTION\s+(\w+)\s+\+\s+USE\s+(\w+)\s+\+\s+PORT\s+\+\s+LAYER\s+(\S+)\s+(\(\s*[-+]?\d+\s+[-+]?\d+\s*\))\s+(\(\s*[-+]?\d+\s+[-+]?\d+\s*\))\s+\+\s+PLACED\s+(\(\s*[-+]?\d+\s+[-+]?\d+\s*\))\s+(\S+)\s*;$',c,re.I)
            if not m: die("cannot source-format PINS entry: "+c)
            pn,nn,d,u,layer,ll,ur,placed,o=m.groups()
            norm=lambda x: "( "+" ".join(re.findall(r'[-+]?\d+',x))+" )"
            pout += [f"    - {pn} + NET {nn} + DIRECTION {d.upper()} + USE {u.upper()}","      + PORT",f"        + LAYER {layer} {norm(ll)} {norm(ur)}",f"        + PLACED {norm(placed)} {o} ;"]
        text=replace_section(text,"PINS",f"PINS {len(pout)//4} ;\n"+"\n".join(pout)+"\nEND PINS")
        ns=get_section(text,"NETS"); nes=entries(ns[4]) if ns else []
        def natkey(e):
            m=re.match(rf'\s*-\s+({NAME})',e); n=m.group(1) if m else e
            return [int(x) if x.isdigit() else x for x in re.split(r'(\d+)',n)]
        nes.sort(key=natkey); nlines=[]
        for e in nes:
            c=" ".join(e.split()); m=re.match(rf'-\s+({NAME})\s+(.*?)\s+\+\s+USE\s+SIGNAL\s*;$',c,re.I)
            if not m: die("cannot source-format NETS entry: "+c)
            n,conn=m.groups(); nlines.append(f"    - {n} {conn} + USE SIGNAL ;")
        text=replace_section(text,"NETS",f"NETS {len(nlines)} ;\n"+"\n".join(nlines)+"\nEND NETS")
        ss=get_section(text,"SPECIALNETS")
        if ss:
            sx=parse_special(text); text=replace_section(text,"SPECIALNETS","\n".join([f"SPECIALNETS {len(sx)} ;"]+[f"    - {n} + USE {u} ;" for n,u in sx]+["END SPECIALNETS"]))
        for kw in ("DIVIDERCHAR", "BUSBITCHARS", "DESIGN", "UNITS", "DIEAREA"):
            text=re.sub(rf'(?mi)^\s*({kw}\b)', r'\1', text, count=1)
        text=re.sub(r'\n[ \t]*\n+','\n',text).rstrip()+"\n"
    else:
        text=re.sub(r'\n[ \t]*\n(?:[ \t]*\n)+','\n\n',text).rstrip()+"\n"
    issues=[]
    _,pins,pissues=pin_info(text); issues+=pissues
    missing=sorted(set(pins)-set(nets))
    if missing: issues.append("PINS without NETS: "+", ".join(missing[:10]))
    if len(nets)!=len(set(nets)): issues.append("duplicate NETS names")
    if get_section(text,"NONDEFAULTRULES"): issues.append("NONDEFAULTRULES remains")
    ns=get_section(text,"NETS")
    if ns and re.search(r'\+\s*(ROUTED|FIXED|COVER|NONDEFAULTRULE|TAPERRULE)\b',ns[4],re.I):
        issues.append("routing/NDR property remains in NETS")
    for req in ("VERSION","DIVIDERCHAR","BUSBITCHARS","DESIGN","UNITS","DIEAREA"):
        if not re.search(rf'(?mi)^\s*{req}\b',text): issues.append(f"missing {req}")
    for req in ("COMPONENTS","PINS","SPECIALNETS","NETS"):
        if not get_section(text,req): issues.append(f"missing {req}")
    if a.librelane_obstructions:
        frag=librelane_fragment(obs)
        a.librelane_obstructions.write_text(json.dumps(frag,indent=4)+"\n")
    a.output.write_text(text)
    print(f"Input: {a.input}\nOutput: {a.output}")
    print(f"DESIGN: {olddesign} -> {design}")
    print(f'BUSBITCHARS: "{oldbus}" -> "[]"')
    print(f"NETS normalised: {nc}")
    print("NONDEFAULTRULES:", "removed" if ndr else "not present")
    print(f"SPECIALNETS: {len(xs)}")
    for n,u in xs: print(f"  {n}: {u}")
    if obs_meta:
        mag_path,pdk,layers,layer_source,unit_um,scale_source=obs_meta
        print(f"Obstruction source: {mag_path}")
        print(f"PDK: {pdk}")
        print(f"Metal layers: {' '.join(layers)}")
        print(f"Layer source: {layer_source}")
        print(f"Magic coordinate unit: {fmt_decimal(unit_um)} um ({scale_source})")
        print(f"obs: labels: {len(obs)}")
        if a.def_blockages: print(f"DEF BLOCKAGES entries: {def_blockage_count} (power-only obstructions are LibreLane-only)")
        if a.librelane_obstructions: print(f"LibreLane obstruction fragment: {a.librelane_obstructions}")
    print(f"Sanity warnings: {len(issues)}")
    for x in issues: warn(x)
    return 1 if issues else 0

if __name__=="__main__":
    raise SystemExit(main())
