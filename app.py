import os
import re
import io
import time
import requests
import unicodedata
from collections import Counter
from datetime import datetime, date
from concurrent.futures import ThreadPoolExecutor, as_completed
from zoneinfo import ZoneInfo
import pandas as pd
import streamlit as st
from fpdf import FPDF
from supabase import create_client, Client
from streamlit_autorefresh import st_autorefresh
import base64

from google.oauth2.service_account import Credentials
import google.auth.transport.requests

# ==========================================
# CONFIGURAÇÃO DE BORDAS E ESPAÇAMENTO DO STREAMLIT
# ==========================================
st.set_page_config(layout="wide", page_title="Monitor Operacional - Multprocessing", page_icon="📊")

st.markdown(
    """
    <style>
        .main .block-container {
            padding-top: 1rem !important;
            padding-bottom: 1rem !important;
            padding-left: 1rem !important;
            padding-right: 1rem !important;
            max-width: 100% !important;
        }
        header[data-testid="stHeader"] {
            display: none;
        }
    </style>
    """,
    unsafe_allow_html=True
)

def get_logo_base64():
    try:
        with open("logoMult.png", "rb") as img_file:
            return base64.b64encode(img_file.read()).decode()
    except Exception:
        return "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="

def exibir_intro():
    """Exibe a intro apenas com o logotipo durante o carregamento"""
    intro_placeholder = st.empty()
    logo_base64 = get_logo_base64()
    
    intro_html = f"""
    <style>
        .intro-container {{
            display: flex;
            flex-direction: column;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
            background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%);
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            z-index: 99999;
            transition: opacity 0.8s ease-in-out;
        }}
        .intro-container.fade-out {{
            opacity: 0;
            pointer-events: none;
        }}
        .logo-container {{
            display: flex;
            justify-content: center;
            align-items: center;
            width: 100%;
            animation: float 2s ease-in-out infinite;
        }}
        .logo-image {{
            max-width: 400px;
            width: 80%;
            margin: 0 auto;
            display: block;
        }}
        @keyframes float {{
            0% {{ transform: translateY(0px); }}
            50% {{ transform: translateY(-10px); }}
            100% {{ transform: translateY(0px); }}
        }}
    </style>
    
    <div id="intro-container" class="intro-container">
        <div class="logo-container">
            <img src="data:image/png;base64,{logo_base64}" class="logo-image" alt="Logo">
        </div>
    </div>
    
    <script>
        var percent = 0;
        var container = document.getElementById('intro-container');
        
        var interval = setInterval(function() {{
            percent += Math.floor(Math.random() * 15) + 5;
            if (percent > 100) percent = 100;
            
            if (percent >= 100) {{
                clearInterval(interval);
                setTimeout(function() {{
                    if (container) {{
                        container.classList.add('fade-out');
                        setTimeout(function() {{
                            container.style.display = 'none';
                        }}, 800);
                    }}
                }}, 300);
            }}
        }}, 100);
    </script>
    """
    
    intro_placeholder.markdown(intro_html, unsafe_allow_html=True)
    time.sleep(1.5)
    intro_placeholder.empty()
    return intro_placeholder

# ==========================================
# INICIALIZAÇÃO
# ==========================================
if 'intro_exibida' not in st.session_state:
    exibir_intro()
    st.session_state['intro_exibida'] = True

TZ_BR = ZoneInfo("America/Sao_Paulo")

def get_now_br() -> datetime:
    """Retorna o datetime atual no fuso de Brasília."""
    return datetime.now(TZ_BR)

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
# GERADOR DE TOKEN GOOGLE OAUTH2
# ==========================================
@st.cache_resource
def get_google_credentials() -> Credentials:
    """Cria (uma única vez) o objeto de credenciais da Service Account.
    Não cacheia o token final, pois ele expira em ~1h — o objeto
    Credentials precisa persistir para poder ser renovado quando expirar."""
    try:
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets.readonly",
            "https://www.googleapis.com/auth/drive.readonly"
        ]

        if "gcp_service_account" in st.secrets:
            creds_dict = dict(st.secrets["gcp_service_account"])
        else:
            creds_dict = {
                "type": st.secrets.get("type"),
                "project_id": st.secrets.get("project_id"),
                "private_key_id": st.secrets.get("private_key_id"),
                "private_key": st.secrets.get("private_key"),
                "client_email": st.secrets.get("client_email"),
                "client_id": st.secrets.get("client_id"),
                "auth_uri": st.secrets.get("auth_uri"),
                "token_uri": st.secrets.get("token_uri"),
                "auth_provider_x509_cert_url": st.secrets.get("auth_provider_x509_cert_url"),
                "client_x509_cert_url": st.secrets.get("client_x509_cert_url")
            }

        return Credentials.from_service_account_info(creds_dict, scopes=scopes)
    except Exception as e:
        st.error(f"❌ Erro ao carregar Credenciais do Google: {e}")
        st.stop()

def get_google_access_token() -> str:
    """Retorna um Access Token válido, renovando automaticamente se
    estiver expirado ou ainda não tiver sido gerado (evita o erro 401
    que ocorria quando o token cacheado expirava após ~1h)."""
    try:
        credentials = get_google_credentials()
        if not credentials.valid or credentials.expired:
            auth_req = google.auth.transport.requests.Request()
            credentials.refresh(auth_req)
        return credentials.token
    except Exception as e:
        st.error(f"❌ Erro ao obter Token de Acesso do Google: {e}")
        st.stop()

# ==========================================
# EXTRAÇÃO DE ID DAS PLANILHAS
# ==========================================
NOME_ABA_LOG = "LOG"

def extract_spreadsheet_id(url_or_id: str) -> str:
    match = re.search(r"/d/([a-zA-Z0-9-_]+)", str(url_or_id))
    return match.group(1) if match else str(url_or_id).strip()

LISTA_PLANILHAS = {
    f"PLANILHA {nome.replace('_', ' ')}": extract_spreadsheet_id(sheet_id_or_url)
    for nome, sheet_id_or_url in st.secrets.get("planilhas", {}).items()
}

DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)

# ==========================================
# GERENCIAMENTO DE LOGS VIA SUPABASE
# ==========================================
def load_logs_by_period(start_date: date, end_date: date):
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
    try:
        response = (
            supabase.table("atividades")
            .select("timestamp, referencia, digitador")
            .eq("sheet_name", sheet_name)
            .execute()
        )
        if response.data:
            return {
                f"{str(row.get('referencia', '')).strip()}_{str(row.get('digitador', '')).strip()}_{str(row.get('timestamp', '')).strip()}"
                for row in response.data
            }
        return set()
    except Exception:
        return set()

def add_log_entries_bulk(logs_list):
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
# TRATAMENTO DE TEXTO E PROCESSAMENTO
# ==========================================
def normalize_text(text: str) -> str:
    text_str = str(text).strip()
    try:
        text_str = text_str.encode('latin1').decode('utf-8')
    except (UnicodeEncodeError, UnicodeDecodeError):
        pass
        
    nfkd_form = unicodedata.normalize('NFKD', text_str)
    only_ascii = "".join([c for c in nfkd_form if not unicodedata.combining(c)])
    return only_ascii.upper()

def process_single_sheet_update(sheet_name, uploaded_df):
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
    
    # 1. REMOVE DUPLICADAS EXATAS VINDA DA PRÓPRIA PLANILHA
    uploaded_df = uploaded_df.drop_duplicates(subset=req_cols)

    existing_keys_in_db = get_existing_timestamps_for_sheet(sheet_name)
    new_logs = []
    now_br = get_now_br()

    for _, row in uploaded_df.iterrows():
        digitador = row.get("DIGITADOR", "-").strip()
        ref = row.get("REFERÊNCIA", "-").strip()
        data_atualizacao = row.get("DATA ATUALIZAÇÃO", "-").strip()

        if not digitador or digitador in ["-", "nan", "None"] or not ref or ref in ["-", "nan", "None"]:
            continue

        # 2. CHAVE DE COMPARAÇÃO NORMALIZADA (Sem espaços extras, case-insensitive)
        row_key = f"{ref.upper()}_{digitador.upper()}_{data_atualizacao.upper()}"

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

            # Conversão robusta de data
            try:
                dt_obj = pd.to_datetime(data_atualizacao, dayfirst=True, errors="coerce")
                if pd.notna(dt_obj):
                    parsed_date = dt_obj.strftime("%Y-%m-%d")
                else:
                    parsed_date = now_br.strftime("%Y-%m-%d")
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
            
            # 3. EVITA DUPLICAR NO MESMO BATCH
            existing_keys_in_db.add(row_key)

    if new_logs:
        add_log_entries_bulk(new_logs)

    return True, None
    
# ==========================================
# LEITURA DE PLANILHA VIA REQUISIÇÃO DIRECT CSV (SEM CORTE DE LINHAS)
# ==========================================
def fetch_and_process_sheet(name, sheet_id, token):
    """Lê a aba LOG inteira da planilha via API oficial do Google Sheets v4."""
    try:
        range_ = f"{NOME_ABA_LOG}"
        url = f"https://sheets.googleapis.com/v4/spreadsheets/{sheet_id}/values/{range_}"
        headers = {"Authorization": f"Bearer {token}"}
        params = {"valueRenderOption": "UNFORMATTED_VALUE", "dateTimeRenderOption": "FORMATTED_STRING"}

        response = requests.get(url, headers=headers, params=params, timeout=20)

        if response.status_code == 404:
            return False, f"❌ **Erro na '{name}'**: A aba '{NOME_ABA_LOG}' ou a planilha não foi encontrada."
        elif response.status_code == 403:
            return False, f"❌ **Erro na '{name}'**: Sem permissão. Verifique se a planilha foi compartilhada com o e-mail da Service Account."
        elif response.status_code != 200:
            return False, f"❌ Erro HTTP {response.status_code} ao buscar '{name}'."

        data = response.json()
        values = data.get("values", [])

        if not values or len(values) < 2:
            return True, None

        header, *rows = values
        # Normaliza número de colunas (linhas mais curtas viram preenchidas com "")
        max_len = len(header)
        rows_fixed = [row + [""] * (max_len - len(row)) for row in rows]

        df_dl = pd.DataFrame(rows_fixed, columns=header)

        success, msg = process_single_sheet_update(name, df_dl)
        return success, msg

    except Exception as e:
        return False, f"❌ Erro inesperado ao processar '{name}': {e}"

def executar_sincronizacao():
    sucessos = 0
    token = get_google_access_token()

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [
            executor.submit(fetch_and_process_sheet, name, sheet_id, token)
            for name, sheet_id in LISTA_PLANILHAS.items()
        ]

        for future in as_completed(futures):
            success, err_msg = future.result()
            if success:
                sucessos += 1
            elif err_msg:
                st.error(err_msg)

    return sucessos

# ==========================================
# RELATÓRIO PDF
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

    digitador_counter = Counter()
    importador_counter = Counter()
    importador_pattern = re.compile(r"—\s*\[(.*?)\]\s*—")

    for item in logs_filtered:
        digitador = str(item.get("digitador", "-")).strip()
        if digitador and digitador not in ("-", "nan", "None"):
            digitador_counter[digitador] += 1

        match = importador_pattern.search(item.get("mensagem", ""))
        if match:
            importador = match.group(1).strip()
            if importador and importador not in ("-", "nan", "None"):
                importador_counter[importador] += 1

    if digitador_counter:
        top_digitador, qtd_digitador = digitador_counter.most_common(1)[0]
        pdf.cell(
            0, 8,
            sanitize_pdf_text(f"Digitador com mais atividade: {top_digitador} ({qtd_digitador} registro(s))"),
            new_x="LMARGIN", new_y="NEXT"
        )

    if importador_counter:
        top_importador, qtd_importador = importador_counter.most_common(1)[0]
        pdf.cell(
            0, 8,
            sanitize_pdf_text(f"Importador com mais atividade: {top_importador} ({qtd_importador} registro(s))"),
            new_x="LMARGIN", new_y="NEXT"
        )

    pdf.ln(3)
    pdf.set_draw_color(220, 220, 220)
    pdf.set_line_width(0.3)
    pdf.line(pdf.get_x(), pdf.get_y(), pdf.get_x() + 190, pdf.get_y())
    pdf.ln(5)

    pdf.set_font("Helvetica", "", 9)
    for item in logs_filtered:
        mensagem = item.get("mensagem", "")
        segments = build_pdf_segments(mensagem)

        for texto, cor in segments:
            texto_limpo = sanitize_pdf_text(texto)
            if cor:
                pdf.set_text_color(*cor)
            else:
                pdf.set_text_color(*PDF_BLACK)
            pdf.write(5, texto_limpo)

        pdf.set_text_color(*PDF_BLACK)
        pdf.ln(6)

    output = pdf.output()
    return bytes(output)

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
with st.spinner("Sincronizando histórico completo das planilhas..."):
    qtd_sucesso = executar_sincronizacao()

# ==========================================
# PAINEL PRINCIPAL
# ==========================================
col_titulo, col_logo = st.columns([0.88, 0.12], vertical_alignment="center")

with col_titulo:
    st.title("📊 Monitor Operacional em Tempo Real")

with col_logo:
    st.image("logoMult.png", use_container_width=True)

st.caption(f"Monitorando **{len(LISTA_PLANILHAS)}** planilha(s) configurada(s) — dados lidos da aba **'{NOME_ABA_LOG}'**. *(Atenção: Atualiza automaticamente a cada 20 segundos!)*")

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

# --- CARREGA LOGS DO BANCO E APLICA FILTRAGEM COMPLETA ---
logs_periodo_brutos = load_logs_by_period(dt_inicio, dt_fim)

if logs_periodo_brutos:
    df_logs_periodo = pd.DataFrame(logs_periodo_brutos)
else:
    df_logs_periodo = pd.DataFrame(columns=["timestamp", "date", "sheet_name", "digitador", "referencia", "mensagem"])

# Garantir conversão da data para filtro de período exato
if not df_logs_periodo.empty and "date" in df_logs_periodo.columns:
    df_logs_periodo["parsed_date"] = pd.to_datetime(df_logs_periodo["date"], errors="coerce").dt.date
    df_logs_periodo = df_logs_periodo[
        (df_logs_periodo["parsed_date"] >= dt_inicio) & 
        (df_logs_periodo["parsed_date"] <= dt_fim)
    ]

st.session_state["df_logs_periodo"] = df_logs_periodo
st.session_state["last_dt_inicio"] = dt_inicio
st.session_state["last_dt_fim"] = dt_fim

logs_periodo = df_logs_periodo.to_dict("records") if not df_logs_periodo.empty else []

st.divider()

# --- LÓGICA DE CÁLCULO DE AÇÕES AGRUPADAS ---
total_acoes_agrupadas = 0

if not df_logs_periodo.empty:
    col_data = None
    for candidatos in ["timestamp", "DATA ATUALIZAÇÃO", "data_atualizacao", "data_hora", "data"]:
        if candidatos in df_logs_periodo.columns:
            col_data = candidatos
            break
            
    col_digitador = "digitador" if "digitador" in df_logs_periodo.columns else None

    if col_data and col_digitador:
        df_sorted = df_logs_periodo.sort_values(by=[col_digitador, col_data]).copy()
        
        # Converte string formatada para Datetime
        df_sorted["dt_parsed"] = pd.to_datetime(df_sorted[col_data], dayfirst=True, errors="coerce")
        df_sorted["diff_tempo"] = df_sorted.groupby(col_digitador)["dt_parsed"].diff()
        
        # Considera nova ação se o intervalo entre edições for superior a 2 minutos (120 seg)
        df_sorted["nova_acao"] = df_sorted["diff_tempo"].isna() | (df_sorted["diff_tempo"].dt.total_seconds() > 120)
        
        total_acoes_agrupadas = int(df_sorted["nova_acao"].sum())
        df_acoes_filtradas = df_sorted[df_sorted["nova_acao"]]
    else:
        total_acoes_agrupadas = len(df_logs_periodo)
        df_acoes_filtradas = df_logs_periodo.copy()
else:
    df_acoes_filtradas = pd.DataFrame(columns=["sheet_name", "digitador", "referencia"])

# --- ESTATÍSTICAS BASEADAS NO PERÍODO SELECIONADO ---
st.subheader(f"📈 Estatísticas no Período ({dt_inicio.strftime('%d/%m/%Y')} a {dt_fim.strftime('%d/%m/%Y')})")

if not df_logs_periodo.empty:
    col_m1, col_m2, col_m3 = st.columns(3)
    
    col_m1.metric("Ações Registradas no Período", total_acoes_agrupadas)
    col_m2.metric("Digitadores Ativos", df_logs_periodo["digitador"].nunique())
    col_m3.metric("Planilhas com Atividade", df_logs_periodo["sheet_name"].nunique())

    # Exibe APENAS planilhas com movimentação no período selecionado
    planilhas_com_movimentacao = sorted([p for p in df_logs_periodo["sheet_name"].unique() if p and str(p) not in ["None", "nan", "-"]])
    
    planilhas_com_log = ["🌐 Consolidado (Todas)"] + planilhas_com_movimentacao
    tabs = st.tabs(planilhas_com_log)
    
    # --- ABA CONSOLIDADO ---
    with tabs[0]:
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Atividades por Digitador (Geral)**")
            st.bar_chart(df_acoes_filtradas["digitador"].value_counts())
        with c2:
            st.markdown("**Atividades por Planilha**")
            st.bar_chart(df_acoes_filtradas["sheet_name"].value_counts())

    # --- ABAS INDIVIDUAIS ---
    for idx, sheet_key in enumerate(planilhas_com_movimentacao, start=1):
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

# --- LOG ATIVIDADES ---
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
        dt_conv = pd.to_datetime(timestamp_str, dayfirst=True, errors="coerce")
        if pd.notna(dt_conv):
            return dt_conv.to_pydatetime()
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

# ==========================================
# EXPORTAÇÃO DO LOG EM PDF
# ==========================================
st.write("")

if logs_periodo:
    logs_para_pdf = sorted(logs_periodo, key=obter_data_log, reverse=True)
    pdf_bytes = generate_pdf(logs_para_pdf, dt_inicio, dt_fim)

    st.download_button(
        label="📄 Extrair Log em PDF",
        data=io.BytesIO(pdf_bytes),
        file_name=f"relatorio_log_{dt_inicio.strftime('%Y%m%d')}_a_{dt_fim.strftime('%Y%m%d')}.pdf",
        mime="application/pdf",
        use_container_width=True,
    )
else:
    st.caption("📄 Nenhum registro no período selecionado para extrair em PDF.")
