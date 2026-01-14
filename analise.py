import pandas as pd
import matplotlib.pyplot as plt
import glob
import os
import numpy as np
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext
import requests 
import webbrowser
from fpdf import FPDF
from fpdf.enums import XPos, YPos
from datetime import datetime
from scipy.interpolate import interp1d
from scipy.signal import find_peaks, savgol_filter
import warnings
import threading

# =================================================================
# ⚙️ CONFIGURAÇÕES DE VERSÃO E REPOSITÓRIO
# =================================================================
VERSION = "1.0" 
GITHUB_USER = "sergiolbj"
GITHUB_REPO = "kartbox-datalogger"
REPO_URL = f"https://api.github.com/repos/{GITHUB_USER}/{GITHUB_REPO}/releases/latest"
# =================================================================

warnings.filterwarnings("ignore")
np.seterr(divide='ignore', invalid='ignore') 
plt.style.use('default') 

class KartReport(FPDF):
    def __init__(self, titulo, subtitulo, eng_nome, rodape):
        super().__init__()
        self.titulo_custom = titulo
        self.subtitulo_custom = subtitulo
        self.eng_nome = eng_nome
        self.rodape_custom = rodape

    def header(self):
        self.set_font('helvetica', 'B', 18)
        self.set_text_color(44, 62, 80)
        self.cell(0, 10, self.titulo_custom, align='L', new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_font('helvetica', 'I', 9)
        self.set_text_color(127, 140, 141)
        self.cell(0, 8, f'{self.subtitulo_custom} | Gerado em: {datetime.now().strftime("%d/%m/%Y %H:%M")}', align='L', new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.line(15, 33, 195, 33)
        self.ln(10)

    def footer(self):
        self.set_y(-15)
        self.set_font('helvetica', 'I', 8)
        self.set_text_color(149, 165, 166)
        self.cell(0, 10, f'{self.rodape_custom} - Página {self.page_no()}', align='C')

def converter_tempo_sec(t):
    try:
        t_str = str(t).strip()
        if ':' in t_str:
            parts = t_str.split(':')
            if len(parts) == 2: return int(parts[0]) * 60 + float(parts[1])
            if len(parts) == 3: return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
        return float(t_str)
    except: return 0.0

def calcular_distancia_metros(df):
    coords = df[['Lat', 'Lon']].values
    if len(coords) < 2: return np.zeros(len(df))
    diffs = np.diff(coords, axis=0)
    dists_coord = np.sqrt(np.sum(diffs**2, axis=1))
    return np.concatenate(([0], np.cumsum(dists_coord * 111111)))

def gerar_mapa_master(df_mov, top_laps, win, thresh, dist_min, smoothing, gap):
    todas_curvas = []
    for v_num in top_laps:
        lap_data = df_mov[df_mov['Lap'] == v_num].copy().reset_index(drop=True)
        dy = np.diff(lap_data['Lat']); dx = np.diff(lap_data['Lon'])
        headings = np.unwrap(np.arctan2(dy, dx))
        curvatura = np.abs(pd.Series(headings).diff(periods=win)).fillna(0).values
        curvatura_smooth = savgol_filter(curvatura, smoothing, 3) if len(curvatura) > smoothing else curvatura
        peaks, _ = find_peaks(curvatura_smooth, height=thresh, distance=dist_min)
        for p in peaks:
            todas_curvas.append({'dist': lap_data.loc[p, 'Dist'], 'lat': lap_data.loc[p, 'Lat'], 'lon': lap_data.loc[p, 'Lon']})
    if not todas_curvas: return []
    todas_curvas = sorted(todas_curvas, key=lambda x: x['dist'])
    curvas_finais = []; atual_grupo = [todas_curvas[0]]
    for i in range(1, len(todas_curvas)):
        if todas_curvas[i]['dist'] - atual_grupo[-1]['dist'] < gap: atual_grupo.append(todas_curvas[i])
        else: curvas_finais.append(atual_grupo); atual_grupo = [todas_curvas[i]]
    curvas_finais.append(atual_grupo)
    return [{'id': i+1, 'dist_ref': np.mean([c['dist'] for c in g]), 'lat': np.mean([c['lat'] for c in g]), 'lon': np.mean([c['lon'] for c in g])} for i, g in enumerate(curvas_finais)]

class TelemetryApp:
    def __init__(self, root):
        self.root = root
        self.root.title(f"KARTBOX - TELEMETRY PRO {VERSION}")
        self.root.geometry("750x750")
        self.pasta_selecionada = tk.StringVar(value=os.getcwd())
        
        header_frame = tk.Frame(root)
        header_frame.pack(pady=15)
        tk.Label(header_frame, text="KARTBOX ANALYZER PRO", font=("Helvetica", 18, "bold"), fg="#2c3e50").pack(side="left")
        self.lbl_version = tk.Label(header_frame, text=f"v{VERSION}", font=("Helvetica", 10), fg="#7f8c8d")
        self.lbl_version.pack(side="left", padx=10, pady=5) # CORRIGIDO: pady em vez de pt

        self.btn_update = tk.Button(root, text="Nova Versão Disponível!", bg="#e67e22", fg="white", 
                                    font=("Helvetica", 9, "bold"), command=self.abrir_github)
        
        f_pdf = tk.LabelFrame(root, text=" Personalização do Relatório ", padx=10, pady=10)
        f_pdf.pack(padx=20, fill="x")
        
        tk.Label(f_pdf, text="Título Principal:").grid(row=0, column=0, sticky="w")
        self.ent_titulo = tk.Entry(f_pdf, width=65); self.ent_titulo.insert(0, "KARTBOX - TRACK INSIGHTS ELITE"); self.ent_titulo.grid(row=0, column=1)
        tk.Label(f_pdf, text="Subtítulo:").grid(row=1, column=0, sticky="w")
        self.ent_sub = tk.Entry(f_pdf, width=65); self.ent_sub.insert(0, "Relatório de Performance e Telemetria"); self.ent_sub.grid(row=1, column=1)
        tk.Label(f_pdf, text="Engenheiro:").grid(row=2, column=0, sticky="w")
        self.ent_eng = tk.Entry(f_pdf, width=65); self.ent_eng.insert(0, "AI RACE ENGINEER"); self.ent_eng.grid(row=2, column=1)

        f_path = tk.Frame(root, pady=10)
        f_path.pack(padx=20, fill="x")
        tk.Entry(f_path, textvariable=self.pasta_selecionada, width=75).pack(side="left")
        tk.Button(f_path, text="Pasta", command=self.buscar_pasta).pack(side="right")
        
        self.btn_run = tk.Button(root, text="GERAR RELATÓRIO DE TELEMETRIA", bg="#27ae60", fg="white", font=("Helvetica", 12, "bold"), height=2, command=self.start_processing)
        self.btn_run.pack(pady=10, padx=20, fill="x")
        
        self.log_area = scrolledtext.ScrolledText(root, height=15, font=("Consolas", 9), bg="#2c3e50", fg="#ecf0f1")
        self.log_area.pack(pady=10, padx=20, fill="both")

        threading.Thread(target=self.check_for_updates, daemon=True).start()

    def check_for_updates(self):
        try:
            response = requests.get(REPO_URL, timeout=5)
            if response.status_code == 200:
                latest = response.json()["tag_name"].replace("v", "")
                if float(latest) > float(VERSION): self.root.after(0, lambda: self.btn_update.pack(pady=5))
        except: pass

    def abrir_github(self): webbrowser.open(f"https://github.com/{GITHUB_USER}/{GITHUB_REPO}/releases")
    def buscar_pasta(self):
        f = filedialog.askdirectory()
        if f: self.pasta_selecionada.set(f)
    def log(self, m): self.log_area.insert(tk.END, m + "\n"); self.log_area.see(tk.END)

    def start_processing(self):
        self.btn_run.config(state="disabled", text="ANALISANDO...")
        threading.Thread(target=self.run_logic, daemon=True).start()

    def run_logic(self):
        target_dir = self.pasta_selecionada.get()
        titulo = self.ent_titulo.get(); sub = self.ent_sub.get(); eng_nome = self.ent_eng.get()
        arquivos = glob.glob(os.path.join(target_dir, "data_*.csv"))
        
        if not arquivos:
            self.log("ERRO: CSVs não encontrados."); self.root.after(0, lambda: self.btn_run.config(state="normal", text="GERAR TELEMETRIA ELITE"))
            return

        for f_data in arquivos:
            try:
                sid = os.path.basename(f_data).replace("data_", "").replace(".csv", "")
                base_dir = os.path.join(target_dir, f"Analise_{sid}")
                v_dir = os.path.join(base_dir, "Voltas"); os.makedirs(v_dir, exist_ok=True)
                self.log(f">>> Processando Sessão: {sid}")
                
                df = pd.read_csv(f_data)
                df_l = pd.read_csv(f_data.replace('data_', 'laps_'))
                df_l.columns = [c.strip() for c in df_l.columns]
                df_l['Time_sec'] = df_l['Time'].apply(converter_tempo_sec)
                
                df_m = df[df['Speed'] > 5].copy().reset_index(drop=True)
                for v in df_m['Lap'].unique():
                    mask = df_m['Lap'] == v
                    df_m.loc[mask, 'Dist'] = calcular_distancia_metros(df_m[mask])

                top_laps = df_l.sort_values('Time_sec')
                t3_nums = top_laps['Lap'].head(3).tolist()
                mapa = gerar_mapa_master(df_m, t3_nums, 20, 0.1, 30, 25, 7.5)
                
                ref_lp = df_m[df_m['Lap'] == t3_nums[0]].copy().reset_index(drop=True)
                r_dist_max = ref_lp['Dist'].max()
                r_interp = interp1d(ref_lp['Dist'], (ref_lp['Timestamp_ms'] - ref_lp['Timestamp_ms'].min())/1000.0, bounds_error=False, fill_value="extrapolate")
                r_speed_interp = interp1d(ref_lp['Dist'], ref_lp['Speed'], bounds_error=False, fill_value="extrapolate")
                
                apex_ref = {c['id']: ref_lp.loc[(ref_lp['Dist'] - c['dist_ref']).abs().idxmin(), 'Speed'] for c in mapa}

                # Volta Ideal (Lógica 4.8)
                b_sectors = []
                for i in range(len(mapa)):
                    p_times = []
                    d_fim = mapa[i]['dist_ref']; d_ini = mapa[i-1]['dist_ref'] if i > 0 else 0
                    for v in df_l['Lap']:
                        lpts = df_m[df_m['Lap'] == v]
                        if lpts.empty: continue
                        t_i = lpts.loc[(lpts['Dist'] - d_ini).abs().idxmin(), 'Timestamp_ms']
                        t_f = lpts.loc[(lpts['Dist'] - d_fim).abs().idxmin(), 'Timestamp_ms']
                        p_times.append((t_f - t_i)/1000)
                    valid = [p for p in p_times if p > 0]
                    if valid: b_sectors.append(min(valid))
                v_ideal = sum(b_sectors)

                pdf = KartReport(titulo, sub, eng_nome, f"Powered by KartBox Elite v{VERSION}")
                pdf.add_page()
                
                # Insights (Lógica 4.8)
                pdf.set_fill_color(44, 62, 80); pdf.set_text_color(255, 255, 255); pdf.set_font('helvetica', 'B', 14)
                pdf.cell(0, 12, f" DEBRIEFING TÉCNICO: {eng_nome}", fill=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
                pdf.ln(5); pdf.set_text_color(0, 0, 0); pdf.set_font('helvetica', '', 11)
                pdf.multi_cell(0, 8, f"> PERFORMANCE: Recorde Real de {df_l['Time_sec'].min():.3f}s.\n> VOLTA IDEAL: {v_ideal:.3f}s. Ganho potencial de {df_l['Time_sec'].min() - v_ideal:.3f}s.")
                
                pdf.ln(5); pdf.set_font('helvetica', 'B', 12); pdf.cell(0, 10, "ESTABILIDADE POR CURVA", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
                for c in mapa[:10]:
                    vls = []
                    for v in df_m['Lap'].unique():
                        if v == 0: continue
                        l_sub = df_m[df_m['Lap'] == v]
                        vls.append(l_sub.loc[(l_sub['Dist'] - c['dist_ref']).abs().idxmin(), 'Speed'])
                    osc = np.std(vls) if len(vls) > 1 else 0
                    pdf.set_x(15); pdf.set_font('helvetica', '', 10)
                    pdf.cell(0, 7, f"- Curva {c['id']}: Variacao de {osc:.1f} km/h. " + ("Crítico!" if osc > 2.2 else "Estável."), new_x=XPos.LMARGIN, new_y=YPos.NEXT)

                # Voltas Individuais (Split View 4.8)
                for vn in sorted(df_m['Lap'].unique()):
                    if vn == 0: continue
                    self.log(f"   Gerando Volta {vn}...")
                    lp = df_m[df_m['Lap'] == vn].copy().reset_index(drop=True)
                    cvs = []
                    for c in mapa:
                        ia = (lp['Dist'] - c['dist_ref']).abs().idxmin()
                        vi = lp.loc[(lp['Dist'] - (c['dist_ref']-15)).abs().idxmin(), 'Speed']
                        va = lp.loc[max(0, ia-8):min(len(lp)-1, ia+8), 'Speed'].min()
                        cvs.append({'id': c['id'], 'v_in': vi, 'v_ap': va, 'diff': va - apex_ref.get(c['id'], va), 'lat': c['lat'], 'lon': c['lon'], 'dist': c['dist_ref']})
                    
                    fig, axs = plt.subplot_mosaic([['map', 'map'], ['speed', 'delta']], figsize=(10, 8.5), gridspec_kw={'height_ratios': [1.4, 1]})
                    axs['map'].scatter(lp['Lon'], lp['Lat'], c=lp['Speed'], cmap='RdYlGn', s=15, alpha=0.6)
                    for c in cvs: axs['map'].annotate(f"C{c['id']}", (c['lon'], c['lat']), xytext=(0,5), textcoords="offset points", ha='center', fontsize=8, fontweight='bold', bbox=dict(boxstyle='circle,pad=0.2', fc='yellow', alpha=0.8, ec='none'))
                    axs['map'].set_aspect('equal'); axs['map'].axis('off')
                    
                    dist_grid = np.linspace(0, max(lp['Dist'].max(), r_dist_max), 250)
                    axs['speed'].plot(dist_grid, r_speed_interp(dist_grid), color='#95a5a6', lw=1, alpha=0.7)
                    axs['speed'].plot(dist_grid, interp1d(lp['Dist'], lp['Speed'], bounds_error=False, fill_value="extrapolate")(dist_grid), color='#27ae60', lw=1.5)
                    for c in cvs: 
                        axs['speed'].annotate(f"C{c['id']}", (c['dist'], c['v_ap']), textcoords="offset points", xytext=(0, 8), ha='center', fontsize=6, fontweight='bold', color='red')
                        axs['speed'].scatter(c['dist'], c['v_ap'], color='red', s=10, zorder=5)
                    
                    dlt = interp1d(lp['Dist'], (lp['Timestamp_ms'] - lp['Timestamp_ms'].min())/1000.0, bounds_error=False, fill_value="extrapolate")(dist_grid) - r_interp(dist_grid)
                    axs['delta'].plot(dist_grid, dlt, color='#2980B9'); axs['delta'].axhline(0, color='black', lw=0.8, ls='--')
                    axs['delta'].fill_between(dist_grid, dlt, 0, where=(dlt > 0), color='red', alpha=0.3); axs['delta'].fill_between(dist_grid, dlt, 0, where=(dlt < 0), color='green', alpha=0.3)
                    
                    ipath = os.path.join(v_dir, f"V_{vn}.png"); plt.tight_layout(); plt.savefig(ipath, dpi=120); plt.close()
                    pdf.add_page(); pdf.image(ipath, x=15, y=38, w=180)
                    
                    if cvs:
                        pdf.set_y(205); pdf.set_font('helvetica', 'B', 7); pdf.set_fill_color(240, 240, 240)
                        for i in range(0, len(cvs), 12):
                            ln = cvs[i:i+12]; cw = 180 / len(ln)
                            pdf.set_x(15); [pdf.cell(cw, 5.5, f"C{c['id']}", 1, 0, 'C', True) for c in ln]; pdf.ln()
                            pdf.set_x(15); pdf.set_font('helvetica', '', 6); [pdf.cell(cw, 4.5, f"In:{c['v_in']:.1f}", 1, 0, 'C') for c in ln]; pdf.ln()
                            pdf.set_x(15); pdf.set_font('helvetica', 'B', 6)
                            for c in ln:
                                pdf.set_text_color(46, 204, 113) if c['diff'] > 0.5 else pdf.set_text_color(231, 76, 60) if c['diff'] < -0.5 else pdf.set_text_color(0,0,0)
                                pdf.cell(cw, 5, f"Ap:{c['v_ap']:.1f}", 1, 0, 'C')
                            pdf.ln(); pdf.set_text_color(0,0,0); pdf.set_x(15); [pdf.cell(cw, 4, f"{'+' if c['diff']>0 else ''}{c['diff']:.1f}", 1, 0, 'C') for c in ln]; pdf.ln(7)

                # Ranking Final
                pdf.add_page(); pdf.set_fill_color(44, 62, 80); pdf.set_text_color(255, 255, 255); pdf.set_font('helvetica', 'B', 16)
                pdf.cell(0, 15, " RANKING FINAL DA SESSÃO", fill=True, align='C', new_x=XPos.LMARGIN, new_y=YPos.NEXT)
                pdf.ln(10); pdf.set_text_color(0, 0, 0); cw = pdf.epw / 4
                pdf.set_font('helvetica', 'B', 10); pdf.set_fill_color(230, 230, 230)
                for h in ["RANK", "VOLTA", "TEMPO", "MODO"]: pdf.cell(cw, 10, h, 1, 0, 'C', True)
                pdf.ln(); pdf.set_font('helvetica', '', 10)
                for i, (idx, row) in enumerate(top_laps.head(10).iterrows(), 1):
                    pdf.cell(cw, 10, f"{i} Lugar", 1, 0, 'C'); pdf.cell(cw, 10, str(int(row['Lap'])), 1, 0, 'C')
                    pdf.cell(cw, 10, f"{row['Time']}s", 1, 0, 'C'); pdf.cell(cw, 10, str(row['Mode']), 1, 1, 'C')

                pdf.output(os.path.join(base_dir, f"Relatorio_Elite_{sid}.pdf"))
                self.log(f"--- SUCESSO: Sessão {sid} Concluída ---")

            except Exception as e: self.log(f"ERRO: {str(e)}"); import traceback; self.log(traceback.format_exc())
        
        self.root.after(0, lambda: self.btn_run.config(state="normal", text="GERAR TELEMETRIA PRO"))
        messagebox.showinfo("Sucesso", "Relatórios gerados!")
        os.startfile(target_dir) # Abre a pasta de resultados automaticamente

if __name__ == "__main__":
    root = tk.Tk(); app = TelemetryApp(root); root.mainloop()