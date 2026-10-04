"""Meta-labeling: a cabeca que decide SE vale agir, nao para onde.

A IDEIA (Lopez de Prado)
    Dois modelos em serie, nao um melhor:
      primario -- diz a DIRECAO (o que ja existe: z -> alta/queda)
      meta     -- diz P(o primario estar CERTO), dadas as condicoes do dia
    Voce age so quando o meta passa de um limiar.

POR QUE ISSO IMPORTA AQUI
    A direcao tem IC de 0.081, ou seja ~52.6% de acerto medio. Esse numero e
    uma MEDIA sobre condicoes muito diferentes: dia de sinal forte e painel
    calmo nao e o mesmo que dia de sinal fraco com fontes discordando. O meta
    separa os dois, e voce opera so no primeiro.

    O que se ganha nao e IC -- e PRECISAO SOBRE UM SUBCONJUNTO. Troca-se
    frequencia por acerto. E e o unico regime em que custo de transacao e
    sobrevivivel, porque voce opera pouco.

O QUE O META NAO FAZ
    Nao conserta um primario sem sinal. Se o IC da direcao for zero, o meta
    nao tem o que filtrar: ele aprende a prever um acerto que e moeda, e a
    precisao do subconjunto fica em 50% como a do todo. O teste em
    scripts/metalabel_test.py existe justamente para checar isso.

FEATURES (todas conhecidas antes do alvo)
    forca do sinal primario |z|, padronizada no dia
    volatilidade prevista do papel (a terceira cabeca)
    volatilidade realizada recente
    discordancia entre as fontes / entre os drivers
    evidencia de noticia (n_eff), quando houver
"""
from __future__ import annotations

import numpy as np

from .volatility import logit_fit, logit_predict

LIMIAR_PADRAO = 0.58
MIN_TREINO = 400

# MEDIDO E REPROVADO (scripts/metalabel_test.py, 2 anos, 18 papeis):
#   acerto sem filtro 52.5%; no limiar 0.56 sobe para 57.2%, MAS t = 1.53
#   (abaixo de 2) e a sequencia nao e monotona (57.2% -> 55.7% -> 56.0%).
#   AUC do meta = 0.517, ou seja ele quase nao separa.
# Conclusao: com |z|, volatilidade e discordancia como features, o meta nao
# identifica condicoes em que o primario seja mais confiavel. Fica DESLIGADO
# por padrao; ligar exige refazer o teste e obter t > 2 com monotonia.
ATIVO = False


def montar_features(forca: float, vol_prev: float, vol_real: float,
                    dispersao: float, n_eff: float) -> list[float]:
    """Vetor de condicoes do dia para UM par (papel, data)."""
    return [abs(forca), vol_prev, vol_real, dispersao, min(n_eff, 8.0)]


def fit(X: np.ndarray, y: np.ndarray) -> dict | None:
    """y = 1 se o primario acertou o sinal naquele par (papel, dia)."""
    if len(y) < MIN_TREINO or len(set(y.tolist())) < 2:
        return None
    return logit_fit(X, y)


def predict(modelo: dict | None, X: np.ndarray) -> np.ndarray | None:
    if modelo is None:
        return None
    return logit_predict(modelo, X)


def porta(p_conf: float | None, limiar: float = LIMIAR_PADRAO,
          ativo: bool = None) -> bool:
    """Porta de confianca do alarme.

    Com ATIVO=False devolve True (nao filtra nada) em vez de bloquear tudo:
    um filtro que nao discrimina so reduziria a amostra sem ganho, e dar a ele
    poder de veto seria pior que nao te-lo. Quando o teste passar, ligue ATIVO.
    """
    if not (ATIVO if ativo is None else ativo):
        return True
    return p_conf is not None and p_conf >= limiar
