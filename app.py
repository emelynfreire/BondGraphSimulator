"""Interface grafica do simulador de Bond Graph (Tkinter).

Uso:  python app.py
"""
from __future__ import annotations

import glob
import os
import tkinter as tk
from tkinter import filedialog, scrolledtext, ttk

import matplotlib
matplotlib.use("TkAgg")
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure

from bondgraph import METODOS, carregar, diagnosticar, montar, simular
from bondgraph.analise import texto_diagnostico
from bondgraph.visual import desenhar_bond_graph, plotar_resultado

PASTA = os.path.dirname(os.path.abspath(__file__))
EXEMPLOS_TEXTO = {
    "Texto: RC serie": "Um resistor de 100 Ohms em série com um capacitor de 1 µF "
                       "conectado a uma fonte de tensão de 10V",
    "Texto: RLC serie": "Fonte de tensão de 5 V ligada a um resistor de 10 ohms, um indutor "
                        "de 10 mH e um capacitor de 100 uF em série. Simular por 20 ms",
    "Texto: RC paralelo": "Fonte de corrente de 2 mA alimentando um resistor de 1 kΩ em "
                          "paralelo com um capacitor de 1 µF",
    "Texto: massa-mola-amortecedor": "Uma massa de 2 kg presa a uma mola de 50 N/m e a um "
                                     "amortecedor de 3 N.s/m, com força de 10 N",
    "Texto: retificador com diodo": "Fonte de tensão senoidal de 10 V e 60 Hz, um diodo em série "
                                    "com um resistor de 1 kΩ em paralelo com um capacitor de "
                                    "100 uF. Simular por 100 ms",
}


class Aplicacao(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Simulador de Bond Graph - prototipo")
        self.geometry("1150x700")
        self.resultado = None
        self.exemplos = dict(EXEMPLOS_TEXTO)
        for caminho in sorted(glob.glob(os.path.join(PASTA, "exemplos", "*.json"))):
            self.exemplos["JSON: " + os.path.basename(caminho)] = caminho
        self._montar_tela()
        self.combo_ex.current(0)
        self._carregar_exemplo()

    # ---------------------------------------------------------------- tela
    def _montar_tela(self):
        esq = ttk.Frame(self, padding=8)
        esq.pack(side=tk.LEFT, fill=tk.Y)
        ttk.Label(esq, text="Exemplos").pack(anchor="w")
        self.combo_ex = ttk.Combobox(esq, values=list(self.exemplos), state="readonly", width=42)
        self.combo_ex.pack(fill=tk.X)
        self.combo_ex.bind("<<ComboboxSelected>>", lambda _: self._carregar_exemplo())

        ttk.Label(esq, text="Descrição do sistema (texto em português ou JSON)").pack(
            anchor="w", pady=(10, 0))
        self.txt = scrolledtext.ScrolledText(esq, width=46, height=16, wrap=tk.WORD)
        self.txt.pack(fill=tk.BOTH, expand=True)

        linha = ttk.Frame(esq)
        linha.pack(fill=tk.X, pady=8)
        ttk.Label(linha, text="Método").grid(row=0, column=0, sticky="w")
        self.combo_met = ttk.Combobox(linha, values=list(METODOS), state="readonly", width=10)
        self.combo_met.set("auto")
        self.combo_met.grid(row=0, column=1, padx=6)
        ttk.Label(linha, text="Tempo final (s)").grid(row=0, column=2, sticky="w")
        self.ent_tf = ttk.Entry(linha, width=10)
        self.ent_tf.grid(row=0, column=3, padx=6)
        ttk.Label(esq, text="Tempo final vazio = escolha automática.",
                  foreground="#666").pack(anchor="w")

        botoes = ttk.Frame(esq)
        botoes.pack(fill=tk.X, pady=8)
        ttk.Button(botoes, text="Gerar Bond Graph", command=self.gerar).pack(side=tk.LEFT)
        ttk.Button(botoes, text="Simular", command=self.simular).pack(side=tk.LEFT, padx=6)
        ttk.Button(botoes, text="Exportar CSV", command=self.exportar).pack(side=tk.LEFT)
        self.status = ttk.Label(esq, text="", wraplength=360, foreground="#a33")
        self.status.pack(anchor="w", fill=tk.X)

        abas = ttk.Notebook(self)
        abas.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
        self.abas = abas
        self.fig_bg, self.canvas_bg = self._aba_figura("Bond Graph")
        self.fig_sim, self.canvas_sim = self._aba_figura("Simulação", barra=True)
        self.saida = scrolledtext.ScrolledText(abas, wrap=tk.WORD, font=("Consolas", 10))
        abas.add(self.saida, text="Equações e diagnóstico")

    def _aba_figura(self, titulo, barra=False):
        quadro = ttk.Frame(self.abas)
        self.abas.add(quadro, text=titulo)
        fig = Figure(figsize=(7, 5), dpi=100)
        canvas = FigureCanvasTkAgg(fig, master=quadro)
        if barra:
            NavigationToolbar2Tk(canvas, quadro)
        canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        return fig, canvas

    # --------------------------------------------------------------- acoes
    def _carregar_exemplo(self):
        valor = self.exemplos[self.combo_ex.get()]
        if valor.endswith(".json") and os.path.exists(valor):
            with open(valor, encoding="utf-8") as arq:
                valor = arq.read()
        self.txt.delete("1.0", tk.END)
        self.txt.insert("1.0", valor)
        self.ent_tf.delete(0, tk.END)

    def _modelo(self):
        bg, opcoes, notas = carregar(self.txt.get("1.0", tk.END).strip())
        sistema = montar(bg)
        self.fig_bg.clear()
        desenhar_bond_graph(bg, self.fig_bg.add_subplot(111))
        self.canvas_bg.draw()
        texto = ""
        if notas:
            texto += "INTERPRETAÇÃO DO TEXTO\n" + "\n".join(notas) + "\n\n"
        texto += bg.resumo() + "\n\nEQUAÇÕES DE ESTADO\n" + sistema.equacoes_texto + "\n"
        return sistema, opcoes, texto

    def _mostrar(self, texto):
        self.saida.delete("1.0", tk.END)
        self.saida.insert("1.0", texto)

    def gerar(self):
        self.status.config(text="")
        try:
            _, _, texto = self._modelo()
            self._mostrar(texto)
            self.abas.select(0)
        except Exception as exc:
            self.status.config(text=f"Erro: {exc}")

    def simular(self):
        self.status.config(text="")
        try:
            sistema, opcoes, texto = self._modelo()
            tf = self.ent_tf.get().strip().replace(",", ".")
            if tf:
                opcoes["t_final"] = float(tf)
            opcoes["metodo"] = self.combo_met.get()
            self.config(cursor="watch")
            self.update_idletasks()
            self.resultado = simular(sistema, **opcoes)
            plotar_resultado(self.resultado, self.fig_sim)
            self.canvas_sim.draw()
            self._mostrar(texto + "\nDIAGNÓSTICO\n"
                          + texto_diagnostico(diagnosticar(self.resultado)) + "\n")
            self.abas.select(1)
        except Exception as exc:
            self.status.config(text=f"Erro: {exc}")
        finally:
            self.config(cursor="")

    def exportar(self):
        if self.resultado is None:
            self.status.config(text="Simule antes de exportar.")
            return
        caminho = filedialog.asksaveasfilename(defaultextension=".csv",
                                               filetypes=[("CSV", "*.csv")])
        if caminho:
            self.resultado.salvar_csv(caminho)


if __name__ == "__main__":
    Aplicacao().mainloop()
