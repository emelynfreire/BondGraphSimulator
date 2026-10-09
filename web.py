"""Interface web do simulador de Bond Graph (Streamlit), usada no Docker.

Uso local:   streamlit run web.py
Com Docker:  docker compose up        (abre em http://localhost:8501)
"""
from __future__ import annotations

import glob
import io
import os

import matplotlib
matplotlib.use("Agg")
import numpy as np
import streamlit as st
from matplotlib.figure import Figure

from bondgraph import METODOS, carregar, diagnosticar, montar, simular
from bondgraph.analise import texto_diagnostico
from bondgraph.exemplos_texto import EXEMPLOS_TEXTO
from bondgraph.visual import desenhar_bond_graph, plotar_resultado

PASTA = os.path.dirname(os.path.abspath(__file__))

st.set_page_config(page_title="Simulador de Bond Graph", layout="wide")
st.title("Simulador de Bond Graph — protótipo")

exemplos = dict(EXEMPLOS_TEXTO)
for caminho in sorted(glob.glob(os.path.join(PASTA, "exemplos", "*.json"))):
    with open(caminho, encoding="utf-8") as arq:
        exemplos["JSON: " + os.path.basename(caminho)] = arq.read()


def _trocar_exemplo():
    st.session_state["descricao"] = exemplos[st.session_state["exemplo"]]


if "descricao" not in st.session_state:
    st.session_state["descricao"] = next(iter(exemplos.values()))

with st.sidebar:
    st.selectbox("Exemplos", list(exemplos), key="exemplo", on_change=_trocar_exemplo)
    st.text_area("Descrição do sistema (texto em português ou JSON)", key="descricao", height=260)
    metodo = st.selectbox("Método de integração", list(METODOS))
    tf_txt = st.text_input("Tempo final (s)", help="Vazio = escolha automática.")
    executar = st.button("Simular", type="primary")

try:
    bg, opcoes, notas = carregar(st.session_state["descricao"].strip())
    sistema = montar(bg)
except Exception as exc:
    st.error(f"Erro: {exc}")
    st.stop()

aba_bg, aba_sim, aba_eq = st.tabs(["Bond Graph", "Simulação", "Equações e diagnóstico"])

with aba_bg:
    fig = Figure(figsize=(7, 4.5), dpi=100)
    desenhar_bond_graph(bg, fig.add_subplot(111))
    st.pyplot(fig)

texto = ""
if notas:
    texto += "INTERPRETAÇÃO DO TEXTO\n" + "\n".join(notas) + "\n\n"
texto += bg.resumo() + "\n\nEQUAÇÕES DE ESTADO\n" + sistema.equacoes_texto + "\n"

with aba_sim:
    if not executar:
        st.info("Clique em **Simular** na barra lateral.")
    else:
        try:
            if tf_txt.strip():
                opcoes["t_final"] = float(tf_txt.strip().replace(",", "."))
            opcoes["metodo"] = metodo
            with st.spinner("Simulando..."):
                res = simular(sistema, **opcoes)
            fig = Figure(figsize=(9, 6), dpi=100)
            plotar_resultado(res, fig)
            st.pyplot(fig)
            texto += "\nDIAGNÓSTICO\n" + texto_diagnostico(diagnosticar(res)) + "\n"

            nomes = list(res.sinais)
            saida = io.StringIO()
            np.savetxt(saida, np.column_stack([res.t] + [res.sinais[n] for n in nomes]),
                       delimiter=",", header="t," + ",".join(nomes), comments="")
            st.download_button("Baixar sinais (CSV)", saida.getvalue(),
                               file_name="simulacao.csv", mime="text/csv")
        except Exception as exc:
            st.error(f"Erro: {exc}")

with aba_eq:
    st.code(texto, language=None)
