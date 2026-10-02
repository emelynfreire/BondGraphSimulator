"""Geracao automatica das equacoes de estado a partir do Bond Graph (SymPy).

Para cada bond i ha duas incognitas: esforco e_i e fluxo f_i.
Cada no contribui com suas equacoes:

  Se : e = u(t)                      Sf : f = u(t)
  R  : e = R f                       (ou lei nao linear f = g(e))
  C  : e = q / C ,  dq/dt = f        (estado q: carga / deslocamento)
  I  : f = p / I ,  dp/dt = e        (estado p: fluxo magnetico / momento)
  1  : fluxos iguais, soma dos esforcos = 0
  0  : esforcos iguais, soma dos fluxos = 0
  TF : e1 = n e2 , f2 = n f1         GY : e1 = r f2 , e2 = r f1

O sistema algebrico (2 equacoes por bond) e resolvido simbolicamente em
funcao dos estados e das fontes; as derivadas dos estados saem dai.
Com elementos nao lineares, a parte algebrica e resolvida numericamente
a cada passo de integracao.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import sympy as sp
from scipy import optimize

from .modelo import BondGraph, ErroBondGraph

t = sp.Symbol("t", real=True)


def expressao_fonte(fonte: dict) -> sp.Expr:
    """Converte a descricao do sinal de uma fonte em expressao de t."""
    tipo = fonte.get("tipo", "constante")
    if tipo == "constante":
        return sp.Float(fonte["valor"])
    if tipo == "degrau":
        t0 = fonte.get("t0", 0.0)
        return sp.Piecewise((sp.Float(fonte["valor"]), t >= t0), (sp.Float(0.0), True))
    if tipo == "seno":
        return (fonte.get("offset", 0.0) + fonte["amplitude"]
                * sp.sin(2 * sp.pi * fonte["frequencia"] * t + fonte.get("fase", 0.0)))
    raise ErroBondGraph(f"Tipo de sinal de fonte desconhecido: {tipo!r}.")


def lei_diodo(e, Is=1e-12, n=1.0, Vt=0.025852):
    """Diodo de Shockley, f = Is (exp(e / nVt) - 1), linearizado acima de 30 nVt
    para evitar estouro numerico (mesmo artificio dos simuladores tipo SPICE)."""
    nvt = n * Vt
    vc = 30 * nvt
    gc = Is * sp.exp(30) / nvt
    return Is * (sp.exp(sp.Min(e, vc) / nvt) - 1) + gc * sp.Max(e - vc, 0)


@dataclass
class Sistema:
    """Modelo matematico pronto para simular."""
    bg: BondGraph
    estados: list            # simbolos dos estados (q_*, p_*)
    nomes_estados: list      # nomes legiveis
    elementos_estado: list   # nome do elemento C/I de cada estado
    linear: bool
    equacoes_texto: str
    f_estado: object = None  # f(t, x) -> dx/dt
    f_bonds: object = None   # f(t, x) -> vetor [e_1..e_n, f_1..f_n]
    derivadas: list = field(default_factory=list)   # expressoes simbolicas (caso linear)
    n_bonds: int = 0
    parametros: list = field(default_factory=list)  # nomes dos parametros (R1, C1, ...)
    valores: np.ndarray = None                      # valores atuais (podem ser alterados)

    def valor(self, nome: str) -> float:
        return float(self.valores[self.parametros.index(nome)])

    def definir(self, nome: str, valor: float) -> None:
        self.valores[self.parametros.index(nome)] = float(valor)

    def jacobiana(self, tt: float, x: np.ndarray) -> np.ndarray:
        """Jacobiana numerica de dx/dt em relacao a x (diferencas finitas)."""
        x = np.asarray(x, dtype=float)
        f0 = np.asarray(self.f_estado(tt, x), dtype=float)
        J = np.zeros((len(x), len(x)))
        for j in range(len(x)):
            h = 1e-6 * max(1.0, abs(x[j]))
            xp = x.copy()
            xp[j] += h
            J[:, j] = (np.asarray(self.f_estado(tt, xp)) - f0) / h
        return J


def montar(bg: BondGraph) -> Sistema:
    """Deriva as equacoes de estado do Bond Graph."""
    bg.validar()
    ids = [i for i, _, _ in bg.bonds]
    e = {i: sp.Symbol(f"e{i}") for i in ids}
    f = {i: sp.Symbol(f"f{i}") for i in ids}
    X = [e[i] for i in ids] + [f[i] for i in ids]

    eqs, nao_lin = [], []                  # equacoes "= 0"; nao_lin: indices das nao lineares
    estados, nomes_est, elem_est, deriv = [], [], [], []
    subs_num, subs_fonte, funcoes = {}, {}, {}

    for no in bg.nos:
        lig = bg.bonds_do_no(no.nome)
        simb = sp.Symbol(no.nome)
        if no.tipo == "Se":
            (i, _), = lig
            eqs.append(e[i] - simb)
            subs_fonte[simb] = expressao_fonte(no.fonte)
        elif no.tipo == "Sf":
            (i, s), = lig
            eqs.append(f[i] + s * simb)    # bond saindo da fonte (s = -1): f = u
            subs_fonte[simb] = expressao_fonte(no.fonte)
        elif no.tipo == "R":
            (i, s), = lig
            if no.lei is None:
                eqs.append(e[i] - simb * s * f[i])
                subs_num[simb] = float(no.valor)
            else:
                if no.lei == "diodo":
                    g = lei_diodo(e[i], **no.params)
                elif no.lei == "polinomio":      # f = c1 e + c2 e^2 + c3 e^3 + ...
                    g = sum(c * e[i] ** (k + 1) for k, c in enumerate(no.params["coef"]))
                elif no.lei == "funcao":
                    nome_f = f"g_{no.nome}"
                    funcoes[nome_f] = no.funcao
                    g = sp.Function(nome_f)(e[i])
                else:
                    raise ErroBondGraph(f"Lei nao linear desconhecida: {no.lei!r}.")
                nao_lin.append(len(eqs))
                eqs.append(s * f[i] - g)
        elif no.tipo == "C":
            (i, s), = lig
            q = sp.Symbol(f"q_{no.nome}")
            eqs.append(e[i] - q / simb)
            subs_num[simb] = float(no.valor)
            estados.append(q); nomes_est.append(f"q_{no.nome}"); elem_est.append(no.nome)
            deriv.append(s * f[i])
        elif no.tipo == "I":
            (i, s), = lig
            p = sp.Symbol(f"p_{no.nome}")
            eqs.append(s * f[i] - p / simb)
            subs_num[simb] = float(no.valor)
            estados.append(p); nomes_est.append(f"p_{no.nome}"); elem_est.append(no.nome)
            deriv.append(e[i])
        elif no.tipo == "1":
            i0 = lig[0][0]
            eqs += [f[i] - f[i0] for i, _ in lig[1:]]
            eqs.append(sum(s * e[i] for i, s in lig))
        elif no.tipo == "0":
            i0 = lig[0][0]
            eqs += [e[i] - e[i0] for i, _ in lig[1:]]
            eqs.append(sum(s * f[i] for i, s in lig))
        elif no.tipo in ("TF", "GY"):
            a = next(i for i, s in lig if s == +1)
            b = next(i for i, s in lig if s == -1)
            subs_num[simb] = float(no.valor)
            if no.tipo == "TF":
                eqs += [e[a] - simb * e[b], f[b] - simb * f[a]]
            else:
                eqs += [e[a] - simb * f[b], e[b] - simb * f[a]]

    linear = not nao_lin
    P = list(subs_num)                     # simbolos dos parametros
    sistema = Sistema(bg=bg, estados=estados, nomes_estados=nomes_est,
                      elementos_estado=elem_est, linear=linear, equacoes_texto="",
                      n_bonds=len(ids), parametros=[str(s) for s in P],
                      valores=np.array([subs_num[s] for s in P], dtype=float))
    mods = [funcoes, "numpy"] if funcoes else "numpy"

    if linear:
        sol = _resolver_linear(eqs, X)
        derivadas = [sp.simplify(d.subs(sol)) for d in deriv]
        sistema.derivadas = derivadas
        linhas = [f"d{n}/dt = {sp.sstr(d)}" for n, d in zip(nomes_est, derivadas)]
        sistema.equacoes_texto = "\n".join(linhas)

        num = [d.subs(subs_fonte) for d in derivadas]
        saida = [sol[x].subs(subs_fonte) for x in X]
        fx = sp.lambdify((t, estados, P), num, modules=mods)
        fy = sp.lambdify((t, estados, P), saida, modules=mods)
        sistema.f_estado = lambda tt, x: np.array(fx(tt, x, sistema.valores), dtype=float)
        sistema.f_bonds = lambda tt, x: np.array(fy(tt, x, sistema.valores), dtype=float)
    else:
        # As equacoes lineares sao resolvidas simbolicamente, deixando livres apenas
        # tantas incognitas quantos forem os elementos nao lineares; so esse sistema
        # reduzido e resolvido numericamente a cada avaliacao.
        lineares = [q for k, q in enumerate(eqs) if k not in nao_lin]
        conj = sp.linsolve(lineares, X)
        if not conj:
            raise ErroBondGraph(_MSG_SINGULAR)
        valores = list(conj)[0]
        livres = sorted(set().union(*[v.free_symbols for v in valores]) & set(X), key=str)
        if len(livres) != len(nao_lin):
            raise ErroBondGraph(_MSG_SINGULAR)
        sol = dict(zip(X, valores))
        res = [eqs[k].subs(sol).subs(subs_fonte) for k in nao_lin]
        fres = sp.lambdify((livres, t, estados, P), res, modules=mods)
        fbonds = sp.lambdify((livres, t, estados, P),
                             [sol[x].subs(subs_fonte) for x in X], modules=mods)
        fder = sp.lambdify((livres, t, estados, P),
                           [d.subs(sol).subs(subs_fonte) for d in deriv], modules=mods)
        cache = {"z": np.zeros(len(livres))}

        def algebrico(tt, x):
            fun = lambda z: np.array(fres(z, tt, x, sistema.valores), dtype=float).ravel()
            z, _, ok, _ = optimize.fsolve(fun, cache["z"], full_output=True, xtol=1e-12)
            if ok != 1 or np.max(np.abs(fun(z))) > 1e-9:
                for z0 in (cache["z"], np.zeros(len(livres))):
                    r = optimize.root(fun, z0, method="lm", tol=1e-14)
                    z = r.x
                    if np.max(np.abs(r.fun)) < 1e-9:
                        break
            cache["z"] = z
            return z

        sistema.f_bonds = lambda tt, x: np.array(
            fbonds(algebrico(tt, x), tt, x, sistema.valores), dtype=float)
        sistema.f_estado = lambda tt, x: np.array(
            fder(algebrico(tt, x), tt, x, sistema.valores), dtype=float)
        linhas = ["Sistema com elemento(s) nao linear(es): parte algebrica resolvida numericamente.",
                  "Equacoes dos bonds (cada expressao = 0):"]
        linhas += [f"  {sp.sstr(q)}" for q in eqs]
        linhas += [f"d{n}/dt = {sp.sstr(d)}" for n, d in zip(nomes_est, deriv)]
        sistema.equacoes_texto = "\n".join(linhas)
    return sistema


_MSG_SINGULAR = (
           "Nao foi possivel obter equacoes de estado explicitas: o sistema algebrico e "
           "singular. Causa tipica: causalidade derivativa (estados dependentes), por exemplo "
           "fonte de tensao ideal diretamente em paralelo com capacitor, dois capacitores em "
           "paralelo, dois indutores em serie ou fonte de corrente em serie com indutor. "
           "Sugestao: combine os elementos dependentes em um equivalente ou inclua uma "
           "pequena resistencia entre eles.")


def _resolver_linear(eqs, X) -> dict:
    """Resolve o sistema algebrico linear; detecta causalidade derivativa."""
    msg = _MSG_SINGULAR
    try:
        A, b = sp.linear_eq_to_matrix(eqs, X)
        conj = sp.linsolve((A, b), X)
    except Exception as exc:  # pragma: no cover
        raise ErroBondGraph(f"Falha ao resolver as equacoes: {exc}") from exc
    if not conj:
        raise ErroBondGraph(msg)
    valores = list(conj)[0]
    if any(v.free_symbols & set(X) for v in valores):
        raise ErroBondGraph(msg)
    return dict(zip(X, valores))
