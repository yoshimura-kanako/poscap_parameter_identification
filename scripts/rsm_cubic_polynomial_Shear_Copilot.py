# -*- coding: utf-8 -*-

import os, json, math
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patheffects as pe
from mpl_toolkits.mplot3d import Axes3D  # noqa: F401
HALO = [pe.Stroke(linewidth=4.6, foreground='white'), pe.Normal()]

# ===== Settings =====
DATA_FILE = 'せん断.csv'
X1_COL = '転がり抵抗'
X2_COL = '動摩擦係数'
Y_COL  = '定常傾き'

# Labels (English)
X1_LABEL = 'Rolling resistance coefficient'
X2_LABEL = 'Dynamic friction coefficient'
Y_LABEL  = 'Steady-state slope'

OUT_PREFIX = 'cubic_poly_'
GRID_N = 401
DPI = 300

BASE_ENABLE   = True
TARGET_ENABLE = True
TARGET_LEVELS = [0.69898]

CONTRAST_COLORS = ['#000000', '#D62728', '#FF7F0E', '#9467BD', '#E377C2', '#8C564B']
# =====================

def _load_df_strict():
    errs = []
    for enc in ('cp932','utf-8','utf-8-sig'):
        try:
            return pd.read_csv(DATA_FILE, encoding=enc)
        except Exception as e:
            errs.append(f"{enc}: {e}")
    raise RuntimeError('Failed to read '+DATA_FILE+' with encodings: '+', '.join(errs))

def _grid_domain(df):
    x1 = df[X1_COL].astype(float).values
    x2 = df[X2_COL].astype(float).values
    x1g = np.linspace(x1.min(), x1.max(), GRID_N)
    x2g = np.linspace(x2.min(), x2.max(), GRID_N)
    return x1, x2, x1g, x2g

def _extract_contours(X1g,X2g,Yg,levels):
    fig_tmp,ax_tmp=plt.subplots(figsize=(1,1))
    CS=ax_tmp.contour(X1g,X2g,Yg,levels=sorted(levels))
    out={}
    if hasattr(CS,'collections') and CS.collections:
        for lev,coll in zip(CS.levels, CS.collections):
            segs=[]
            for p in coll.get_paths():
                v=p.vertices
                if v.shape[0]>=2: segs.append(v)
            out[lev]=segs
    plt.close(fig_tmp)
    return out

def _save_residuals_and_predictions(df, yhat):
    x1=df[X1_COL].astype(float).values
    x2=df[X2_COL].astype(float).values
    y =df[Y_COL].astype(float).values
    resid=y-yhat
    # Use quadratic design for leverage approx
    X=np.column_stack([np.ones_like(x1), x1, x2, x1**2, x2**2, x1*x2])
    try:
        H=X@np.linalg.inv(X.T@X)@X.T
        h=np.clip(np.diag(H),0,0.9999)
        SSE=float(np.sum(resid**2)); sigma2=SSE/max(1,(X.shape[0]-X.shape[1]))
        std_resid=resid/np.sqrt(sigma2*(1-h))
        stud=np.empty_like(resid)
        for i in range(len(resid)):
            s_i2=(SSE - resid[i]**2/(1-h[i]))/max(1,(X.shape[0]-X.shape[1]-1))
            stud[i]=resid[i]/np.sqrt(max(1e-12,s_i2*(1-h[i])))
    except Exception:
        h=np.zeros_like(resid); std_resid=resid; stud=resid

    pd.DataFrame({
        '転がり抵抗':df[X1_COL], '動摩擦係数':df[X2_COL], '定常傾き':y,
        f'Fitted ({Y_LABEL})':yhat,
        'Residual (Data - Fitted)':resid,
        'Leverage (h)':h,
        'Std. residual':std_resid,
        'Studentized residual':stud
    }).to_csv(f'{OUT_PREFIX}RSM_residuals_table.csv', index=False)

    # residuals plots
    plt.figure(figsize=(8,6)); plt.scatter(yhat,resid,color='#4C78A8',edgecolor='k',s=80)
    plt.axhline(0,color='gray',lw=1); plt.grid(True,alpha=0.3)
    plt.title(f'Residuals vs. Fitted ({Y_LABEL})'); plt.xlabel(f'Fitted value ({Y_LABEL})'); plt.ylabel('Residual (Data - Fitted)')
    plt.tight_layout(); plt.savefig(f'{OUT_PREFIX}Residuals_vs_Fitted.png', dpi=DPI); plt.close()

    plt.figure(figsize=(8,6)); plt.scatter(x1,resid,color='#F58518',edgecolor='k',s=80)
    plt.axhline(0,color='gray',lw=1); plt.grid(True,alpha=0.3)
    plt.title(f'Residuals vs. {X1_LABEL}'); plt.xlabel(X1_LABEL); plt.ylabel('Residual (Data - Fitted)')
    plt.tight_layout(); plt.savefig(f'{OUT_PREFIX}Residuals_vs_x1.png', dpi=DPI); plt.close()

    plt.figure(figsize=(8,6)); plt.scatter(x2,resid,color='#54A24B',edgecolor='k',s=80)
    plt.axhline(0,color='gray',lw=1); plt.grid(True,alpha=0.3)
    plt.title(f'Residuals vs. {X2_LABEL}'); plt.xlabel(X2_LABEL); plt.ylabel('Residual (Data - Fitted)')
    plt.tight_layout(); plt.savefig(f'{OUT_PREFIX}Residuals_vs_x2.png', dpi=DPI); plt.close()

    plt.figure(figsize=(7,6)); m=float(np.max(np.abs(resid))) if len(resid)>0 else 1.0
    sc=plt.scatter(x1,x2,c=resid,cmap='seismic',vmin=-m,vmax=+m,s=120,edgecolor='k')
    plt.colorbar(sc,label='Residual (Data - Fitted)'); plt.title(f'Residuals on {X1_LABEL}–{X2_LABEL} plane')
    plt.xlabel(X1_LABEL); plt.ylabel(X2_LABEL); plt.grid(True,alpha=0.3)
    plt.tight_layout(); plt.savefig(f'{OUT_PREFIX}Residuals_plane_scatter.png', dpi=DPI); plt.close()

    plt.figure(figsize=(7,5)); plt.hist(resid,bins=6,color='#4C78A8',edgecolor='k',alpha=0.8)
    plt.axvline(0,color='gray',lw=1); plt.title('Residuals histogram'); plt.xlabel('Residual (Data - Fitted)'); plt.ylabel('Count')
    plt.tight_layout(); plt.savefig(f'{OUT_PREFIX}Residuals_hist.png', dpi=DPI); plt.close()

    out2=df.copy(); out2[f'Predicted ({Y_LABEL})']=yhat; out2['Residual (Data - Pred)']=y - yhat
    out2.to_csv(f'{OUT_PREFIX}RSM_point_predictions_residuals.csv', index=False)


def _surface_and_contour(df, X1g, X2g, Yg):
    x1=df[X1_COL].astype(float).values; x2=df[X2_COL].astype(float).values; y=df[Y_COL].astype(float).values
    fig=plt.figure(figsize=(8,6)); ax=plt.axes(projection='3d')
    surf=ax.plot_surface(X1g,X2g,Yg,cmap='viridis',edgecolor='none',alpha=0.9)
    ax.set_title(f'Response Surface: {Y_LABEL}')
    ax.set_xlabel(X1_LABEL); ax.set_ylabel(X2_LABEL); ax.set_zlabel(Y_LABEL)
    ax.set_xlim(x1.min(),x1.max()); ax.set_ylim(x2.min(),x2.max()); ax.view_init(25,-135)
    plt.colorbar(surf,shrink=0.6,aspect=10,label=Y_LABEL)
    plt.tight_layout(); plt.savefig(f'{OUT_PREFIX}RSM_surface.png',dpi=DPI); plt.close()

    plt.figure(figsize=(7,6)); cont=plt.contourf(X1g,X2g,Yg,levels=30,cmap='viridis')
    plt.scatter(x1,x2,c=y,cmap='viridis',edgecolor='k',s=70)
    plt.title(f'Contour: {Y_LABEL}')
    plt.xlabel(X1_LABEL); plt.ylabel(X2_LABEL)
    plt.xlim(x1.min(),x1.max()); plt.ylim(x2.min(),x2.max())
    plt.colorbar(cont,label=f'{Y_LABEL} (model)')
    plt.tight_layout(); plt.savefig(f'{OUT_PREFIX}RSM_contour.png',dpi=DPI); plt.close()


def _overlay_targets(df, X1g, X2g, Yg):
    x1=df[X1_COL].astype(float).values; x2=df[X2_COL].astype(float).values; y=df[Y_COL].astype(float).values
    level_to_segments=_extract_contours(X1g,X2g,Yg,TARGET_LEVELS)

    fig=plt.figure(figsize=(8,6)); ax=plt.axes(projection='3d')
    surf=ax.plot_surface(X1g,X2g,Yg,cmap='viridis',edgecolor='none',alpha=0.9)
    ax.set_title(f'Response Surface: {Y_LABEL}')
    ax.set_xlabel(X1_LABEL); ax.set_ylabel(X2_LABEL); ax.set_zlabel(Y_LABEL)
    ax.set_xlim(x1.min(),x1.max()); ax.set_ylim(x2.min(),x2.max()); ax.view_init(25,-135)
    plt.colorbar(surf,shrink=0.6,aspect=10,label=Y_LABEL)
    for i,(lev,segs) in enumerate(sorted(level_to_segments.items())):
        col=CONTRAST_COLORS[i%len(CONTRAST_COLORS)]
        for seg in segs:
            ax.plot(seg[:,0], seg[:,1], zs=lev, zdir='z', color=col, lw=3.0, path_effects=HALO)
    plt.tight_layout(); plt.savefig(f'{OUT_PREFIX}RSM_surface_with_target_contrast.png',dpi=DPI); plt.close()

    plt.figure(figsize=(7,6)); cont=plt.contourf(X1g,X2g,Yg,levels=30,cmap='viridis')
    plt.scatter(x1,x2,c=y,cmap='viridis',edgecolor='k',s=70)
    plt.title(f'Contour: {Y_LABEL}')
    plt.xlabel(X1_LABEL); plt.ylabel(X2_LABEL)
    plt.xlim(x1.min(),x1.max()); plt.ylim(x2.min(),x2.max())
    plt.colorbar(cont,label=f'{Y_LABEL} (model)')
    for i,(lev,segs) in enumerate(sorted(level_to_segments.items())):
        col=CONTRAST_COLORS[i%len(CONTRAST_COLORS)]
        for seg in segs:
            plt.plot(seg[:,0], seg[:,1], color=col, lw=3.0, path_effects=HALO, label=f'{Y_LABEL} = {lev:.5f}')
    h,l=plt.gca().get_legend_handles_labels(); uniq=dict(zip(l,h))
    if uniq: plt.legend(uniq.values(), uniq.keys(), loc='lower right')
    plt.tight_layout(); plt.savefig(f'{OUT_PREFIX}RSM_contour_with_target_contrast.png',dpi=DPI); plt.close()

    # Export contour points and levels
    rows=[]
    for lev,segs in level_to_segments.items():
        for seg_id,seg in enumerate(segs):
            for xv,yv in seg:
                rows.append([lev,seg_id,xv,yv])
    if rows:
        pd.DataFrame(rows,columns=['target','segment','x1','x2']).to_csv(f'{OUT_PREFIX}RSM_target_curve_points.csv',index=False)
    levels_str = ', '.join(['{:.10g}'.format(v) for v in TARGET_LEVELS])
    with open(f'{OUT_PREFIX}RSM_target_levels.txt','w',encoding='utf-8') as f:
        f.write('Target levels (y): ' + levels_str + '\n')

PARAM_NAMES=['b0','b1','b2','b11','b22','b12','b111','b222','b112','b122']

def _build_X(x1,x2):
    return np.column_stack([
        np.ones_like(x1), x1, x2,
        x1**2, x2**2, x1*x2,
        x1**3, x2**3, (x1**2)*x2, x1*(x2**2)
    ])

def _fit(df):
    x1,x2,_,_=_grid_domain(df); y=df[Y_COL].astype(float).values
    X=_build_X(x1,x2); beta,*_=np.linalg.lstsq(X,y,rcond=None)
    yhat=X@beta
    n=len(y); p=X.shape[1]
    SSE=float(np.sum((y-yhat)**2)); SST=float(np.sum((y-np.mean(y))**2)); R2=1-SSE/SST; Adj=1-(1-R2)*(n-1)/(n-p) if n>p else R2
    return beta,yhat,R2,Adj

def _predict_grid(beta,df):
    x1,x2,x1g,x2g=_grid_domain(df); X1g,X2g=np.meshgrid(x1g,x2g)
    Xg=_build_X(X1g.ravel(), X2g.ravel())
    Yg=(Xg@beta).reshape(X1g.shape)
    return X1g,X2g,Yg

def _loocv_rmse(df):
    x1,x2,_,_=_grid_domain(df); y=df[Y_COL].astype(float).values; X=_build_X(x1,x2)
    se=0.0
    for i in range(len(y)):
        m=np.ones(len(y),dtype=bool); m[i]=False
        b,*_=np.linalg.lstsq(X[m], y[m], rcond=None)
        yi=float(X[i]@b)
        se+=(y[i]-yi)**2
    return float(np.sqrt(se/len(y)))

def _write_equation_txt(beta):
    lines=[]
    lines.append("Model: global cubic response surface (generic variables)\n\n")
    lines.append("Equation (symbolic):\n")
    lines.append("  y = b0 + b1*x1 + b2*x2 + b11*x1^2 + b22*x2^2 + b12*x1*x2 + b111*x1^3 + b222*x2^3 + b112*x1^2*x2 + b122*x1*x2^2\n\n")
    lines.append("Variable mapping:\n")
    lines.append(f"  x1 : {X1_LABEL}  (CSV column: '{X1_COL}')\n")
    lines.append(f"  x2 : {X2_LABEL}  (CSV column: '{X2_COL}')\n")
    lines.append(f"  y  : {Y_LABEL}   (CSV column: '{Y_COL}')\n\n")
    lines.append('Coefficients (numeric):\n')
    for nm,v in zip(PARAM_NAMES,beta):
        lines.append(f"  {nm} = {float(v):.12f}\n")
    with open(f"{OUT_PREFIX}RSM_model_equation.txt","w",encoding="utf-8") as f:
        f.writelines(lines)

def main():
    df=_load_df_strict(); beta,yhat,R2,Adj=_fit(df); loocv=_loocv_rmse(df)
    pd.DataFrame({'Parameter':PARAM_NAMES,'Estimate':[float(v) for v in beta]}).to_csv(f'{OUT_PREFIX}RSM_coefficients.csv',index=False)
    with open(f'{OUT_PREFIX}model_info.json','w',encoding='utf-8') as jf:
        json.dump({'family':'CubicRSM','beta':[float(v) for v in beta],'R2':R2,'Adj_R2':Adj,'LOOCV_RMSE':loocv,'param_count':len(PARAM_NAMES)}, jf, ensure_ascii=False, indent=2)
    _write_equation_txt(beta)
    X1g,X2g,Yg=_predict_grid(beta, df)
    if BASE_ENABLE:
        _surface_and_contour(df, X1g,X2g,Yg)
        # slices
        x1_levels=sorted(df[X1_COL].unique()); x2_levels=sorted(df[X2_COL].unique())
        x1_min,x1_max=min(x1_levels),max(x1_levels); x2_min,x2_max=min(x2_levels),max(x2_levels)
        plt.figure(figsize=(8,6)); colors=[tuple(c) for c in plt.cm.tab10(np.linspace(0,1,len(x1_levels)))]
        for i,x1_fixed in enumerate(x1_levels):
            x2_line=np.linspace(x2_min,x2_max,300)
            Xs=_build_X(np.full_like(x2_line,x1_fixed), x2_line)
            y_slice= Xs@beta
            plt.plot(x2_line,y_slice,color=colors[i],lw=2,label=f'{X1_LABEL} = {x1_fixed:.2f}')
            sub=df[df[X1_COL]==x1_fixed].sort_values(X2_COL)
            plt.scatter(sub[X2_COL], sub[Y_COL], color=colors[i], edgecolor='k', s=70, zorder=3)
        plt.title(f'{Y_LABEL} vs. {X2_LABEL} (global surface slices)')
        plt.xlabel(X2_LABEL); plt.ylabel(Y_LABEL); plt.legend(title=X1_LABEL); plt.grid(True,alpha=0.3)
        plt.tight_layout(); plt.savefig(f'{OUT_PREFIX}Slices_y_vs_x2_global_RSM.png',dpi=DPI); plt.close()
        plt.figure(figsize=(8,6)); colors2=[tuple(c) for c in plt.cm.tab20(np.linspace(0,1,len(x2_levels)))]
        for i,x2_fixed in enumerate(x2_levels):
            x1_line=np.linspace(x1_min,x1_max,300)
            Xs=_build_X(x1_line, np.full_like(x1_line,x2_fixed))
            y_slice= Xs@beta
            plt.plot(x1_line,y_slice,color=colors2[i],lw=2,label=f'{X2_LABEL} = {x2_fixed:.2f}')
            sub=df[df[X2_COL]==x2_fixed].sort_values(X1_COL)
            plt.scatter(sub[X1_COL], sub[Y_COL], color=colors2[i], edgecolor='k', s=70, zorder=3)
        plt.title(f'{Y_LABEL} vs. {X1_LABEL} (global surface slices)')
        plt.xlabel(X1_LABEL); plt.ylabel(Y_LABEL); plt.legend(title=X2_LABEL); plt.grid(True,alpha=0.3)
        plt.tight_layout(); plt.savefig(f'{OUT_PREFIX}Slices_y_vs_x1_global_RSM.png',dpi=DPI); plt.close()
        _save_residuals_and_predictions(df, yhat)
    if TARGET_ENABLE:
        _overlay_targets(df, X1g,X2g,Yg)

if __name__=='__main__':
    main()
