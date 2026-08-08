"""Agente Questor: análise de certidões negativas e caixa postal fiscal.

Lê o retrato (snapshot) do sistema Questor — situação das certidões (Federal/PGFN,
Estadual, Municipal, FGTS, Trabalhista) e mensagens da caixa postal eletrônica —,
detecta problemas (certidão positiva/vencida/a vencer, mensagem não lida, prazo de
ciência) e, havendo pendência, envia e-mail ao time fiscal e de contabilidade.
"""
