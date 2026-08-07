import os
import re
import json
import time
from datetime import datetime, date
import pandas as pd
import streamlit as st
from fpdf import FPDF
import requests
import io

# ==========================================
# CONFIGURAÇÕES INICIAIS
# ==========================================
st.set_page_config(
    page_title="Monitor de Digitação & Estatísticas",
    page_icon="📊",
    layout="wide"
)

# ==========================================
# CONVERSOR DE LINK (Google Sheets para CSV)
# ==========================================
def extract_spreadsheet_id(url: str) -> str:
    """Extrai o ID da planilha do Google Sheets."""
    match = re.search(r"/d/([a-zA-Z0-9-_]+)", url)
    return match.group(1) if match else None

def convert_to_csv_url(url: str) -> str:
    """
    Converte URLs do Google Sheets para o formato GViz CSV.
    Se houver 'gid' na URL, utiliza. Se não houver, baixa a primeira aba sem forçar 'gid=0'.
    """
    sheet_id = extract_spreadsheet_id(url)
    if not sheet_id:
        return url

    # Verifica se há um 'gid' específico no link
    gid_match = re.search(r"[#&?]gid=([0-9]+)", url)
    
    if gid_match:
        gid = gid_match.group(1)
        return f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:csv&gid={gid}"
    else:
        # Sem gid: pega a primeira aba disponível automaticamente sem dar Erro 400
        return f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:csv"

# ==========================================
# LINKS DAS PLANILHAS FIXOS NO CÓDIGO
# ==========================================
LISTA_PLANILHAS = {
    "Planilha HENKEL": "https://docs.google.com/spreadsheets/d/1iZ9CcRjNk_C3uAWRTYO1xMGyLzGKKWLTHPguxq4pHOE/edit?usp=sharing",
    "Planilha RENAN": "https://docs.google.com/spreadsheets/d/1zRkVSttkkpqekEdXjGPlz3-Dl7NzgqnkbGioJGuAdRY/edit?usp=sharing",
    "Planilha ROCHE": "https://docs.google.com/spreadsheets/d/1ym-kHhuaW1pD5KNXzrmgY2QaUSol339R4fCHdGRS3K8", #ROCHE
    "Planilha RENAN": "https://docs.google.com/spreadsheets/d/1zRkVSttkkpqekEdXjGPlz3-Dl7NzgqnkbGioJGuAdRY", #RENAN
    "Planilha VALERIA": "https://docs.google.com/spreadsheets/d/1uJzArQ8oF19s2yYQD3BFoNeaZW_xPMdD1RvdSIWnGR8", #VALERIA
    "Planilha SALVADOR LENNON": "https://docs.google.com/spreadsheets/d/1Q0BMTebNMSEyGqTwuQjy2r6nLeSNQE7oIhEntpUhQAA", #SALVADOR LENNON
    "Planilha RIO LENNON": "https://docs.google.com/spreadsheets/d/10P8YgNIqxox-MqDA63DnO5yKAueAQ5GgJONDH2fu9-8", #RIO LENNON
    "Planilha ABB": "https://docs.google.com/spreadsheets/d/1gNeE9CY8KLaI7DOajWFJcGmZ-UuS4ME8firbFkovNS4", #ABB
    "Planilha KERING": "https://docs.google.com/spreadsheets/d/1mH3TIpm23KkNK-JODDwfd8Igqm1ZtvIeQRUTJAHLZVI", #KERING
    "Planilha ZARA": "https://docs.google.com/spreadsheets/d/1CSX4tQoZsspQ0GmVHuzt5h0ABc28Bdd_DqyPR-rGNns", #ZARA
    "Planilha PRADA": "https://docs.google.com/spreadsheets/d/11xDf-tkye_MeVOh_Re5_Piby9_AdVNv-_TOJyqEk9rQ", #PRADA
    "Planilha LOUIS VUITTON": "https://docs.google.com/spreadsheets/d/1zgYootR8Dx5arj7O3Mi31nTgUgvr8xpxhatgn5DgPok", #LOUIS VUITTON
    "Planilha FASHION DIVERSOS": "https://docs.google.com/spreadsheets/d/1Xzggnm2N0YizRHUs0V--cr5OZh5ypSbAReEK_iSchT0", #FASHION DIVERSOS
    "Planilha RAYANE": "https://docs.google.com/spreadsheets/d/1Ch3UFNIBYKVm4BF48iB-DjCbcrzUwM0Cl_QG6NB16_4", #FASHION RAYANE
    "Planilha ADIENT": "https://docs.google.com/spreadsheets/d/1Ii3u9yezVPscByz2q33uTGXPCNL64JV5syXArMnPeP0", #OSGT ADIENT
    "Planilha SCANIA": "https://docs.google.com/spreadsheets/d/1BJpKdZlGo13vxs_sJ-467_RJbP8BBbMpD89pxrkzCFM",
    "Planilha SIG COMBIBLOC": "https://docs.google.com/spreadsheets/d/1EjLNlp5-_vmRQ834JWIH0rGSqZre3MvNoiHF92RI2LQ",
}

DATA_DIR = "data"
LOGS_DIR = "logs"
LOG_FILE = os.path.join(LOGS_DIR, "activity_log.json")

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(LOGS_DIR, exist_ok=True)

# ==========================================
# GERENCIAMENTO DE LOGS E PERSISTÊNCIA
# ==========================================
def load_logs():
    if os.path.exists(LOG_FILE):
        try:
            with open(LOG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []

def save_logs(logs):
    with open(LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(logs, f, ensure_ascii=False, indent=2)

def add_log_entry(sheet_name, digitador, referencia, acao):
    logs = load_logs()
    novo_registro = {
        "timestamp": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
        "date": datetime.now().strftime("%Y-%m-%d"),
        "sheet_name": str(sheet_name),
        "digitador": str(digitador),
        "referencia": str(referencia),
        "mensagem": f"[{sheet_name}] {digitador} {acao} na Referência {referencia}"
    }
    logs.insert(0, novo_registro)
    save_logs(logs)

# ==========================================
# LÓGICA DE COMPARAÇÃO E CACHE LOCAL
# ==========================================
def process_single_sheet_update(sheet_name, uploaded_df):
    # 1. Normaliza nomes das colunas (remove espaços extras e deixa em maiúsculo para comparar)
    uploaded_df.columns = [str(col).strip() for col in uploaded_df.columns]
    
    # 2. Se o cabeçalho não estiver na linha 1, tenta localizar a linha correta automaticamente
    cols_upper = [c.upper() for c in uploaded_df.columns]
    if "DIGITADOR" not in cols_upper and "REFERÊNCIA" not in cols_upper and "REFERENCIA" not in cols_upper:
        header_row_idx = None
        for idx, row in uploaded_df.head(10).iterrows():
            row_values = [str(v).strip().upper() for v in row.values]
            if "DIGITADOR" in row_values or "REFERÊNCIA" in row_values or "REFERENCIA" in row_values:
                header_row_idx = idx
                break
        
        if header_row_idx is not None:
            # Reorganiza o DataFrame considerando a linha encontrada como o novo cabeçalho
            new_headers = [str(v).strip() for v in uploaded_df.iloc[header_row_idx].values]
            uploaded_df = uploaded_df.iloc[header_row_idx + 1:].copy()
            uploaded_df.columns = new_headers

    # 3. Tratamento flexível para aceitar 'REFERÊNCIA' ou 'REFERENCIA' (com ou sem acento)
    col_mapping = {}
    for col in uploaded_df.columns:
        col_clean = str(col).strip()
        if col_clean.upper() == "REFERENCIA":
            col_mapping[col] = "REFERÊNCIA"
        elif col_clean.upper() == "DIGITADOR":
            col_mapping[col] = "DIGITADOR"
            
    uploaded_df = uploaded_df.rename(columns=col_mapping)

    # 4. Validação das colunas obrigatórias
    req_cols = ["DIGITADOR", "REFERÊNCIA"]
    missing = [col for col in req_cols if col not in uploaded_df.columns]
    if missing:
        st.error(f"A planilha '{sheet_name}' precisa conter as colunas: {', '.join(missing)}. Colunas encontradas: {list(uploaded_df.columns)}")
        return False

    uploaded_df = uploaded_df.fillna("-").astype(str)
    cache_path = os.path.join(DATA_DIR, f"cache_{sheet_name.lower().replace(' ', '_')}.csv")

    if os.path.exists(cache_path):
        try:
            previous_df = pd.read_csv(cache_path, dtype=str).fillna("-")
            
            prev_indexed = previous_df.set_index("REFERÊNCIA")
            curr_indexed = uploaded_df.set_index("REFERÊNCIA")

            # Checar alterações APENAS em registros que já existiam
            common_refs = curr_indexed.index.intersection(prev_indexed.index)
            for ref in common_refs:
                row_prev = prev_indexed.loc[ref]
                row_curr = curr_indexed.loc[ref]

                if isinstance(row_prev, pd.DataFrame):
                    row_prev = row_prev.iloc[0]
                if isinstance(row_curr, pd.DataFrame):
                    row_curr = row_curr.iloc[0]

                digitador = str(row_curr.get("DIGITADOR", "")).strip()

                if digitador and digitador not in ["-", "nan", "None"]:
                    for col in curr_indexed.columns:
                        val_old = row_prev.get(col, "-")
                        val_new = row_curr.get(col, "-")

                        if val_old != val_new:
                            if col.upper() in ["STATUS", "SITUAÇÃO", "SITUACAO"]:
                                acao = f"alterou o status de '{val_old}' para '{val_new}'"
                            else:
                                acao = f"alterou o campo '{col}' de '{val_old}' para '{val_new}'"
                            
                            add_log_entry(sheet_name, digitador, ref, acao)

        except Exception as e:
            st.warning(f"Erro ao comparar alterações da planilha '{sheet_name}': {e}")

    uploaded_df.to_csv(cache_path, index=False)
    return True

# ==========================================
# RELATÓRIO PDF
# ==========================================
class PDFReport(FPDF):
    def header(self):
        self.set_font("Helvetica", "B", 14)
        self.cell(0, 10, "Relatório de Atividades dos Digitadores", border=False, new_x="LMARGIN", new_y="NEXT", align="C")
        self.set_font("Helvetica", "", 9)
        self.cell(0, 5, f"Gerado em: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}", border=False, new_x="LMARGIN", new_y="NEXT", align="C")
        self.ln(5)

    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "I", 8)
        self.cell(0, 10, f"Página {self.page_no()}/{{nb}}", align="C")

def generate_pdf(logs_filtered, start_date, end_date):
    pdf = PDFReport()
    pdf.add_page()
    pdf.set_font("Helvetica", "", 10)

    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 8, f"Período selecionado: {start_date.strftime('%d/%m/%Y')} a {end_date.strftime('%d/%m/%Y')}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 8, f"Total de Registros: {len(logs_filtered)}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    pdf.set_font("Helvetica", "", 9)
    for item in logs_filtered:
        texto = f"[{item['timestamp']}] {item['mensagem']}"
        pdf.multi_cell(0, 6, text=texto)
        pdf.ln(1)

    return pdf.output()

# ==========================================
# TELA DE AUTENTICAÇÃO
# ==========================================
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    st.write("")
    col1, col2, col3 = st.columns([1, 2, 1])

    with col2:
        with st.container(border=True):
            st.title("🔐 Acesso ao Sistema")
            st.caption("Digite a senha para prosseguir")
            
            pass_required = st.secrets.get("system_password", "multproc")
            password_input = st.text_input("Senha de Acesso", type="password")
            
            if st.button("Entrar", use_container_width=True):
                if password_input == pass_required:
                    st.session_state.authenticated = True
                    st.rerun()
                else:
                    st.error("Senha incorreta! Tente novamente.")
    st.stop()

# ==========================================
# PAINEL PRINCIPAL
# ==========================================
st.title("📊 Monitor de Digitação em Tempo Real")

col_btn, col_info = st.columns([1, 3])

with col_btn:
    if st.button("🔄 Sincronizar Planilhas", use_container_width=True, type="primary"):
        with st.spinner("Baixando dados e calculando alterações..."):
            sucessos = 0
            
            headers = {
                'User-Agent': (
                    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                    'AppleWebKit/537.36 (KHTML, like Gecko) '
                    'Chrome/120.0.0.0 Safari/537.36'
                )
            }

            for name, url in LISTA_PLANILHAS.items():
                try:
                    csv_url = convert_to_csv_url(url)
                    
                    response = requests.get(csv_url, headers=headers, timeout=15)
                    
                    if response.status_code == 200:
                        df_dl = pd.read_csv(io.StringIO(response.text), dtype=str)
                        
                        if process_single_sheet_update(name, df_dl):
                            sucessos += 1
                            
                    elif response.status_code == 400:
                        st.error(
                            f"❌ **Erro 400 na '{name}'**: "
                            f"A aba (gid) informada não existe ou a planilha possui estruturas corrompidas. "
                            f"Verifique o link ou a aba selecionada."
                        )
                    elif response.status_code == 403:
                        st.error(
                            f"❌ **Erro 403 na '{name}'**: "
                            f"Acesso negado. Verifique se as permissões de compartilhamento estão abertas."
                        )
                    else:
                        st.error(f"❌ Erro HTTP {response.status_code} na planilha '{name}'.")

                except Exception as e:
                    st.error(f"Erro inesperado ao processar '{name}': {e}")

                time.sleep(1.0)

            if sucessos > 0:
                st.success(f"{sucessos} planilha(s) sincronizada(s) com sucesso!")
                st.rerun()

with col_info:
    st.caption(f"Monitorando **{len(LISTA_PLANILHAS)}** planilha(s) configurada(s) no sistema.")

st.divider()

# --- CARREGAR CACHES LOCAIS PARA ESTATÍSTICAS ---
all_dfs = {}
for name in LISTA_PLANILHAS.keys():
    cache_path = os.path.join(DATA_DIR, f"cache_{name.lower().replace(' ', '_')}.csv")
    if os.path.exists(cache_path):
        try:
            df_cache = pd.read_csv(cache_path, dtype=str)
            df_cache["PLANILHA_ORIGEM"] = name
            all_dfs[name] = df_cache
        except Exception:
            pass

# --- ESTATÍSTICAS ---
if all_dfs:
    st.subheader("📈 Estatísticas")
    
    df_consolidado = pd.concat(all_dfs.values(), ignore_index=True)
    
    col_m1, col_m2, col_m3 = st.columns(3)
    col_m1.metric("Total de Processos", len(df_consolidado))
    col_m2.metric("Digitadores Ativos", df_consolidado["DIGITADOR"].nunique() if "DIGITADOR" in df_consolidado.columns else 0)
    col_m3.metric("Planilhas no Sistema", len(all_dfs))

    tab_names = ["🌐 Consolidado (Todas)"] + list(all_dfs.keys())
    tabs = st.tabs(tab_names)
    
    with tabs[0]:
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Processos por Digitador (Geral)**")
            if "DIGITADOR" in df_consolidado.columns:
                st.bar_chart(df_consolidado["DIGITADOR"].value_counts())
        with c2:
            st.markdown("**Processos por Planilha**")
            st.bar_chart(df_consolidado["PLANILHA_ORIGEM"].value_counts())

    for idx, sheet_key in enumerate(all_dfs.keys(), start=1):
        with tabs[idx]:
            df_sheet = all_dfs[sheet_key]
            c_s1, c_s2 = st.columns(2)
            with c_s1:
                st.markdown("**Processos por Digitador**")
                if "DIGITADOR" in df_sheet.columns:
                    st.bar_chart(df_sheet["DIGITADOR"].value_counts())
            with c_s2:
                status_col = next((c for c in df_sheet.columns if c.upper() in ["STATUS", "SITUAÇÃO", "SITUACAO"]), None)
                if status_col:
                    st.markdown(f"**Status ({status_col})**")
                    st.bar_chart(df_sheet[status_col].value_counts())

st.divider()

# --- LOG DE ATIVIDADES EM TEMPO REAL ---
st.subheader("🪵 Log de Atividades dos Digitadores")

logs_all = load_logs()

col_search, col_dt1, col_dt2 = st.columns([2, 1, 1])

with col_search:
    search_query = st.text_input(
        "🔍 Pesquisar no Log:",
        placeholder="Nome do digitador ou número de referência..."
    )

with col_dt1:
    dt_inicio = st.date_input("Data Inicial (PDF)", value=date.today())

with col_dt2:
    dt_fim = st.date_input("Data Final (PDF)", value=date.today())

# Filtragem do Log
filtered_logs = []
for log in logs_all:
    matches_search = True
    if search_query:
        q = search_query.lower()
        matches_search = (
            q in log.get("digitador", "").lower() or 
            q in log.get("referencia", "").lower() or 
            q in log.get("mensagem", "").lower() or
            q in log.get("sheet_name", "").lower()
        )
    if matches_search:
        filtered_logs.append(log)

# Filtro para o PDF
logs_for_pdf = []
for l in logs_all:
    try:
        log_dt = datetime.strptime(l["date"], "%Y-%m-%d").date()
        if dt_inicio <= log_dt <= dt_fim:
            logs_for_pdf.append(l)
    except Exception:
        pass

if logs_for_pdf:
    try:
        pdf_bytes = generate_pdf(logs_for_pdf, dt_inicio, dt_fim)
        st.download_button(
            label="📄 Extrair Relatório PDF (Período Selecionado)",
            data=bytes(pdf_bytes),
            file_name=f"relatorio_digitacao_{dt_inicio}_{dt_fim}.pdf",
            mime="application/pdf"
        )
    except Exception as e:
        st.error(f"Erro ao gerar PDF: {e}")
else:
    st.info("Nenhum registro no período selecionado para exportação.")

# Container de Logs Permanente
st.markdown("**Histórico de Eventos:**")
log_container = st.container(height=380, border=True)

with log_container:
    if filtered_logs:
        for entry in filtered_logs:
            st.markdown(f"`{entry['timestamp']}` — **{entry['mensagem']}**")
    else:
        st.write("Nenhum registro encontrado para a busca informada.")
