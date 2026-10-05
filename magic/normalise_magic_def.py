#!/usr/bin/env python3
import argparse, re, sys
from pathlib import Path

NAME = r'[^\s();+]+'

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
                     [f"   - {n} + USE {u} ;" for n,u in xs]+["END SPECIALNETS"])

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
    ap.add_argument("--format-like-source", action="store_true", help="format close to TinyTapeout source.def for minimal diffs")
    a=ap.parse_args()
    if a.input.resolve()==a.output.resolve(): die("input and output must differ")
    if not a.input.is_file(): die(f"not found: {a.input}")
    text=a.input.read_text()
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
    a.output.write_text(text)
    print(f"Input: {a.input}\nOutput: {a.output}")
    print(f"DESIGN: {olddesign} -> {design}")
    print(f'BUSBITCHARS: "{oldbus}" -> "[]"')
    print(f"NETS normalised: {nc}")
    print("NONDEFAULTRULES:", "removed" if ndr else "not present")
    print(f"SPECIALNETS: {len(xs)}")
    for n,u in xs: print(f"  {n}: {u}")
    print(f"Sanity warnings: {len(issues)}")
    for x in issues: warn(x)
    return 1 if issues else 0

if __name__=="__main__":
    raise SystemExit(main())

