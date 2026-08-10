import os
import re
import io
import time
import requests
import unicodedata
from datetime import datetime, date
from concurrent.futures import ThreadPoolExecutor, as_completed
from zoneinfo import ZoneInfo
import pandas as pd
import streamlit as st
from fpdf import FPDF
from supabase import create_client, Client
from streamlit_autorefresh import st_autorefresh

# ==========================================
# CONFIGURAÇÕES DE FUSO HORÁRIO E STREAMLIT
# ==========================================
TZ_BR = ZoneInfo("America/Sao_Paulo")

def get_now_br() -> datetime:
    """Retorna o datetime atual formatado no fuso de Brasília."""
    return datetime.now(TZ_BR)

st.set_page_config(
    page_title="Monitor Operacional",
    page_icon="📊",
    layout="wide"
)

# ---------------------------------------------------------
# AUTOMAÇÃO: Recarrega/Executa a cada 2 minutos (120.000ms)
# ---------------------------------------------------------
st_autorefresh(interval=120000, key="auto_sync_timer")

# ==========================================
# CONEXÃO COM O SUPABASE
# ==========================================
@st.cache_resource
def init_supabase() -> Client:
    url = st.secrets.get("SUPABASE_URL")
    key = st.secrets.get("SUPABASE_KEY")
    if not url or not key:
        st.error("❌ Configurações do Supabase (SUPABASE_URL / SUPABASE_KEY) não encontradas nos Secrets.")
        st.stop()
    return create_client(url, key)

supabase = init_supabase()

# ==========================================
# CONVERSOR DE LINK (Google Sheets para GViz CSV)
# ==========================================
def extract_spreadsheet_id(url: str) -> str:
    """Extrai o ID da planilha do Google Sheets."""
    match = re.search(r"/d/([a-zA-Z0-9-_]+)", url)
    return match.group(1) if match else None

def convert_to_csv_url(url: str) -> str:
    """
    Converte URLs do Google Sheets para o formato GViz CSV.
    Se houver 'gid' na URL, utiliza. Se não houver, baixa a primeira aba.
    """
    sheet_id = extract_spreadsheet_id(url)
    if not sheet_id:
        return url

    gid_match = re.search(r"[#&?]gid=([0-9]+)", url)
    if gid_match:
        gid = gid_match.group(1)
        return f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:csv&gid={gid}"
    else:
        return f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:csv"

# ==========================================
# LINKS DAS PLANILHAS FIXOS NO CÓDIGO
# ==========================================
LISTA_PLANILHAS = {
    "PLANILHA ROCHE": "https://docs.google.com/spreadsheets/d/1ym-kHhuaW1pD5KNXzrmgY2QaUSol339R4fCHdGRS3K8",
    "PLANILHA RENAN": "https://docs.google.com/spreadsheets/d/1zRkVSttkkpqekEdXjGPlz3-Dl7NzgqnkbGioJGuAdRY",
    "PLANILHA VALERIA": "https://docs.google.com/spreadsheets/d/1uJzArQ8oF19s2yYQD3BFoNeaZW_xPMdD1RvdSIWnGR8",
    "PLANILHA SALVADOR LENNON": "https://docs.google.com/spreadsheets/d/1Q0BMTebNMSEyGqTwuQjy2r6nLeSNQE7oIhEntpUhQAA",
    "PLANILHA RIO LENNON": "https://docs.google.com/spreadsheets/d/10P8YgNIqxox-MqDA63DnO5yKAueAQ5GgJONDH2fu9-8",
    "PLANILHA ABB": "https://docs.google.com/spreadsheets/d/1gNeE9CY8KLaI7DOajWFJcGmZ-UuS4ME8firbFkovNS4",
    "PLANILHA KERING": "https://docs.google.com/spreadsheets/d/1mH3TIpm23KkNK-JODDwfd8Igqm1ZtvIeQRUTJAHLZVI",
    "PLANILHA ZARA": "https://docs.google.com/spreadsheets/d/1CSX4tQoZsspQ0GmVHuzt5h0ABc28Bdd_DqyPR-rGNns",
    "PLANILHA PRADA": "https://docs.google.com/spreadsheets/d/11xDf-tkye_MeVOh_Re5_Piby9_AdVNv-_TOJyqEk9rQ",
    "PLANILHA LOUIS VUITTON": "https://docs.google.com/spreadsheets/d/1zgYootR8Dx5arj7O3Mi31nTgUgvr8xpxhatgn5DgPok",
    "PLANILHA FASHION DIVERSOS": "https://docs.google.com/spreadsheets/d/1Xzggnm2N0YizRHUs0V--cr5OZh5ypSbAReEK_iSchT0",
    "PLANILHA RAYANE": "https://docs.google.com/spreadsheets/d/1Ch3UFNIBYKVm4BF48iB-DjCbcrzUwM0Cl_QG6NB16_4",
    "PLANILHA ADIENT": "https://docs.google.com/spreadsheets/d/1Ii3u9yezVPscByz2q33uTGXPCNL64JV5syXArMnPeP0",
    "PLANILHA HENKEL": "https://docs.google.com/spreadsheets/d/1iZ9CcRjNk_C3uAWRTYO1xMGyLzGKKWLTHPguxq4pHOE",
    "PLANILHA SCANIA": "https://docs.google.com/spreadsheets/d/1BJpKdZlGo13vxs_sJ-467_RJbP8BBbMpD89pxrkzCFM",
    "PLANILHA SIG COMBIBLOC": "https://docs.google.com/spreadsheets/d/1EjLNlp5-_vmRQ834JWIH0rGSqZre3MvNoiHF92RI2LQ",
}

DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)

# ==========================================
# GERENCIAMENTO DE LOGS VIA SUPABASE
# ==========================================
def load_logs_by_period(start_date: date, end_date: date):
    """Carrega logs do Supabase dentro do período especificado."""
    try:
        response = (
            supabase.table("atividades")
            .select("*")
            .gte("date", start_date.isoformat())
            .lte("date", end_date.isoformat())
            .order("id", desc=True)
            .execute()
        )
        return response.data if response.data else []
    except Exception as e:
        st.error(f"Erro ao buscar logs do Supabase: {e}")
        return []

def add_log_entries_bulk(logs_list):
    """Insere registros de atividade em lote no banco Supabase."""
    if not logs_list:
        return
    try:
        supabase.table("atividades").insert(logs_list).execute()
    except Exception as e:
        st.error(f"Erro ao salvar registros no Supabase: {e}")

# ==========================================
# TRATAMENTO DE TEXTO E COMPARADOR DE PLANILHAS
# ==========================================
def normalize_text(text: str) -> str:
    """Remove acentos, espaços extras e converte para maiúsculo."""
    text = str(text).strip()
    nfkd_form = unicodedata.normalize('NFKD', text)
    only_ascii = "".join([c for c in nfkd_form if not unicodedata.combining(c)])
    return only_ascii.upper()

def highlight_log_message(mensagem: str) -> str:
    """Aplica destaque de cores: valores alterados (vermelho) e referência (azul claro)."""
    # Destaca os valores 'de' e 'para' em vermelho
    mensagem = re.sub(
        r"de '([^']*)' para '([^']*)'",
        r"de '<span style='color:#FF4B4B;font-weight:bold;'>\1</span>' "
        r"para '<span style='color:#FF4B4B;font-weight:bold;'>\2</span>'",
        mensagem
    )
    # Destaca a referência em azul claro (funciona com ou sem o sufixo "| Importador:")
    mensagem = re.sub(
        r"(na Referência )(.+?)((?: \| Importador: .+)?)$",
        r"\1<span style='color:#5DADE2;font-weight:bold;'>\2</span>\3",
        mensagem
    )
    return mensagem

def process_single_sheet_update(sheet_name, uploaded_df):
    new_columns = []
    for col in uploaded_df.columns:
        col_str = str(col).strip()
        norm_col = normalize_text(col_str)
        
        if norm_col.startswith("DIGITADOR"):
            new_columns.append("DIGITADOR")
        elif norm_col.startswith("REFERENCIA"):
            new_columns.append("REFERÊNCIA")
        elif norm_col.startswith("IMPORTADOR"):
            new_columns.append("IMPORTADOR")
        else:
            new_columns.append(col_str)
            
    uploaded_df.columns = new_columns

    req_cols = ["DIGITADOR", "REFERÊNCIA"]
    missing = [col for col in req_cols if col not in uploaded_df.columns]
    
    if missing:
        st.error(
            f"❌ A planilha '{sheet_name}' não possui as colunas necessárias: {', '.join(missing)}.\n\n"
            f"**Colunas encontradas:** {list(uploaded_df.columns)}"
        )
        return False

    uploaded_df = uploaded_df.fillna("-").astype(str)
    uploaded_df = uploaded_df.drop_duplicates(subset=["REFERÊNCIA"], keep="last")

    cache_path = os.path.join(DATA_DIR, f"cache_{sheet_name.lower().replace(' ', '_')}.csv")
    new_logs = []
    now_br = get_now_br()

    if os.path.exists(cache_path):
        try:
            previous_df = pd.read_csv(cache_path, dtype=str).fillna("-")
            previous_df = previous_df.drop_duplicates(subset=["REFERÊNCIA"], keep="last")
            
            prev_indexed = previous_df.set_index("REFERÊNCIA")
            curr_indexed = uploaded_df.set_index("REFERÊNCIA")

            common_refs = curr_indexed.index.intersection(prev_indexed.index)
            for ref in common_refs:
                row_prev = prev_indexed.loc[ref]
                row_curr = curr_indexed.loc[ref]

                digitador = str(row_curr.get("DIGITADOR", "")).strip()

                if digitador and digitador not in ["-", "nan", "None"]:
                    importador = str(row_curr.get("IMPORTADOR", "-")).strip()
                    if importador in ["nan", "None", ""]:
                        importador = "-"

                    for col in curr_indexed.columns:
                        val_old = row_prev.get(col, "-")
                        val_new = row_curr.get(col, "-")

                        if val_old != val_new:
                            col_norm = normalize_text(col)
                            if col_norm in ["STATUS", "SITUACAO"]:
                                acao = f"alterou o status de '{val_old}' para '{val_new}'"
                            else:
                                acao = f"alterou o campo '{col}' de '{val_old}' para '{val_new}'"
                            
                            new_logs.append({
                                "timestamp": now_br.strftime("%d/%m/%Y %H:%M:%S"),
                                "date": now_br.strftime("%Y-%m-%d"),
                                "sheet_name": str(sheet_name),
                                "digitador": str(digitador),
                                "referencia": str(ref),
                                "mensagem": f"[{sheet_name}] {digitador} {acao} na Referência {ref} | Importador: {importador}"
                            })

        except Exception as e:
            st.warning(f"Erro ao comparar alterações da planilha '{sheet_name}': {e}")

    if new_logs:
        add_log_entries_bulk(new_logs)

    uploaded_df.to_csv(cache_path, index=False)
    return True

def fetch_and_process_sheet(name, url, headers):
    """Função auxiliar para download e processamento concorrente."""
    try:
        csv_url = convert_to_csv_url(url)
        response = requests.get(csv_url, headers=headers, timeout=15)
        
        if response.status_code == 200:
            df_dl = pd.read_csv(io.StringIO(response.text), dtype=str)
            if process_single_sheet_update(name, df_dl):
                return True, None
        elif response.status_code == 400:
            return False, f"❌ **Erro 400 na '{name}'**: A aba (gid) informada não existe ou está corrompida."
        elif response.status_code == 403:
            return False, f"❌ **Erro 403 na '{name}'**: Acesso negado. Verifique as permissões de compartilhamento."
        else:
            return False, f"❌ Erro HTTP {response.status_code} na planilha '{name}'."
    except Exception as e:
        return False, f"Erro inesperado ao processar '{name}': {e}"
    
    return False, f"Falha desconhecida ao baixar '{name}'."

def executar_sincronizacao():
    """Executa a sincronização de todas as planilhas."""
    sucessos = 0
    headers = {
        'User-Agent': (
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/120.0.0.0 Safari/537.36'
        )
    }

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [
            executor.submit(fetch_and_process_sheet, name, url, headers)
            for name, url in LISTA_PLANILHAS.items()
        ]

        for future in as_completed(futures):
            success, err_msg = future.result()
            if success:
                sucessos += 1
            elif err_msg:
                st.error(err_msg)

    return sucessos

# ==========================================
# RELATÓRIO PDF (SUPORTE MULTIBYTE / LATIN-1 SAFE)
# ==========================================
class PDFReport(FPDF):
    def header(self):
        self.set_font("Helvetica", "B", 14)
        self.cell(0, 10, "Relatorio de Atividades dos Digitadores", border=False, new_x="LMARGIN", new_y="NEXT", align="C")
        self.set_font("Helvetica", "", 9)
        self.cell(0, 5, f"Gerado em: {get_now_br().strftime('%d/%m/%Y %H:%M:%S')}", border=False, new_x="LMARGIN", new_y="NEXT", align="C")
        self.ln(5)

    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "I", 8)
        self.cell(0, 10, f"Pagina {self.page_no()}/{{nb}}", align="C")

def sanitize_pdf_text(text: str) -> str:
    """Converte caracteres UTF-8 para um formato compatível com fontes padrão do FPDF."""
    return unicodedata.normalize('NFKD', str(text)).encode('latin-1', 'ignore').decode('latin-1')

# Cores usadas no destaque do PDF (RGB)
PDF_RED = (200, 30, 30)
PDF_BLUE = (41, 128, 185)
PDF_BLACK = (0, 0, 0)

def build_pdf_segments(mensagem: str):
    """
    Quebra a mensagem em segmentos (texto, cor) para permitir
    destacar 'de/para' em vermelho e a Referência em azul no PDF.
    """
    segments = []
    pattern = re.compile(
        r"de '([^']*)' para '([^']*)'"
        r"|na Referência (.+?)(?: \| Importador: (.+))?$"
    )
    pos = 0

    for m in pattern.finditer(mensagem):
        start, end = m.span()
        if start > pos:
            segments.append((mensagem[pos:start], None))

        if m.group(1) is not None:
            segments.append(("de '", None))
            segments.append((m.group(1), PDF_RED))
            segments.append(("' para '", None))
            segments.append((m.group(2), PDF_RED))
            segments.append(("'", None))
        else:
            segments.append(("na Referência ", None))
            segments.append((m.group(3), PDF_BLUE))
            if m.group(4):
                segments.append((f" | Importador: {m.group(4)}", None))

        pos = end

    if pos < len(mensagem):
        segments.append((mensagem[pos:], None))

    return segments

def generate_pdf(logs_filtered, start_date, end_date):
    pdf = PDFReport()
    pdf.alias_nb_pages()
    pdf.add_page()
    pdf.set_font("Helvetica", "", 10)

    str_inicio = start_date.strftime('%d/%m/%Y') if hasattr(start_date, 'strftime') else str(start_date)
    str_fim = end_date.strftime('%d/%m/%Y') if hasattr(end_date, 'strftime') else str(end_date)

    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 8, sanitize_pdf_text(f"Periodo selecionado: {str_inicio} a {str_fim}"), new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 8, sanitize_pdf_text(f"Total de Registros: {len(logs_filtered)}"), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    pdf.set_font("Helvetica", "", 9)
    for item in logs_filtered:
        pdf.set_text_color(*PDF_BLACK)
        pdf.write(6, sanitize_pdf_text(f"[{item['timestamp']}] "))

        segments = build_pdf_segments(item['mensagem'])
        for texto_seg, cor in segments:
            pdf.set_text_color(*(cor if cor else PDF_BLACK))
            pdf.write(6, sanitize_pdf_text(texto_seg))

        pdf.set_text_color(*PDF_BLACK)
        pdf.ln(8)

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
# EXECUÇÃO AUTOMÁTICA DE SINCRONIZAÇÃO A CADA LOOP
# ==========================================
with st.spinner("Sincronizando planilhas em segundo plano..."):
    qtd_sucesso = executar_sincronizacao()

# ==========================================
# PAINEL PRINCIPAL
# ==========================================
st.title("📊 Monitor Operacional em Tempo Real")
st.caption(f"Monitorando **{len(LISTA_PLANILHAS)}** planilha(s) configurada(s). *(Atualizando e sincronizando automaticamente a cada 2 minutos)*")

st.divider()

# --- SELEÇÃO DE DATAS E BUSCA NO SUPABASE ---
hoje_br = get_now_br().date()

st.subheader("📅 Seleção de Período de Análise")
col_search, col_dt1, col_dt2 = st.columns([2, 1, 1])

with col_dt1:
    dt_inicio = st.date_input(
        "Data Inicial",
        value=hoje_br,
        format="DD/MM/YYYY"
    )

with col_dt2:
    dt_fim = st.date_input(
        "Data Final",
        value=hoje_br,
        format="DD/MM/YYYY"
    )

with col_search:
    search_query = st.text_input(
        "🔍 Pesquisar no Log:",
        placeholder="Nome do digitador, importador ou referência..."
    )

# Busca logs direto no banco do Supabase referente ao período
logs_periodo = load_logs_by_period(dt_inicio, dt_fim)

if logs_periodo:
    df_logs_periodo = pd.DataFrame(logs_periodo)
else:
    df_logs_periodo = pd.DataFrame(columns=["timestamp", "date", "sheet_name", "digitador", "referencia", "mensagem"])

st.divider()

# --- ESTATÍSTICAS BASEADAS NO PERÍODO SELECIONADO ---
st.subheader(f"📈 Estatísticas no Período ({dt_inicio.strftime('%d/%m/%Y')} a {dt_fim.strftime('%d/%m/%Y')})")

if not df_logs_periodo.empty:
    col_m1, col_m2, col_m3 = st.columns(3)
    col_m1.metric("Ações Registradas no Período", len(df_logs_periodo))
    col_m2.metric("Digitadores Ativos", df_logs_periodo["digitador"].nunique())
    col_m3.metric("Planilhas com Atividade", df_logs_periodo["sheet_name"].nunique())

    planilhas_com_log = ["🌐 Consolidado (Todas)"] + sorted(list(df_logs_periodo["sheet_name"].unique()))
    tabs = st.tabs(planilhas_com_log)
    
    with tabs[0]:
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Atividades por Digitador (Geral)**")
            st.bar_chart(df_logs_periodo["digitador"].value_counts())
        with c2:
            st.markdown("**Atividades por Planilha**")
            st.bar_chart(df_logs_periodo["sheet_name"].value_counts())

    for idx, sheet_key in enumerate(planilhas_com_log[1:], start=1):
        with tabs[idx]:
            df_sheet_logs = df_logs_periodo[df_logs_periodo["sheet_name"] == sheet_key]
            
            c_s1, c_s2 = st.columns(2)
            with c_s1:
                st.markdown("**Atividades por Digitador**")
                st.bar_chart(df_sheet_logs["digitador"].value_counts())
            with c_s2:
                st.markdown("**Ações mais Frequentes**")
                st.bar_chart(df_sheet_logs["referencia"].value_counts().head(10))
else:
    st.info("Nenhuma atividade registrada no período selecionado.")

st.divider()

# --- LOG DE ATIVIDADES EM TEMPO REAL ---
st.subheader("🪵 Log de Atividades dos Digitadores")

# Filtragem Adicional por Texto
filtered_logs = []
for log in logs_periodo:
    # 1. Ignora registros cuja coluna alterada seja 'DATA ATUALIZAÇÃO'
    coluna_modificada = str(log.get("coluna", "")).strip().upper()
    if coluna_modificada == "DATA ATUALIZAÇÃO":
        continue

    # Alternativa: se o nome da coluna fica dentro do texto da 'mensagem' ou 'referencia'
    # if "DATA ATUALIZAÇÃO" in str(log.get("mensagem", "")).upper():
    #     continue

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

# Botão de Exportação de PDF
if filtered_logs:
    try:
        pdf_bytes = generate_pdf(
            filtered_logs,
            dt_inicio,
            dt_fim
        )
        st.download_button(
            label="📄 Extrair Relatório PDF (Registros Exibidos)",
            data=bytes(pdf_bytes),
            file_name=f"relatorio_digitacao_{dt_inicio.strftime('%d-%m-%Y')}_{dt_fim.strftime('%d-%m-%Y')}.pdf",
            mime="application/pdf"
        )
    except Exception as e:
        st.error(f"Erro ao gerar PDF: {e}")

# Container de Logs
st.markdown("**Histórico de Eventos:**")
log_container = st.container(height=380, border=True)

with log_container:
    if filtered_logs:
        for entry in filtered_logs:
            msg_destacada = highlight_log_message(entry['mensagem'])
            # Mantida a exibição do horário do log/evento
            st.markdown(f"`{entry['timestamp']}` — **{msg_destacada}**", unsafe_allow_html=True)
    else:
        st.write("Nenhum registro encontrado para os filtros selecionados.")
