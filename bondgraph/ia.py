"""Recursos de IA / otimizacao do prototipo.

1. ajustar_parametros: estima parametros do modelo (R, C, I...) a partir de
   dados medidos, por minimos quadrados nao lineares (otimizacao).

2. aprender_elemento: treina uma pequena rede neural (MLP) com pares medidos
   (esforco, fluxo) de um componente nao linear desconhecido e devolve a lei
   f = g(e), que pode ser usada como elemento R no Bond Graph:
       bg.adicionar("R", "Rnl", lei="funcao", funcao=g)

Sao versoes minimas, para validar a ideia de integrar IA ao simulador.
"""
from __future__ import annotations

import numpy as np
from scipy.optimize import least_squares

from .equacoes import Sistema
from .simulacao import simular


def ajustar_parametros(sistema: Sistema, t_medido, y_medido, sinal: str,
                       parametros: list[str], metodo: str = "auto") -> dict:
    """Ajusta os parametros indicados para que `sinal` reproduza os dados medidos.

    Retorna {"valores": {nome: valor}, "erro_rms": ..., "iniciais": {...}}.
    Os valores ajustados ficam gravados em `sistema`.
    """
    t_medido = np.asarray(t_medido, dtype=float)
    y_medido = np.asarray(y_medido, dtype=float)
    iniciais = {p: sistema.valor(p) for p in parametros}
    escala = max(float(np.max(np.abs(y_medido))), 1e-300)

    def residuo(log_p):
        for nome, lp in zip(parametros, log_p):      # busca em escala logaritmica
            sistema.definir(nome, np.exp(lp))        # (parametros positivos)
        res = simular(sistema, t_final=float(t_medido[-1]), metodo=metodo, n_pontos=400)
        return (np.interp(t_medido, res.t, res.sinal(sinal)) - y_medido) / escala

    otimo = least_squares(residuo, np.log([iniciais[p] for p in parametros]))
    for nome, lp in zip(parametros, otimo.x):
        sistema.definir(nome, np.exp(lp))
    return {"valores": {p: sistema.valor(p) for p in parametros}, "iniciais": iniciais,
            "erro_rms": float(np.sqrt(np.mean(otimo.fun ** 2)) * escala)}


def aprender_elemento(e_medido, f_medido, neuronios=(16, 16), semente: int = 0):
    """Aprende a curva caracteristica f = g(e) de um elemento resistivo nao linear.

    Usa scikit-learn (MLPRegressor) no treino; a funcao devolvida calcula a rede
    diretamente com NumPy, o que a torna rapida dentro da simulacao.
    """
    from sklearn.neural_network import MLPRegressor

    e = np.asarray(e_medido, dtype=float).ravel()
    f = np.asarray(f_medido, dtype=float).ravel()
    e_m, e_s, f_m, f_s = e.mean(), e.std() or 1.0, f.mean(), f.std() or 1.0
    rede = MLPRegressor(hidden_layer_sizes=neuronios, activation="tanh", solver="lbfgs",
                        alpha=1e-6, max_iter=5000, random_state=semente)
    rede.fit(((e - e_m) / e_s).reshape(-1, 1), (f - f_m) / f_s)
    pesos = [w.copy() for w in rede.coefs_]
    vies = [b.copy() for b in rede.intercepts_]

    def g(valor):
        a = (np.atleast_1d(np.asarray(valor, dtype=float)) - e_m) / e_s
        a = a.reshape(-1, 1)
        for w, b in zip(pesos[:-1], vies[:-1]):
            a = np.tanh(a @ w + b)
        saida = (a @ pesos[-1] + vies[-1]).ravel() * f_s + f_m
        return saida if np.ndim(valor) else float(saida[0])

    g.faixa_treino = (float(e.min()), float(e.max()))
    return g
