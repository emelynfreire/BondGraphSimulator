# Simulador de Bond Graph — protótipo de validação

Protótipo em Python que segue a proposta do documento desta pasta: recebe a descrição de um
sistema (texto em português ou JSON), monta o Bond Graph, deriva as equações de estado,
simula no tempo e analisa o resultado.

## Como executar

Requisitos: Python 3.9+ com `numpy`, `scipy`, `sympy`, `networkx`, `matplotlib`
(`scikit-learn` e `pytest` são opcionais). No Anaconda, quase tudo já vem instalado:

```
pip install -r requirements.txt
```

| Comando | O que faz |
|---|---|
| `python app.py` | Abre a interface gráfica (Tkinter) |
| `python main.py "Um resistor de 100 Ohms em série com um capacitor de 1 µF conectado a uma fonte de tensão de 10V"` | Simula pela linha de comando |
| `python main.py exemplos/rlc_serie.json --metodo RK4 --figura saida.png` | Simula um arquivo JSON e salva as figuras |
| `python validar.py` | Compara com soluções analíticas e gera `validacao.png` |
| `python -m pytest -v` | Executa os 24 testes de validação |

## Estrutura

| Arquivo | Módulo da proposta | Conteúdo |
|---|---|---|
| `bondgraph/entrada.py` | 2.1 e 2.2 | Leitura de texto ou JSON e conversão em Bond Graph |
| `bondgraph/modelo.py` | 2.2 | Estrutura do Bond Graph (grafo direcionado NetworkX) e validação |
| `bondgraph/equacoes.py` | 2.3 | Equações de estado simbólicas (SymPy) |
| `bondgraph/simulacao.py` | 2.3 | Integração numérica (SciPy; RK4 e Euler de passo fixo) |
| `bondgraph/analise.py` | 2.4 | Diagnóstico automático do modelo e da simulação |
| `bondgraph/ia.py` | 2.4 | Ajuste de parâmetros e elemento não linear aprendido por rede neural |
| `bondgraph/visual.py`, `app.py` | 2.5 | Desenho do Bond Graph, gráficos e interface |
| `exemplos/`, `testes/`, `validar.py` | etapa 7 | Casos de teste e validação |

## Formas de entrada

**Texto.** Componentes reconhecidos: resistor, capacitor, indutor/bobina, diodo, fonte de
tensão, fonte de corrente (constante ou senoidal), massa, mola, amortecedor e força. Valores
com prefixos (p, n, u/µ, m, k, M) e ligações "em série" / "em paralelo" (paralelo tem
precedência). "Simular por 20 ms" define o tempo final. A interpretação é feita por regras
(expressões regulares), não por modelo de linguagem; o programa mostra o que entendeu para
conferência.

**JSON "circuito"** (árvore série/paralelo):

```json
{"formato": "circuito",
 "fonte": {"tipo": "tensao", "valor": 10},
 "circuito": {"serie": [{"R": 100}, {"paralelo": [{"C": 1e-6}, {"R": 1000}]}]},
 "simulacao": {"t_final": 0.001}}
```

Tipos de fonte: `tensao`, `corrente`, `forca`, `velocidade`. Sinal senoidal:
`"sinal": {"tipo": "seno", "amplitude": 10, "frequencia": 60}`; degrau:
`{"tipo": "degrau", "valor": 10, "t0": 0.001}`.

**JSON "bondgraph"** (elementos e bonds explícitos), para qualquer topologia e para sistemas
multidomínio com `TF` e `GY`; ver `exemplos/motor_cc.json`.

## Convenções adotadas

- Cada bond tem esforço `e` e fluxo `f`; potência = `e·f`. O sentido do bond é o sentido
  positivo da potência (use bonds apontando para dentro de R, C e I).
- **Junção 1**: fluxo comum, soma dos esforços nula (ligação em série).
  **Junção 0**: esforço comum, soma dos fluxos nula (ligação em paralelo).
- Estados: `q` em cada C (carga/deslocamento) e `p` em cada I (fluxo magnético/momento).
- Mola de rigidez `k` vira elemento C com valor `1/k`.
- Condições iniciais nulas, salvo se `x0` for passado a `simular`.

Duas passagens do documento divergem dessa convenção, que é a da literatura: a seção 2
associa a junção 1 ao esforço e a junção 0 ao fluxo, e a seção 4 coloca a fonte em uma
junção 0 e o resistor e o capacitor em junções 1. No circuito RC série há uma única
junção 1 ligando Se, R e C, e é assim que o protótipo o constrói.

## Validação

`python validar.py` compara quatro casos com a solução analítica:

| Caso | Erro máximo relativo |
|---|---|
| RC série (exemplo do documento) | 3e-12 |
| RLC série subamortecido | 2e-9 |
| Massa-mola-amortecedor | 3e-8 |
| Motor CC (elétrico + mecânico, girador) | 1e-9 |

Os testes cobrem ainda: fonte de corrente, resposta senoidal em regime, transformador,
cinco métodos de integração, balanço de energia (erro abaixo de 1 %), retificador com
diodo, detecção de causalidade derivativa, interpretação de texto, ajuste de parâmetros e
elemento não linear aprendido.

## O que a parte de "IA" faz neste protótipo

- **Interpretação de texto e diagnóstico**: regras determinísticas. O diagnóstico usa
  autovalores e balanço de energia para apontar instabilidade, rigidez, tempo final ou passo
  inadequados e erro numérico, com sugestão de correção.
- **Ajuste de parâmetros** (`ia.ajustar_parametros`): mínimos quadrados não lineares sobre
  dados medidos.
- **Elemento não linear aprendido** (`ia.aprender_elemento`): rede neural pequena (MLP)
  treinada com pares (esforço, fluxo) e usada como elemento R. Testada apenas com dados
  sintéticos; fora da faixa de treino a curva não é confiável.

## Fora do escopo desta versão

- Editor gráfico com arrastar e soltar (a interface recebe texto/JSON e desenha o grafo).
- Atribuição gráfica de causalidade (traço causal); a causalidade derivativa é detectada e
  informada, mas não resolvida.
- Vocabulário hidráulico e térmico na entrada em texto (possíveis via JSON "bondgraph",
  que é independente de domínio).
- Elementos modulados, fontes controladas, transistores, ruído e variáveis estocásticas.
- Detecção de anomalias por aprendizado de máquina e otimização por redes neurais.
- Diodo: modelo de Shockley linearizado acima de ~0,78 V para evitar estouro numérico.
