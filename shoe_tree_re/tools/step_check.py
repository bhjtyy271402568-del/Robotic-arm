#!/usr/bin/env python3
"""STEP 核对工具：给鞋撑机芯逆向建模做独立检查。

用法（需要 cadquery-ocp、numpy、matplotlib）：
  python step_check.py info      model.step                 # 实体清单：名称、体积、包围盒
  python step_check.py holes     model.step [--min 1 --max 20]   # 圆柱面清单：直径、轴线、长度（找孔、销、光轴）
  python step_check.py interfere model.step [--tol 0.01]   # 两两求交：干涉体积；并列出最小间隙 < 0.5 mm 的零件对
  python step_check.py section   model.step --axis x --at 50 --out sec.png   # 截面图
  python step_check.py distance  model.step "零件A" "零件B" # 两个零件的最小距离

零件名取自 STEP 里的产品名；同名多实例会加 #1、#2。
只做几何核对，不代表强度、装配可行性或运动全程无干涉。
"""
import argparse
import itertools
import math
import sys

from OCP.STEPCAFControl import STEPCAFControl_Reader
from OCP.STEPControl import STEPControl_Reader
from OCP.TDocStd import TDocStd_Document
from OCP.TCollection import TCollection_ExtendedString
from OCP.XCAFDoc import XCAFDoc_DocumentTool
from OCP.TDF import TDF_Label
try:
    from OCP.TDF import TDF_LabelSequence
except ImportError:  # 新版 OCP 把序列放在 OCP.collections
    from OCP.collections import Sequence_TDF_Label as TDF_LabelSequence
from OCP.TDataStd import TDataStd_Name
from OCP.TopLoc import TopLoc_Location
from OCP.TopExp import TopExp_Explorer
from OCP.TopAbs import TopAbs_SOLID, TopAbs_FACE, TopAbs_EDGE
from OCP.TopoDS import TopoDS
from OCP.Bnd import Bnd_Box
from OCP.BRepBndLib import BRepBndLib
from OCP.GProp import GProp_GProps
from OCP.BRepGProp import BRepGProp
from OCP.BRepAlgoAPI import BRepAlgoAPI_Common, BRepAlgoAPI_Section
from OCP.BRepExtrema import BRepExtrema_DistShapeShape
from OCP.BRepAdaptor import BRepAdaptor_Surface, BRepAdaptor_Curve
from OCP.GeomAbs import GeomAbs_Cylinder
from OCP.gp import gp_Pln, gp_Pnt, gp_Dir
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.BRep import BRep_Tool
from OCP.GCPnts import GCPnts_QuasiUniformDeflection


def load_parts(path):
    """返回 [(名称, 已定位的形状)]，每个实体一项。读不到装配结构时退回按实体编号命名。"""
    doc = TDocStd_Document(TCollection_ExtendedString("doc"))
    rd = STEPCAFControl_Reader()
    rd.SetNameMode(True)
    if rd.ReadFile(path) != 1:
        sys.exit(f"读不了 STEP：{path}")
    rd.Transfer(doc)
    st = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
    parts = []

    def name_of(lab):
        attr = TDataStd_Name()
        if lab.FindAttribute(TDataStd_Name.GetID_s(), attr):
            s = attr.Get().ToExtString()
            try:  # 有些导出器把 UTF-8 原样写进 STEP，读回来会变成 latin-1 乱码
                s = s.encode("latin-1").decode("utf-8")
            except (UnicodeEncodeError, UnicodeDecodeError):
                pass
            return s
        return "未命名"

    def walk(lab, loc, pname):
        if st.IsReference_s(lab):
            r = TDF_Label()
            st.GetReferredShape_s(lab, r)
            walk(r, loc.Multiplied(st.GetLocation_s(lab)), name_of(lab) or pname)
            return
        if st.IsAssembly_s(lab):
            comps = TDF_LabelSequence()
            st.GetComponents_s(lab, comps)
            for i in range(1, comps.Length() + 1):
                walk(comps.Value(i), loc, pname)
            return
        shp = st.GetShape_s(lab).Moved(loc)
        nm = name_of(lab) if name_of(lab) != "未命名" else pname
        ex = TopExp_Explorer(shp, TopAbs_SOLID)
        k = 0
        while ex.More():
            k += 1
            parts.append([nm if k == 1 else f"{nm}/实体{k}", ex.Current()])
            ex.Next()

    roots = TDF_LabelSequence()
    st.GetFreeShapes(roots)
    for i in range(1, roots.Length() + 1):
        walk(roots.Value(i), TopLoc_Location(), name_of(roots.Value(i)))
    if not parts:  # 退回普通读取
        r2 = STEPControl_Reader()
        r2.ReadFile(path)
        r2.TransferRoots()
        ex = TopExp_Explorer(r2.OneShape(), TopAbs_SOLID)
        k = 0
        while ex.More():
            k += 1
            parts.append([f"实体{k}", ex.Current()])
            ex.Next()
    seen = {}
    for p in parts:  # 同名加编号
        seen[p[0]] = seen.get(p[0], 0) + 1
    cnt = {}
    for p in parts:
        if seen[p[0]] > 1:
            cnt[p[0]] = cnt.get(p[0], 0) + 1
            p[0] = f"{p[0]}#{cnt[p[0]]}"
    return [tuple(p) for p in parts]


def bbox(s):
    b = Bnd_Box()
    BRepBndLib.AddOptimal_s(s, b, False, False)
    a, c = b.CornerMin(), b.CornerMax()
    return (a.X(), a.Y(), a.Z(), c.X(), c.Y(), c.Z())


def volume(s):
    g = GProp_GProps()
    BRepGProp.VolumeProperties_s(s, g)
    return g.Mass()


def cmd_info(a):
    parts = load_parts(a.step)
    print(f"{len(parts)} 个实体")
    print(f"{'名称':<36}{'体积mm3':>12}   包围盒 X[min,max] Y[min,max] Z[min,max]")
    for n, s in parts:
        b = bbox(s)
        print(f"{n:<36}{volume(s):>12.1f}   X[{b[0]:.2f},{b[3]:.2f}] Y[{b[1]:.2f},{b[4]:.2f}] Z[{b[2]:.2f},{b[5]:.2f}]")


def cmd_holes(a):
    for n, s in load_parts(a.step):
        rows = {}
        ex = TopExp_Explorer(s, TopAbs_FACE)
        while ex.More():
            f = TopoDS.Face_s(ex.Current()) if hasattr(TopoDS, "Face_s") else TopoDS.Face(ex.Current())
            ad = BRepAdaptor_Surface(f)
            if ad.GetType() == GeomAbs_Cylinder:
                c = ad.Cylinder()
                d = 2 * c.Radius()
                if a.min <= d <= a.max:
                    ax = c.Axis()
                    p, v = ax.Location(), ax.Direction()
                    b = bbox(f)
                    key = (round(d, 3), round(abs(v.X()), 2), round(abs(v.Y()), 2), round(abs(v.Z()), 2),
                           round(p.X(), 1), round(p.Y(), 1), round(p.Z(), 1))
                    rows[key] = b
            ex.Next()
        if rows:
            print(f"\n[{n}]")
            for k, b in sorted(rows.items()):
                print(f"  Ø{k[0]:<8} 轴向({k[1]},{k[2]},{k[3]})  过点({k[4]},{k[5]},{k[6]})  "
                      f"面包围盒 X[{b[0]:.1f},{b[3]:.1f}] Y[{b[1]:.1f},{b[4]:.1f}] Z[{b[2]:.1f},{b[5]:.1f}]")


def cmd_interfere(a):
    parts = load_parts(a.step)
    boxes = [bbox(s) for _, s in parts]
    hits, near = [], []
    for (i, (ni, si)), (j, (nj, sj)) in itertools.combinations(enumerate(parts), 2):
        bi, bj = boxes[i], boxes[j]
        if any(bi[k] > bj[k + 3] + 0.5 or bj[k] > bi[k + 3] + 0.5 for k in range(3)):
            continue
        com = BRepAlgoAPI_Common(si, sj)
        v = volume(com.Shape()) if com.IsDone() else float("nan")
        if v > a.tol:
            hits.append((v, ni, nj))
        else:
            d = BRepExtrema_DistShapeShape(si, sj)
            if d.IsDone() and d.Value() < 0.5:
                near.append((d.Value(), ni, nj))
    print(f"干涉（重叠体积 > {a.tol} mm3）：{len(hits)} 对")
    for v, ni, nj in sorted(hits, reverse=True):
        print(f"  {v:10.3f} mm3   {ni}  ×  {nj}")
    print(f"间隙 < 0.5 mm（接触或贴合，需人工判断是否设计如此）：{len(near)} 对")
    for d, ni, nj in sorted(near):
        print(f"  {d:8.3f} mm   {ni}  ×  {nj}")


def cmd_distance(a):
    parts = dict(load_parts(a.step))
    for k in (a.a, a.b):
        if k not in parts:
            sys.exit(f"找不到零件：{k}\n可选：{', '.join(parts)}")
    d = BRepExtrema_DistShapeShape(parts[a.a], parts[a.b])
    p1, p2 = d.PointOnShape1(1), d.PointOnShape2(1)
    print(f"最小距离 {d.Value():.3f} mm  点A({p1.X():.2f},{p1.Y():.2f},{p1.Z():.2f})  点B({p2.X():.2f},{p2.Y():.2f},{p2.Z():.2f})")


def cmd_section(a):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager as fm
    try:
        fm.fontManager.addfont("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc")
        plt.rcParams["font.family"] = "WenQuanYi Zen Hei"
        plt.rcParams["axes.unicode_minus"] = False
    except Exception:
        pass
    nrm = {"x": gp_Dir(1, 0, 0), "y": gp_Dir(0, 1, 0), "z": gp_Dir(0, 0, 1)}[a.axis]
    pt = {"x": gp_Pnt(a.at, 0, 0), "y": gp_Pnt(0, a.at, 0), "z": gp_Pnt(0, 0, a.at)}[a.axis]
    hv = {"x": (1, 2), "y": (0, 2), "z": (0, 1)}[a.axis]
    lab = "XYZ"
    fig, ax = plt.subplots(figsize=(10, 8))
    cmap = plt.get_cmap("tab20")
    for idx, (n, s) in enumerate(load_parts(a.step)):
        sec = BRepAlgoAPI_Section(s, gp_Pln(pt, nrm))
        sec.Build()
        ex = TopExp_Explorer(sec.Shape(), TopAbs_EDGE)
        drawn = False
        while ex.More():
            e = TopoDS.Edge_s(ex.Current()) if hasattr(TopoDS, "Edge_s") else TopoDS.Edge(ex.Current())
            cu = BRepAdaptor_Curve(e)
            disc = GCPnts_QuasiUniformDeflection(cu, 0.02)
            if disc.IsDone():
                P = [disc.Value(i) for i in range(1, disc.NbPoints() + 1)]
                xy = [((p.X(), p.Y(), p.Z())[hv[0]], (p.X(), p.Y(), p.Z())[hv[1]]) for p in P]
                ax.plot(*zip(*xy), color=cmap(idx % 20), lw=1.4, label=None if drawn else n)
                drawn = True
            ex.Next()
    ax.set_aspect("equal")
    ax.grid(alpha=.3)
    ax.set_xlabel(lab[hv[0]] + " (mm)")
    ax.set_ylabel(lab[hv[1]] + " (mm)")
    ax.set_title(f"截面 {a.axis.upper()} = {a.at}")
    ax.legend(fontsize=8, loc="best")
    fig.tight_layout()
    fig.savefig(a.out, dpi=150)
    print("已保存", a.out)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = p.add_subparsers(dest="cmd", required=True)
    s = sp.add_parser("info"); s.add_argument("step"); s.set_defaults(f=cmd_info)
    s = sp.add_parser("holes"); s.add_argument("step"); s.add_argument("--min", type=float, default=1); s.add_argument("--max", type=float, default=30); s.set_defaults(f=cmd_holes)
    s = sp.add_parser("interfere"); s.add_argument("step"); s.add_argument("--tol", type=float, default=0.01); s.set_defaults(f=cmd_interfere)
    s = sp.add_parser("distance"); s.add_argument("step"); s.add_argument("a"); s.add_argument("b"); s.set_defaults(f=cmd_distance)
    s = sp.add_parser("section"); s.add_argument("step"); s.add_argument("--axis", choices="xyz", required=True); s.add_argument("--at", type=float, required=True); s.add_argument("--out", default="section.png"); s.set_defaults(f=cmd_section)
    a = p.parse_args()
    a.f(a)


if __name__ == "__main__":
    main()
