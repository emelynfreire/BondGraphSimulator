"""Validacao do simulador contra solucoes analiticas conhecidas.

Executar na pasta do projeto:   python -m pytest -v
"""
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bondgraph import BondGraph, ErroBondGraph, balanco_energia, carregar, montar, simular
from bondgraph.ia import ajustar_parametros, aprender_elemento

EXEMPLOS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "exemplos")


def _simular(entrada, **kw):
    bg, opcoes, _ = carregar(entrada)
    opcoes.update(kw)
    return simular(montar(bg), **opcoes)


# ------------------------------------------------------------ circuitos lineares
def test_rc_serie_texto_do_documento():
    """Exemplo do documento: v_C(t) = V (1 - exp(-t/RC))."""
    res = _simular("Um resistor de 100 Ohms em série com um capacitor de 1 µF "
                   "conectado a uma fonte de tensão de 10V")
    analitico = 10 * (1 - np.exp(-res.t / (100 * 1e-6)))
    assert np.max(np.abs(res.sinal("C1.e") - analitico)) < 1e-6


def test_rc_equacao_simbolica():
    bg, _, _ = carregar(os.path.join(EXEMPLOS, "rc_serie.json"))
    assert montar(bg).equacoes_texto == "dq_C1/dt = (C1*V1 - q_C1)/(C1*R1)"


def test_rlc_serie_subamortecido():
    R, L, C, V = 10.0, 0.01, 1e-4, 5.0
    res = _simular(os.path.join(EXEMPLOS, "rlc_serie.json"))
    alfa, w0 = R / (2 * L), 1 / np.sqrt(L * C)
    wd = np.sqrt(w0 ** 2 - alfa ** 2)
    vc = V * (1 - np.exp(-alfa * res.t) * (np.cos(wd * res.t) + alfa / wd * np.sin(wd * res.t)))
    corrente = V / (wd * L) * np.exp(-alfa * res.t) * np.sin(wd * res.t)
    assert np.max(np.abs(res.sinal("C1.e") - vc)) < 1e-5
    assert np.max(np.abs(res.sinal("L1.f") - corrente)) < 1e-6


def test_rc_paralelo_fonte_de_corrente():
    res = _simular(os.path.join(EXEMPLOS, "rc_paralelo_corrente.json"))
    analitico = 0.002 * 1000 * (1 - np.exp(-res.t / (1000 * 1e-6)))
    assert np.max(np.abs(res.sinal("C1.e") - analitico)) < 1e-6


def test_fonte_senoidal_regime_permanente():
    """RC com fonte senoidal: amplitude em regime = V / sqrt(1 + (wRC)^2)."""
    R, C, f = 1000.0, 1e-6, 500.0
    res = _simular({"fonte": {"tipo": "tensao", "sinal": {"tipo": "seno", "amplitude": 1.0,
                                                           "frequencia": f}},
                    "circuito": {"serie": [{"R": R}, {"C": C}]}}, t_final=0.04, n_pontos=8000)
    amplitude = np.max(np.abs(res.sinal("C1.e")[res.t > 0.03]))
    assert amplitude == pytest.approx(1 / np.sqrt(1 + (2 * np.pi * f * R * C) ** 2), rel=1e-3)


# ------------------------------------------------------------- outros dominios
def test_massa_mola_amortecedor():
    m, k, b, F = 2.0, 50.0, 3.0, 10.0
    res = _simular("Uma massa de 2 kg presa a uma mola de 50 N/m e a um amortecedor "
                   "de 3 N.s/m, com força de 10 N")
    alfa, wn = b / (2 * m), np.sqrt(k / m)
    wd = np.sqrt(wn ** 2 - alfa ** 2)
    x = F / k * (1 - np.exp(-alfa * res.t) * (np.cos(wd * res.t) + alfa / wd * np.sin(wd * res.t)))
    assert np.max(np.abs(res.sinal("q_K1") - x)) < 1e-6      # deslocamento da mola


def test_motor_cc_multidominio():
    """Girador acoplando dominio eletrico e mecanico: velocidade em regime."""
    res = _simular(os.path.join(EXEMPLOS, "motor_cc.json"), t_final=2.0)
    K, R, b, V = 0.05, 1.0, 1e-4, 12.0
    assert res.sinal("J.f")[-1] == pytest.approx(K * V / (R * b + K ** 2), rel=1e-6)
    assert res.sinal("La.f")[-1] == pytest.approx(b * V / (R * b + K ** 2), rel=1e-6)


def test_transformador():
    """TF de razao n (e1 = n e2) com R no secundario: resistencia refletida n^2 R."""
    bg = BondGraph("transformador")
    bg.adicionar("Se", "V", 10.0)
    bg.adicionar("1", "J1"); bg.adicionar("I", "L", 0.1); bg.adicionar("TF", "T", 2.0)
    bg.adicionar("R", "R", 5.0)
    for a, b in [("V", "J1"), ("J1", "L"), ("J1", "T"), ("T", "R")]:
        bg.ligar(a, b)
    res = simular(montar(bg), t_final=0.1)
    assert res.sinal("L.f")[-1] == pytest.approx(10.0 / (2.0 ** 2 * 5.0), rel=1e-6)


# --------------------------------------------------------- metodos e energia
@pytest.mark.parametrize("metodo,tol", [("RK45", 1e-7), ("Radau", 1e-6), ("LSODA", 1e-5),
                                        ("RK4", 1e-7), ("Euler", 2e-2)])
def test_metodos_de_integracao(metodo, tol):
    res = _simular(os.path.join(EXEMPLOS, "rc_serie.json"), metodo=metodo, n_pontos=1000)
    analitico = 10 * (1 - np.exp(-res.t / 1e-4))
    assert np.max(np.abs(res.sinal("C1.e") - analitico)) < tol


@pytest.mark.parametrize("arquivo", ["rc_serie.json", "rlc_serie.json", "motor_cc.json",
                                     "massa_mola_amortecedor.json", "retificador_diodo.json"])
def test_balanco_de_energia(arquivo):
    res = _simular(os.path.join(EXEMPLOS, arquivo))
    assert balanco_energia(res)["erro_relativo"] < 0.01


# ------------------------------------------------------------ nao linearidade
def test_retificador_com_diodo():
    res = _simular(os.path.join(EXEMPLOS, "retificador_diodo.json"))
    vc = res.sinal("C1.e")
    assert vc.min() > -1e-6                         # o diodo nao deixa o capacitor inverter
    assert 8.5 < vc.max() < 10.0                    # pico = 10 V menos a queda no diodo
    assert res.sinal("D1.f").min() > -1e-9          # corrente reversa desprezivel


# -------------------------------------------------------------- deteccao de erros
def test_causalidade_derivativa_e_detectada():
    with pytest.raises(ErroBondGraph, match="causalidade derivativa"):
        _simular("fonte de tensão de 10 V em paralelo com um capacitor de 1 uF "
                 "e um resistor de 100 ohms")


def test_texto_sem_fonte():
    with pytest.raises(ErroBondGraph, match="fonte"):
        carregar("um resistor de 10 ohms em série com um capacitor de 1 uF")


def test_interpretacao_serie_paralelo():
    bg, _, _ = carregar("fonte de tensão de 5 V, resistor de 1 kΩ em série com um capacitor "
                        "de 2,2 nF em paralelo com um resistor de 4,7 kΩ")
    tipos = sorted(n.tipo for n in bg.nos)
    assert tipos == ["0", "1", "C", "R", "R", "Se"]
    assert bg.no("C1").valor == pytest.approx(2.2e-9)
    assert bg.no("R2").valor == pytest.approx(4700.0)


# ------------------------------------------------------------------------- IA
def test_ajuste_de_parametros():
    """Recupera R e C a partir de 'medidas' sinteticas com ruido."""
    rng = np.random.default_rng(1)
    t = np.linspace(0, 5e-4, 60)
    medido = 10 * (1 - np.exp(-t / (100 * 1e-6))) + rng.normal(0, 0.02, t.size)
    bg, _, _ = carregar({"fonte": {"tipo": "tensao", "valor": 10},
                         "circuito": {"serie": [{"R": 100}, {"C": 3e-6}]}})   # C errado
    sistema = montar(bg)
    ajuste = ajustar_parametros(sistema, t, medido, "C1.e", ["C1"])
    assert ajuste["valores"]["C1"] == pytest.approx(1e-6, rel=0.03)


def test_elemento_nao_linear_aprendido():
    """Rede neural aprende f = g(e) de um resistor nao linear e substitui a lei exata."""
    pytest.importorskip("sklearn")
    coef = [1e-3, 0.0, 2e-4]                        # f = 1e-3 e + 2e-4 e^3
    rng = np.random.default_rng(0)
    e = np.linspace(-6, 6, 200)
    f = coef[0] * e + coef[2] * e ** 3 + rng.normal(0, 2e-5, e.size)
    g = aprender_elemento(e, f)

    def circuito(**lei):
        bg = BondGraph("RC com resistor nao linear")
        bg.adicionar("Se", "V", 5.0)
        bg.adicionar("1", "J"); bg.adicionar("R", "Rnl", **lei); bg.adicionar("C", "C", 1e-6)
        for a, b in [("V", "J"), ("J", "Rnl"), ("J", "C")]:
            bg.ligar(a, b)
        return simular(montar(bg), t_final=2e-3, n_pontos=300)

    exato = circuito(lei="polinomio", params={"coef": coef})
    aprendido = circuito(lei="funcao", funcao=g)
    assert np.max(np.abs(exato.sinal("C.e") - aprendido.sinal("C.e"))) < 0.05   # < 1 % de 5 V
