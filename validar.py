"""Compara o simulador com solucoes analiticas e gera a figura validacao.png.

Uso:  python validar.py
"""
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from bondgraph import balanco_energia, carregar, montar, simular


def caso(entrada, **kw):
    bg, opcoes, _ = carregar(entrada)
    opcoes.update(kw)
    return simular(montar(bg), **opcoes)


def segunda_ordem(t, ganho, alfa, w0):
    wd = np.sqrt(w0 ** 2 - alfa ** 2)
    return ganho * (1 - np.exp(-alfa * t) * (np.cos(wd * t) + alfa / wd * np.sin(wd * t)))


casos = []
r = caso("exemplos/rc_serie.json")
casos.append(("RC serie: tensao no capacitor (V)", r, r.sinal("C1.e"),
              10 * (1 - np.exp(-r.t / 1e-4))))
r = caso("exemplos/rlc_serie.json")
casos.append(("RLC serie: tensao no capacitor (V)", r, r.sinal("C1.e"),
              segunda_ordem(r.t, 5.0, 10 / (2 * 0.01), 1 / np.sqrt(0.01 * 1e-4))))
r = caso("exemplos/massa_mola_amortecedor.json")
casos.append(("Massa-mola-amortecedor: deslocamento (m)", r, r.sinal("q_K1"),
              segunda_ordem(r.t, 10 / 50, 3 / (2 * 2), np.sqrt(50 / 2))))
r = caso("exemplos/motor_cc.json")
K, R, b, V, L, J = 0.05, 1.0, 1e-4, 12.0, 0.005, 2e-4
A = np.array([[-R / L, -K / J], [K / L, -b / J]])          # estados: p_La, p_J
lam, vec = np.linalg.eig(A)
regime = -np.linalg.solve(A, [V, 0.0])
coef = np.linalg.solve(vec, -regime)
p_j = (regime[:, None] + (vec * coef) @ np.exp(np.outer(lam, r.t)))[1].real
casos.append(("Motor CC: velocidade angular (rad/s)", r, r.sinal("J.f"), p_j / J))

fig, eixos = plt.subplots(2, 2, figsize=(11, 7))
print(f"{'caso':<45}{'erro max. relativo':>20}{'erro de energia':>18}")
for ax, (titulo, r, sim, ana) in zip(eixos.ravel(), casos):
    erro = np.max(np.abs(sim - ana)) / np.max(np.abs(ana))
    print(f"{titulo:<45}{erro:>20.2e}{balanco_energia(r)['erro_relativo']:>18.2e}")
    ax.plot(r.t, ana, color="#bbbbbb", lw=5, label="analitico")
    ax.plot(r.t, sim, color="#2a6fb0", lw=1.4, label="simulador")
    ax.set_title(f"{titulo}\nerro max. relativo = {erro:.1e}", fontsize=10)
    ax.set_xlabel("tempo (s)")
    ax.grid(alpha=0.3)
    ax.legend(fontsize=8)
fig.tight_layout()
fig.savefig("validacao.png", dpi=110)
print("Figura salva em validacao.png")
