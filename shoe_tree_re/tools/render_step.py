#!/usr/bin/env python3
"""把 STEP 装配渲染成带零件编号的图片（多视角），用于核对零件位置和相互关系。

用法：
  python render_step.py model.step out_prefix [--views iso,front,top,side] [--hide 名称片段,...] [--only 名称片段,...]
       [--section y=0]   # 只画剖切面一侧，看内部
输出 out_prefix_<视角>.png 和 out_prefix_图例.txt。
依赖：cadquery-ocp、numpy、playwright（自带 Chromium）、three.js（脚本同目录 three.min.js，或环境变量 THREE_JS 指定路径）。
"""
import argparse, json, os, sys, subprocess, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from step_check import load_parts, bbox
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.TopExp import TopExp_Explorer
from OCP.TopAbs import TopAbs_FACE, TopAbs_REVERSED
from OCP.BRep import BRep_Tool
from OCP.TopLoc import TopLoc_Location
from OCP.TopoDS import TopoDS

PALETTE = ["#4e79a7", "#f28e2b", "#59a14f", "#e15759", "#76b7b2", "#edc948", "#b07aa1", "#ff9da7", "#9c755f", "#bab0ac",
           "#1f77b4", "#2ca02c", "#d62728", "#9467bd", "#8c564b", "#17becf", "#bcbd22", "#7f7f7f"]


def mesh(shape, defl):
    BRepMesh_IncrementalMesh(shape, defl, False, 0.3, True)
    V, F = [], []
    ex = TopExp_Explorer(shape, TopAbs_FACE)
    while ex.More():
        f = TopoDS.Face_s(ex.Current()) if hasattr(TopoDS, "Face_s") else TopoDS.Face(ex.Current())
        loc = TopLoc_Location()
        tr = BRep_Tool.Triangulation_s(f, loc)
        if tr is not None:
            off = len(V) // 3
            tf = loc.Transformation()
            for i in range(1, tr.NbNodes() + 1):
                p = tr.Node(i).Transformed(tf)
                V += [round(p.X(), 3), round(p.Y(), 3), round(p.Z(), 3)]
            rev = f.Orientation() == TopAbs_REVERSED
            for i in range(1, tr.NbTriangles() + 1):
                a, b, c = tr.Triangle(i).Get()
                F += [off + a - 1, off + (b - 1 if not rev else c - 1), off + (c - 1 if not rev else b - 1)]
        ex.Next()
    return V, F


HTML = r"""<!doctype html><html><head><meta charset="utf-8"><style>html,body{margin:0;background:#fff;font-family:'WenQuanYi Zen Hei',sans-serif}
#c{width:1600px;height:1000px;display:block}.l{position:absolute;font-size:15px;background:rgba(255,255,255,.88);border:1px solid #333;border-radius:10px;padding:0 6px;transform:translate(-50%,-50%);white-space:nowrap}
#t{position:absolute;left:12px;top:8px;font-size:18px;font-weight:bold}#ax{position:absolute;right:12px;bottom:8px;font-size:14px;color:#555}</style></head>
<body><canvas id="c" width="1600" height="1000"></canvas><div id="t"></div><div id="ax"></div><script>/*THREE*/</script><script>
const D=/*DATA*/;const W=1600,H=1000;const r=new THREE.WebGLRenderer({canvas:document.getElementById('c'),antialias:true,preserveDrawingBuffer:true});r.setSize(W,H,false);r.localClippingEnabled=true;
const s=new THREE.Scene();s.background=new THREE.Color(0xffffff);s.add(new THREE.HemisphereLight(0xffffff,0x888888,.7));const L=new THREE.DirectionalLight(0xffffff,.6);s.add(L);
const clip=D.section?[new THREE.Plane(new THREE.Vector3(...D.section.n),D.section.c)]:[];
const box=new THREE.Box3();const meshes=[];
D.parts.forEach((p,i)=>{const g=new THREE.BufferGeometry();g.setAttribute('position',new THREE.Float32BufferAttribute(p.v,3));g.setIndex(p.f);g.computeVertexNormals();
 const m=new THREE.Mesh(g,new THREE.MeshPhongMaterial({color:p.c,side:THREE.DoubleSide,clippingPlanes:clip,transparent:p.o<1,opacity:p.o,depthWrite:p.o>=1}));s.add(m);
 const e=new THREE.LineSegments(new THREE.EdgesGeometry(g,30),new THREE.LineBasicMaterial({color:0x222222,transparent:true,opacity:.35,clippingPlanes:clip}));s.add(e);
 g.computeBoundingBox();box.union(g.boundingBox);meshes.push(p)});
const ctr=box.getCenter(new THREE.Vector3()),sz=box.getSize(new THREE.Vector3()).length();
const cam=new THREE.OrthographicCamera(-1,1,1,-1,-10*sz,10*sz);
const lbls=D.parts.map((p,i)=>{const d=document.createElement('div');d.className='l';d.textContent=p.n;d.style.borderColor=p.c;document.body.appendChild(d);return d});
window.view=function(dir,up,title){const v=new THREE.Vector3(...dir).normalize();cam.position.copy(ctr).addScaledVector(v,sz*2);cam.up.set(...up);cam.lookAt(ctr);
 const h=sz*0.55,a=W/H;cam.left=-h*a;cam.right=h*a;cam.top=h;cam.bottom=-h;cam.updateProjectionMatrix();L.position.copy(cam.position).add(new THREE.Vector3(sz,sz,sz));
 r.render(s,cam);document.getElementById('t').textContent=title;
 const used=[];D.parts.forEach((p,i)=>{const q=new THREE.Vector3(...p.a).project(cam);let x=(q.x+1)/2*W,y=(1-q.y)/2*H;
  for(let k=0;k<20&&used.some(u=>Math.abs(u[0]-x)<34&&Math.abs(u[1]-y)<20);k++)y+=20;used.push([x,y]);lbls[i].style.left=x+'px';lbls[i].style.top=y+'px';lbls[i].hidden=!p.lab});
 const R=new THREE.Matrix4().extractRotation(cam.matrixWorldInverse);const ax=['X','Y','Z'].map((n,j)=>{const e=new THREE.Vector3(j==0,j==1,j==2).applyMatrix4(R);return n+(Math.abs(e.z)>.9?(e.z>0?'⊙':'⊗'):'→'+(Math.round(Math.atan2(e.y,e.x)*180/Math.PI))+'°')});
 document.getElementById('ax').textContent='屏幕上轴向（0°=向右，90°=向上）：'+ax.join('  ')};window.READY=true;
</script></body></html>"""

VIEWS = {"iso": ([1, -1, 1], [0, 0, 1], "等轴测"), "front": ([0, -1, 0], [0, 0, 1], "从 -Y 看"), "back": ([0, 1, 0], [0, 0, 1], "从 +Y 看"),
         "top": ([0, 0, 1], [0, 1, 0], "从 +Z 看"), "bottom": ([0, 0, -1], [0, 1, 0], "从 -Z 看"), "side": ([1, 0, 0], [0, 0, 1], "从 +X 看"),
         "side2": ([-1, 0, 0], [0, 0, 1], "从 -X 看"), "iso2": ([-1, 1, 1], [0, 0, 1], "等轴测（反向）")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("step"); ap.add_argument("out")
    ap.add_argument("--views", default="iso,front,top,side")
    ap.add_argument("--hide", default=""); ap.add_argument("--only", default="")
    ap.add_argument("--ghost", default="", help="半透明显示的零件名称片段，逗号分隔")
    ap.add_argument("--section", default="", help="如 y=0：只保留 y<0 一侧；y=-0 写成 y>0 保留另一侧")
    ap.add_argument("--defl", type=float, default=0.15)
    a = ap.parse_args()
    parts = load_parts(a.step)
    hide = [h for h in a.hide.split(",") if h]; only = [h for h in a.only.split(",") if h]; ghost = [h for h in a.ghost.split(",") if h]
    out, legend = [], []
    for i, (n, s) in enumerate(parts):
        if any(h in n for h in hide) or (only and not any(o in n for o in only)):
            continue
        V, F = mesh(s, a.defl)
        b = bbox(s)
        idx = len(out) + 1
        out.append({"n": str(idx), "v": V, "f": F, "c": PALETTE[(idx - 1) % len(PALETTE)], "o": 0.25 if any(g in n for g in ghost) else 1,
                    "a": [(b[0] + b[3]) / 2, (b[1] + b[4]) / 2, (b[2] + b[5]) / 2], "lab": True})
        legend.append(f"{idx:>3}  {n}")
    sec = None
    if a.section:
        ax_, rest = a.section[0], a.section[1:]
        keep_pos = rest.startswith(">")
        val = float(rest.lstrip("=<>"))
        nvec = {"x": [1, 0, 0], "y": [0, 1, 0], "z": [0, 0, 1]}[ax_]
        # three.js 保留 n·p + c > 0 的一侧
        sec = {"n": nvec if keep_pos else [-v for v in nvec], "c": -val if keep_pos else val}
    three = os.environ.get("THREE_JS", os.path.join(os.path.dirname(os.path.abspath(__file__)), "three.min.js"))
    html = HTML.replace("/*THREE*/", open(three).read()).replace("/*DATA*/", json.dumps({"parts": out, "section": sec}))
    tmp = tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8"); tmp.write(html); tmp.close()
    open(a.out + "_图例.txt", "w", encoding="utf-8").write("\n".join(legend) + "\n")
    views = [v for v in a.views.split(",") if v]
    js = f"""const {{chromium}}=require('playwright');(async()=>{{const b=await chromium.launch({{args:['--use-gl=swiftshader','--enable-unsafe-swiftshader']}});
const p=await b.newPage({{viewport:{{width:1600,height:1000}}}});await p.goto('file://{tmp.name}');await p.waitForFunction('window.READY');
for(const [k,d,u,t] of {json.dumps([[v, *VIEWS[v]] for v in views], ensure_ascii=False)}){{await p.evaluate(([d,u,t])=>view(d,u,t),[d,u,t]);await p.screenshot({{path:'{a.out}_'+k+'.png'}})}}
await b.close()}})()"""
    jf = tmp.name + ".js"; open(jf, "w").write(js)
    subprocess.run(["node", jf], check=True)
    print("\n".join(legend))
    print("图片：", ", ".join(f"{a.out}_{v}.png" for v in views))


if __name__ == "__main__":
    main()
