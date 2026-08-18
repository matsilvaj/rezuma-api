"""
Glossário de termos do mercado financeiro brasileiro.

Fonte única de verdade: a API enriquece cada relatório com os termos
encontrados no resumo, e o e-mail usa a mesma função. O dashboard consome
o resultado via API, sem duplicar as definições no frontend.

As definições são escritas em linguagem simples: quem lê não tem formação
financeira. Nenhuma definição pode conter outro jargão sem explicar.
"""

import re

# ── Definições ────────────────────────────────────────────────────────────
# Chave = termo como aparece no texto. Valor = explicação em 1 frase.

GLOSSARY: dict[str, str] = {
    # ── Fundos imobiliários: estrutura ──
    "FII": "Fundo de Investimento Imobiliário: um fundo que junta dinheiro de vários investidores para comprar imóveis ou títulos ligados a imóveis, e distribui os aluguéis recebidos.",
    "FIAGRO": "Fundo de Investimento nas Cadeias Produtivas Agroindustriais: mesma lógica de um fundo imobiliário, mas investindo no agronegócio.",
    "FoF": "Fundo de fundos: em vez de comprar imóveis diretamente, ele compra cotas de outros fundos imobiliários.",
    "cota": "A menor fração do fundo que você pode comprar. Ter cotas é ser dono de um pedaço do fundo.",
    "cotista": "Quem possui cotas do fundo, ou seja, o investidor.",
    "gestor": "Quem decide o que o fundo compra e vende no dia a dia.",
    "administrador": "Quem cuida da parte formal e legal do fundo: contabilidade, relatórios e pagamentos.",
    "taxa de administração": "Percentual anual que o fundo cobra para pagar sua gestão. Sai do valor do fundo antes de você receber os rendimentos.",
    "taxa de performance": "Cobrança extra que o gestor recebe quando o fundo rende acima de uma meta combinada.",
    "assembleia": "Reunião em que os cotistas votam decisões importantes do fundo, como comprar um imóvel ou trocar o gestor.",

    # ── Fundos imobiliários: imóveis e contratos ──
    "BTS": "Built to Suit, ou construção sob medida: o imóvel é construído sob encomenda para um inquilino específico, que assina um contrato longo e difícil de romper.",
    "sale and leaseback": "A empresa vende seu próprio imóvel para o fundo e continua nele como inquilina, pagando aluguel.",
    "contrato atípico": "Contrato de aluguel mais rígido que o normal: prazo longo e multa alta se o inquilino sair antes. Dá mais previsibilidade de renda ao fundo.",
    "contrato típico": "Contrato de aluguel comum, em que o inquilino pode sair com aviso prévio e multa menor.",
    "WALE": "Prazo médio que falta para os contratos de aluguel do fundo vencerem. Quanto maior, mais tempo de renda garantida.",
    "ABL": "Área Bruta Locável: o total de metros quadrados que o fundo tem disponível para alugar.",
    "vacância física": "Percentual da área do fundo que está vazia, sem inquilino.",
    "vacância financeira": "Percentual da receita de aluguel que o fundo deixa de receber por causa de espaços vazios ou descontos concedidos.",
    "inadimplência": "Percentual dos aluguéis que os inquilinos deveriam ter pago e não pagaram.",
    "laje corporativa": "Andar ou conjunto de andares de um prédio de escritórios.",
    "galpão logístico": "Armazém grande usado por empresas para estocar e distribuir mercadorias.",
    "renda garantida": "Promessa do vendedor do imóvel de complementar o aluguel durante um período, geralmente enquanto o imóvel ainda não está totalmente ocupado.",
    "cap rate": "Quanto o imóvel rende por ano em relação ao que custou. Um cap rate de 8% significa que o aluguel anual equivale a 8% do preço do imóvel.",
    "fundo de tijolo": "Fundo imobiliário que investe em imóveis físicos, como shoppings, galpões e escritórios.",
    "fundo de papel": "Fundo imobiliário que investe em títulos de dívida ligados a imóveis, em vez de comprar imóveis diretamente.",
    "fundo híbrido": "Fundo imobiliário que mistura imóveis físicos e títulos de dívida imobiliária.",

    # ── Títulos e dívida imobiliária ──
    "CRI": "Certificado de Recebíveis Imobiliários: um título de dívida em que o investidor empresta dinheiro para o setor imobiliário e recebe juros.",
    "CRA": "Certificado de Recebíveis do Agronegócio: mesma ideia do CRI, mas o dinheiro vai para o agronegócio.",
    "LCI": "Letra de Crédito Imobiliário: título de renda fixa emitido por bancos, com o dinheiro destinado ao setor imobiliário. Isento de imposto de renda para pessoa física.",
    "LCA": "Letra de Crédito do Agronegócio: título de renda fixa parecido com a LCI, mas voltado ao agronegócio.",
    "LTV": "Loan to Value: quanto da dívida está coberto pelo valor do imóvel dado em garantia. Quanto menor, mais seguro para quem emprestou.",
    "PDD": "Provisão para Devedores Duvidosos: dinheiro que o fundo separa por precaução, prevendo que parte dos devedores não vai pagar.",
    "NPL": "Non Performing Loan: empréstimo que parou de ser pago pelo devedor.",
    "duration": "Prazo médio até o título devolver o dinheiro investido. Quanto maior, mais o preço do título oscila quando os juros mudam.",
    "marcação a mercado": "Atualizar diariamente o valor de um título para o preço que ele valeria se fosse vendido hoje.",
    "amortização": "Devolução de parte do dinheiro que você investiu. Diferente do rendimento, não é lucro: é o próprio capital voltando.",

    # ── Rendimento e valuation ──
    "dividend yield": "Quanto o investimento pagou de rendimento no período em relação ao preço da cota ou ação. Um yield de 8% ao ano significa R$ 8 recebidos para cada R$ 100 investidos.",
    "DY": "Abreviação de dividend yield: quanto o investimento pagou de rendimento em relação ao seu preço.",
    "rendimento por cota": "Valor em reais que o fundo distribuiu para cada cota que você possui.",
    "P/VP": "Preço sobre Valor Patrimonial: compara o preço de mercado com o valor real dos bens do fundo. Abaixo de 1 significa que está sendo negociado por menos do que vale no papel.",
    "VPC": "Valor Patrimonial por Cota: quanto vale cada cota se somarmos todos os bens do fundo e dividirmos pelo número de cotas.",
    "VPA": "Valor Patrimonial por Ação: quanto vale cada ação considerando o patrimônio contábil da empresa.",
    "patrimônio líquido": "Tudo o que o fundo ou a empresa possui, menos tudo o que deve.",
    "P/L": "Preço sobre Lucro: quantos anos de lucro atual seriam necessários para pagar o preço da ação. Serve para comparar empresas do mesmo setor.",
    "LPA": "Lucro por Ação: o lucro da empresa dividido pelo número de ações existentes.",
    "TIR": "Taxa Interna de Retorno: o retorno anual que um investimento entregou considerando todas as entradas e saídas de dinheiro ao longo do tempo.",
    "VPL": "Valor Presente Líquido: quanto um investimento vale hoje, considerando todo o dinheiro que ele deve gerar no futuro.",
    "WACC": "Custo médio do dinheiro que a empresa usa, somando o que ela paga de juros aos bancos e o retorno esperado pelos acionistas.",
    "payout": "Percentual do lucro que a empresa distribui aos acionistas em vez de reinvestir no negócio.",
    "JCP": "Juros sobre Capital Próprio: uma forma de a empresa distribuir lucro aos acionistas com vantagem fiscal para ela. Para você, tem desconto de 15% de imposto na fonte.",
    "dividendo": "Parte do lucro da empresa distribuída em dinheiro aos acionistas.",

    # ── Resultado das empresas ──
    "EBITDA": "Lucro da empresa considerando apenas sua operação, antes de descontar juros, impostos e o desgaste dos equipamentos. Mostra se o negócio em si dá dinheiro.",
    "EBIT": "Lucro da operação depois de descontar o desgaste dos equipamentos, mas antes de juros e impostos.",
    "receita líquida": "Todo o dinheiro que entrou com vendas, já descontados impostos e devoluções.",
    "lucro líquido": "O que sobra para a empresa depois de pagar absolutamente tudo: custos, juros e impostos.",
    "margem líquida": "Quanto de cada R$ 100 vendidos vira lucro no fim. Margem de 12% significa R$ 12 de lucro a cada R$ 100 de venda.",
    "margem EBITDA": "Quanto de cada R$ 100 vendidos sobra da operação, antes de juros, impostos e desgaste de equipamentos.",
    "margem bruta": "Quanto sobra de cada R$ 100 vendidos depois de pagar apenas o custo direto do produto ou serviço.",
    "dívida líquida": "Tudo o que a empresa deve, menos o dinheiro que ela tem em caixa.",
    "alavancagem": "O quanto a empresa depende de dinheiro emprestado para operar. Alta alavancagem aumenta o risco se o negócio piorar.",
    "capex": "Dinheiro que a empresa investe em bens duráveis como máquinas, fábricas e equipamentos.",
    "opex": "Gastos do dia a dia para manter a empresa funcionando, como salários, energia e manutenção.",
    "fluxo de caixa livre": "Dinheiro que sobra no caixa depois de pagar as contas e os investimentos. É o que pode virar dividendo ou abater dívida.",
    "ROE": "Retorno sobre o Patrimônio: quanto de lucro a empresa gera para cada real investido pelos sócios. Quanto maior, mais eficiente.",
    "ROIC": "Retorno sobre o Capital Investido: quanto de lucro a empresa gera para cada real aplicado no negócio, seja próprio ou emprestado.",
    "ROA": "Retorno sobre os Ativos: quanto de lucro a empresa gera para cada real que ela possui em bens e direitos.",
    "NII": "Margem financeira de um banco: a diferença entre o que ele ganha emprestando dinheiro e o que paga a quem deixa dinheiro com ele.",
    "índice de Basileia": "Medida de segurança de um banco: mostra se ele tem capital próprio suficiente para aguentar perdas. No Brasil o mínimo exigido é 8%.",
    "guidance": "Previsão que a própria empresa divulga sobre seus resultados futuros, como quanto espera faturar no ano.",

    # ── Mercado e eventos societários ──
    "IPO": "Primeira vez que uma empresa vende ações na bolsa e passa a ter o capital aberto ao público.",
    "follow-on": "Nova emissão de ações ou cotas por uma empresa ou fundo que já está na bolsa, para captar mais dinheiro.",
    "emissão": "Criação e venda de novas cotas ou ações para levantar dinheiro. Aumenta a quantidade total em circulação.",
    "direito de preferência": "Direito de quem já é cotista comprar as novas cotas antes do mercado, mantendo sua fatia no fundo.",
    "free float": "Percentual das ações que está realmente disponível para negociação na bolsa, fora das mãos dos controladores.",
    "recompra de ações": "Quando a empresa compra suas próprias ações no mercado, reduzindo a quantidade em circulação e concentrando o lucro em menos ações.",
    "grupamento": "Juntar várias ações ou cotas em uma só, elevando o preço unitário. Sua fatia no total não muda.",
    "desdobramento": "Dividir cada ação ou cota em várias, barateando o preço unitário. Sua fatia no total não muda.",
    "bonificação": "Entrega de ações ou cotas novas aos investidores sem cobrança, a partir de lucros acumulados.",
    "data-base": "Data em que se define quem tem direito ao rendimento. Se você tinha o ativo nesse dia, recebe.",
    "data ex": "Primeiro dia em que o ativo passa a ser negociado sem o direito ao próximo rendimento. Quem comprar a partir dela não recebe.",
    "data de pagamento": "Dia em que o dinheiro do rendimento efetivamente cai na sua conta.",

    # ── Documentos e órgãos ──
    "CVM": "Comissão de Valores Mobiliários: o órgão do governo que fiscaliza a bolsa, os fundos e as empresas de capital aberto.",
    "B3": "A bolsa de valores brasileira, onde ações, fundos imobiliários e outros ativos são negociados.",
    "fato relevante": "Comunicado obrigatório sobre algo que pode mudar a decisão de comprar ou vender o ativo, como uma aquisição ou mudança de comando.",
    "ITR": "Informações Trimestrais: o balanço que empresas de capital aberto publicam a cada três meses.",
    "DFP": "Demonstrações Financeiras Padronizadas: o balanço anual completo e auditado da empresa.",
    "informe mensal": "Relatório que os fundos imobiliários publicam todo mês com números de vacância, receita e rendimento.",

    # ── Índices e taxas ──
    "Selic": "A taxa básica de juros do Brasil, definida pelo Banco Central. Serve de referência para todos os outros juros da economia.",
    "CDI": "Taxa de juros que os bancos cobram entre si, sempre muito próxima da Selic. É a principal referência de rentabilidade da renda fixa.",
    "IPCA": "O índice oficial de inflação do Brasil. Muitos contratos de aluguel são reajustados por ele.",
    "IGP-M": "Índice de inflação bastante usado para reajustar contratos de aluguel, mais sensível a preços no atacado que o IPCA.",
}

# Formas alternativas que aparecem no texto e apontam para o mesmo verbete.
ALIASES: dict[str, str] = {
    "build to suit": "BTS",
    "built to suit": "BTS",
    "construção sob medida": "BTS",
    "fundo de investimento imobiliário": "FII",
    "fundos imobiliários": "FII",
    "fundo imobiliário": "FII",
    "certificado de recebíveis imobiliários": "CRI",
    "certificados de recebíveis imobiliários": "CRI",
    "certificado de recebíveis do agronegócio": "CRA",
    "taxa interna de retorno": "TIR",
    "valor patrimonial por cota": "VPC",
    "valor patrimonial por ação": "VPA",
    "preço sobre valor patrimonial": "P/VP",
    "loan to value": "LTV",
    "juros sobre capital próprio": "JCP",
    "lucro por ação": "LPA",
    "retorno sobre o patrimônio": "ROE",
    "retorno sobre o capital investido": "ROIC",
    "área bruta locável": "ABL",
    "fundo de fundos": "FoF",
    "dividend yield anualizado": "dividend yield",
    "margem ebitda": "margem EBITDA",
    "patrimonio líquido": "patrimônio líquido",
    "data base": "data-base",
    "ex-data": "data ex",
    "basileia": "índice de Basileia",
    "juros sobre o capital próprio": "JCP",
    # Plurais irregulares, que o "s" opcional do padrão não cobre
    "galpões logísticos": "galpão logístico",
    "emissões": "emissão",
    "bonificações": "bonificação",
    "amortizações": "amortização",
    "assembleias": "assembleia",
    "inadimplências": "inadimplência",
}

# Termos escritos em caixa alta são casados respeitando maiúsculas para evitar
# falso positivo (ex: "B3" vs "b3", "DY" dentro de outra palavra).
_CASE_SENSITIVE = {
    t for t in GLOSSARY
    if t.isupper() or (t.replace("/", "").replace("-", "").isupper() and len(t) <= 6)
}
_CASE_SENSITIVE |= {"FoF", "B3", "IGP-M", "P/VP", "P/L"}


def _pattern(term: str) -> re.Pattern:
    """
    Regex do termo com fronteira de palavra e plural opcional.

    Em português o plural flexiona todas as palavras da expressão
    ("contrato atípico" vira "contratos atípicos"), então cada palavra
    recebe seu próprio "s" opcional. Plurais irregulares (galpão/galpões)
    entram como alias.
    """
    flags = 0 if term in _CASE_SENSITIVE else re.IGNORECASE
    words = term.split(" ")
    if len(words) > 1:
        body = r"\s+".join(rf"{re.escape(w)}s?" for w in words)
    else:
        body = rf"{re.escape(term)}s?"
    return re.compile(rf"(?<![\w/-]){body}(?![\w-])", flags)


# Pré-compila: verbetes mais longos primeiro para o mais específico vencer
# (ex: "margem EBITDA" antes de "EBITDA", "dívida líquida" antes de "dívida").
_ENTRIES: list[tuple[str, re.Pattern]] = sorted(
    [(t, _pattern(t)) for t in GLOSSARY],
    key=lambda e: len(e[0]),
    reverse=True,
)
_ALIAS_ENTRIES: list[tuple[str, re.Pattern]] = sorted(
    [(canonical, _pattern(alias)) for alias, canonical in ALIASES.items()],
    key=lambda e: len(e[1].pattern),
    reverse=True,
)


def known_terms() -> list[str]:
    """Termos que a IA pode usar livremente, pois o glossário os explica."""
    return sorted(GLOSSARY.keys(), key=str.lower)


def find_terms(text: str) -> list[dict]:
    """
    Retorna os termos do glossário presentes no texto, na ordem em que
    aparecem: [{"term": "BTS", "definition": "..."}, ...]

    Trechos já casados por um termo mais longo não são reaproveitados, para
    "margem EBITDA" não gerar também um verbete solto de "EBITDA".
    """
    if not text:
        return []

    # Remove marcação de negrito para não atrapalhar as fronteiras de palavra
    clean = re.sub(r"\*\*(.+?)\*\*", r"\1", text)

    consumed: list[tuple[int, int]] = []
    found: dict[str, int] = {}  # termo -> posição da primeira ocorrência

    def _scan(entries: list[tuple[str, re.Pattern]]) -> None:
        for canonical, pattern in entries:
            for match in pattern.finditer(clean):
                start, end = match.span()
                if any(s <= start and end <= e for s, e in consumed):
                    continue
                consumed.append((start, end))
                if canonical not in found or start < found[canonical]:
                    found[canonical] = start
                break  # um verbete por termo, basta a primeira ocorrência

    _scan(_ENTRIES)
    _scan(_ALIAS_ENTRIES)

    return [
        {"term": term, "definition": GLOSSARY[term]}
        for term in sorted(found, key=lambda t: found[t])
    ]
