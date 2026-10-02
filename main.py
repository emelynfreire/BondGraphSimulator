"""Uso pela linha de comando.

  python main.py "Um resistor de 100 Ohms em serie com um capacitor de 1 uF
                  conectado a uma fonte de tensao de 10V"
  python main.py exemplos/rlc_serie.json --metodo RK4 --figura saida.png --csv saida.csv
"""
from __future__ import annotations

import argparse

from bondgraph import METODOS, ErroBondGraph, carregar, diagnosticar, montar, simular
from bondgraph.analise import texto_diagnostico


def main():
    ap = argparse.ArgumentParser(description="Simulador simples de Bond Graph")
    ap.add_argument("entrada", help="descricao em texto, JSON ou caminho de arquivo .json")
    ap.add_argument("--metodo", default="auto", choices=METODOS)
    ap.add_argument("--t-final", type=float, default=None)
    ap.add_argument("--figura", help="salva os graficos (PNG) em vez de abrir janela")
    ap.add_argument("--csv", help="salva os sinais em CSV")
    ap.add_argument("--sem-grafico", action="store_true")
    args = ap.parse_args()

    try:
        bg, opcoes, notas = carregar(args.entrada)
        if notas:
            print("INTERPRETACAO DO TEXTO\n" + "\n".join(notas) + "\n")
        print(bg.resumo())
        sistema = montar(bg)
        print("\nEQUACOES DE ESTADO\n" + sistema.equacoes_texto)
        if args.t_final:
            opcoes["t_final"] = args.t_final
        opcoes["metodo"] = args.metodo
        res = simular(sistema, **opcoes)
    except ErroBondGraph as exc:
        raise SystemExit(f"Erro: {exc}")
    print("\nDIAGNOSTICO\n" + texto_diagnostico(diagnosticar(res)))
    if args.csv:
        res.salvar_csv(args.csv)
    if args.sem_grafico:
        return

    import matplotlib
    if args.figura:
        matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from bondgraph.visual import desenhar_bond_graph, plotar_resultado

    fig1, ax = plt.subplots(figsize=(6, 4))
    desenhar_bond_graph(bg, ax)
    fig2 = plt.figure(figsize=(8, 6))
    plotar_resultado(res, fig2)
    if args.figura:
        base = args.figura.rsplit(".", 1)[0]
        fig1.savefig(base + "_bondgraph.png", dpi=120)
        fig2.savefig(args.figura, dpi=120)
        print(f"\nFiguras salvas: {args.figura} e {base}_bondgraph.png")
    else:
        plt.show()


if __name__ == "__main__":
    main()
