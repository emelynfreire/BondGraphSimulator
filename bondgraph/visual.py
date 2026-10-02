"""Desenho do Bond Graph e graficos dos resultados (Matplotlib)."""
from __future__ import annotations

import networkx as nx
import numpy as np

from .modelo import BondGraph
from .simulacao import Resultado

CORES = {"Se": "#2a6fb0", "Sf": "#2a6fb0", "R": "#b0452a", "C": "#2a8f5a", "I": "#7a4fb0",
         "TF": "#555555", "GY": "#555555", "0": "#222222", "1": "#222222"}


def _posicoes(bg: BondGraph) -> dict:
    """Juncoes ao centro; elementos distribuidos em volta da juncao a que pertencem."""
    g = bg.g.to_undirected()
    nucleo = [n.nome for n in bg.nos if len(bg.bonds_do_no(n.nome)) > 1]
    sub = g.subgraph(nucleo)
    if len(nucleo) == 1:
        pos = {nucleo[0]: np.zeros(2)}
    else:
        pos = nx.kamada_kawai_layout(sub, scale=1.6 * max(1, len(nucleo) - 1) ** 0.5)
        pos = {k: np.asarray(v) for k, v in pos.items()}
    centro = np.mean(list(pos.values()), axis=0)
    for j in nucleo:
        folhas = [v for v in g.neighbors(j) if v not in pos]
        if not folhas:
            continue
        # direcoes ja ocupadas por outras juncoes
        ocupadas = [np.arctan2(*(pos[v] - pos[j])[::-1]) for v in g.neighbors(j) if v in nucleo]
        base = np.arctan2(*(pos[j] - centro)[::-1]) if np.linalg.norm(pos[j] - centro) > 1e-9 \
            else np.pi / 2
        candidatos = base + np.linspace(0, 2 * np.pi, 24, endpoint=False)
        for folha in folhas:
            def folga(a):
                return min([abs(np.angle(np.exp(1j * (a - o)))) for o in ocupadas], default=np.pi)
            ang = max(candidatos, key=folga)
            ocupadas.append(ang)
            pos[folha] = pos[j] + 1.1 * np.array([np.cos(ang), np.sin(ang)])
    return pos


def _recuo(bg: BondGraph, nome: str, d) -> float:
    """Distancia entre o centro do rotulo e a ponta do bond (evita sobreposicao)."""
    no = bg.no(nome)
    if no.tipo in ("0", "1"):
        return 0.16
    return 0.14 + 0.05 * len(f"{no.tipo}: {no.nome}") * abs(d[0])


def desenhar_bond_graph(bg: BondGraph, ax) -> None:
    """Desenha o Bond Graph: cada bond e uma meia seta no sentido da potencia."""
    ax.clear()
    pos = _posicoes(bg)
    for i, u, v in bg.bonds:
        a, b = pos[u], pos[v]
        d = (b - a) / np.linalg.norm(b - a)
        normal = np.array([-d[1], d[0]])
        a2, b2 = a + _recuo(bg, u, d) * d, b - _recuo(bg, v, d) * d
        ax.plot([a2[0], b2[0]], [a2[1], b2[1]], color="#333333", lw=1.6, zorder=1)
        farpa = b2 - 0.13 * d + 0.09 * normal          # meia seta
        ax.plot([b2[0], farpa[0]], [b2[1], farpa[1]], color="#333333", lw=1.6, zorder=1)
        meio = (a2 + b2) / 2 - 0.11 * normal
        ax.text(meio[0], meio[1], str(i), fontsize=8, color="#777777", ha="center", va="center")
    for no in bg.nos:
        x, y = pos[no.nome]
        if no.tipo in ("0", "1"):
            texto, peso, tam = no.tipo, "bold", 15
        else:
            texto, peso, tam = f"{no.tipo}: {no.nome}", "normal", 10
        ax.text(x, y, texto, ha="center", va="center", fontsize=tam, fontweight=peso,
                color=CORES[no.tipo], zorder=2)
    xs, ys = zip(*pos.values())
    ax.set_xlim(min(xs) - 0.7, max(xs) + 0.7)
    ax.set_ylim(min(ys) - 0.5, max(ys) + 0.5)
    ax.set_aspect("equal")
    ax.axis("off")
    ax.set_title(f"Bond Graph: {bg.nome}", fontsize=10)


def plotar_resultado(res: Resultado, fig) -> None:
    """Esforco e fluxo de cada elemento ao longo do tempo."""
    fig.clear()
    rot_e, rot_f = res.rotulos()
    ax1, ax2 = fig.subplots(2, 1, sharex=True)
    for nome, y in res.sinais.items():
        if nome.endswith(".e"):
            ax1.plot(res.t, y, label=nome[:-2], lw=1.4)
        elif nome.endswith(".f"):
            ax2.plot(res.t, y, label=nome[:-2], lw=1.4)
    ax1.set_ylabel(rot_e)
    ax2.set_ylabel(rot_f)
    ax2.set_xlabel("tempo (s)")
    for ax in (ax1, ax2):
        ax.grid(alpha=0.3)
        ax.legend(fontsize=8, ncol=4, loc="best")
    ax1.set_title(f"{res.sistema.bg.nome}  (metodo {res.metodo})", fontsize=10)
    fig.tight_layout()
