#!/usr/bin/env python3
"""せん断試験と安息角試験を両立するパラメータを求める(手順書3.3)。

2つの応答曲面モデル式を重ね合わせ、目標値を同時に満たす点(交点)を算出する。

実行例:
    python scripts/overlay_targets.py
    python scripts/overlay_targets.py --saor-target 42.9 --shear-target 0.69898
    python scripts/overlay_targets.py --saor-range 41.9 42.9 --shear-target 0.69898
"""

import argparse
import os, numpy as np, pandas as pd, matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
from matplotlib.path import Path as MplPath
import matplotlib.patheffects as pe
import re
from pathlib import Path

from poscap_calibration.project_layout import (
    DEFAULT_PROJECT_ID,
    RSM_COMBINED_NAME,
    RSM_SAOR_NAME,
    RSM_SHEAR_NAME,
    ProjectLayout,
)
from poscap_calibration.shear_analysis_excel import get_peak_ratio
from poscap_calibration.state.identified_parameters import (
    PHASE1,
    record_identified_parameters,
)

# カレントディレクトリに依存しないようリポジトリ直下を基点にする。
REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROJECT_ROOT = REPO_ROOT / 'projects'

# ====== User inputs (STRICT) ======
X1_COL = '転がり抵抗'
X2_COL = '動摩擦係数'
DOMAIN_PAD = 0.00
Y1_NAME='SAOR'; Y2_NAME='Steady-state slope'
X1_LABEL='Rolling resistance coefficient'; X2_LABEL='Dynamic friction coefficient'
GRID_N=601; DPI=300

# CSV出力時の列名(モデル式のx1/x2を物理量名へ読み替える)。
X1_OUT_COL='rolling_resistance'
X2_OUT_COL='dynamic_friction'
STATIC_OUT_COL='static_friction'
COLOR_Y1=(31/255,119/255,180/255,1.0)
COLOR_Y2=(214/255,39/255,40/255,1.0)
COLOR_OVL=(176/255,0/255,255/255,1.0)
BASE_CURVE_LW=2.2; FEASIBLE_LW=4.6
HALO=[pe.Stroke(linewidth=BASE_CURVE_LW+2.6, foreground='white'), pe.Normal()]
HALO_FEAS=[pe.Stroke(linewidth=FEASIBLE_LW+2.6, foreground='white'), pe.Normal()]

DEFAULT_SAOR_TARGET = 42.9
DEFAULT_SHEAR_TARGET = 0.69898


def parse_arguments():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--project-id', default=DEFAULT_PROJECT_ID)
    parser.add_argument('--project-root', type=Path, default=DEFAULT_PROJECT_ROOT)
    parser.add_argument('--saor-equation', type=Path, default=None,
                        help='安息角のモデル式txt(既定はrsm/phase1/saor/outputs)')
    parser.add_argument('--shear-equation', type=Path, default=None,
                        help='せん断のモデル式txt(既定はrsm/phase1/shear/outputs)')
    parser.add_argument('--domain-csv', type=Path, default=None,
                        help='探索範囲を決める応答曲面用CSV(既定は安息角のCSV)')
    parser.add_argument('--output-dir', type=Path, default=None,
                        help='出力先フォルダ(既定はrsm/phase1/combined/outputs)')
    parser.add_argument('--peak-ratio-workbook', type=Path, default=None,
                        help='実験ピーク比を読む解析Excel(既定はせん断→安息角の順で探索)')
    parser.add_argument('--peak-ratio', type=float, default=None,
                        help='実験ピーク比を直接指定する(解析Excelより優先)')

    saor = parser.add_mutually_exclusive_group()
    saor.add_argument('--saor-target', type=float, default=None, help='安息角の目標値')
    saor.add_argument('--saor-range', type=float, nargs=2, metavar=('LOW', 'HIGH'),
                      default=None, help='安息角の許容範囲')
    shear = parser.add_mutually_exclusive_group()
    shear.add_argument('--shear-target', type=float, default=None, help='定常傾きの目標値')
    shear.add_argument('--shear-range', type=float, nargs=2, metavar=('LOW', 'HIGH'),
                       default=None, help='定常傾きの許容範囲')

    parser.add_argument('--extra-point', type=float, nargs=2, action='append',
                        metavar=('X1', 'X2'), default=None,
                        help='図に星印で重ねる任意の点(複数指定可)')
    return parser.parse_args()


def _target_spec(value, value_range, default_value):
    if value_range is not None:
        low, high = sorted(value_range)
        return {'type':'range','low':low,'high':high}
    return {'type':'value','val':default_value if value is None else value}


def _resolve_peak_ratio(args, layout):
    """\u5b9f\u9a13\u30d4\u30fc\u30af\u6bd4\u3092CLI\u6307\u5b9a\u307e\u305f\u306f\u89e3\u6790Excel\u306e\u300c\u8a2d\u5b9a\u30fb\u96c6\u8a08\u300d\u30b7\u30fc\u30c8\u304b\u3089\u53d6\u5f97\u3059\u308b\u3002"""
    if args.peak_ratio is not None:
        return args.peak_ratio, 'CLI (--peak-ratio)'
    if args.peak_ratio_workbook is not None:
        candidates = [args.peak_ratio_workbook]
    else:
        candidates = [layout.shear_workbook, layout.saor_workbook]
    checked = []
    for workbook in candidates:
        checked.append(str(workbook))
        if not Path(workbook).is_file():
            continue
        ratio = get_peak_ratio(workbook)
        if ratio is not None:
            return ratio, str(Path(workbook).resolve())
    raise RuntimeError(
        '\u5b9f\u9a13\u30d4\u30fc\u30af\u6bd4\u3092\u53d6\u5f97\u3067\u304d\u307e\u305b\u3093\u3067\u3057\u305f\u3002\u89e3\u6790Excel\u306e\u300c\u8a2d\u5b9a\u30fb\u96c6\u8a08\u300d\u30b7\u30fc\u30c8\u306b'
        f'\u300c\u30d4\u30fc\u30af\u6bd4\u300d\u3092\u5165\u529b\u3059\u308b\u304b--peak-ratio\u3067\u6307\u5b9a\u3057\u3066\u304f\u3060\u3055\u3044\u3002\u78ba\u8a8d\u5148: {checked}')


_ARGS = parse_arguments()
_LAYOUT = ProjectLayout(_ARGS.project_id, _ARGS.project_root)
PEAK_RATIO, PEAK_RATIO_SOURCE = _resolve_peak_ratio(_ARGS, _LAYOUT)


def save_points_csv(records, filename):
    """x1/x2を物理量名へ変換し、静止摩擦係数を加えてCSV出力する。"""
    frame = pd.DataFrame(records).rename(columns={'x1':X1_OUT_COL,'x2':X2_OUT_COL})
    frame.insert(frame.columns.get_loc(X2_OUT_COL)+1,
                 STATIC_OUT_COL, frame[X2_OUT_COL].astype(float)*PEAK_RATIO)
    frame.to_csv(os.path.join(case_dir, filename), index=False)
    return frame

# === Single targets (only this case is executed) ===
TARGETS = {
    'y1': _target_spec(_ARGS.saor_target, _ARGS.saor_range, DEFAULT_SAOR_TARGET),
    'y2': _target_spec(_ARGS.shear_target, _ARGS.shear_range, DEFAULT_SHEAR_TARGET),
}
# 図に重ねる任意の点(手順書では検証したいパラメータ候補を指定する)。
EXTRA_POINTS = [tuple(p) for p in (_ARGS.extra_point or [])]

# ====== Model helpers (EDIT ONLY THIS BLOCK for future changes) ======
COEFF_Y1_PATH = _ARGS.saor_equation or _LAYOUT.rsm_model_equation(RSM_SAOR_NAME)
COEFF_Y2_PATH = _ARGS.shear_equation or _LAYOUT.rsm_model_equation(RSM_SHEAR_NAME)
DOMAIN_CSV = _ARGS.domain_csv or _LAYOUT.saor_response_surface_csv
OUTPUT_DIR = _ARGS.output_dir or _LAYOUT.rsm_output_directory(RSM_COMBINED_NAME)

_DEF_ORDER=['1','x1','x2','x1^2','x2^2','x1*x2','x1^3','x2^3','x1^2*x2','x1*x2^2']

def parse_poly10_coeffs_from_txt(txt_path: str) -> dict:
    KEYS_MAP={'b0':'1','b1':'x1','b2':'x2','b11':'x1^2','b22':'x2^2','b12':'x1*x2','b111':'x1^3','b222':'x2^3','b112':'x1^2*x2','b122':'x1*x2^2'}
    float_re=r"([+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)"
    with open(txt_path,'r',encoding='utf-8') as f:
        s=f.read()
    coeffs={}
    for b,term in KEYS_MAP.items():
        m=re.search(rf"\b{b}\s*=\s*{float_re}", s)
        if not m: raise KeyError(f"Coefficient {b} not found in {txt_path}")
        coeffs[term]=float(m.group(1))
    return coeffs

def set_y1_parameters(txt_path: str | None = None) -> dict:
    txt = txt_path if txt_path else COEFF_Y1_PATH
    return parse_poly10_coeffs_from_txt(txt)

def set_y2_parameters(txt_path: str | None = None) -> dict:
    txt = txt_path if txt_path else COEFF_Y2_PATH
    return parse_poly10_coeffs_from_txt(txt)

# ---- scalar -> scalar（ここだけ編集） ----
def y_scalar_poly10(x1: float, x2: float, params: dict) -> float:
    b=params
    return (
        b['1']
        + b['x1']*x1 + b['x2']*x2
        + b['x1^2']*(x1**2) + b['x2^2']*(x2**2) + b['x1*x2']*(x1*x2)
        + b['x1^3']*(x1**3) + b['x2^3']*(x2**3)
        + b['x1^2*x2']*((x1**2)*x2) + b['x1*x2^2']*(x1*(x2**2))
    )

# ---- wrapper（配列 -> 配列 へ自動拡張） ----
def lift_to_array(scalar_fn):
    def array_fn(params: dict, X1, X2):
        X1 = np.asarray(X1, dtype=float)
        X2 = np.asarray(X2, dtype=float)
        orig_shape = np.broadcast(X1, X2).shape
        x1f = np.broadcast_to(X1, orig_shape).ravel()
        x2f = np.broadcast_to(X2, orig_shape).ravel()
        f = np.frompyfunc(lambda a,b: scalar_fn(float(a), float(b), params), 2, 1)
        y = f(x1f, x2f).astype(float)
        return y.reshape(orig_shape)
    return array_fn

# ---- eval（本文はこれだけ呼ぶ） ----
eval_model_y1 = lift_to_array(y_scalar_poly10)
eval_model_y2 = lift_to_array(y_scalar_poly10)

# ====== STRICT domain from CSV ======
if not (DOMAIN_CSV and X1_COL and X2_COL):
    raise ValueError('DOMAIN_CSV, X1_COL, X2_COL are required.')
if not os.path.exists(DOMAIN_CSV):
    raise FileNotFoundError(f'DOMAIN_CSV not found: {DOMAIN_CSV}')

_read_ok=False
# 応答曲面用CSVはBOM付きUTF-8。cp932は手動作成ファイルへの互換用。
for _enc in ('utf-8-sig','utf-8','cp932'):
    try:
        df=pd.read_csv(DOMAIN_CSV, encoding=_enc)
        _read_ok=True
        break
    except Exception:
        pass
if not _read_ok:
    raise RuntimeError(f'Failed to read CSV: {DOMAIN_CSV}')

if X1_COL not in df.columns: raise KeyError(f'x1 column not found: {X1_COL}')
if X2_COL not in df.columns: raise KeyError(f'x2 column not found: {X2_COL}')
x1v=df[X1_COL].astype(float).to_numpy(); x2v=df[X2_COL].astype(float).to_numpy()
if not np.isfinite(x1v).any() or not np.isfinite(x2v).any():
    raise ValueError('Non-finite values in domain columns.')
x1min,x1max=float(np.nanmin(x1v)), float(np.nanmax(x1v))
x2min,x2max=float(np.nanmin(x2v)), float(np.nanmax(x2v))
if abs(x1max-x1min)<1e-12 or abs(x2max-x2min)<1e-12:
    raise ValueError('Degenerate domain.')
if DOMAIN_PAD>0:
    x1rng=max(1e-9,x1max-x1min); x2rng=max(1e-9,x2max-x2min)
    x1min-=DOMAIN_PAD*x1rng; x1max+=DOMAIN_PAD*x1rng
    x2min-=DOMAIN_PAD*x2rng; x2max+=DOMAIN_PAD*x2rng

# ====== Grid ======
x1=np.linspace(x1min,x1max,GRID_N)
x2=np.linspace(x2min,x2max,GRID_N)
X1,X2=np.meshgrid(x1,x2)

PARAMS_Y1 = set_y1_parameters()
PARAMS_Y2 = set_y2_parameters()
Y1 = eval_model_y1(PARAMS_Y1, X1, X2)
Y2 = eval_model_y2(PARAMS_Y2, X1, X2)

# ====== Utilities ======
def _split_path(path):
    """1つのPathにMOVETOで連結された複数の等値線を分割する。"""
    verts=path.vertices; codes=path.codes
    if codes is None:
        return [verts.copy()]
    starts=[i for i,c in enumerate(codes) if c==MplPath.MOVETO] or [0]
    bounds=starts+[len(verts)]
    return [verts[a:b].copy() for a,b in zip(bounds[:-1],bounds[1:]) if b-a>=2]

def contour_paths(X,Y,Z,level):
    fig,ax=plt.subplots(figsize=(1,1))
    CS=ax.contour(X,Y,Z,levels=[level])
    segs=[]
    for p in CS.get_paths():
        segs.extend(_split_path(p))
    plt.close(fig); return segs

def contiguous_segments(poly, mask):
    segs=[]; n=len(mask); i=0
    while i<n:
        if mask[i]:
            j=i
            while j<n and mask[j]: j+=1
            if j-i>=2: segs.append(poly[i:j].copy())
            i=j
        else:
            i+=1
    return segs

def poly_intersections(poly1,poly2):
    def seg_intersect(a1,a2,b1,b2):
        x1,y1=a1; x2,y2=a2; x3,y3=b1; x4,y4=b2
        den=(x1-x2)*(y3-y4)-(y1-y2)*(x3-x4)
        if abs(den)<1e-12: return None
        px=((x1*y2-y1*x2)*(x3-x4)-(x1-x2)*(x3*y4-y3*x4))/den
        py=((x1*y2-y1*x2)*(y3-y4)-(y1-y2)*(x3*y4-y3*x4))/den
        def within(p,a,b):
            return (min(a[0],b[0])-1e-10<=p[0]<=max(a[0],b[0])+1e-10 and min(a[1],b[1])-1e-10<=p[1]<=max(a[1],b[1])+1e-10)
        P=(px,py); return P if within(P,a1,a2) and within(P,b1,b2) else None
    pts=[]
    for i in range(len(poly1)-1):
        for j in range(len(poly2)-1):
            P=seg_intersect(poly1[i],poly1[i+1],poly2[j],poly2[j+1])
            if P is not None and not any(abs(P[0]-q[0])<1e-6 and abs(P[1]-q[1])<1e-6 for q in pts):
                pts.append(P)
    return pts

def polyline_edge_intersections(poly, x1min,x1max,x2min,x2max):
    res=[]
    edges=[('x1',x1min),('x1',x1max),('x2',x2min),('x2',x2max)]
    for k in range(len(poly)-1):
        xA,yA=poly[k]; xB,yB=poly[k+1]
        dx=xB-xA; dy=yB-yA
        for axis,val in edges:
            if axis=='x1':
                if (xA-val)*(xB-val)<=0 and abs(dx)>1e-12:
                    t=(val-xA)/dx
                    if -1e-12<=t<=1+1e-12:
                        y=yA+t*dy
                        if x2min-1e-12<=y<=x2max+1e-12:
                            res.append((val,y,f'domain_edge:x1={val}'))
            else:
                if (yA-val)*(yB-val)<=0 and abs(dy)>1e-12:
                    t=(val-yA)/dy
                    if -1e-12<=t<=1+1e-12:
                        x_=xA+t*dx
                        if x1min-1e-12<=x_<=x1max+1e-12:
                            res.append((x_,val,f'domain_edge:x2={val}'))
    out=[]
    for p in res:
        if not any(abs(p[0]-q[0])<1e-6 and abs(p[1]-q[1])<1e-6 and p[2]==q[2] for q in out):
            out.append(p)
    return out

# ====== Render & Save (v9 filenames; title string without the phrase) ======
case_dir=str(OUTPUT_DIR)
os.makedirs(case_dir, exist_ok=True)
fig,ax=plt.subplots(figsize=(8,7))
t1=TARGETS['y1']; t2=TARGETS['y2']

# No explicit title text including the phrase; otherwise as v9
# (if you want a custom title, add it here WITHOUT the words 'blue-red-purple v9').

if t1['type']=='range' and t2['type']=='range':
    extra_handles=[]
    y1l,y1h=sorted([float(t1['low']),float(t1['high'])])
    y2l,y2h=sorted([float(t2['low']),float(t2['high'])])
    m1=(Y1>=y1l)&(Y1<=y1h)
    m2=(Y2>=y2l)&(Y2<=y2h)
    ov=m1 & m2
    rgba=np.zeros((Y1.shape[0],Y1.shape[1],4),float)
    rgba[m1]=COLOR_Y1; rgba[m2]=COLOR_Y2; rgba[ov]=COLOR_OVL
    ax.imshow(rgba, extent=[x1min,x1max,x2min,x2max], origin='lower', aspect='auto')
    endpoints=[]
    segs_y1_low  = contour_paths(X1,X2,Y1,y1l)
    segs_y1_high = contour_paths(X1,X2,Y1,y1h)
    segs_y2_low  = contour_paths(X1,X2,Y2,y2l)
    segs_y2_high = contour_paths(X1,X2,Y2,y2h)
    for lab1,segs1 in [(f"{Y1_NAME}={y1l}",segs_y1_low),(f"{Y1_NAME}={y1h}",segs_y1_high)]:
        for lab2,segs2 in [(f"{Y2_NAME}={y2l}",segs_y2_low),(f"{Y2_NAME}={y2h}",segs_y2_high)]:
            for p1 in segs1:
                for p2 in segs2:
                    for (xi,yi) in poly_intersections(p1,p2):
                        endpoints.append({'x1':xi,'x2':yi,'boundary1':lab1,'boundary2':lab2})
    def add_domain_inters(segs, label):
        for poly in segs:
            for (xi,yi,edge_label) in polyline_edge_intersections(poly, x1min,x1max,x2min,x2max):
                endpoints.append({'x1':xi,'x2':yi,'boundary1':label,'boundary2':edge_label})
    add_domain_inters(segs_y1_low,  f"{Y1_NAME}={y1l}")
    add_domain_inters(segs_y1_high, f"{Y1_NAME}={y1h}")
    add_domain_inters(segs_y2_low,  f"{Y2_NAME}={y2l}")
    add_domain_inters(segs_y2_high, f"{Y2_NAME}={y2h}")
    if endpoints:
        save_points_csv(pd.DataFrame(endpoints).drop_duplicates(subset=['x1','x2']), 'range_boundary_intersections.csv')
    if ov.any():
        xs=X1[ov]; ys=X2[ov]
        xc=0.5*(x1min+x1max); yc=0.5*(x2min+x2max)
        idx=np.argmin((xs-xc)**2+(ys-yc)**2)
        save_points_csv([{'x1':float(xs[idx]),'x2':float(ys[idx])}], 'closest_point_in_region.csv')
        # Labeled closest point in overlap (Overlap color, black edge)
        h_close = ax.scatter([float(xs[idx])], [float(ys[idx])], s=90, color=COLOR_OVL, edgecolors='k', linewidths=0.8, zorder=6, label=f"Closest in overlap ({float(xs[idx]):.5f}, {float(ys[idx]):.5f})")
        extra_handles.append(h_close)
    # Added: user-specified extra points (black stars) [both_ranges]
    for (px,py) in EXTRA_POINTS:
        h_star = ax.scatter([px], [py], marker='*', s=70, c='k', edgecolors='none', zorder=7, label=f"Point ({px:.5f}, {py:.5f})")
        extra_handles.append(h_star)
    ax.legend(handles=[Patch(facecolor=COLOR_Y1,label=f"{Y1_NAME} ∈ [{y1l}, {y1h}]"), Patch(facecolor=COLOR_Y2,label=f"{Y2_NAME} ∈ [{y2l}, {y2h}]"), Patch(facecolor=COLOR_OVL,label='Overlap')] + extra_handles, loc='lower right')

elif (t1['type']=='range' and t2['type']=='value') or (t1['type']=='value' and t2['type']=='range'):
    if t2['type']=='value':
        y1l,y1h=sorted([float(t1['low']),float(t1['high'])]); y2v=float(t2['val'])
        m1=(Y1>=y1l)&(Y1<=y1h)
        rgba=np.zeros((Y1.shape[0],Y1.shape[1],4),float); rgba[m1]=COLOR_Y1
        ax.imshow(rgba, extent=[x1min,x1max,x2min,x2max], origin='lower', aspect='auto')
        segs=contour_paths(X1,X2,Y2,y2v)
        feas_pts=[]; added=False; rows=[]
        for poly in segs:
            ax.plot(poly[:,0],poly[:,1],color=COLOR_Y2,lw=BASE_CURVE_LW,path_effects=HALO,label=f"{Y2_NAME}={y2v}" if not added else '')
            added=True
            vals = eval_model_y1(PARAMS_Y1, poly[:,0], poly[:,1])
            ok=(vals>=y1l)&(vals<=y1h)
            idxs=np.where(ok)[0]
            if idxs.size>0:
                s=idxs[0]; prev=idxs[0]
                for k in idxs[1:]:
                    if k!=prev+1:
                        seg=poly[s:prev+1]; feas_pts.extend(seg.tolist())
                        for tag,pt in [('start',seg[0]),('end',seg[-1])]:
                            x,y=pt; val = float(eval_model_y1(PARAMS_Y1, [x],[y])[0])
                            reason=f"{Y1_NAME}={y1l}" if abs(val-y1l)<abs(val-y1h) else f"{Y1_NAME}={y1h}"
                            if (abs(x-x1min)<1e-6 or abs(x-x1max)<1e-6 or abs(y-x2min)<1e-6 or abs(y-x2max)<1e-6): reason='domain_edge'
                            rows.append({'segment_id':len(rows)//2+1,'endpoint':tag,'x1':x,'x2':y,'terminal_reason':reason})
                        s=k
                    prev=k
                seg=poly[s:prev+1]; feas_pts.extend(seg.tolist())
                for tag,pt in [('start',seg[0]),('end',seg[-1])]:
                    x,y=pt; val = float(eval_model_y1(PARAMS_Y1, [x],[y])[0])
                    reason=f"{Y1_NAME}={y1l}" if abs(val-y1l)<abs(val-y1h) else f"{Y1_NAME}={y1h}"
                    if (abs(x-x1min)<1e-6 or abs(x-x1max)<1e-6 or abs(y-x2min)<1e-6 or abs(y-x2max)<1e-6): reason='domain_edge'
                    rows.append({'segment_id':len(rows)//2+1,'endpoint':tag,'x1':x,'x2':y,'terminal_reason':reason})
            for seg in contiguous_segments(poly, ok):
                ax.plot(seg[:,0],seg[:,1],color=COLOR_OVL,lw=FEASIBLE_LW,path_effects=HALO_FEAS,label='Feasible segment')
        if rows:
            save_points_csv(rows, 'feasible_segment_endpoints.csv')
        with open(os.path.join(case_dir,'Feasible_curve_equation.txt'),'w',encoding='utf-8') as f:
            b=np.array([PARAMS_Y2[k] for k in _DEF_ORDER], dtype=float)
            f.write('Model equation (level set = response):\n')
            f.write(f" {y2v} = {b[0]:.12f} + {b[1]:.12f}*x1 + {b[2]:.12f}*x2 + {b[3]:.12f}*x1^2 + {b[4]:.12f}*x2^2 + {b[5]:.12f}*x1*x2 + {b[6]:.12f}*x1^3 + {b[7]:.12f}*x2^3 + {b[8]:.12f}*x1^2*x2 + {b[9]:.12f}*x1*x2^2\n")
        if feas_pts:
            fp=np.array(feas_pts); xc=0.5*(x1min+x1max); yc=0.5*(x2min+x2max)
            i=np.argmin((fp[:,0]-xc)**2+(fp[:,1]-yc)**2)
            save_points_csv([{'x1':float(fp[i,0]),'x2':float(fp[i,1])}], 'closest_point_on_feasible_curve.csv')
            # Labeled closest point on feasible curve (Overlap color)
            if len(feas_pts)>0:
                cp_x=float(fp[i,0]); cp_y=float(fp[i,1])
                ax.scatter([cp_x], [cp_y], s=90, color=COLOR_OVL, edgecolors='k', linewidths=0.8, zorder=6, label=f"Closest on curve ({cp_x:.5f}, {cp_y:.5f})")
        # Added: user-specified extra points (black stars) [y2_fixed]
        for (px,py) in EXTRA_POINTS:
            ax.scatter([px], [py], marker='*', s=70, c='k', edgecolors='none', zorder=7, label=f"Point ({px:.5f}, {py:.5f})")
        ax.legend(loc='lower right')
        h, lbl = ax.get_legend_handles_labels()
        h.append(Patch(facecolor=COLOR_Y1, label=f"{Y1_NAME} ∈ [{y1l}, {y1h}]"))
        lbl.append(f"{Y1_NAME} ∈ [{y1l}, {y1h}]")
        pairs = list(zip(lbl, h))
        pairs.sort(key=lambda t: (0 if Y1_NAME in t[0] else (1 if Y2_NAME in t[0] else 2)))
        lbl = [t[0] for t in pairs]
        h   = [t[1] for t in pairs]
        ax.legend(h, lbl, loc='lower right')
    else:
        y2l,y2h=sorted([float(t2['low']),float(t2['high'])]); y1v=float(t1['val'])
        m2=(Y2>=y2l)&(Y2<=y2h)
        rgba=np.zeros((Y2.shape[0],Y2.shape[1],4),float); rgba[m2]=COLOR_Y2
        ax.imshow(rgba, extent=[x1min,x1max,x2min,x2max], origin='lower', aspect='auto')
        segs=contour_paths(X1,X2,Y1,y1v)
        feas_pts=[]; added=False; rows=[]
        for poly in segs:
            ax.plot(poly[:,0],poly[:,1],color=COLOR_Y1,lw=BASE_CURVE_LW,path_effects=HALO,label=f"{Y1_NAME}={y1v}" if not added else '')
            added=True
            vals = eval_model_y2(PARAMS_Y2, poly[:,0], poly[:,1])
            ok=(vals>=y2l)&(vals<=y2h)
            idxs=np.where(ok)[0]
            if idxs.size>0:
                s=idxs[0]; prev=idxs[0]
                for k in idxs[1:]:
                    if k!=prev+1:
                        seg=poly[s:prev+1]; feas_pts.extend(seg.tolist())
                        for tag,pt in [('start',seg[0]),('end',seg[-1])]:
                            x,y=pt; val = float(eval_model_y2(PARAMS_Y2, [x],[y])[0])
                            reason=f"{Y2_NAME}={y2l}" if abs(val-y2l)<abs(val-y2h) else f"{Y2_NAME}={y2h}"
                            if (abs(x-x1min)<1e-6 or abs(x-x1max)<1e-6 or abs(y-x2min)<1e-6 or abs(y-x2max)<1e-6): reason='domain_edge'
                            rows.append({'segment_id':len(rows)//2+1,'endpoint':tag,'x1':x,'x2':y,'terminal_reason':reason})
                        s=k
                    prev=k
                seg=poly[s:prev+1]; feas_pts.extend(seg.tolist())
                for tag,pt in [('start',seg[0]),('end',seg[-1])]:
                    x,y=pt; val = float(eval_model_y2(PARAMS_Y2, [x],[y])[0])
                    reason=f"{Y2_NAME}={y2l}" if abs(val-y2l)<abs(val-y2h) else f"{Y2_NAME}={y2h}"
                    if (abs(x-x1min)<1e-6 or abs(x-x1max)<1e-6 or abs(y-x2min)<1e-6 or abs(y-x2max)<1e-6): reason='domain_edge'
                    rows.append({'segment_id':len(rows)//2+1,'endpoint':tag,'x1':x,'x2':y,'terminal_reason':reason})
            for seg in contiguous_segments(poly, ok):
                ax.plot(seg[:,0],seg[:,1],color=COLOR_OVL,lw=FEASIBLE_LW,path_effects=HALO_FEAS,label='Feasible segment')
        if rows:
            save_points_csv(rows, 'feasible_segment_endpoints.csv')
        with open(os.path.join(case_dir,'Feasible_curve_equation.txt'),'w',encoding='utf-8') as f:
            b=np.array([PARAMS_Y1[k] for k in _DEF_ORDER], dtype=float)
            f.write('Model equation (level set = response):\n')
            f.write(f" {y1v} = {b[0]:.12f} + {b[1]:.12f}*x1 + {b[2]:.12f}*x2 + {b[3]:.12f}*x1^2 + {b[4]:.12f}*x2^2 + {b[5]:.12f}*x1*x2 + {b[6]:.12f}*x1^3 + {b[7]:.12f}*x2^3 + {b[8]:.12f}*x1^2*x2 + {b[9]:.12f}*x1*x2^2\n")
        if feas_pts:
            fp=np.array(feas_pts); xc=0.5*(x1min+x1max); yc=0.5*(x2min+x2max)
            i=np.argmin((fp[:,0]-xc)**2+(fp[:,1]-yc)**2)
            save_points_csv([{'x1':float(fp[i,0]),'x2':float(fp[i,1])}], 'closest_point_on_feasible_curve.csv')
            # Labeled closest point on feasible curve (Overlap color)
            if len(feas_pts)>0:
                cp_x=float(fp[i,0]); cp_y=float(fp[i,1])
                ax.scatter([cp_x], [cp_y], s=90, color=COLOR_OVL, edgecolors='k', linewidths=0.8, zorder=6, label=f"Closest on curve ({cp_x:.5f}, {cp_y:.5f})")
        # Added: user-specified extra points (black stars) [y1_fixed]
        for (px,py) in EXTRA_POINTS:
            ax.scatter([px], [py], marker='*', s=70, c='k', edgecolors='none', zorder=7, label=f"Point ({px:.5f}, {py:.5f})")
        ax.legend(loc='lower right')
        h, lbl = ax.get_legend_handles_labels()
        h.append(Patch(facecolor=COLOR_Y2, label=f"{Y2_NAME} ∈ [{y2l}, {y2h}]"))
        lbl.append(f"{Y2_NAME} ∈ [{y2l}, {y2h}]")
        pairs = list(zip(lbl, h))
        pairs.sort(key=lambda t: (0 if Y1_NAME in t[0] else (1 if Y2_NAME in t[0] else 2)))
        lbl = [t[0] for t in pairs]
        h   = [t[1] for t in pairs]
        ax.legend(h, lbl, loc='lower right')

else:
    y1v=float(t1['val']); y2v=float(t2['val'])
    segs1=contour_paths(X1,X2,Y1,y1v)
    segs2=contour_paths(X1,X2,Y2,y2v)
    for poly in segs1:
        ax.plot(poly[:,0],poly[:,1],color=COLOR_Y1,lw=BASE_CURVE_LW+1.0,path_effects=HALO,label=f"{Y1_NAME}={y1v}")
    for poly in segs2:
        ax.plot(poly[:,0],poly[:,1],color=COLOR_Y2,lw=BASE_CURVE_LW+1.0,path_effects=HALO,label=f"{Y2_NAME}={y2v}")
    inters=[]
    for p1 in segs1:
        for p2 in segs2:
            inters+=poly_intersections(p1,p2)
    if inters:
        save_points_csv({'x1':[p[0] for p in inters],'x2':[p[1] for p in inters]}, 'intersections_points.csv')
        # Added: intersections & extra points (both_values only)
        if inters:
            for k,(ix,iy) in enumerate(inters, start=1):
                ax.scatter([ix], [iy], s=90, color=COLOR_OVL, edgecolors='k', linewidths=0.8, zorder=6, label=f"Intersection {k} ({ix:.5f}, {iy:.5f})")
    for (px,py) in EXTRA_POINTS:
        ax.scatter([px], [py], marker='*', s=70, c='k', edgecolors='none', zorder=7, label=f"Point ({px:.5f}, {py:.5f})")
    ax.legend(loc='lower right')

# ===== v9-style filenames =====
# v9で一般的に用いた命名: 'overlay_<case>.png'
png_name = f'overlay.png'
ax.set_xlabel(X1_LABEL); ax.set_ylabel(X2_LABEL)
ax.set_xlim([x1min,x1max]); ax.set_ylim([x2min,x2max])
plt.tight_layout(); fig.savefig(os.path.join(case_dir,png_name), dpi=DPI); plt.close(fig)

print(f'[OK] 重ね合わせ結果を出力しました: {OUTPUT_DIR.resolve()}')
print(f'     安息角モデル式 : {Path(COEFF_Y1_PATH).resolve()}')
print(f'     せん断モデル式 : {Path(COEFF_Y2_PATH).resolve()}')
print(f'     探索範囲CSV    : {Path(DOMAIN_CSV).resolve()}')
print(f'     目標値         : {Y1_NAME}={TARGETS["y1"]} / {Y2_NAME}={TARGETS["y2"]}')
print(f'     実験ピーク比   : {PEAK_RATIO} (取得元: {PEAK_RATIO_SOURCE})')
_SOLUTION_FILES = ('intersections_points.csv', 'closest_point_in_region.csv',
                   'closest_point_on_feasible_curve.csv')
for _name in _SOLUTION_FILES:
    _path=OUTPUT_DIR/_name
    if _path.is_file():
        for _row in pd.read_csv(_path).itertuples(index=False):
            print(f'     解 ({_name}) : {X1_OUT_COL}={getattr(_row,X1_OUT_COL):.5f}'
                  f' / {X2_OUT_COL}={getattr(_row,X2_OUT_COL):.5f}'
                  f' / {STATIC_OUT_COL}={getattr(_row,STATIC_OUT_COL):.5f}')


def _record_phase1_identified_parameters():
    """交点(なければ最近傍点)をフェーズ1の同定値としてプロジェクト直下へ記録する。"""
    for name in _SOLUTION_FILES:
        path = OUTPUT_DIR / name
        if not path.is_file():
            continue
        frame = pd.read_csv(path)
        if frame.empty:
            continue
        row = frame.iloc[0]
        values = {
            X1_OUT_COL: float(row[X1_OUT_COL]),
            X2_OUT_COL: float(row[X2_OUT_COL]),
            STATIC_OUT_COL: float(row[STATIC_OUT_COL]),
        }
        recorded = record_identified_parameters(
            _LAYOUT.project_directory,
            PHASE1,
            values,
            source=str(path.resolve()),
            targets={Y1_NAME: TARGETS['y1'], Y2_NAME: TARGETS['y2']},
            notes=f'解の種類: {name} / 実験ピーク比={PEAK_RATIO} (取得元: {PEAK_RATIO_SOURCE})',
        )
        print(f'[OK] フェーズ1の同定値を記録しました: {recorded}')
        for key, value in values.items():
            print(f'     {key} = {value:.5f}')
        return
    print('[WARN] 解が得られなかったため同定値は記録していません。'
          '目標値(--saor-target/--shear-target)や探索範囲を見直してください。')


_record_phase1_identified_parameters()
