# Log de decisões e portas

## Decisões de desenho

### Retorno anormal, não retorno bruto
**Decisão:** rotular com retorno relativo ao universo/benchmark.  
**Motivo:** retorno bruto permitiria ao modelo aprender o fator de mercado, não a informação específica da ação.

### Regressão ridge para exposições
**Decisão:** estimar os drivers em conjunto.  
**Motivo:** câmbio, commodities e índices são colineares; betas univariados somados contam o mesmo fator várias vezes.

### Roteamento por driver
**Decisão:** usar a cadeia para decidir o que uma ação deve escutar.  
**Motivo:** uma notícia sobre OPEP pode ser relevante a uma petroleira mesmo sem citar seu nome.

### Deduplicação antes de peso
**Decisão:** agrupar republicações e conteúdo quase idêntico.  
**Motivo:** repetição sindical não é confirmação independente.

### LLM como sensor, nunca oráculo
**Decisão:** usar LLM para extrair campos estruturados, como materialidade, rumor e “já precificado”.  
**Motivo:** pedir previsão de preço aumenta risco de vazamento histórico e cria uma resposta não auditável.

## Portas atuais

- Meta-label: desligada até obter monotonicidade e t estatístico adequado.
- Volatilidade: apresentar faixa ordinal enquanto o calibrador não superar a porta de Brier.
- Evento externo: explicação/atribuição, não previsão, se a surpresa for medida pelo próprio movimento contemporâneo do mercado.
- Surpresa macro doméstica: se ligada por configuração apesar do teste negativo, deve ser marcada como experimental e nunca promovida a evidência de previsão.
- Notícias: não tratadas como sinal validado até teste incremental contra retorno realizado.

## Inconsistências que exigem registro

A configuração e a documentação podem divergir. Sempre declarar:
1. o que o código está fazendo;
2. o que a evidência validou;
3. a decisão de produto tomada apesar da evidência.

Exemplo: uma camada pode estar `ATIVO=True` por decisão experimental e, ao mesmo tempo, continuar não validada. Esse estado não é “aprovada”; é “ligada para experimento”.
