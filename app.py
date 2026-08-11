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
    """Retorna o datetime atual no fuso de Brasília."""
    return datetime.now(TZ_BR)

# ---------------------------------------------------------
# AUTOMAÇÃO: Recarrega/Executa a cada 20 segundos (20.000ms)
# ---------------------------------------------------------
st_autorefresh(interval=20000, key="auto_sync_timer")

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
# CONVERSOR DE LINK (Google Sheets para GViz CSV por Nome de Aba)
# ==========================================
NOME_ABA_LOG = "LOG"

def extract_spreadsheet_id(url: str) -> str:
    """Extrai o ID da planilha do Google Sheets."""
    match = re.search(r"/d/([a-zA-Z0-9-_]+)", url)
    return match.group(1) if match else None

def convert_to_gviz_url(url: str, sheet_name: str = NOME_ABA_LOG) -> str:
    """Converte a URL do Google Sheets para o endpoint GViz diretamente pelo nome da aba."""
    sheet_id = extract_spreadsheet_id(url)
    if not sheet_id:
        return url
    return f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:csv&sheet={sheet_name}"

# ==========================================
# LINKS DAS PLANILHAS FIXOS NO CÓDIGO
# ==========================================
LISTA_PLANILHAS = {
    f"PLANILHA {nome.replace('_', ' ')}": f"https://docs.google.com/spreadsheets/d/{sheet_id}"
    for nome, sheet_id in st.secrets.get("planilhas", {}).items()
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

def get_existing_timestamps_for_sheet(sheet_name: str) -> set:
    """Busca no Supabase os timestamps/mensagens que já foram inseridos para uma determinada planilha."""
    try:
        response = (
            supabase.table("atividades")
            .select("timestamp, referencia, digitador")
            .eq("sheet_name", sheet_name)
            .execute()
        )
        if response.data:
            return {
                f"{row.get('referencia', '').strip()}_{row.get('digitador', '').strip()}_{row.get('timestamp', '').strip()}"
                for row in response.data
            }
        return set()
    except Exception:
        return set()

def add_log_entries_bulk(logs_list):
    """Insere registros de atividade em lote no banco Supabase em blocos de 500 para evitar timeout."""
    if not logs_list:
        return
    
    chunk_size = 500
    for i in range(0, len(logs_list), chunk_size):
        chunk = logs_list[i : i + chunk_size]
        try:
            supabase.table("atividades").insert(chunk).execute()
        except Exception as e:
            st.error(f"Erro ao salvar lote de registros no Supabase: {e}")

# ==========================================
# TRATAMENTO DE TEXTO E LEITURA DIRETA DA ABA LOG
# ==========================================
def normalize_text(text: str) -> str:
    """Remove acentos, caracteres corrompidos, espaços extras e converte para maiúsculo."""
    text_str = str(text).strip()
    try:
        text_str = text_str.encode('latin1').decode('utf-8')
    except (UnicodeEncodeError, UnicodeDecodeError):
        pass
        
    nfkd_form = unicodedata.normalize('NFKD', text_str)
    only_ascii = "".join([c for c in nfkd_form if not unicodedata.combining(c)])
    return only_ascii.upper()

def process_single_sheet_update(sheet_name, uploaded_df):
    """Lê TODOS os registros da aba 'LOG' e envia para o Supabase os que ainda não foram cadastrados."""
    
    new_columns = []
    for col in uploaded_df.columns:
        col_str = str(col).strip()
        norm_col = normalize_text(col_str)
        
        if "REFERENC" in norm_col or "REFERANC" in norm_col:
            new_columns.append("REFERÊNCIA")
        elif "IMPORTAD" in norm_col:
            new_columns.append("IMPORTADOR")
        elif "DIGITAD" in norm_col:
            new_columns.append("DIGITADOR")
        elif "DATA" in norm_col and "ATUALIZ" in norm_col:
            new_columns.append("DATA ATUALIZAÇÃO")
        elif "OBSERVAC" in norm_col or "OBSERVAB" in norm_col:
            new_columns.append("OBSERVAÇÃO")
        else:
            new_columns.append(col_str)
            
    uploaded_df.columns = new_columns

    req_cols = ["REFERÊNCIA", "DIGITADOR", "DATA ATUALIZAÇÃO"]
    missing = [col for col in req_cols if col not in uploaded_df.columns]
    
    if missing:
        erro = (
            f"❌ A aba '{NOME_ABA_LOG}' da planilha '{sheet_name}' não possui as colunas necessárias: {', '.join(missing)}.\n\n"
            f"**Colunas encontradas:** {list(uploaded_df.columns)}"
        )
        return False, erro

    uploaded_df = uploaded_df.fillna("-").astype(str)

    existing_keys_in_db = get_existing_timestamps_for_sheet(sheet_name)

    new_logs = []
    now_br = get_now_br()

    for _, row in uploaded_df.iterrows():
        digitador = row.get("DIGITADOR", "-").strip()
        ref = row.get("REFERÊNCIA", "-").strip()
        data_atualizacao = row.get("DATA ATUALIZAÇÃO", "-").strip()

        if not digitador or digitador in ["-", "nan", "None"] or not ref or ref in ["-", "nan", "None"]:
            continue

        row_key = f"{ref}_{digitador}_{data_atualizacao}"

        if row_key not in existing_keys_in_db:
            importador = row.get("IMPORTADOR", "-").strip()
            if importador in ["nan", "None", ""]:
                importador = "-"

            observacao = row.get("OBSERVAÇÃO", "-").strip()
            if observacao in ["nan", "None", ""]:
                observacao = "-"

            msg_log = (
                f"{data_atualizacao} — [{importador}] — {digitador} — "
                f"Ação: {observacao} — Referência: {ref}"
            )

            try:
                date_part = data_atualizacao.split()[0]
                parsed_date = datetime.strptime(date_part, "%d/%m/%Y").strftime("%Y-%m-%d")
            except Exception:
                parsed_date = now_br.strftime("%Y-%m-%d")

            new_logs.append({
                "timestamp": data_atualizacao,
                "date": parsed_date,
                "sheet_name": str(sheet_name),
                "digitador": str(digitador),
                "referencia": str(ref),
                "mensagem": msg_log
            })
            
            existing_keys_in_db.add(row_key)

    if new_logs:
        add_log_entries_bulk(new_logs)

    return True, None

def fetch_and_process_sheet(name, sheet_url, headers):
    try:
        csv_url = convert_to_gviz_url(sheet_url, sheet_name=NOME_ABA_LOG)
        response = requests.get(csv_url, headers=headers, timeout=15)
        
        if response.status_code == 200:
            corpo = response.text.strip()
            if corpo.startswith("<") or "google-viz-error" in corpo.lower():
                return False, f"❌ **Erro na '{name}'**: A aba '{NOME_ABA_LOG}' não foi encontrada ou a planilha não está compartilhada como 'Qualquer pessoa com o link'."

            df_dl = pd.read_csv(io.StringIO(response.text), dtype=str)
            success, msg = process_single_sheet_update(name, df_dl)
            if success:
                return True, msg
            return False, msg
        elif response.status_code in (400, 404):
            return False, f"❌ **Erro na '{name}'**: Aba ou planilha não encontrada."
        elif response.status_code == 403:
            return False, f"❌ **Erro 403 na '{name}'**: Acesso negado. Verifique as permissões."
        else:
            return False, f"❌ Erro HTTP {response.status_code} na planilha '{name}'."
    except Exception as e:
        return False, f"❌ Erro inesperado ao processar '{name}': {e}"

def executar_sincronizacao():
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
    return unicodedata.normalize('NFKD', str(text)).encode('latin-1', 'ignore').decode('latin-1')

PDF_RED = (200, 30, 30)
PDF_BLUE = (41, 128, 185)
PDF_BLACK = (0, 0, 0)

def build_pdf_segments(mensagem: str):
    segments = []
    pattern = re.compile(r"de '([^']*)' para '([^']*)'|Referência: (.*)$")
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
        elif m.group(3) is not None:
            segments.append(("Referência: ", None))
            segments.append((m.group(3), PDF_BLUE))

        pos = end

    if pos < len(mensagem):
        segments.append((mensagem[pos:], None))

    return segments

def generate_pdf(logs_filtered, start_date, end_date) -> bytes:
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

        segments = build_pdf_segments(item['mensagem'])
        for texto_seg, cor in segments:
            pdf.set_text_color(*(cor if cor else PDF_BLACK))
            pdf.write(6, sanitize_pdf_text(texto_seg))

        pdf.set_text_color(*PDF_BLACK)
        pdf.ln(8)

    return bytes(pdf.output())

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
# PAINEL PRINCIPAL COM LOGO NO CANTO SUPERIOR DIREITO
# ==========================================
col_titulo, col_logo = st.columns([0.88, 0.12], vertical_alignment="center")

with col_titulo:
    st.title("📊 Monitor Operacional em Tempo Real")

with col_logo:
    st.image("logoMult.png", use_container_width=True)

st.caption(f"Monitorando **{len(LISTA_PLANILHAS)}** planilha(s) configurada(s) — dados lidos da aba **'{NOME_ABA_LOG}'**. *(Atenção: Atualiza automaticamente a cada 20 segundos)*")

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

logs_periodo = load_logs_by_period(dt_inicio, dt_fim)

if logs_periodo:
    df_logs_periodo = pd.DataFrame(logs_periodo)
else:
    df_logs_periodo = pd.DataFrame(columns=["timestamp", "date", "sheet_name", "digitador", "referencia", "mensagem"])

st.divider()

# --- LÓGICA DE CÁLCULO DE AÇÕES AGRUPADAS (> 2 MINUTOS POR DIGITADOR) ---
total_acoes_agrupadas = 0

if not df_logs_periodo.empty:
    col_data = None
    for candidatos in ["DATA ATUALIZAÇÃO", "timestamp", "data_atualizacao", "data_hora", "data"]:
        if candidatos in df_logs_periodo.columns:
            col_data = candidatos
            break
            
    col_digitador = "digitador" if "digitador" in df_logs_periodo.columns else None

    if col_data and col_digitador:
        df_sorted = df_logs_periodo.sort_values(by=[col_digitador, col_data]).copy()
        df_sorted[col_data] = pd.to_datetime(df_sorted[col_data], errors="coerce")
        df_sorted["diff_tempo"] = df_sorted.groupby(col_digitador)[col_data].diff()
        df_sorted["nova_acao"] = df_sorted["diff_tempo"].isna() | (df_sorted["diff_tempo"].dt.total_seconds() > 120)
        
        total_acoes_agrupadas = int(df_sorted["nova_acao"].sum())
        df_acoes_filtradas = df_sorted[df_sorted["nova_acao"]]
    else:
        st.warning(
            f"⚠️ Colunas não encontradas para agrupamento. "
            f"Colunas disponíveis na tabela: `{list(df_logs_periodo.columns)}`"
        )
        total_acoes_agrupadas = len(df_logs_periodo)
        df_acoes_filtradas = df_logs_periodo.copy()

# --- ESTATÍSTICAS BASEADAS NO PERÍODO SELECIONADO ---
st.subheader(f"📈 Estatísticas no Período ({dt_inicio.strftime('%d/%m/%Y')} a {dt_fim.strftime('%d/%m/%Y')})")

if not df_logs_periodo.empty:
    col_m1, col_m2, col_m3 = st.columns(3)
    
    col_m1.metric("Ações Registradas no Período", total_acoes_agrupadas)
    col_m2.metric("Digitadores Ativos", df_logs_periodo["digitador"].nunique())
    col_m3.metric("Planilhas com Atividade", df_logs_periodo["sheet_name"].nunique())

    planilhas_com_log = ["🌐 Consolidado (Todas)"] + sorted(list(df_logs_periodo["sheet_name"].unique()))
    tabs = st.tabs(planilhas_com_log)
    
    with tabs[0]:
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Atividades por Digitador (Geral)**")
            st.bar_chart(df_acoes_filtradas["digitador"].value_counts())
        with c2:
            st.markdown("**Atividades por Planilha**")
            st.bar_chart(df_acoes_filtradas["sheet_name"].value_counts())

    for idx, sheet_key in enumerate(planilhas_com_log[1:], start=1):
        with tabs[idx]:
            df_sheet_logs = df_acoes_filtradas[df_acoes_filtradas["sheet_name"] == sheet_key]
            
            c_s1, c_s2 = st.columns(2)
            with c_s1:
                st.markdown("**Atividades por Digitador**")
                st.bar_chart(df_sheet_logs["digitador"].value_counts())
            with c_s2:
                st.markdown("**Ações mais Frequentes**")
                st.bar_chart(df_sheet_logs["referencia"].value_counts().head(10))
else:
    st.info("Nenhuma atividade registrada no período selecionado.")

# -- LOG ATIVIDADES ---
st.markdown("**Histórico de Eventos:**")
log_container = st.container(height=380, border=True)

filtered_logs = []
if logs_periodo:
    if search_query.strip():
        term = search_query.strip().lower()
        for log in logs_periodo:
            msg = str(log.get("mensagem", "")).lower()
            digitador = str(log.get("digitador", "")).lower()
            referencia = str(log.get("referencia", "")).lower()
            sheet = str(log.get("sheet_name", "")).lower()

            if (
                term in msg
                or term in digitador
                or term in referencia
                or term in sheet
            ):
                filtered_logs.append(log)
    else:
        filtered_logs = logs_periodo.copy()

def obter_data_log(entry):
    timestamp_str = entry.get("timestamp", "")
    try:
        return datetime.strptime(timestamp_str, "%d/%m/%Y %H:%M:%S")
    except Exception:
        pass

    msg = entry.get("mensagem", "")
    match = re.search(r"^(\d{2}/\d{2}/\d{4}\s\d{2}:\d{2}:\d{2})", msg)
    if match:
        try:
            return datetime.strptime(match.group(1), "%d/%m/%Y %H:%M:%S")
        except Exception:
            pass

    return datetime.min

logs_ordenados = (
    sorted(filtered_logs, key=obter_data_log, reverse=True)
    if filtered_logs
    else []
)

with log_container:
    if logs_ordenados:
        for entry in logs_ordenados:
            mensagem = entry.get("mensagem", "")

            mensagem_formatada = re.sub(
                r"^(\d{2}/\d{2}/\d{4}\s\d{2}:\d{2}:\d{2})",
                r"<span style='color: #008000 !important; background-color: #e0e0e0; padding: 3px 8px; border-radius: 4px; font-weight: bold; display: inline-block;'>\1</span>",
                mensagem,
            )

            mensagem_formatada = re.sub(
                r"\b(de)\b", r"**\1**", mensagem_formatada, flags=re.IGNORECASE
            )
            mensagem_formatada = re.sub(
                r"\b(para)\b", r"**\1**", mensagem_formatada, flags=re.IGNORECASE
            )

            mensagem_formatada = re.sub(
                r"Ação:\s*(.*?)\s*—\s*Referência:\s*(.*)$",
                r"<span style='color: red; font-weight: bold;'>Ação:</span> \1 — Referência: <span style='color: #1E90FF; font-weight: bold;'>\2</span>",
                mensagem_formatada,
            )

            st.markdown(mensagem_formatada, unsafe_allow_html=True)
    else:
        st.write("Nenhum registro encontrado para os filtros selecionados.")
