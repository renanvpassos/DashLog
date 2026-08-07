import os
import json
from datetime import datetime, date
import pandas as pd
import streamlit as st
from fpdf import FPDF

# ==========================================
# CONFIGURAÇÕES INICIAIS
# ==========================================
st.set_page_config(
    page_title="Monitor de Digitação & Estatísticas",
    page_icon="📊",
    layout="wide"
)

# DICIONÁRIO INICIAL DE PLANILHAS (Pode adicionar quantas quiser no código ou pela tela)
DEFAULT_SHEETS = {
    "https://docs.google.com/spreadsheets/d/1ym-kHhuaW1pD5KNXzrmgY2QaUSol339R4fCHdGRS3K8/edit?usp=sharing", #ROCHE
    "https://docs.google.com/spreadsheets/d/1zRkVSttkkpqekEdXjGPlz3-Dl7NzgqnkbGioJGuAdRY/edit?usp=sharing", #RENAN
    "https://docs.google.com/spreadsheets/d/1uJzArQ8oF19s2yYQD3BFoNeaZW_xPMdD1RvdSIWnGR8/edit?usp=sharing", #VALERIA
    "https://docs.google.com/spreadsheets/d/1Q0BMTebNMSEyGqTwuQjy2r6nLeSNQE7oIhEntpUhQAA/edit?gid=0#gid=0", #SALVADOR LENNON
    "https://docs.google.com/spreadsheets/d/10P8YgNIqxox-MqDA63DnO5yKAueAQ5GgJONDH2fu9-8/edit?gid=0#gid=0", #RIO LENNON
    "https://docs.google.com/spreadsheets/d/1gNeE9CY8KLaI7DOajWFJcGmZ-UuS4ME8firbFkovNS4/edit?usp=sharing", #ABB
    "https://docs.google.com/spreadsheets/d/1mH3TIpm23KkNK-JODDwfd8Igqm1ZtvIeQRUTJAHLZVI/edit?gid=0#gid=0", #KERING
    "https://docs.google.com/spreadsheets/d/1CSX4tQoZsspQ0GmVHuzt5h0ABc28Bdd_DqyPR-rGNns/edit?gid=0#gid=0", #ZARA
    "https://docs.google.com/spreadsheets/d/11xDf-tkye_MeVOh_Re5_Piby9_AdVNv-_TOJyqEk9rQ/edit?usp=sharing", #PRADA
    "https://docs.google.com/spreadsheets/d/1zgYootR8Dx5arj7O3Mi31nTgUgvr8xpxhatgn5DgPok/edit?usp=sharing", #LOUIS VUITTON
    "https://docs.google.com/spreadsheets/d/1Xzggnm2N0YizRHUs0V--cr5OZh5ypSbAReEK_iSchT0/edit?gid=0#gid=0", #FASHION DIVERSOS
    "https://docs.google.com/spreadsheets/d/1Ch3UFNIBYKVm4BF48iB-DjCbcrzUwM0Cl_QG6NB16_4/edit?gid=0#gid=0", #FASHION RAYANE
    "https://docs.google.com/spreadsheets/d/1Ii3u9yezVPscByz2q33uTGXPCNL64JV5syXArMnPeP0/edit?gid=0#gid=0", #OSGT ADIENT
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
    logs.insert(0, novo_registro)  # Adiciona no topo
    save_logs(logs)

# ==========================================
# LÓGICA DE COMPARAÇÃO E CACHE MULTI-PLANILHA
# ==========================================
def process_single_sheet_update(sheet_name, uploaded_df):
    """
    Compara a planilha com o cache específico dessa planilha para detectar alterações.
    """
    req_cols = ["DIGITADOR", "REFERÊNCIA"]
    missing = [col for col in req_cols if col not in uploaded_df.columns]
    if missing:
        st.error(f"A planilha '{sheet_name}' precisa conter as colunas: {', '.join(missing)}")
        return False

    uploaded_df = uploaded_df.fillna("-").astype(str)
    cache_path = os.path.join(DATA_DIR, f"cache_{sheet_name.lower().replace(' ', '_')}.csv")

    if os.path.exists(cache_path):
        try:
            previous_df = pd.read_csv(cache_path, dtype=str).fillna("-")
            
            prev_indexed = previous_df.set_index("REFERÊNCIA")
            curr_indexed = uploaded_df.set_index("REFERÊNCIA")

            common_refs = curr_indexed.index.intersection(prev_indexed.index)

            for ref in common_refs:
                row_prev = prev_indexed.loc[ref]
                row_curr = curr_indexed.loc[ref]

                if isinstance(row_prev, pd.DataFrame):
                    row_prev = row_prev.iloc[0]
                if isinstance(row_curr, pd.DataFrame):
                    row_curr = row_curr.iloc[0]

                digitador = row_curr.get("DIGITADOR", "Desconhecido")

                for col in curr_indexed.columns:
                    val_old = row_prev.get(col, "-")
                    val_new = row_curr.get(col, "-")

                    if val_old != val_new:
                        if col.upper() in ["STATUS", "SITUAÇÃO", "SITUACAO"]:
                            acao = f"alterou o status de '{val_old}' para '{val_new}'"
                        else:
                            acao = f"alterou o campo '{col}' de '{val_old}' para '{val_new}'"
                        
                        add_log_entry(sheet_name, digitador, ref, acao)

            new_refs = curr_indexed.index.difference(prev_indexed.index)
            for ref in new_refs:
                row_curr = curr_indexed.loc[ref]
                if isinstance(row_curr, pd.DataFrame):
                    row_curr = row_curr.iloc[0]
                digitador = row_curr.get("DIGITADOR", "Desconhecido")
                add_log_entry(sheet_name, digitador, ref, "adicionou/criou este processo")

        except Exception as e:
            st.warning(f"Erro ao processar comparação de '{sheet_name}': {e}")

    # Atualiza o cache local desta planilha
    uploaded_df.to_csv(cache_path, index=False)
    return True

# ==========================================
# GERADOR DE RELATÓRIOS PDF
# ==========================================
class PDFReport(FPDF):
    def header(self):
        self.set_font("Helvetica", "B", 14)
        self.cell(0, 10, "Relatório de Atividades dos Digitadores (Multi-Planilhas)", border=False, new_x="LMARGIN", new_y="NEXT", align="C")
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
    pdf.cell(0, 8, f"Total de Registros Encontrados: {len(logs_filtered)}", new_x="LMARGIN", new_y="NEXT")
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
    st.markdown("<br><br>", unsafe_allow_headers=True)
    col1, col2, col3 = st.columns([1, 2, 1])

    with col2:
        with st.container(border=True):
            st.title("🔐 Acesso ao Sistema")
            st.caption("Digite a senha para prosseguir")
            
            password_input = st.text_input("Senha de Acesso", type="password")
            
            if st.button("Entrar", use_container_width=True):
                if password_input == "multproc":
                    st.session_state.authenticated = True
                    st.rerun()
                else:
                    st.error("Senha incorreta! Tente novamente.")
    st.stop()

# ==========================================
# PAINEL PRINCIPAL
# ==========================================
st.title("📊 Monitor de Digitação (Multi-Planilhas)")

# Inicializa links no Session State para permitir inclusão/remoção dinâmica
if "sheets_config" not in st.session_state:
    st.session_state.sheets_config = DEFAULT_SHEETS.copy()

# --- CONFIGURAÇÃO E SINCRONIZAÇÃO DE VÁRIAS PLANILHAS ---
with st.expander("⚙️ Gerenciar e Sincronizar Planilhas Google Sheets", expanded=True):
    st.caption("Cadastre e sincronize todas as suas planilhas publicadas como CSV.")
    
    # Adicionar nova planilha dinamicamente
    col_n1, col_n2, col_n3 = st.columns([1.5, 3, 1])
    with col_n1:
        novo_nome = st.text_input("Nome da Planilha", placeholder="Ex: Filial SP / Lote A")
    with col_n2:
        novo_link = st.text_input("Link Público CSV", placeholder="https://docs.google.com/spreadsheets/d/e/.../pub?output=csv")
    with col_n3:
        st.write("")
        if st.button("➕ Adicionar", use_container_width=True):
            if novo_nome and novo_link:
                st.session_state.sheets_config[novo_nome] = novo_link
                st.success(f"Planilha '{novo_nome}' adicionada com sucesso!")
                st.rerun()
            else:
                st.warning("Preencha o nome e o link.")

    st.divider()

    # Listagem e Sincronização
    st.markdown("**Planilhas Cadastradas:**")
    
    col_sync_all, _ = st.columns([1.5, 3])
    with col_sync_all:
        if st.button("🔄 Sincronizar TODAS as Planilhas", use_container_width=True, type="primary"):
            with st.spinner("Sincronizando todas as planilhas..."):
                sucessos = 0
                for s_name, s_url in st.session_state.sheets_config.items():
                    try:
                        df_dl = pd.read_csv(s_url, dtype=str)
                        if process_single_sheet_update(s_name, df_dl):
                            sucessos += 1
                    except Exception as e:
                        st.error(f"Erro ao baixar '{s_name}': {e}")
                if sucessos > 0:
                    st.success(f"{sucessos} planilha(s) sincronizada(s) com sucesso!")
                    st.rerun()

    # Lista de planilhas individuais com remoção
    for name, url in list(st.session_state.sheets_config.items()):
        c1, c2, c3 = st.columns([1.5, 3, 0.8])
        c1.text(f"📌 {name}")
        c2.caption(url[:60] + "..." if len(url) > 60 else url)
        if c3.button("🗑️ Remover", key=f"del_{name}"):
            del st.session_state.sheets_config[name]
            st.rerun()

st.divider()

# --- CARREGAR DADOS DOS CACHES DE TODAS AS PLANILHAS ---
all_dfs = {}
for name in st.session_state.sheets_config.keys():
    cache_path = os.path.join(DATA_DIR, f"cache_{name.lower().replace(' ', '_')}.csv")
    if os.path.exists(cache_path):
        try:
            df_cache = pd.read_csv(cache_path, dtype=str)
            df_cache["PLANILHA_ORIGEM"] = name
            all_dfs[name] = df_cache
        except Exception:
            pass

# --- ESTATÍSTICAS UNIFICADAS E INDIVIDUAIS ---
if all_dfs:
    st.subheader("📈 Estatísticas Gerais e Consolidadas")
    
    # Junta todas as planilhas em um único DataFrame Consolidado
    df_consolidado = pd.concat(all_dfs.values(), ignore_index=True)
    
    col_m1, col_m2, col_m3 = st.columns(3)
    total_processos = len(df_consolidado)
    num_digitadores = df_consolidado["DIGITADOR"].nunique() if "DIGITADOR" in df_consolidado.columns else 0
    total_planilhas = len(all_dfs)
    
    col_m1.metric("Total de Processos (Todas)", total_processos)
    col_m2.metric("Digitadores Ativos", num_digitadores)
    col_m3.metric("Planilhas Monitoradas", total_planilhas)

    # Visualização por abas (Geral vs Cada Planilha)
    tab_names = ["🌐 Consolidado (Todas)"] + list(all_dfs.keys())
    tabs = st.tabs(tab_names)
    
    with tabs[0]:
        c_chart1, c_chart2 = st.columns(2)
        with c_chart1:
            st.markdown("**Processos por Digitador (Geral)**")
            if "DIGITADOR" in df_consolidado.columns:
                st.bar_chart(df_consolidado["DIGITADOR"].value_counts())
        with c_chart2:
            st.markdown("**Processos por Planilha**")
            st.bar_chart(df_consolidado["PLANILHA_ORIGEM"].value_counts())

    for idx, sheet_key in enumerate(all_dfs.keys(), start=1):
        with tabs[idx]:
            df_sheet = all_dfs[sheet_key]
            st.caption(f"Dados da planilha: {sheet_key}")
            
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
st.subheader("🪵 Log de Atividades dos Digitadores (Unificado)")

logs_all = load_logs()

# Filtro de busca, planilha e datas
col_search, col_sheet_filter, col_dt1, col_dt2 = st.columns([2, 1.2, 1, 1])

with col_search:
    search_query = st.text_input(
        "🔍 Pesquisar no Log:",
        placeholder="Digitador, referência ou texto..."
    )

with col_sheet_filter:
    sheet_filter = st.selectbox(
        "Planilha:",
        options=["Todas"] + list(st.session_state.sheets_config.keys())
    )

with col_dt1:
    dt_inicio = st.date_input("Data Inicial (PDF)", value=date.today())

with col_dt2:
    dt_fim = st.date_input("Data Final (PDF)", value=date.today())

# Filtragem dos registros do log
filtered_logs = []
for log in logs_all:
    # Filtro por planilha
    if sheet_filter != "Todas" and log.get("sheet_name") != sheet_filter:
        continue
        
    # Filtro por busca de texto
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

# Botão de extração do relatório em PDF por período
logs_for_pdf = []
for l in logs_all:
    try:
        log_dt = datetime.strptime(l["date"], "%Y-%m-%d").date()
        if dt_inicio <= log_dt <= dt_fim:
            if sheet_filter == "Todas" or l.get("sheet_name") == sheet_filter:
                logs_for_pdf.append(l)
    except Exception:
        pass

if logs_for_pdf:
    try:
        pdf_bytes = generate_pdf(logs_for_pdf, dt_inicio, dt_fim)
        st.download_button(
            label="📄 Baixar Relatório PDF (Período Selecionado)",
            data=bytes(pdf_bytes),
            file_name=f"relatorio_digitacao_{dt_inicio}_{dt_fim}.pdf",
            mime="application/pdf"
        )
    except Exception as e:
        st.error(f"Erro ao gerar PDF: {e}")
else:
    st.info("Nenhum registro encontrado no período selecionado para exportação.")

# Exibição do container de logs (Informações nunca são apagadas)
st.markdown("**Histórico Permanente de Eventos:**")
log_container = st.container(height=380, border=True)

with log_container:
    if filtered_logs:
        for entry in filtered_logs:
            st.markdown(f"`{entry['timestamp']}` — **{entry['mensagem']}**")
    else:
        st.write("Nenhum registro encontrado para a busca informada.")
