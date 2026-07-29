import json, glob, os, statistics as st
from collections import defaultdict
rows=[]
for path in sorted(glob.glob(r"F:/SPT/SPT4.0.13/BepInEx/plugins/Framesaver-logs/framesaver-*marathon*.ndjson")):
    stem=os.path.basename(path).split("-marathon")[0].replace("framesaver-","")
    leg,prev=0,None
    for ln in open(path,encoding="utf-8-sig",errors="replace"):
        try: o=json.loads(ln)
        except ValueError: continue
        if o.get("type")!="sample" or o.get("state")!="raid": continue
        m=str(o.get("map") or "?")
        if m!=prev: prev,leg=m,leg+1
        if o.get("final") or (o.get("raidElapsed") or 0)<120: continue
        ph=o.get("phases") or {}
        rows.append({"leg":"%s %s L%d"%(stem,m,leg),
                     "late":(o.get("playerLate") or {}).get("avg") or 0.0,
                     "fin":(ph.get("PostLateUpdate/FinishFrameRendering") or {}).get("avg") or 0.0,
                     "total":(o.get("bots") or {}).get("total") or 0})
by=defaultdict(list)
for r in rows: by[r["leg"]].append(r)

def ols(xs,ys):
    n=len(xs); mx=sum(xs)/n; my=sum(ys)/n
    sxx=sum((x-mx)**2 for x in xs)
    if sxx<=1e-9 or n<4: return None
    b=sum((x-mx)*(y-my) for x,y in zip(xs,ys))/sxx
    a=my-b*mx
    res=sum((y-(a+b*x))**2 for x,y in zip(xs,ys))
    return b, 1.96*(res/(n-2)/sxx)**0.5

lh=[k for k in sorted(by) if "Lighthouse" in k and len(by[k])>=5]
print("DELTA CLAIM: playerLate ~ bots.total within Lighthouse L4 = 0.0751 +/- 0.0461, predicts 81%\n")
for k in lh:
    v=by[k]
    f=ols([r["total"] for r in v],[r["late"] for r in v])
    print("%-30s n=%2d  median late %.3f  total %.1f  slope %s"
          % (k,len(v),st.median([r["late"] for r in v]),st.median([r["total"] for r in v]),
             ("%.4f +/- %.4f"%f) if f else "--"))
if len(lh)==2:
    a,b=by[lh[0]],by[lh[1]]
    gap=abs(st.median([r["late"] for r in b])-st.median([r["late"] for r in a]))
    dn=abs(st.median([r["total"] for r in b])-st.median([r["total"] for r in a]))
    f=ols([r["total"] for r in b],[r["late"] for r in b])
    if f:
        lo,hi=f[0]-f[1],f[0]+f[1]
        print("\nobserved playerLate gap %.3f ms over %.0f bots" % (gap,dn))
        print("point   %.4f x %.0f = %.3f  -> %.0f%%" % (f[0],dn,f[0]*dn,100*f[0]*dn/gap))
        print("CI low  %.4f x %.0f = %.3f  -> %.0f%%" % (lo,dn,lo*dn,100*lo*dn/gap))
        print("CI high %.4f x %.0f = %.3f  -> %.0f%%" % (hi,dn,hi*dn,100*hi*dn/gap))

print("\nNOISE FLOOR: between-leg |d| on the same map, FinishFrameRendering")
bymap=defaultdict(list)
for k in by: bymap[k.split()[1]].append(k)
ds=[]
for m,ks in sorted(bymap.items()):
    if len(ks)<2: continue
    meds=[st.median([r["fin"] for r in by[k]]) for k in ks if len(by[k])>=5]
    if len(meds)<2: continue
    d=max(meds)-min(meds); ds.append(d)
    print("  %-14s %s  d=%.3f" % (m," -> ".join("%.3f"%x for x in meds), d))
if ds: print("  median |d| across maps: %.3f ms   (gap being explained: 0.549)" % st.median(ds))
