"""Simulacao no tempo das equacoes de estado.

Metodos disponiveis:
  - "auto"   : escolhe RK45 (Runge-Kutta adaptativo) ou, se o sistema for rigido
               ou nao linear, LSODA (alterna entre metodo explicito e implicito);
  - metodos do SciPy: "RK45", "RK23", "DOP853", "Radau", "BDF", "LSODA";
  - passo fixo, implementados aqui para comparacao: "RK4" e "Euler".
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.integrate import solve_ivp

from .equacoes import Sistema
from .modelo import ErroBondGraph

METODOS_SCIPY = ("RK45", "RK23", "DOP853", "Radau", "BDF", "LSODA")
METODOS = ("auto",) + METODOS_SCIPY + ("RK4", "Euler")

ROTULOS = {  # dominio -> (esforco, fluxo)
    "eletrico": ("tensão (V)", "corrente (A)"),
    "mecanico": ("força (N)", "velocidade (m/s)"),
}


@dataclass
class Resultado:
    sistema: Sistema
    t: np.ndarray
    x: np.ndarray                      # estados, formato (n_estados, n_tempos)
    sinais: dict                       # "R1.e", "R1.f", "R1.P" -> vetor no tempo
    metodo: str
    t_final: float
    passo: float | None = None
    autovalores: np.ndarray = None
    avisos: list = field(default_factory=list)

    def sinal(self, nome: str) -> np.ndarray:
        if nome in self.sinais:
            return self.sinais[nome]
        if nome in self.sistema.nomes_estados:
            return self.x[self.sistema.nomes_estados.index(nome)]
        raise KeyError(f"Sinal desconhecido: {nome!r}. Disponiveis: {sorted(self.sinais)}")

    def rotulos(self) -> tuple[str, str]:
        return ROTULOS.get(self.sistema.bg.dominio, ("esforço", "fluxo"))

    def salvar_csv(self, caminho: str) -> None:
        nomes = list(self.sinais)
        dados = np.column_stack([self.t] + [self.sinais[n] for n in nomes])
        np.savetxt(caminho, dados, delimiter=",", header="t," + ",".join(nomes), comments="")


def _frequencia_fontes(sistema: Sistema) -> float:
    fs = [n.fonte.get("frequencia", 0.0) for n in sistema.bg.nos
          if n.tipo in ("Se", "Sf") and n.fonte.get("tipo") == "seno"]
    return max(fs, default=0.0)


def sugerir_tempo_final(sistema: Sistema, autovalores: np.ndarray) -> float:
    """5 constantes de tempo do modo mais lento (ou 10 periodos, se nao amortecido)."""
    candidatos = []
    amort = np.abs(autovalores.real)
    amort = amort[amort > 1e-9 * max(1.0, np.max(np.abs(autovalores), initial=0.0))]
    if amort.size:
        candidatos.append(5.0 / amort.min())
    elif np.any(np.abs(autovalores.imag) > 0):
        candidatos.append(10 * 2 * np.pi / np.abs(autovalores.imag).max())
    f = _frequencia_fontes(sistema)
    if f > 0:
        candidatos.append(5.0 / f)
    return float(max(candidatos)) if candidatos else 1.0


def simular(sistema: Sistema, t_final: float | None = None, metodo: str = "auto",
            n_pontos: int = 1000, x0=None, passo: float | None = None,
            rtol: float = 1e-7) -> Resultado:
    """Integra as equacoes de estado de 0 a t_final (condicoes iniciais nulas por padrao)."""
    if metodo not in METODOS:
        raise ErroBondGraph(f"Metodo desconhecido: {metodo!r}. Use um de {METODOS}.")
    n = len(sistema.estados)
    x0 = np.zeros(n) if x0 is None else np.asarray(x0, dtype=float)
    avisos = []

    autovalores = np.linalg.eigvals(sistema.jacobiana(0.0, x0))
    if t_final is None:
        t_final = sugerir_tempo_final(sistema, autovalores)
        avisos.append(f"Tempo final escolhido automaticamente: {t_final:.4g} s.")
    mods = np.abs(autovalores)
    mods = mods[mods > 0]
    rigidez = mods.max() / mods.min() if mods.size else 1.0

    if metodo == "auto":
        metodo = "LSODA" if (rigidez > 1e3 or not sistema.linear) else "RK45"
        avisos.append(f"Metodo escolhido automaticamente: {metodo}.")

    t_aval = np.linspace(0.0, t_final, n_pontos)
    if metodo in METODOS_SCIPY:
        # max_step limita o passo para nao "pular" variacoes das fontes
        sol = solve_ivp(sistema.f_estado, (0.0, t_final), x0, method=metodo, t_eval=t_aval,
                        rtol=rtol, atol=1e-13, max_step=t_final / 200)
        if not sol.success:
            raise ErroBondGraph(f"A integracao falhou: {sol.message}")
        t, x = sol.t, sol.y
        passo = None
    else:
        if passo is None:
            passo = t_final / (n_pontos - 1)
        t, x = _passo_fixo(sistema.f_estado, x0, t_final, passo, metodo)

    # esforco, fluxo e potencia em cada elemento
    nb = sistema.n_bonds
    y = np.array([sistema.f_bonds(tt, x[:, k]) for k, tt in enumerate(t)]).T
    sinais = {}
    ids = [i for i, _, _ in sistema.bg.bonds]
    for no in sistema.bg.nos:
        if no.tipo in ("0", "1", "TF", "GY"):
            continue
        (i, _), = sistema.bg.bonds_do_no(no.nome)
        k = ids.index(i)
        sinais[f"{no.nome}.e"] = y[k]
        sinais[f"{no.nome}.f"] = y[nb + k]
        sinais[f"{no.nome}.P"] = y[k] * y[nb + k]
    return Resultado(sistema=sistema, t=t, x=x, sinais=sinais, metodo=metodo, t_final=t_final,
                     passo=passo, autovalores=autovalores, avisos=avisos)


def _passo_fixo(f, x0, t_final, h, metodo):
    """Euler explicito e Runge-Kutta classico de 4a ordem, com passo fixo."""
    n = int(round(t_final / h)) + 1
    t = np.linspace(0.0, t_final, n)
    h = t[1] - t[0]
    x = np.zeros((len(x0), n))
    x[:, 0] = x0
    with np.errstate(over="ignore", invalid="ignore"):
        for k in range(n - 1):
            tk, xk = t[k], x[:, k]
            if metodo == "Euler":
                x[:, k + 1] = xk + h * f(tk, xk)
            else:
                k1 = f(tk, xk)
                k2 = f(tk + h / 2, xk + h / 2 * k1)
                k3 = f(tk + h / 2, xk + h / 2 * k2)
                k4 = f(tk + h, xk + h * k3)
                x[:, k + 1] = xk + h / 6 * (k1 + 2 * k2 + 2 * k3 + k4)
    return t, x
